# Offline puzzle assets

Generate a sample from the reviewed dataset, from the project root:

```powershell
python -m pip install -r requirements-people.txt
python tools\generate_mosaic.py --target albert-einstein
python tools\generate_all_mosaics.py
python -m unittest discover -s tools -p "test_*.py"
```

Default output is five 768 x 768 JPEGs with grids of 8, 12, 24, 48, and 96 tiles
per side, ordered from coarse to fine. Optional `--size`, `--grids`, and
`--output` arguments change these settings; each grid must divide the output size.
No downloads or manual image editing occur during generation.

The included sample is `public\1d79c84a0dd89e24dd601cfe`, with its answer
and provenance in the matching private JSON file. All five levels were visually
reviewed: coarse levels obscure the target, and finer levels reveal the face.
The sample is an offline demonstration, not yet assigned to a puzzle date.

`1d79c84a0dd89e24dd601cfe` is intentionally **not** a person name. Puzzle IDs are
opaque content-version hashes (first 24 hex chars of SHA-256), derived from the
algorithm version, target ID, all portrait hashes/credits, output size/grids, and
processing dependency versions. This avoids leaking the answer in public URLs and
ensures reproducible versioning.

## Generate every puzzle

From the project root:

```powershell
python tools\generate_all_mosaics.py
```

This builds one puzzle per reviewed person and writes `private\targets.json`:
`{target-id -> puzzle-id}` for offline scheduling workflows.

When the people dataset changes (add/remove/replace portraits), regenerate all:

```powershell
python tools\curate_people.py --verify
python tools\generate_all_mosaics.py --prune
```

`--prune` removes stale puzzle outputs that no longer correspond to the current
people set, while keeping newly generated versioned outputs.

## Output boundary

- `public\<puzzle-id>\`: level images, a public `manifest.json`, and `credits.md`.
- `private\<puzzle-id>.json`: answer, input hashes, processing versions, and tile
  assignments for auditing and future server-side puzzle configuration.

**Serve only `public`, never this whole directory or the repository.** The private
files and the original `people` dataset are not browser assets. A public source
repository still reveals private files to repository readers; this separation
prevents accidental browser delivery, not discovery by someone inspecting source.
Public manifests use opaque content-version IDs and numbered filenames, without
target names, source paths, answers, or tile assignments. Credits list the entire
portrait dataset in stable order so credit selection does not identify the answer.
Keep credits accessible in the eventual game UI and alongside redistributed assets.
Individual portrait licenses, including share-alike requirements, still apply.

## Matching and reproducibility

Each tile is matched by squared Euclidean distance between average RGB colors.
Target regions are averaged at each grid resolution. The target portrait is
excluded from the tile pool at every level. Ties use stable portrait-ID order;
tiles may repeat, including adjacent tiles. No randomization, color overlay, or
face synthesis is applied. These are photographic mosaics, not pixelated originals.
Average-color matching intentionally does not guarantee monotonically increasing
recognizability for every possible target; review each puzzle before publication.

The version ID covers the algorithm, target, all portrait hashes and credits,
size, grids, Pillow version, and NumPy version. Identical inputs in the same
processing environment produce byte-identical assets and manifests. Different
settings or dependency versions create a new asset directory. Existing versioned
files are never silently overwritten with different bytes. Portrait hashes and
dataset visual/license approval are checked before generation.
