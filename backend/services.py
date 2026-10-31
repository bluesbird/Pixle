import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from threading import Lock

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.database import Person, Player, Puzzle


COOKIE = "pixle_session"


@dataclass
class AppContext:
    root: Path
    database: object
    current_date: object
    secure_cookie: bool
    portraits: dict[str, Path]
    people_records: dict[str, dict]
    targets: dict[str, str]
    target_ids: list[str]
    target_count: int
    cycle_seed: str
    cycle_start_date: date | None
    levels_cache: dict[str, list[dict]] = field(default_factory=dict)
    cycle_cache: dict[int, list[str]] = field(default_factory=dict)
    practice_games: dict[str, dict] = field(default_factory=dict)
    practice_lock: Lock = field(default_factory=Lock)


def resolve_secure_cookie(secure_cookie):
    if secure_cookie is not None:
        return secure_cookie
    setting = os.environ.get("COOKIE_SECURE", "true").lower()
    if setting not in ("true", "false"):
        raise ValueError("COOKIE_SECURE must be true or false")
    return setting == "true"


def load_context(root: Path, database, current_date, secure_cookie):
    metadata_path = root / "people" / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    targets_path = root / "puzzles" / "private" / "targets.json"
    targets = json.loads(targets_path.read_text(encoding="utf-8"))["targets"]
    if not targets:
        raise ValueError("targets.json must contain at least one puzzle target")
    image_directory = (root / "people" / metadata["image_directory"]).resolve()
    portraits = {
        person["id"]: (image_directory / person["filename"]).resolve()
        for person in metadata["people"]
    }
    cycle_start_override = os.environ.get("PUZZLE_CYCLE_START_DATE")
    cycle_start_date = date.fromisoformat(cycle_start_override) if cycle_start_override else None
    return AppContext(
        root=root,
        database=database,
        current_date=current_date,
        secure_cookie=secure_cookie,
        portraits=portraits,
        people_records={person["id"]: person for person in metadata["people"]},
        targets=targets,
        target_ids=sorted(targets),
        target_count=len(targets),
        cycle_seed=os.environ.get("PUZZLE_CYCLE_SEED", "pixle-cycle-v1"),
        cycle_start_date=cycle_start_date,
    )


def session_dependency_factory(database):
    def session_dependency():
        with Session(database) as session:
            yield session

    return session_dependency


def player(session, request: Request, lock=False):
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


def portrait_url(context: AppContext, person_id):
    if person_id not in context.portraits:
        raise HTTPException(404, "Portrait is not available")
    return f"/api/people/{person_id}/photo"


def ensure_catalogue_seeded(session, context: AppContext, normalizer, bynames_map):
    missing_people = [
        person_id for person_id in context.target_ids
        if session.get(Person, person_id) is None
    ]
    if not missing_people:
        return
    for person_id in missing_people:
        record = context.people_records[person_id]
        bynames = bynames_map.get(person_id, set())
        aliases = sorted({
            normalizer(record["name"]),
            normalizer(record["wikipedia_title"]),
            normalizer(record["id"]),
            *(normalizer(value) for value in bynames),
        })
        session.add(Person(id=record["id"], name=record["name"], aliases=aliases))
    session.flush()
