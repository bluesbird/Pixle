import hashlib
import json
import random
import secrets
from datetime import date

from fastapi import HTTPException, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from backend.catalog import PERSON_BYNAMES, normalize_answer
from backend.database import Game, Guess, Person, Player, Puzzle, Result
from backend.schemas import GameOutput, GuessOutput, LevelOutput, PersonOutput, StatisticsOutput
from backend.services import COOKIE, ensure_catalogue_seeded, portrait_url


class DailyService:
    def __init__(self, context, player):
        self.context = context
        self.player = player

    def level_outputs(self, puzzle_id, levels):
        prefix = f"/puzzles/{puzzle_id}"
        return [
            LevelOutput(
                level=entry["level"], grid=entry["grid"], width=entry["width"],
                height=entry["height"], url=f"{prefix}/{entry['file']}"
            )
            for entry in levels
        ]

    def puzzle_for(self, session, puzzle_date):
        if puzzle_date > self.context.current_date():
            raise HTTPException(404, "Puzzle not available")
        puzzle = session.get(Puzzle, puzzle_date)
        if puzzle is None:
            ensure_catalogue_seeded(session, self.context, normalize_answer, PERSON_BYNAMES)
            start = self.context.cycle_start_date or session.scalar(select(func.min(Puzzle.date)))
            if start is None:
                start = puzzle_date
            if puzzle_date >= start:
                offset = (puzzle_date - start).days
                cycle = offset // self.context.target_count
                index = offset % self.context.target_count
                order = self.context.cycle_cache.get(cycle)
                if order is None:
                    order = self.context.target_ids.copy()
                    random.Random(f"{self.context.cycle_seed}:{cycle}").shuffle(order)
                    self.context.cycle_cache[cycle] = order
                target_id = order[index]
                asset_id = self.context.targets[target_id]
                levels = self.context.levels_cache.get(asset_id)
                if levels is None:
                    manifest_path = self.context.root / "puzzles" / "public" / asset_id / "manifest.json"
                    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    levels = manifest["levels"]
                    self.context.levels_cache[asset_id] = levels
                session.add(Puzzle(date=puzzle_date, asset_id=asset_id, target_id=target_id, levels=levels))
                session.flush()
                session.info["created_auto_puzzle"] = True
                puzzle = session.get(Puzzle, puzzle_date)
        if puzzle is None:
            raise HTTPException(404, "No puzzle configured for this date")
        return puzzle

    def game_output(self, session, puzzle, game):
        attempts = game.attempts if game else 0
        status = game.status if game else "playing"
        levels = self.level_outputs(puzzle.asset_id, puzzle.levels)
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
            original_image_url=portrait_url(self.context, puzzle.target_id) if status != "playing" else None,
            score=result.score if result else None,
            answer=session.get(Person, puzzle.target_id).name if status != "playing" else None,
        )

    def retrieve(self, puzzle_date, request, session):
        existing_player = self.player(session, request)
        puzzle = self.puzzle_for(session, puzzle_date)
        game = session.scalar(select(Game).where(
            Game.player_id == existing_player.token_hash, Game.puzzle_date == puzzle_date
        ))
        output = self.game_output(session, puzzle, game)
        if session.info.pop("created_auto_puzzle", False):
            session.commit()
        return output

    def create_session(self, request: Request, response: Response, session):
        token = request.cookies.get(COOKIE)
        if token:
            self.player(session, request)
            return {"status": "ready"}
        token = secrets.token_urlsafe(32)
        session.add(Player(token_hash=hashlib.sha256(token.encode()).hexdigest()))
        session.commit()
        response.set_cookie(COOKIE, token, max_age=31536000, httponly=True,
                            secure=self.context.secure_cookie, samesite="lax", path="/api")
        return {"status": "ready"}

    def people(self, session):
        return [PersonOutput(id=p.id, name=p.name)
                for p in session.scalars(select(Person).order_by(Person.name))]

    def person_photo(self, person_id: str):
        path = self.context.portraits.get(person_id)
        if path is None or not path.exists():
            raise HTTPException(404, "Portrait not found")
        return FileResponse(path, media_type="image/jpeg")

    def daily_original(self, puzzle_date: date, request: Request, session):
        existing_player = self.player(session, request)
        puzzle = self.puzzle_for(session, puzzle_date)
        game = session.scalar(select(Game).where(
            Game.player_id == existing_player.token_hash, Game.puzzle_date == puzzle_date
        ))
        if game is None or game.status == "playing":
            raise HTTPException(409, "Finish the puzzle to view the original portrait")
        path = self.context.portraits.get(puzzle.target_id)
        if path is None or not path.exists():
            raise HTTPException(404, "Portrait not found")
        return FileResponse(path, media_type="image/jpeg")

    def submit_guess(self, puzzle_date: date, body, request: Request, session):
        if puzzle_date != self.context.current_date():
            raise HTTPException(409, "Guesses are accepted only for today's UTC puzzle")
        existing_player = self.player(session, request, lock=True)
        puzzle = self.puzzle_for(session, puzzle_date)
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
            return self.game_output(session, puzzle, game)
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
        output = self.game_output(session, puzzle, game)
        session.commit()
        return output

    def skip_guess(self, puzzle_date: date, body, request: Request, session):
        if puzzle_date != self.context.current_date():
            raise HTTPException(409, "Guesses are accepted only for today's UTC puzzle")
        existing_player = self.player(session, request, lock=True)
        puzzle = self.puzzle_for(session, puzzle_date)
        game = session.scalar(select(Game).where(
            Game.player_id == existing_player.token_hash, Game.puzzle_date == puzzle_date
        ))
        if game is None:
            game = Game(player_id=existing_player.token_hash, puzzle_date=puzzle_date,
                        attempts=0, status="playing")
            session.add(game)
            session.flush()
        raw_request_id = str(body.request_id)
        skip_key = "s" + raw_request_id[1:]
        previous = session.scalar(select(Guess).where(
            Guess.game_id == game.id, Guess.request_id == skip_key
        ))
        if previous:
            return self.game_output(session, puzzle, game)
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
        output = self.game_output(session, puzzle, game)
        session.commit()
        return output

    def statistics(self, request: Request, session):
        existing_player = self.player(session, request)
        played, total_score = session.execute(
            select(func.count(Result.game_id), func.coalesce(func.sum(Result.score), 0))
            .join(Game, Game.id == Result.game_id).where(Game.player_id == existing_player.token_hash)
        ).one()
        won = session.scalar(select(func.count(Game.id)).where(
            Game.player_id == existing_player.token_hash, Game.status == "won"
        ))
        return StatisticsOutput(played=played, won=won, total_score=total_score)
