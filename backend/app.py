import hashlib
import json
import logging
import os
import random
import secrets
from io import BytesIO
from pathlib import Path
from threading import Lock
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from uuid import UUID
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from PIL import Image
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.responses import Response as RawResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.catalog import normalize_answer
from backend.database import Game, Guess, Person, Player, Puzzle, Result, make_engine


LOGGER = logging.getLogger(__name__)
COOKIE = "pixle_session"
ROOT = Path(__file__).resolve().parent.parent
PRACTICE_GRIDS = (8, 12, 24, 48, 96)


class GuessInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    guess: str = Field(min_length=1, max_length=200)
    request_id: UUID

    @field_validator("guess")
    @classmethod
    def meaningful_guess(cls, value):
        if not normalize_answer(value):
            raise ValueError("Guess must contain a person's name")
        return value


class SkipInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID


class PersonOutput(BaseModel):
    id: str
    name: str


class LevelOutput(BaseModel):
    level: int
    grid: int
    width: int
    height: int
    url: str


class GuessOutput(BaseModel):
    attempt: int
    name: str
    correct: bool


class GameOutput(BaseModel):
    date: date
    puzzle_id: str
    mode: str
    status: str
    attempts: int
    max_attempts: int
    level: LevelOutput
    levels: list[LevelOutput]
    guesses: list[GuessOutput]
    credits_url: str
    practice_id: str | None = None
    original_image_url: str | None = None
    score: int | None = None
    answer: str | None = None


class StatisticsOutput(BaseModel):
    played: int
    won: int
    total_score: int


