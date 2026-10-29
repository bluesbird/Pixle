"""Generate deterministic puzzle assets for every reviewed person."""

import argparse
import json
from pathlib import Path
import shutil

from curate_people import PEOPLE, ROOT, verify
from generate_mosaic import build_puzzle, write_puzzle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "puzzles")
    parser.add_argument(
        "--prune",
        action="store_true",
        help="Remove stale public/private puzzle outputs not generated in this run.",
    )
    args = parser.parse_args()

    metadata = json.loads((PEOPLE / "metadata.json").read_text(encoding="utf-8"))
    records = metadata["people"]
    verify(records)
    image_directory = PEOPLE / metadata["image_directory"]

    generated = {}
    for record in sorted(records, key=lambda item: item["id"]):
        files, private = build_puzzle(records, image_directory, record["id"])
        write_puzzle(args.output, files, private)
        generated[record["id"]] = private["puzzle_id"]
        print(f"{record['id']} -> {private['puzzle_id']}", flush=True)

    private_dir = args.output / "private"
    private_dir.mkdir(parents=True, exist_ok=True)
    mapping_path = private_dir / "targets.json"
    mapping_path.write_text(
        json.dumps({"schema_version": 1, "targets": generated}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    if args.prune:
        expected_ids = set(generated.values())
        public_root = args.output / "public"
        if public_root.exists():
            for candidate in public_root.iterdir():
                if candidate.is_dir() and candidate.name not in expected_ids:
                    shutil.rmtree(candidate)
                    print(f"Pruned public/{candidate.name}", flush=True)
        if private_dir.exists():
            for candidate in private_dir.glob("*.json"):
                if candidate.name == "targets.json":
                    continue
                if candidate.stem not in expected_ids:
                    candidate.unlink()
                    print(f"Pruned private/{candidate.name}", flush=True)

    print(f"Generated {len(generated)} puzzles.")
    print(f"Wrote private target map: {mapping_path}")


if __name__ == "__main__":
    main()
