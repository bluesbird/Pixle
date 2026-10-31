import json
import random
from io import BytesIO
from uuid import uuid4

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.responses import Response as RawResponse
from PIL import Image
from sqlalchemy import select

from backend.catalog import normalize_answer
from backend.database import Person, Puzzle
from backend.schemas import GameOutput, GuessOutput, LevelOutput
from backend.services import portrait_url


PRACTICE_GRIDS = (8, 12, 24, 48, 96)


class PracticeService:
    def __init__(self, context, player, level_outputs):
        self.context = context
        self.player = player
        self.level_outputs = level_outputs

    def require_practice(self, existing_player, practice_id):
        game = self.context.practice_games.get(practice_id)
        if not game or game["player_id"] != existing_player.token_hash:
            raise HTTPException(404, "Practice game not found")
        return game

    def practice_output(self, session, state):
        level_index = state["attempts"] if state["status"] == "playing" else max(0, state["attempts"] - 1)
        level = state["levels"][min(level_index, len(state["levels"]) - 1)]
        return GameOutput(
            date=self.context.current_date(),
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
            original_image_url=portrait_url(self.context, state["target_id"]) if state["status"] != "playing" else None,
            answer=session.get(Person, state["target_id"]).name if state["status"] != "playing" else None,
        )

    def create_random_practice(self, session, existing_player, source_puzzle, excluded_target):
        choices = list(session.scalars(select(Person.id)))
        if excluded_target is not None:
            choices = [person_id for person_id in choices if person_id != excluded_target]
        if not choices:
            raise HTTPException(503, "No people are available for practice")
        target_id = random.choice(choices)
        practice_id = uuid4().hex
        puzzle_id = f"practice-{practice_id[:16]}"
        portrait = self.context.portraits.get(target_id)
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
        with self.context.practice_lock:
            self.context.practice_games[practice_id] = {
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
            return self.context.practice_games[practice_id]

    def create_mosaic_practice(self, existing_player, source_puzzle):
        if source_puzzle is None:
            raise HTTPException(404, "No mosaic puzzle is available for practice")
        if isinstance(source_puzzle, Puzzle):
            asset_id = source_puzzle.asset_id
            target_id = source_puzzle.target_id
            levels = source_puzzle.levels
        else:
            asset_id = source_puzzle["asset_id"]
            target_id = source_puzzle["target_id"]
            levels = source_puzzle["levels"]
        practice_id = uuid4().hex
        levels = self.level_outputs(asset_id, levels)
        with self.context.practice_lock:
            self.context.practice_games[practice_id] = {
                "id": practice_id,
                "player_id": existing_player.token_hash,
                "target_id": target_id,
                "puzzle_id": asset_id,
                "status": "playing",
                "attempts": 0,
                "levels": levels,
                "guesses": [],
                "credits_url": f"/puzzles/{asset_id}/credits.md",
                "requests": {},
                "files": {},
            }
            return self.context.practice_games[practice_id]

    def offline_mosaic_sources(self, session):
        sources = []
        private_root = self.context.root / "puzzles" / "private"
        public_root = self.context.root / "puzzles" / "public"
        for metadata_path in sorted(private_root.glob("*.json")):
            if metadata_path.name == "targets.json":
                continue
            try:
                private = json.loads(metadata_path.read_text(encoding="utf-8"))
                asset_id = private["puzzle_id"]
                target_id = private["target"]["id"]
                if session.get(Person, target_id) is None:
                    continue
                manifest_path = public_root / asset_id / "manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                levels = manifest["levels"]
                if manifest["puzzle_id"] != asset_id or not levels:
                    continue
                sources.append({"asset_id": asset_id, "target_id": target_id, "levels": levels})
            except (OSError, KeyError, TypeError, json.JSONDecodeError):
                continue
        return sources

    def start_practice_random(self, request: Request, session):
        existing_player = self.player(session, request)
        current = session.get(Puzzle, self.context.current_date())
        source_puzzle = current or session.scalar(select(Puzzle).order_by(Puzzle.date.desc()))
        state = self.create_random_practice(
            session, existing_player, source_puzzle, current.target_id if current else None
        )
        return self.practice_output(session, state)

    def start_practice_mosaic(self, request: Request, session):
        existing_player = self.player(session, request)
        published = list(session.scalars(select(Puzzle)))
        source_puzzles = [{
            "asset_id": puzzle.asset_id,
            "target_id": puzzle.target_id,
            "levels": puzzle.levels,
        } for puzzle in published]
        known_assets = {source["asset_id"] for source in source_puzzles}
        for source in self.offline_mosaic_sources(session):
            if source["asset_id"] not in known_assets:
                source_puzzles.append(source)
        source_puzzle = random.choice(source_puzzles) if source_puzzles else None
        state = self.create_mosaic_practice(existing_player, source_puzzle)
        return self.practice_output(session, state)

    def get_practice(self, practice_id: str, request: Request, session):
        existing_player = self.player(session, request)
        with self.context.practice_lock:
            state = self.require_practice(existing_player, practice_id)
        return self.practice_output(session, state)

    def submit_practice_guess(self, practice_id: str, body, request: Request, session):
        existing_player = self.player(session, request)
        answer = normalize_answer(body.guess)
        candidates = [p for p in session.scalars(select(Person)) if answer in p.aliases]
        if len(candidates) != 1:
            raise HTTPException(422, "Choose an unambiguous person from the catalogue")
        person = candidates[0]
        with self.context.practice_lock:
            state = self.require_practice(existing_player, practice_id)
            previous = state["requests"].get(str(body.request_id))
            if previous is not None:
                if previous != person.id and previous != "__skip__":
                    raise HTTPException(409, "Request ID was already used for a different guess")
                return self.practice_output(session, state)
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
        return self.practice_output(session, state)

    def skip_practice_guess(self, practice_id: str, body, request: Request, session):
        existing_player = self.player(session, request)
        with self.context.practice_lock:
            state = self.require_practice(existing_player, practice_id)
            request_id = str(body.request_id)
            previous = state["requests"].get(request_id)
            if previous is not None:
                return self.practice_output(session, state)
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
        return self.practice_output(session, state)

    def practice_level(self, practice_id: str, level: int, request: Request, session):
        existing_player = self.player(session, request)
        with self.context.practice_lock:
            state = self.require_practice(existing_player, practice_id)
            if level < 1 or level > len(state["levels"]):
                raise HTTPException(404, "Practice level not found")
            filename = f"level-{level:02d}.jpg"
            data = state["files"].get(filename)
            if data is None:
                raise HTTPException(404, "Practice level not found")
        return RawResponse(content=data, media_type="image/jpeg")

    def practice_original(self, practice_id: str, request: Request, session):
        existing_player = self.player(session, request)
        with self.context.practice_lock:
            state = self.require_practice(existing_player, practice_id)
        if state["status"] == "playing":
            raise HTTPException(409, "Finish the practice game to view the original portrait")
        path = self.context.portraits.get(state["target_id"])
        if path is None or not path.exists():
            raise HTTPException(404, "Portrait not found")
        return FileResponse(path, media_type="image/jpeg")
