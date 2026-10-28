"""Gather license-checked alternative photographs for human visual selection."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import io
import json
from pathlib import Path
import re
import textwrap

from PIL import Image, ImageDraw, ImageFont, ImageOps

from curate_people import ROOT, PEOPLE, api, check_license, fetch, plain, slug


REVIEW = ROOT / ".people-review"


def collect(title, search=None, refresh=False, category=None, files=None):
    directory = REVIEW / "candidates" / slug(title)
    if not refresh and (directory / "candidates.json").exists():
        return title
    existing = json.loads((PEOPLE / "metadata.json").read_text(encoding="utf-8"))["people"]
    old = next((p for p in existing if p["wikipedia_title"] == title), {})
    name = old.get("name", re.sub(r" \([^)]*\)$", "", title))
    try:
        generator_params = (
            dict(generator="categorymembers", gcmtitle="Category:" + category, gcmnamespace=6, gcmlimit=50)
            if category else
            dict(generator="search", gsrsearch=search or f'intitle:"{name}" filetype:bitmap',
                 gsrnamespace=6, gsrlimit=20)
        )
        query = api(
            "commons.wikimedia.org", **({"titles": "|".join(files)} if files else generator_params), prop="imageinfo",
            iiprop="url|extmetadata|size|sha1|timestamp", iiurlwidth=400,
            iiextmetadatalanguage="en",
        )
    except ValueError as error:
        if "cirrussearch-too-busy-error" not in str(error):
            raise
        print(f"{title}: Commons search busy; using article photographs", flush=True)
        article = api("en.wikipedia.org", titles=title, redirects=1, prop="images", imlimit=500)
        tokens = [token.lower().strip(".,") for token in name.split() if len(token) > 2]
        titles = [
            item["title"]
            for page in article["pages"].values() for item in page.get("images", [])
            if item["title"].lower().endswith((".jpg", ".jpeg", ".png"))
            and any(token in item["title"].lower() for token in tokens)
        ]
        if not titles:
            raise ValueError(f"No article photographs found for {title}") from error
        query = api(
            "commons.wikimedia.org", titles="|".join(titles[:50]), prop="imageinfo",
            iiprop="url|extmetadata|size|sha1|timestamp", iiurlwidth=400,
            iiextmetadatalanguage="en",
        )
    candidates = []
    for page in query.get("pages", {}).values():
        if "imageinfo" not in page:
            continue
        info = page["imageinfo"][0]
        try:
            license_info = check_license(info)
        except ValueError:
            continue
        if min(info["width"], info["height"]) < 600:
            continue
        description = plain(info["extmetadata"].get("ImageDescription", {}).get("value", ""))
        text = (page["title"] + " " + description).lower()
        if any(word in text for word in (
            "statue", "sculpture", "wax figure", "madame tussaud", "mural",
            "caricature", "painting", "graffiti", "drawing", "impersonator", "lookalike",
        )):
            continue
        if info["descriptionurl"] == old.get("source_page_url"):
            continue
        score = 0
        for word, weight in (
            ("portrait", 8), ("headshot", 8), ("cropped", 3), ("close-up", 6),
            ("performing", -3), ("concert", -3), ("stage", -2), ("with ", -3),
            ("signature", -20), ("grave", -20), ("house", -20), ("birthplace", -20),
        ):
            if word in text:
                score += weight
        if info["height"] >= info["width"]:
            score += 2
        candidates.append({
            "file_title": page["title"], "info": info,
            "description": description, "license": license_info["name"], "score": score,
        })
    candidates.sort(key=lambda c: c["score"], reverse=True)
    chosen = []
    # Avoid filling the gallery with several crops of the same photograph.
    bases = set()
    for candidate in candidates:
        base = re.sub(r"\([^)]*(?:crop|cut)[^)]*\)", "", candidate["file_title"], flags=re.I)
        base = re.sub(r"[^a-z0-9]", "", base.lower())
        if base not in bases:
            bases.add(base)
            chosen.append(candidate)
        if len(chosen) == 6:
            break
    directory.mkdir(parents=True, exist_ok=True)
    for index, candidate in enumerate(chosen):
        info = candidate["info"]
        path = directory / f"{index + 1}.jpg"
        data = fetch(info.get("thumburl", info["url"]))
        with Image.open(io.BytesIO(data)) as original:
            image = ImageOps.exif_transpose(original).convert("RGB")
            image.thumbnail((360, 400))
            image.save(path, quality=92)
        candidate["preview"] = str(path)
    (directory / "candidates.json").write_text(
        json.dumps({"title": title, "candidates": chosen}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"{title}: {len(chosen)} alternatives", flush=True)
    return title


def sheets(titles):
    font = ImageFont.truetype("C:\\Windows\\Fonts\\arial.ttf", 17)
    small = ImageFont.truetype("C:\\Windows\\Fonts\\arial.ttf", 12)
    for title in titles:
        directory = REVIEW / "candidates" / slug(title)
        data = json.loads((directory / "candidates.json").read_text(encoding="utf-8"))
        sheet = Image.new("RGB", (1080, 980), "white")
        draw = ImageDraw.Draw(sheet)
        draw.text((8, 4), title, fill="black", font=font)
        for i, candidate in enumerate(data["candidates"]):
            x, y = (i % 3) * 360, 30 + (i // 3) * 475
            with Image.open(candidate["preview"]) as image:
                sheet.paste(image, (x + (360 - image.width) // 2, y))
            label = f'{i + 1}: {candidate["file_title"][5:]}'
            draw.text((x + 4, y + 402), "\n".join(textwrap.wrap(label, 48)[:4]), fill="black", font=small)
        sheet.save(directory / "sheet.jpg", quality=90)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("titles", nargs="+")
    parser.add_argument("--sheets-only", action="store_true")
    parser.add_argument("--search", help="Custom Commons query for a single person")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--category", help="Commons category (without Category: prefix)")
    parser.add_argument("--files", nargs="+", help="Explicit Commons file titles for a single person")
    args = parser.parse_args()
    if (args.search or args.files or args.category) and len(args.titles) != 1:
        parser.error("--search, --files and --category require exactly one person")
    if not args.sheets_only:
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(
                lambda title: collect(title, args.search, args.refresh, args.category, args.files),
                args.titles,
            ))
    sheets(args.titles)


if __name__ == "__main__":
    main()
