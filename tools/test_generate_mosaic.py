import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

from generate_mosaic import build_puzzle, write_puzzle


class MosaicTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.records = []
        for identifier, color in [("answer-person", (240, 0, 0)),
                                  ("red-tile", (220, 0, 0)),
                                  ("blue-tile", (0, 0, 220))]:
            path = self.root / f"{identifier}.jpg"
            Image.new("RGB", (24, 24), color).save(path)
            self.records.append({
                "id": identifier, "name": identifier, "wikipedia_title": identifier,
                "filename": path.name, "output_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "attribution": f"Credit for {identifier}; CC0",
            })

    def build(self, **kwargs):
        return build_puzzle(self.records, self.root, "answer-person", size=24,
                            grids=kwargs.pop("grids", (2, 4, 8)), **kwargs)

    def test_levels_color_matching_exclusion_and_public_metadata(self):
        files, private = self.build()
        manifest = json.loads(files["manifest.json"])
        self.assertNotIn("answer-person", files["manifest.json"].decode())
        self.assertNotIn("target", manifest)
        self.assertEqual([level["grid"] for level in manifest["levels"]], [2, 4, 8])
        for level, assignments in zip(manifest["levels"], private["levels"]):
            with Image.open(io.BytesIO(files[level["file"]])) as image:
                self.assertEqual(image.size, (24, 24))
                self.assertEqual(image.mode, "RGB")
            self.assertEqual(len(assignments["tile_ids"]), level["grid"])
            for row in assignments["tile_ids"]:
                self.assertEqual(row, ["red-tile"] * level["grid"])
        credits = files["credits.md"].decode()
        for record in self.records:
            self.assertIn(record["attribution"], credits)

    def test_determinism_input_order_and_idempotent_writes(self):
        files, private = self.build()
        self.records.reverse()
        self.assertEqual((files, private), self.build())
        output = self.root / "output"
        public = write_puzzle(output, files, private)
        write_puzzle(output, files, private)
        self.assertEqual({path.name for path in public.iterdir()}, set(files))
        (public / "manifest.json").write_text("corrupted", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
            write_puzzle(output, files, private)

    def test_version_changes_with_input(self):
        _, before = self.build()
        self.records[1]["attribution"] += " updated"
        _, after = self.build()
        self.assertNotEqual(before["puzzle_id"], after["puzzle_id"])

    def test_invalid_inputs(self):
        for grids in [(4, 2), (2, 2), (5,), (0,), ()]:
            with self.subTest(grids=grids), self.assertRaises(ValueError):
                self.build(grids=grids)
        with self.assertRaisesRegex(ValueError, "Unknown target"):
            build_puzzle(self.records, self.root, "missing")
        with self.assertRaisesRegex(ValueError, "other portrait"):
            build_puzzle(self.records[:1], self.root, "answer-person")
        self.records[1]["output_sha256"] = "invalid"
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            self.build()

    def test_spatial_region_averages(self):
        pixels = np.zeros((24, 24, 3), dtype=np.uint8)
        pixels[:, :12] = (220, 0, 0)
        pixels[:, 12:] = (0, 0, 220)
        path = self.root / self.records[0]["filename"]
        Image.fromarray(pixels).save(path, quality=100, subsampling=0)
        self.records[0]["output_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        _, private = self.build(grids=(2,))
        self.assertEqual(private["levels"][0]["tile_ids"],
                         [["red-tile", "blue-tile"], ["red-tile", "blue-tile"]])


if __name__ == "__main__":
    unittest.main()
