# Recognizable people photo dataset

An editorial selection of 116 recognizable people: 27 music, 24 screen/media,
26 sports, 24 politics/public-life, and 15 other figures. It is **not an
empirically measured global ranking**. Recognition varies by country, age, and
audience.

The original contemporary-focused selection was revised following `feedback.md`:
11 people were removed, all 27 requested additions were included, and all 36
flagged photographs were replaced. The resulting 116-person scope was explicitly
approved. Requested names have been normalized (for example, Erling Haaland,
James Dean, Conor McGregor, and Muhammad Ali). The expanded set intentionally
includes more historical figures and reflects the requested selection rather
than the original regional/category balance.

The second photo-review pass addressed 21 additional requests in `feedback.md`:
20 sources were replaced and 50 Cent's existing photograph was reframed.
Younger photographs were selected for Schwarzenegger, McGregor, and Thunberg;
tight face crops were widened or replaced with less tightly framed sources.
Hawking now uses the familiar smiling StarChild archival portrait. Its original
is only 250 x 359 pixels, so the square output remains visibly soft.
Completed requests and specific corrections are checked off in `feedback.md`.

The selection includes figures associated with the Americas, Europe, Africa,
South Asia, East Asia, Southeast Asia, and the Middle East. English-language
Wikipedia and the availability of open photographs introduce selection bias;
the set is not regionally or demographically representative. Historical figures
are included alongside contemporary personalities. Category assignments are
organizational, not exclusive. Inclusion is for recognition purposes and is not
an endorsement of any person or ideology.

## Files and provenance

- `images\*.jpg`: one 768 x 768 RGB JPEG per person, with ASCII kebab-case name filenames.
- `selection.json`: the curated selection, identified by Wikipedia article title.
- `metadata.json`: individual author/credit, source page and original image URLs,
  actual downloaded URL, license name and URL, raw Commons license metadata,
  source revision and hashes, output hash, crop coordinates, and review status.
- `ATTRIBUTIONS.md`: readable, per-image attribution and modification notices.
- `MISSING.md`: explicit download/licensing failures, or confirmation of none.
- `crop-overrides.json`, if present: reviewed source-image or crop corrections.

Image filenames and person IDs are stable and independent of category. Resolve
each metadata record's `filename` under the top-level `image_directory`, which
is relative to the directory containing `metadata.json` (currently `images`).
For example, Adele's image is `people\images\adele.jpg`. Attribution headings
link directly to the corresponding images.

Wikipedia lead images are used to locate candidate photographs. **Wikimedia
Commons file pages are the image sources and licensing authorities**, not
Wikipedia article text. Only files with explicit CC BY, CC BY-SA, CC0, OGL v3,
or public-domain metadata are accepted; ambiguous and non-free files are rejected.
License verification means checking the file's published license declaration,
not independently establishing the uploader's chain of ownership. Raw published
license evidence is retained in `metadata.json`, together with retrieval time.

Square crops preserve the main face, hair/headwear, and as much distinctive
clothing or pose as the source allows. No beautification, face reconstruction,
background substitution, or generative editing is applied. Automatic face-guided
crops are reviewed on contact sheets by the coding assistant; corrections are
stored as explicit overrides. Crop boxes use `[left, top, right, bottom]` coordinates in the
EXIF-oriented downloaded image, before resizing.

Replacement sources favor unobstructed faces, distinctive appearances, and
usable detail over a uniform photographic style. Historical press photographs
and some older images retain source grain or softness; converting them to
768 x 768 does not create missing detail. No AI upscaling or invented facial
detail is used. Individual crops and source dimensions are recorded in metadata.

## Usage obligations

**There is no blanket license covering all photographs.** Each image retains its
own recorded license. Include the credited author, source link, license link,
and modification notice when redistributing. CC BY-SA derivatives must retain
the applicable share-alike license; consult each linked license's exact terms.
OGL v3 photographs include the source credit and the required public-sector
information acknowledgement; the license permits adaptation and commercial use,
but not implied official endorsement.
Keep `ATTRIBUTIONS.md` and `metadata.json` with copies of this dataset, and carry
credits into any interface or distribution that uses individual images.

Public-domain works may have jurisdiction-specific copyright considerations.
Copyright permission does not automatically clear personality/publicity,
privacy, trademark, endorsement, or other non-copyright rights. Presence here
does not imply endorsement or unrestricted commercial use. Source restrictions,
where supplied by Commons, are preserved in metadata.

## Reproducing or extending

From the project root, using Python 3:

```powershell
python -m pip install -r requirements-people.txt
python tools\curate_people.py
```

Successful downloads are reused. Missing entries are retried; failures are
recorded and the script exits nonzero if any images are missing. To refresh
specific people (including crop/source overrides):

```powershell
python tools\curate_people.py --only "Taylor Swift" "Lionel Messi"
python tools\curate_people.py --sheets-only
```

The selection size is read from `selection.json`, not fixed at 100. Changing
the selection updates metadata on the next download run; delete the specifically
removed people's JPEGs from `images` as well. Verification rejects unlisted JPEGs
and JPEGs left in the dataset root.

For source selection, `tools\review_people.py "Person Name"` gathers
license-checked alternative photographs and creates a candidate sheet. Search
results are suggestions only: verify the subject, clarity, and final crop
visually. `--category` or `--files` can narrow ambiguous names to exact Commons
sources. Selected sources, download widths, and crop corrections belong in
`crop-overrides.json`. Use `--sheets-only` to rebuild saved candidate sheets.

Inspect all contact sheets before recording completed review and validating:

```powershell
python tools\curate_people.py --approve-review
python tools\curate_people.py --verify
```

For crop-only adjustments, `--recrop --only "Person Name"` reuses cached source
bytes (or downloads and verifies them against the recorded hash). It does not
change the selected source photograph. Use a normal `--only` refresh after
changing a `file_title` override. Manual crop coordinates refer to the recorded
downloaded dimensions, not necessarily the original-resolution source.

Temporary contact sheets and cached source bytes are written to the ignored
`.people-review` directory; they are not needed to use the finished dataset.
`download_width` overrides request a supported Wikimedia thumbnail size where
original-file downloads are rate-limited. Requests with long `Retry-After`
delays are reported as failures rather than silently hanging; retry later.
Network source files and lead-image choices may change: metadata records the
actual retrieved file and revision, while a future refresh deliberately queries
current sources. A refresh resets visual review for affected images; review
those images again before publishing the refreshed dataset.