def create_app(engine=None, today=None, secure_cookie=None):
    owns_engine = engine is None
    database = engine if engine is not None else make_engine()
    current_date = today or (lambda: datetime.now(timezone.utc).date())
    if secure_cookie is None:
        setting = os.environ.get("COOKIE_SECURE", "true").lower()
        if setting not in ("true", "false"):
            raise ValueError("COOKIE_SECURE must be true or false")
        secure_cookie = setting == "true"

    @asynccontextmanager
    async def lifespan(_):
        try:
            with database.connect() as connection:
                connection.execute(text("SELECT 1"))
                connection.execute(select(Puzzle.date).limit(1))
            yield
        finally:
            if owns_engine:
                database.dispose()

    app = FastAPI(title="Pixle API", version="0.1.0", lifespan=lifespan)
    metadata_path = ROOT / "people" / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    image_directory = (ROOT / "people" / metadata["image_directory"]).resolve()
    portraits = {
        person["id"]: (image_directory / person["filename"]).resolve()
        for person in metadata["people"]
    }
    practice_games = {}
    practice_lock = Lock()

    @app.middleware("http")
    async def private_responses(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, error):
        LOGGER.error("Database operation failed for %s", request.url.path, exc_info=error)
        return JSONResponse(status_code=503, content={"detail": "Database temporarily unavailable"})

    def session_dependency():
        with Session(database) as session:
            yield session

    def player(session, request, lock=False):
        token = request.cookies.get(COOKIE, "")
        if len(token) != 43:
            raise HTTPException(401, "Create an anonymous session first")
        query = select(Player).where(Player.token_hash == hashlib.sha256(token.encode()).hexdigest())
        if lock:
            query = query.with_for_update()
        existing = session.scalar(query)
        if existing is None:
            raise HTTPException(401, "Anonymous session is invalid")
        return existing

    def puzzle_for(session, puzzle_date):
        if puzzle_date > current_date():
            raise HTTPException(404, "Puzzle not available")
        puzzle = session.get(Puzzle, puzzle_date)
        if puzzle is None:
            raise HTTPException(404, "No puzzle configured for this date")
        return puzzle

    def level_outputs(puzzle_id, levels):
        prefix = f"/puzzles/{puzzle_id}"
        return [
            LevelOutput(
                level=entry["level"], grid=entry["grid"], width=entry["width"],
                height=entry["height"], url=f"{prefix}/{entry['file']}"
            )
            for entry in levels
        ]

    def portrait_url(person_id):
        if person_id not in portraits:
            raise HTTPException(404, "Portrait is not available")
        return f"/api/people/{person_id}/photo"

    def game_output(session, puzzle, game):
        attempts = game.attempts if game else 0
        status = game.status if game else "playing"
        levels = level_outputs(puzzle.asset_id, puzzle.levels)
        maximum = len(levels)
        level_index = attempts if status == "playing" else max(0, attempts - 1)
        level = levels[min(level_index, maximum - 1)]
        guesses = []
        if game:
            rows = session.execute(
                select(Guess, Person).join(Person, Guess.person_id == Person.id)
                .where(Guess.game_id == game.id).order_by(Guess.attempt)
            )
            guesses = [
                GuessOutput(attempt=guess.attempt,
                            name="Skipped" if guess.request_id.startswith("s") else person.name,
                            correct=person.id == puzzle.target_id)
                for guess, person in rows
            ]
        result = session.get(Result, game.id) if game else None
        return GameOutput(
            date=puzzle.date, puzzle_id=puzzle.asset_id, status=status,
            mode="daily",
            attempts=attempts, max_attempts=maximum,
            level=level, levels=levels,
            guesses=guesses, credits_url=f"/puzzles/{puzzle.asset_id}/credits.md",
            original_image_url=portrait_url(puzzle.target_id) if status != "playing" else None,
            score=result.score if result else None,
            answer=session.get(Person, puzzle.target_id).name if status != "playing" else None,
        )

    def require_practice(existing_player, practice_id):
        game = practice_games.get(practice_id)
        if not game or game["player_id"] != existing_player.token_hash:
            raise HTTPException(404, "Practice game not found")
        return game

    def practice_output(session, state):
        level_index = state["attempts"] if state["status"] == "playing" else max(0, state["attempts"] - 1)
        level = state["levels"][min(level_index, len(state["levels"]) - 1)]
        return GameOutput(
            date=current_date(),
            puzzle_id=state["puzzle_id"],
            mode="practice",
            practice_id=state["id"],
            status=state["status"],
            attempts=state["attempts"],
            max_attempts=len(state["levels"]),
            level=level,
            levels=state["levels"],
            guesses=state["guesses"],
            credits_url=state["credits_url"],
            original_image_url=portrait_url(state["target_id"]) if state["status"] != "playing" else None,
            answer=session.get(Person, state["target_id"]).name if state["status"] != "playing" else None,
        )

    @app.get("/api/health")
    def health(session: Session = Depends(session_dependency)):
        session.execute(text("SELECT 1"))
        return {"status": "ok"}

    @app.post("/api/session", status_code=201)
    def create_session(request: Request, response: Response,
                       session: Session = Depends(session_dependency)):
        token = request.cookies.get(COOKIE)
        if token:
            player(session, request)
            return {"status": "ready"}
        token = secrets.token_urlsafe(32)
        session.add(Player(token_hash=hashlib.sha256(token.encode()).hexdigest()))
        session.commit()
        response.set_cookie(COOKIE, token, max_age=31536000, httponly=True,
                            secure=secure_cookie, samesite="lax", path="/api")
        return {"status": "ready"}

    @app.get("/api/people", response_model=list[PersonOutput])
    def people(session: Session = Depends(session_dependency)):
        return [PersonOutput(id=p.id, name=p.name)
                for p in session.scalars(select(Person).order_by(Person.name))]

    @app.get("/api/people/{person_id}/photo")
    def person_photo(person_id: str):
        path = portraits.get(person_id)
        if path is None or not path.exists():
            raise HTTPException(404, "Portrait not found")
        return FileResponse(path, media_type="image/jpeg")

    def retrieve(puzzle_date, request, session):
        existing_player = player(session, request)
        puzzle = puzzle_for(session, puzzle_date)
        game = session.scalar(select(Game).where(
            Game.player_id == existing_player.token_hash, Game.puzzle_date == puzzle_date
        ))
        return game_output(session, puzzle, game)

    @app.get("/api/puzzles/daily", response_model=GameOutput, response_model_exclude_none=True)
    def daily(request: Request, session: Session = Depends(session_dependency)):
        return retrieve(current_date(), request, session)

    @app.get("/api/puzzles/{puzzle_date}", response_model=GameOutput, response_model_exclude_none=True)
    def puzzle(puzzle_date: date, request: Request,
               session: Session = Depends(session_dependency)):
        return retrieve(puzzle_date, request, session)

    @app.get("/api/puzzles/{puzzle_date}/original")
    def daily_original(puzzle_date: date, request: Request,
                       session: Session = Depends(session_dependency)):
        existing_player = player(session, request)
        puzzle = puzzle_for(session, puzzle_date)
        game = session.scalar(select(Game).where(
            Game.player_id == existing_player.token_hash, Game.puzzle_date == puzzle_date
        ))
        if game is None or game.status == "playing":
            raise HTTPException(409, "Finish the puzzle to view the original portrait")
        path = portraits.get(puzzle.target_id)
        if path is None or not path.exists():
            raise HTTPException(404, "Portrait not found")
        return FileResponse(path, media_type="image/jpeg")

    @app.post("/api/puzzles/{puzzle_date}/guesses", response_model=GameOutput,
              response_model_exclude_none=True)
    def submit_guess(puzzle_date: date, body: GuessInput, request: Request,
                     session: Session = Depends(session_dependency)):
        if puzzle_date != current_date():
            raise HTTPException(409, "Guesses are accepted only for today's UTC puzzle")
        # Lock an existing parent row, so concurrent first guesses cannot create two games.
        existing_player = player(session, request, lock=True)
        puzzle = puzzle_for(session, puzzle_date)
        answer = normalize_answer(body.guess)
        candidates = [p for p in session.scalars(select(Person)) if answer in p.aliases]
        if len(candidates) != 1:
            raise HTTPException(422, "Choose an unambiguous person from the catalogue")
        person = candidates[0]
        game = session.scalar(select(Game).where(
            Game.player_id == existing_player.token_hash, Game.puzzle_date == puzzle_date
        ))
        if game is None:
            game = Game(player_id=existing_player.token_hash, puzzle_date=puzzle_date,
                        attempts=0, status="playing")
            session.add(game)
            session.flush()
        previous = session.scalar(select(Guess).where(
            Guess.game_id == game.id, Guess.request_id == str(body.request_id)
        ))
        if previous:
            if previous.person_id != person.id:
                raise HTTPException(409, "Request ID was already used for a different guess")
            return game_output(session, puzzle, game)
        if game.status != "playing":
            raise HTTPException(409, "This puzzle is already finished")
        if session.scalar(select(Guess.id).where(
                Guess.game_id == game.id, Guess.person_id == person.id)) is not None:
            raise HTTPException(409, "This person has already been guessed")
        game.attempts += 1
        session.add(Guess(game_id=game.id, request_id=str(body.request_id),
                          person_id=person.id, attempt=game.attempts))
        maximum = len(puzzle.levels)
        if person.id == puzzle.target_id:
            game.status = "won"
        elif game.attempts == maximum:
            game.status = "lost"
        if game.status != "playing":
            score = (maximum - game.attempts + 1) * 100 if game.status == "won" else 0
            session.add(Result(game_id=game.id, score=score))
        session.flush()
        output = game_output(session, puzzle, game)
        session.commit()
        return output

    @app.post("/api/puzzles/{puzzle_date}/skip", response_model=GameOutput,
              response_model_exclude_none=True)
    def skip_guess(puzzle_date: date, body: SkipInput, request: Request,
                   session: Session = Depends(session_dependency)):
        if puzzle_date != current_date():
            raise HTTPException(409, "Guesses are accepted only for today's UTC puzzle")
        existing_player = player(session, request, lock=True)
        puzzle = puzzle_for(session, puzzle_date)
        game = session.scalar(select(Game).where(
            Game.player_id == existing_player.token_hash, Game.puzzle_date == puzzle_date
        ))
        if game is None:
            game = Game(player_id=existing_player.token_hash, puzzle_date=puzzle_date,
                        attempts=0, status="playing")
            session.add(game)
            session.flush()
        # guesses.request_id is VARCHAR(36); keep skip markers within that limit.
        # Regular guess IDs are UUID strings (hex + hyphens, never starting with "s"),
        # so this preserves uniqueness and lets outputs label skip turns.
        raw_request_id = str(body.request_id)
        skip_key = "s" + raw_request_id[1:]
        previous = session.scalar(select(Guess).where(
            Guess.game_id == game.id, Guess.request_id == skip_key
        ))
        if previous:
            return game_output(session, puzzle, game)
        if game.status != "playing":
            raise HTTPException(409, "This puzzle is already finished")
        guessed = select(Guess.person_id).where(Guess.game_id == game.id)
        person = session.scalar(select(Person).where(
            Person.id != puzzle.target_id, ~Person.id.in_(guessed)
        ).order_by(Person.name).limit(1))
        if person is None:
            raise HTTPException(409, "No skip is possible in this state")
        game.attempts += 1
        session.add(Guess(game_id=game.id, request_id=skip_key,
                          person_id=person.id, attempt=game.attempts))
        maximum = len(puzzle.levels)
        if game.attempts == maximum:
            game.status = "lost"
            session.add(Result(game_id=game.id, score=0))
        session.flush()
        output = game_output(session, puzzle, game)
        session.commit()
        return output

    def create_random_practice(session, existing_player, source_puzzle, excluded_target):
        choices = list(session.scalars(select(Person.id)))
        if excluded_target is not None:
            choices = [person_id for person_id in choices if person_id != excluded_target]
        if not choices:
            raise HTTPException(503, "No people are available for practice")
        target_id = random.choice(choices)
        practice_id = uuid4().hex
        puzzle_id = f"practice-{practice_id[:16]}"
        portrait = portraits.get(target_id)
        if portrait is None or not portrait.exists():
            raise HTTPException(404, "Portrait not found")
        level_files = {}
        with Image.open(portrait) as original:
            source = original.convert("RGB").resize((768, 768), Image.Resampling.LANCZOS)
            for index, grid in enumerate(PRACTICE_GRIDS, start=1):
                reduced = source.resize((grid, grid), Image.Resampling.BILINEAR)
                blocky = reduced.resize((768, 768), Image.Resampling.NEAREST)
                output = BytesIO()
                blocky.save(output, "JPEG", quality=94, subsampling=0)
                filename = f"level-{index:02d}.jpg"
                level_files[filename] = output.getvalue()
        levels = [
            LevelOutput(
                level=index, grid=grid, width=768, height=768,
                url=f"/api/practice/{practice_id}/level-{index:02d}.jpg"
            )
            for index, grid in enumerate(PRACTICE_GRIDS, start=1)
        ]
        with practice_lock:
            practice_games[practice_id] = {
                "id": practice_id,
                "player_id": existing_player.token_hash,
                "target_id": target_id,
                "puzzle_id": puzzle_id,
                "status": "playing",
                "attempts": 0,
                "levels": levels,
                "guesses": [],
                "credits_url": f"/puzzles/{source_puzzle.asset_id}/credits.md" if source_puzzle else "/api/people",
                "requests": {},
                "files": level_files,
            }
            return practice_games[practice_id]

    def create_mosaic_practice(existing_player, source_puzzle):
        if source_puzzle is None:
            raise HTTPException(404, "No published puzzle is available for mosaic practice")
        practice_id = uuid4().hex
        levels = level_outputs(source_puzzle.asset_id, source_puzzle.levels)
        with practice_lock:
            practice_games[practice_id] = {
                "id": practice_id,
                "player_id": existing_player.token_hash,
                "target_id": source_puzzle.target_id,
                "puzzle_id": source_puzzle.asset_id,
                "status": "playing",
                "attempts": 0,
                "levels": levels,
                "guesses": [],
                "credits_url": f"/puzzles/{source_puzzle.asset_id}/credits.md",
                "requests": {},
                "files": {},
            }
            return practice_games[practice_id]

    @app.post("/api/practice/random", response_model=GameOutput, response_model_exclude_none=True)
    def start_practice_random(request: Request, session: Session = Depends(session_dependency)):
        existing_player = player(session, request)
        current = session.get(Puzzle, current_date())
        source_puzzle = current or session.scalar(select(Puzzle).order_by(Puzzle.date.desc()))
        state = create_random_practice(
            session, existing_player, source_puzzle, current.target_id if current else None
        )
        return practice_output(session, state)

    @app.post("/api/practice/mosaic", response_model=GameOutput, response_model_exclude_none=True)
    def start_practice_mosaic(request: Request, session: Session = Depends(session_dependency)):
        existing_player = player(session, request)
        source_puzzle = session.get(Puzzle, current_date()) or session.scalar(
            select(Puzzle).order_by(Puzzle.date.desc())
        )
        state = create_mosaic_practice(existing_player, source_puzzle)
        return practice_output(session, state)

    @app.get("/api/practice/{practice_id}", response_model=GameOutput, response_model_exclude_none=True)
    def get_practice(practice_id: str, request: Request, session: Session = Depends(session_dependency)):
        existing_player = player(session, request)
        with practice_lock:
            state = require_practice(existing_player, practice_id)
        return practice_output(session, state)

    @app.post("/api/practice/{practice_id}/guesses", response_model=GameOutput, response_model_exclude_none=True)
    def submit_practice_guess(practice_id: str, body: GuessInput, request: Request,
                              session: Session = Depends(session_dependency)):
        existing_player = player(session, request)
        answer = normalize_answer(body.guess)
        candidates = [p for p in session.scalars(select(Person)) if answer in p.aliases]
        if len(candidates) != 1:
            raise HTTPException(422, "Choose an unambiguous person from the catalogue")
        person = candidates[0]
        with practice_lock:
            state = require_practice(existing_player, practice_id)
            previous = state["requests"].get(str(body.request_id))
            if previous is not None:
                if previous != person.id and previous != "__skip__":
                    raise HTTPException(409, "Request ID was already used for a different guess")
                return practice_output(session, state)
            if state["status"] != "playing":
                raise HTTPException(409, "This practice game is already finished")
            if any(guess.name == person.name for guess in state["guesses"]):
                raise HTTPException(409, "This person has already been guessed")
            state["attempts"] += 1
            correct = person.id == state["target_id"]
            state["guesses"].append(GuessOutput(
                attempt=state["attempts"], name=person.name, correct=correct
            ))
            state["requests"][str(body.request_id)] = person.id
            if correct:
                state["status"] = "won"
            elif state["attempts"] >= len(state["levels"]):
                state["status"] = "lost"
        return practice_output(session, state)

    @app.post("/api/practice/{practice_id}/skip", response_model=GameOutput, response_model_exclude_none=True)
    def skip_practice_guess(practice_id: str, body: SkipInput, request: Request,
                            session: Session = Depends(session_dependency)):
        existing_player = player(session, request)
        with practice_lock:
            state = require_practice(existing_player, practice_id)
            request_id = str(body.request_id)
            previous = state["requests"].get(request_id)
            if previous is not None:
                return practice_output(session, state)
            if state["status"] != "playing":
                raise HTTPException(409, "This practice game is already finished")
            used = {normalize_answer(guess.name) for guess in state["guesses"]}
            candidates = [p for p in session.scalars(select(Person).order_by(Person.name))
                          if p.id != state["target_id"] and normalize_answer(p.name) not in used]
            if not candidates:
                raise HTTPException(409, "No skip is possible in this state")
            state["attempts"] += 1
            state["guesses"].append(GuessOutput(
                attempt=state["attempts"], name="Skipped", correct=False
            ))
            state["requests"][request_id] = "__skip__"
            if state["attempts"] >= len(state["levels"]):
                state["status"] = "lost"
        return practice_output(session, state)

    @app.get("/api/practice/{practice_id}/level-{level}.jpg")
    def practice_level(practice_id: str, level: int, request: Request, session: Session = Depends(session_dependency)):
        existing_player = player(session, request)
        with practice_lock:
            state = require_practice(existing_player, practice_id)
            if level < 1 or level > len(state["levels"]):
                raise HTTPException(404, "Practice level not found")
            filename = f"level-{level:02d}.jpg"
            data = state["files"].get(filename)
            if data is None:
                raise HTTPException(404, "Practice level not found")
        return RawResponse(content=data, media_type="image/jpeg")

    @app.get("/api/practice/{practice_id}/original")
    def practice_original(practice_id: str, request: Request, session: Session = Depends(session_dependency)):
        existing_player = player(session, request)
        with practice_lock:
            state = require_practice(existing_player, practice_id)
        if state["status"] == "playing":
            raise HTTPException(409, "Finish the practice game to view the original portrait")
        path = portraits.get(state["target_id"])
        if path is None or not path.exists():
            raise HTTPException(404, "Portrait not found")
        return FileResponse(path, media_type="image/jpeg")

    @app.get("/api/stats/me", response_model=StatisticsOutput)
    def statistics(request: Request, session: Session = Depends(session_dependency)):
        existing_player = player(session, request)
        played, total_score = session.execute(
            select(func.count(Result.game_id), func.coalesce(func.sum(Result.score), 0))
            .join(Game, Game.id == Result.game_id).where(Game.player_id == existing_player.token_hash)
        ).one()
        won = session.scalar(select(func.count(Game.id)).where(
            Game.player_id == existing_player.token_hash, Game.status == "won"
        ))
        return StatisticsOutput(played=played, won=won, total_score=total_score)

    return app
