import hashlib
import json
import re
import unicodedata
from pathlib import Path

from sqlalchemy.orm import Session

from backend.database import Person, Puzzle


ROOT = Path(__file__).resolve().parents[1]


def normalize_answer(value):
    value = unicodedata.normalize("NFKD", value.casefold())
    return "".join(character for character in value
                   if character.isalnum() and not unicodedata.combining(character))


def configure_puzzle(engine, puzzle_date, asset_id, puzzle_root=ROOT / "puzzles",
                     metadata_path=ROOT / "people" / "metadata.json"):
    """Import a reviewed offline puzzle; never accept answer data via HTTP."""
    if not re.fullmatch(r"[a-f0-9]{24}", asset_id):
        raise ValueError("Asset ID must contain exactly 24 lowercase hexadecimal characters")
    private = json.loads((puzzle_root / "private" / f"{asset_id}.json").read_text(encoding="utf-8"))
    public = puzzle_root / "public" / asset_id
    manifest = json.loads((public / "manifest.json").read_text(encoding="utf-8"))
    if private["puzzle_id"] != asset_id or manifest["puzzle_id"] != asset_id:
        raise ValueError("Puzzle IDs do not match")
    levels = manifest["levels"]
    if (manifest["schema_version"] != 1 or not levels
            or manifest["credits"] != "credits.md"):
        raise ValueError("Unsupported or incomplete manifest")
    expected_files = {"manifest.json", "credits.md"}
    previous_grid = 0
    for number, level in enumerate(levels, start=1):
        if (level["level"] != number or level["grid"] <= previous_grid
                or level["width"] <= 0 or level["width"] != level["height"]
                or level["width"] != level["grid"] * level["tile_size"]
                or level["file"] != f"level-{number:02d}.jpg"):
            raise ValueError("Invalid mosaic level dimensions, ordering, or filename")
        previous_grid = level["grid"]
        expected_files.add(level["file"])
    if set(private["public_files"]) != expected_files:
        raise ValueError("Public file inventory does not match manifest")
    for filename in sorted(expected_files):
        checksum = hashlib.sha256((public / filename).read_bytes()).hexdigest()
        if checksum != private["public_files"][filename]:
            raise ValueError(f"Asset hash mismatch: {filename}")
    if any(level["sha256"] != private["public_files"][level["file"]] for level in levels):
        raise ValueError("Level checksums do not match provenance")

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    records = metadata["people"]
    if any(p["status"] != "downloaded" or p["visual_review"] != "contact-sheet-reviewed"
           or not p["attribution"] for p in records):
        raise ValueError("Only reviewed, attributed portraits can be imported")
    actual_inputs = [
        {"id": p["id"], "sha256": p["output_sha256"], "attribution": p["attribution"]}
        for p in sorted(records, key=lambda record: record["id"])
    ]
    if private["inputs"]["portraits"] != actual_inputs:
        raise ValueError("Puzzle provenance does not match current portrait metadata")
    target_id = private["target"]["id"]
    target = next((p for p in records if p["id"] == target_id), None)
    if target is None or private["inputs"]["target_id"] != target_id:
        raise ValueError("Puzzle target is not in the reviewed catalogue")

    with Session(engine) as session, session.begin():
        existing = session.get(Puzzle, puzzle_date)
        if existing:
            if (existing.asset_id != asset_id or existing.target_id != target_id
                    or existing.levels != levels):
                raise ValueError("A different puzzle is already assigned to this date")
            return
        for record in records:
            aliases = sorted({
                normalize_answer(record["name"]), normalize_answer(record["wikipedia_title"]),
                normalize_answer(record["id"]),
            })
            person = session.get(Person, record["id"])
            if person is None:
                session.add(Person(id=record["id"], name=record["name"], aliases=aliases))
            elif person.name != record["name"] or person.aliases != aliases:
                raise ValueError(f"Catalogue changed for {record['id']}; migrate explicitly")
        session.flush()
        session.add(Puzzle(date=puzzle_date, asset_id=asset_id, target_id=target_id, levels=levels))
