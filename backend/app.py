import hashlib
import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.catalog import normalize_answer
from backend.database import Game, Guess, Person, Player, Puzzle, Result, make_engine


LOGGER = logging.getLogger(__name__)
COOKIE = "pixle_session"


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
    status: str
    attempts: int
    max_attempts: int
    level: LevelOutput
    guesses: list[GuessOutput]
    credits_url: str
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

    def game_output(session, puzzle, game):
        attempts = game.attempts if game else 0
        status = game.status if game else "playing"
        maximum = len(puzzle.levels)
        level_index = attempts if status == "playing" else max(0, attempts - 1)
        level = puzzle.levels[min(level_index, maximum - 1)]
        prefix = f"/puzzles/{puzzle.asset_id}"
        guesses = []
        if game:
            rows = session.execute(
                select(Guess, Person).join(Person, Guess.person_id == Person.id)
                .where(Guess.game_id == game.id).order_by(Guess.attempt)
            )
            guesses = [
                GuessOutput(attempt=guess.attempt, name=person.name,
                            correct=person.id == puzzle.target_id)
                for guess, person in rows
            ]
        result = session.get(Result, game.id) if game else None
        return GameOutput(
            date=puzzle.date, puzzle_id=puzzle.asset_id, status=status,
            attempts=attempts, max_attempts=maximum,
            level=LevelOutput(level=level["level"], grid=level["grid"],
                              width=level["width"], height=level["height"],
                              url=f"{prefix}/{level['file']}"),
            guesses=guesses, credits_url=f"{prefix}/credits.md",
            score=result.score if result else None,
            answer=session.get(Person, puzzle.target_id).name if status != "playing" else None,
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
