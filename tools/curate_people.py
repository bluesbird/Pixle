"""Download license-checked Wikimedia portraits and make reproducible square crops."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import html
import io
import json
from pathlib import Path
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[1]
PEOPLE = ROOT / "people"
IMAGES = PEOPLE / "images"
USER_AGENT = "PixlePeopleDataset/1.0 (Wikimedia portrait curation; Python urllib)"
SIZE = 768
LOCAL = threading.local()


def now():
    return datetime.now(timezone.utc).isoformat()


def plain(value):
    return html.unescape(re.sub(r"<[^>]*>", "", str(value))).strip()


def slug(name):
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def fetch(url):
    for attempt in range(5):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=90) as response:
                data = response.read(40 * 1024 * 1024 + 1)
                if len(data) > 40 * 1024 * 1024:
                    raise ValueError(f"Response exceeds 40 MiB: {url}")
                return data
        except urllib.error.HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == 4:
                raise
            retry_after = float(error.headers.get("Retry-After", 0))
            if retry_after > 120:
                raise
            time.sleep(max(retry_after, 3 * 2**attempt))
        except (urllib.error.URLError, TimeoutError):
            if attempt == 4:
                raise
            time.sleep(3 * 2**attempt)


def api(host, **params):
    url = f"https://{host}/w/api.php?" + urllib.parse.urlencode(
        {"action": "query", "format": "json", **params}
    )
    result = json.loads(fetch(url))
    if "error" in result:
        raise ValueError(f"Wikimedia API error: {result['error']}")
    return result.get("query", {})


def lead_images(titles):
    result = {}
    for start in range(0, len(titles), 40):
        query = api(
            "en.wikipedia.org", titles="|".join(titles[start:start + 40]),
            redirects=1, prop="pageimages", piprop="original", pilicense="free",
        )
        aliases = {
            entry["from"]: entry["to"]
            for key in ("normalized", "redirects") for entry in query.get(key, [])
        }
        pages = {page["title"]: page for page in query["pages"].values()}
        for title in titles[start:start + 40]:
            canonical = title
            while canonical in aliases:
                canonical = aliases[canonical]
            result[title] = pages[canonical]
    return result


def source_info(file_title, width=1600):
    query = api(
        "commons.wikimedia.org", titles=file_title, prop="imageinfo",
        iiprop="url|extmetadata|size|sha1|timestamp", iiurlwidth=width,
        iiextmetadatalanguage="en",
    )
    page = next(iter(query["pages"].values()))
    if "imageinfo" not in page:
        raise ValueError(f"No Commons image metadata for {file_title}")
    return page["imageinfo"][0]


def check_license(info):
    metadata = info["extmetadata"]
    values = {key: plain(item["value"]) for key, item in metadata.items()}
    name = values.get("LicenseShortName", "")
    url = values.get("LicenseUrl", "")
    creative_commons = re.fullmatch(
        r"https?://creativecommons\.org/(licenses/(by|by-sa)/[0-9.]+(?:/[a-z-]+)?|publicdomain/(zero/1\.0|mark/1\.0))/?(?:deed\.[a-z-]+)?",
        url,
    )
    public_domain = name in ("Public domain", "CC0")
    ogl = name == "OGL 3" and re.fullmatch(
        r"https?://www\.nationalarchives\.gov\.uk/doc/open-government-licence/version/3/?", url
    )
    if not (creative_commons or public_domain or ogl):
        raise ValueError(f"Unapproved or ambiguous license: {name!r}, {url!r}")
    if values.get("NonFree", "").lower() in ("true", "1", "yes"):
        raise ValueError("File is marked non-free")
    return {
        "name": name,
        "url": url or "https://commons.wikimedia.org/wiki/Commons:Public_domain",
        "artist": values.get("Artist", ""),
        "credit": values.get("Credit", ""),
        "copyright_notice": values.get("Copyright", ""),
        "attribution_statement": values.get("Attribution", ""),
        "usage_terms": values.get("UsageTerms", ""),
        "attribution_required": values.get("AttributionRequired", ""),
        "restrictions": values.get("Restrictions", ""),
        "raw_extmetadata": metadata,
    }


def square_crop(image, override=None):
    width, height = image.size
    face = None
    if override is not None:
        box = tuple(override)
        if not (0 <= box[0] < box[2] <= width and 0 <= box[1] < box[3] <= height):
            raise ValueError(f"Invalid crop {box} for {image.size}")
        if box[2] - box[0] != box[3] - box[1]:
            raise ValueError("Manual crop must be square")
        method = "manual"
    else:
        if not hasattr(LOCAL, "detector"):
            LOCAL.detector = cv2.CascadeClassifier(
                cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            )
        detection_scale = min(1.0, 960 / max(width, height))
        preview = image.resize((round(width * detection_scale), round(height * detection_scale)))
        gray = cv2.cvtColor(np.array(preview), cv2.COLOR_RGB2GRAY)
        faces = LOCAL.detector.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40)
        )
        faces = [tuple(round(int(value) / detection_scale) for value in f) for f in faces]
        faces = [f for f in faces if f[3] >= min(width, height) * 0.12]
        if len(faces):
            x, y, fw, fh = map(int, max(faces, key=lambda f: int(f[2]) * int(f[3])))
            face = [x, y, fw, fh]
            side = min(width, height, max(int(fh * 4), int(fw * 2.8)))
            left = max(0, min(width - side, round(x + fw / 2 - side / 2)))
            top = max(0, min(height - side, round(y - fh * 0.45)))
            method = "largest-face-guided"
        else:
            side = min(width, height)
            left = (width - side) // 2
            top = round((height - side) * 0.15)
            method = "top-biased-center"
        box = (left, top, left + side, top + side)
    cropped = image.crop(box).resize((SIZE, SIZE), Image.Resampling.LANCZOS)
    return cropped, {"method": method, "box_xyxy": list(box), "detected_face_xywh": face}


def process(entry, page, overrides):
    title = entry["wikipedia_title"]
    name = re.sub(r" \([^)]*\)$", "", page["title"])
    identifier = slug(name)
    result = {**entry, "name": name, "id": identifier, "status": "missing"}
    try:
        override = overrides.get(title, {})
        if "file_title" in override:
            file_title = override["file_title"]
        else:
            original = page.get("original", {}).get("source")
            if not original:
                raise ValueError("No freely licensed Wikipedia lead image")
            path = urllib.parse.urlsplit(original).path
            if "/wikipedia/commons/" not in path:
                raise ValueError("Lead image is not hosted on Wikimedia Commons")
            file_title = "File:" + urllib.parse.unquote(path.rsplit("/", 1)[-1])
        info = source_info(file_title, override.get("download_width", 1600))
        license_info = check_license(info)
        if not license_info["artist"] and license_info["name"] not in ("Public domain", "CC0"):
            raise ValueError("Attribution author missing")
        image_url = info.get("thumburl", info["url"])
        data = fetch(image_url)
        cache = ROOT / ".people-review" / "sources"
        cache.mkdir(parents=True, exist_ok=True)
        (cache / f"{identifier}.bin").write_bytes(data)
        with Image.open(io.BytesIO(data)) as original_image:
            image = ImageOps.exif_transpose(original_image).convert("RGB")
        cropped, crop = square_crop(image, override.get("crop"))
        IMAGES.mkdir(parents=True, exist_ok=True)
        output = IMAGES / f"{identifier}.jpg"
        cropped.save(output, "JPEG", quality=94, subsampling=0)
        result.update(
            status="downloaded", filename=output.name, width=SIZE, height=SIZE,
            wikipedia_url="https://en.wikipedia.org/wiki/" + urllib.parse.quote(page["title"].replace(" ", "_")),
            source_file_title=file_title, source_page_url=info["descriptionurl"],
            source_original_url=info["url"], downloaded_url=image_url,
            source_width=info["width"], source_height=info["height"],
            source_revision_timestamp=info["timestamp"], source_sha1=info["sha1"],
            downloaded_sha256=hashlib.sha256(data).hexdigest(),
            output_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
            downloaded_dimensions=list(image.size), crop=crop, license=license_info,
            retrieved_at=now(), visual_review="pending",
        )
    except (ValueError, KeyError, OSError, urllib.error.URLError) as error:
        result["failure_reason"] = f"{type(error).__name__}: {error}"
    return result


def recrop(record, overrides):
    if record["status"] != "downloaded":
        return record
    record = {key: value for key, value in record.items() if key != "visual_reviewed_at"}
    cache = ROOT / ".people-review" / "sources" / f'{record["id"]}.bin'
    if cache.exists():
        data = cache.read_bytes()
        if hashlib.sha256(data).hexdigest() != record["downloaded_sha256"]:
            expected = record["source_sha1"]
            actual = hashlib.sha1(data).hexdigest()
            matches = actual == expected if len(expected) == 40 else int(actual, 16) == int(expected, 36)
            if not matches:
                raise ValueError(f'Cached source changed for {record["name"]}')
            record = {
                **record, "downloaded_url": record["source_original_url"],
                "downloaded_sha256": hashlib.sha256(data).hexdigest(),
            }
    else:
        data = fetch(record["downloaded_url"])
        if hashlib.sha256(data).hexdigest() != record["downloaded_sha256"]:
            raise ValueError(f'Source changed for {record["name"]}; refresh metadata first')
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(data)
    with Image.open(io.BytesIO(data)) as original:
        image = ImageOps.exif_transpose(original).convert("RGB")
    crop_override = overrides.get(record["wikipedia_title"], {}).get("crop")
    cropped, crop = square_crop(image, crop_override)
    output = IMAGES / record["filename"]
    cropped.save(output, "JPEG", quality=94, subsampling=0)
    print(f'Recropped: {record["name"]}', flush=True)
    return {
        **record, "crop": crop, "downloaded_dimensions": list(image.size),
        "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "visual_review": "pending",
    }


def save_metadata(records):
    for record in records:
        if record["status"] != "downloaded":
            continue
        license_info = record["license"]
        attribution = (
            f'{record["name"]} - {license_info["artist"] or "Author not specified (public domain)"}; '
            f'{license_info["name"]} ({license_info["url"]}); '
            f'{record["source_page_url"]}. Modified: square crop, resized to {SIZE}x{SIZE}, '
            "converted to JPEG; source metadata removed."
        )
        for label, key in (
            ("Credit", "credit"), ("Copyright notice", "copyright_notice"),
            ("Source attribution statement", "attribution_statement"),
        ):
            value = license_info.get(key, "")
            if not value and key == "attribution_statement":
                value = plain(license_info["raw_extmetadata"].get("Attribution", {}).get("value", ""))
            if value:
                attribution += f" {label}: {value}."
        if license_info["name"] == "OGL 3":
            attribution += " Contains public sector information licensed under the Open Government Licence v3.0."
        record["attribution"] = attribution
    payload = {
        "title": f"{len(records)} recognizable people: curated editorial selection",
        "generated_at": now(),
        "selection_note": "Not a measured ranking or claim of universal recognition. See README.md.",
        "requested_count": sum(len(titles) for titles in json.loads(
            (PEOPLE / "selection.json").read_text(encoding="utf-8")
        ).values()),
        "downloaded_count": sum(r["status"] == "downloaded" for r in records),
        "image_size": [SIZE, SIZE],
        "image_directory": IMAGES.relative_to(PEOPLE).as_posix(),
        "people": records,
    }
    temporary = PEOPLE / "metadata.json.tmp"
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(PEOPLE / "metadata.json")
    credits = ["# Image attributions", "", "Per-image licenses apply; this is not a blanket dataset license.", ""]
    missing = []
    for record in records:
        if record["status"] == "downloaded":
            credits.extend([f'## {record["name"]} ([`{record["filename"]}`](images/{record["filename"]}))', "", record["attribution"], ""])
        else:
            missing.append(f'- {record["name"]}: {record["failure_reason"]}')
    (PEOPLE / "ATTRIBUTIONS.md").write_text("\n".join(credits), encoding="utf-8")
    (PEOPLE / "MISSING.md").write_text(
        "# Missing images\n\n" + ("\n".join(missing) if missing else
            f"None. All {len(records)} selected people have an image.") + "\n",
        encoding="utf-8",
    )


def contact_sheets(records):
    font = ImageFont.load_default(size=15)
    for start in range(0, len(records), 25):
        sheet = Image.new("RGB", (1000, 1125), "white")
        draw = ImageDraw.Draw(sheet)
        for offset, record in enumerate(records[start:start + 25]):
            x, y = (offset % 5) * 200, (offset // 5) * 225
            if record["status"] == "downloaded":
                with Image.open(IMAGES / record["filename"]) as image:
                    sheet.paste(image.resize((200, 200)), (x, y))
            draw.text((x + 3, y + 202), f'{start + offset + 1}. {record["name"]}', fill="black", font=font)
        review_dir = ROOT / ".people-review"
        review_dir.mkdir(exist_ok=True)
        sheet.save(review_dir / f"contact-{start // 25 + 1}.jpg", quality=90)


def verify(records, require_review=True):
    selection = json.loads((PEOPLE / "selection.json").read_text(encoding="utf-8"))
    selected = {title for titles in selection.values() for title in titles}
    if len(records) != len(selected) or {r["wikipedia_title"] for r in records} != selected:
        raise ValueError(f"Metadata must contain exactly the {len(selected)} selected people")
    filenames = set()
    hashes = set()
    for record in records:
        if record["status"] != "downloaded":
            raise ValueError(f'Missing image for {record["name"]}')
        filename = record["filename"]
        if filename != slug(record["name"]) + ".jpg" or filename in filenames:
            raise ValueError(f"Invalid or duplicate filename: {filename}")
        filenames.add(filename)
        path = IMAGES / filename
        with Image.open(path) as image:
            if image.size != (SIZE, SIZE) or image.mode != "RGB" or image.format != "JPEG":
                raise ValueError(f"Invalid image dimensions, format or color mode: {filename}")
            image.load()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != record["output_sha256"] or digest in hashes:
            raise ValueError(f"Image hash mismatch or duplicate: {filename}")
        hashes.add(digest)
        license_info = check_license({"extmetadata": record["license"]["raw_extmetadata"]})
        if license_info["name"] != record["license"]["name"] or not record["attribution"]:
            raise ValueError(f"Invalid license or missing attribution: {filename}")
        if require_review and record["visual_review"] != "contact-sheet-reviewed":
            raise ValueError(f"Visual review is not recorded for {filename}")
        left, top, right, bottom = record["crop"]["box_xyxy"]
        width, height = record["downloaded_dimensions"]
        if not (0 <= left < right <= width and 0 <= top < bottom <= height and right-left == bottom-top):
            raise ValueError(f"Invalid source crop box: {filename}")
    if filenames != {path.name for path in IMAGES.glob("*.jpg")} or any(PEOPLE.glob("*.jpg")):
        raise ValueError("Unlisted or missing JPEG files")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="+", help="Refresh these Wikipedia titles only")
    parser.add_argument("--sheets-only", action="store_true")
    parser.add_argument("--recrop", action="store_true", help="Recrop existing, hash-verified downloads")
    parser.add_argument("--verify", action="store_true", help="Check all images, metadata, licenses and review status")
    parser.add_argument(
        "--approve-review", action="store_true",
        help="Record a completed visual inspection of all selected images; does not perform inspection",
    )
    args = parser.parse_args()
    existing_path = PEOPLE / "metadata.json"
    existing = json.loads(existing_path.read_text(encoding="utf-8"))["people"] if existing_path.exists() else []
    if args.verify:
        verify(existing)
        print(f"Verified {len(existing)} unique, square, licensed, visually reviewed photographs.")
        return
    if args.approve_review:
        verify(existing, require_review=False)
        for record in existing:
            record["visual_review"] = "contact-sheet-reviewed"
            record["visual_reviewed_at"] = now()
        save_metadata(existing)
        print(f"Recorded completed contact-sheet review for all {len(existing)} images.")
        return
    if args.sheets_only:
        contact_sheets(existing)
        return
    selection = json.loads((PEOPLE / "selection.json").read_text(encoding="utf-8"))
    entries = [{"wikipedia_title": title, "field": field} for field, titles in selection.items() for title in titles]
    if not entries or len({e["wikipedia_title"] for e in entries}) != len(entries):
        raise ValueError("Selection must contain unique people and must not be empty")
    if args.only and set(args.only) - {entry["wikipedia_title"] for entry in entries}:
        raise ValueError("--only contains a title outside selection.json")
    overrides_path = PEOPLE / "crop-overrides.json"
    overrides = json.loads(overrides_path.read_text(encoding="utf-8")) if overrides_path.exists() else {}
    if args.recrop:
        records = existing.copy()
        for index, record in enumerate(existing):
            if record["status"] == "downloaded" and (not args.only or record["wikipedia_title"] in args.only):
                records[index] = recrop(record, overrides)
                save_metadata(records)
        contact_sheets(records)
        count = sum(
            r["status"] == "downloaded" and (not args.only or r["wikipedia_title"] in args.only)
            for r in records
        )
        print(f"Recropped {count} images.", flush=True)
        return
    previous = {record["wikipedia_title"]: record for record in existing}
    wanted = [
        entry for entry in entries
        if (entry["wikipedia_title"] in args.only if args.only else
            previous.get(entry["wikipedia_title"], {}).get("status") != "downloaded")
    ]
    pages = lead_images([entry["wikipedia_title"] for entry in wanted])
    with ThreadPoolExecutor(max_workers=2) as pool:
        for result in pool.map(lambda e: process(e, pages[e["wikipedia_title"]], overrides), wanted):
            previous[result["wikipedia_title"]] = result
            print(f'{result["status"]}: {result["name"]}' + (f' - {result["failure_reason"]}' if result["status"] == "missing" else ""), flush=True)
            save_metadata([previous[e["wikipedia_title"]] for e in entries if e["wikipedia_title"] in previous])
    records = [previous[entry["wikipedia_title"]] for entry in entries]
    filenames = [record["filename"] for record in records if record["status"] == "downloaded"]
    if len(filenames) != len(set(filenames)):
        raise ValueError("Duplicate output filename")
    save_metadata(records)
    contact_sheets(records)
    missing = sum(record["status"] != "downloaded" for record in records)
    print(f"Finished: {len(records) - missing}/{len(records)} downloaded; {missing} missing.", flush=True)
    if missing:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
