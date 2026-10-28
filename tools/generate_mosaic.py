"""Generate deterministic mosaics offline; publish only the public output tree."""

import argparse
import hashlib
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image, __version__ as pillow_version

from curate_people import PEOPLE, ROOT, verify


ALGORITHM = "rgb-average-v1"
DEFAULT_GRIDS = (8, 12, 24, 48, 96)
DEFAULT_SIZE = 768


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def build_puzzle(records, image_directory, target_id, size=DEFAULT_SIZE, grids=DEFAULT_GRIDS):
    """Return public files and private provenance without writing to disk."""
    grids = tuple(grids)
    if size <= 0 or not grids or any(g <= 0 or size % g for g in grids):
        raise ValueError("Output size must be positive and divisible by every positive grid size")
    if list(grids) != sorted(set(grids)):
        raise ValueError("Grid sizes must be unique and strictly increasing")
    ordered = sorted(records, key=lambda record: record["id"])
    if len({record["id"] for record in ordered}) != len(ordered):
        raise ValueError("Portrait IDs must be unique")
    targets = [record for record in ordered if record["id"] == target_id]
    if len(targets) != 1:
        raise ValueError(f"Unknown target ID: {target_id}")
    target = targets[0]
    pool = [record for record in ordered if record["id"] != target_id]
    if not pool:
        raise ValueError("At least one other portrait is required for mosaic tiles")

    images = {}
    for record in ordered:
        filename = record["filename"]
        if Path(filename).name != filename or "/" in filename or "\\" in filename:
            raise ValueError(f"Expected a plain image filename: {filename}")
        data = (image_directory / filename).read_bytes()
        if digest(data) != record["output_sha256"]:
            raise ValueError(f"Portrait hash mismatch: {filename}")
        with Image.open(io.BytesIO(data)) as original:
            if original.mode != "RGB" or original.width != original.height:
                raise ValueError(f"Expected a square RGB portrait: {filename}")
            images[record["id"]] = original.copy()

    inputs = {
        "algorithm": ALGORITHM,
        "pillow_version": pillow_version,
        "numpy_version": np.__version__,
        "size": size,
        "grids": list(grids),
        "target_id": target_id,
        "portraits": [
            {"id": record["id"], "sha256": record["output_sha256"],
             "attribution": record["attribution"]}
            for record in ordered
        ],
    }
    puzzle_id = digest(json_bytes(inputs))[:24]
    colors = np.array([
        np.asarray(images[record["id"]], dtype=np.float64).mean(axis=(0, 1))
        for record in pool
    ])
    target_pixels = np.asarray(
        images[target_id].resize((size, size), Image.Resampling.LANCZOS), dtype=np.float64
    )
    files = {}
    levels = []
    private_levels = []
    for number, grid in enumerate(grids, start=1):
        side = size // grid
        regions = target_pixels.reshape(grid, side, grid, side, 3).mean(axis=(1, 3))
        distances = ((regions[:, :, None, :] - colors[None, None, :, :]) ** 2).sum(axis=3)
        matches = distances.argmin(axis=2)
        tiles = [
            images[record["id"]].resize((side, side), Image.Resampling.LANCZOS)
            for record in pool
        ]
        mosaic = Image.new("RGB", (size, size))
        for row in range(grid):
            for column in range(grid):
                mosaic.paste(tiles[int(matches[row, column])], (column * side, row * side))
        output = io.BytesIO()
        mosaic.save(output, "JPEG", quality=94, subsampling=0)
        filename = f"level-{number:02d}.jpg"
        files[filename] = output.getvalue()
        levels.append({
            "level": number, "grid": grid, "tile_size": side,
            "width": size, "height": size, "file": filename,
            "sha256": digest(files[filename]),
        })
        private_levels.append({
            "level": number,
            "tile_ids": [[pool[int(index)]["id"] for index in row] for row in matches],
        })

    # Credit the entire pool in stable order, not the target or tile usage order.
    credits = ["# Portrait credits", "",
               "All source portraits are credited below, without identifying the puzzle answer.",
               "Mosaic tiles are square crops resized from these portraits; per-image licenses apply.", ""]
    for record in ordered:
        credits.extend([record["attribution"], ""])
    files["credits.md"] = "\n".join(credits).encode("utf-8")
    manifest = {
        "schema_version": 1, "algorithm": ALGORITHM, "puzzle_id": puzzle_id,
        "levels": levels, "credits": "credits.md",
    }
    files["manifest.json"] = json_bytes(manifest)
    private = {
        "schema_version": 1, "puzzle_id": puzzle_id,
        "target": {"id": target_id, "name": target["name"],
                   "wikipedia_title": target["wikipedia_title"]},
        "inputs": inputs, "levels": private_levels,
        "public_files": {name: digest(data) for name, data in sorted(files.items())},
    }
    return files, private


def write_puzzle(output_directory, files, private):
    puzzle_id = private["puzzle_id"]
    public = output_directory / "public" / puzzle_id
    private_path = output_directory / "private" / f"{puzzle_id}.json"
    outputs = {public / name: data for name, data in files.items()}
    outputs[private_path] = json_bytes(private)
    for path, data in outputs.items():
        if path.exists() and path.read_bytes() != data:
            raise ValueError(f"Versioned output differs; refusing to overwrite: {path}")
    for path, data in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return public


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, help="Portrait ID, e.g. albert-einstein")
    parser.add_argument("--output", type=Path, default=ROOT / "puzzles")
    parser.add_argument("--size", type=int, default=DEFAULT_SIZE)
    parser.add_argument("--grids", nargs="+", type=int, default=DEFAULT_GRIDS)
    args = parser.parse_args()
    metadata = json.loads((PEOPLE / "metadata.json").read_text(encoding="utf-8"))
    verify(metadata["people"])
    image_directory = PEOPLE / metadata["image_directory"]
    files, private = build_puzzle(
        metadata["people"], image_directory, args.target, args.size, args.grids
    )
    public = write_puzzle(args.output, files, private)
    print(f"Generated {len(private['levels'])} levels: {public}")
    print("Publish only the public directory; private contains the answer and tile assignments.")


if __name__ == "__main__":
    main()
