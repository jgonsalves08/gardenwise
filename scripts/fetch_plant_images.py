"""One-time helper: fetch one freely licensed photo per plant from Wikimedia Commons.

Run:  python scripts/fetch_plant_images.py           (skips plants that already have a photo)

For each plant it looks up the lead image of a Wikipedia article, asks Wikimedia Commons for a
~320 px thumbnail plus its license and author, keeps it only if the license is Creative Commons
or public domain, and re-encodes it with Pillow (pixels only, no metadata). Credits go to
data/plant_images/credits.json so the app and report can attribute every photo.
The app itself never calls the internet; it only reads the saved files.
"""

from __future__ import annotations

import html
import io
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import certifi
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "plant_images"
CREDITS = OUT / "credits.json"
UA = "Gardenwise-class-project/1.0 (Yale SOM course project; educational use)"
WIDTH = 320
SSL_CTX = ssl.create_default_context(cafile=certifi.where())  # verified TLS with Mozilla's CA bundle

ARTICLES = {
    "arugula": "Eruca vesicaria", "basil": "Basil", "bean_bush": "Green bean", "bean_pole": "Phaseolus vulgaris",
    "bee_balm": "Monarda didyma", "beet": "Beetroot", "calendula": "Calendula officinalis", "carrot": "Carrot",
    "chamomile": "Matricaria chamomilla", "chives": "Chives", "cilantro": "Coriander",
    "coneflower": "Echinacea purpurea", "corn_sweet": "Sweet corn", "cosmos": "Cosmos bipinnatus",
    "cucumber_pickling": "Cucumber", "dill": "Dill", "garlic": "Garlic", "kale": "Kale",
    "lavender": "Lavandula angustifolia", "lemon_balm": "Lemon balm", "lettuce": "Lettuce", "marigold": "Tagetes",
    "microgreens": "Microgreen", "mint": "Mentha", "nasturtium": "Tropaeolum majus", "onion_sets": "Onion",
    "oregano": "Oregano", "parsley": "Parsley", "pea_snap": "Snap pea", "pepper_bell": "Bell pepper",
    "pepper_jalapeno": "Jalapeño", "potato": "Potato", "pumpkin": "Pumpkin", "radish": "Radish",
    "scallion": "Scallion", "spinach": "Spinach", "squash_butternut": "Butternut squash",
    "strawberry": "Garden strawberry", "sunflower": "Helianthus annuus", "swiss_chard": "Chard",
    "thyme": "Thymus vulgaris", "tomatillo": "Tomatillo", "tomato_cherry": "Cherry tomato",
    "tomato_paste": "Roma tomato", "tomato_slicing": "Tomato", "winter_rye": "Rye", "zinnia": "Zinnia",
    "zucchini": "Zucchini",
}
OK_LICENSE = re.compile(r"^(cc|public domain|pd)", re.IGNORECASE)


FALLBACKS = {"bean_bush": "Phaseolus vulgaris", "cucumber_pickling": "Gherkin", "microgreens": "Sprouting",
             "winter_rye": "Secale cereale", "tomato_paste": "Plum tomato", "scallion": "Allium fistulosum",
             "parsley": "Petroselinum crispum", "sunflower": "Sunflower seed"}


def fetch(url: str, limit: int = 3_000_000) -> bytes:
    """GET with polite retries: Wikimedia rate-limits bursts (HTTP 429), so back off and retry."""
    for attempt in range(5):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as r:
                return r.read(limit)
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 4:
                raise
            wait = int(e.headers.get("Retry-After") or 0) or 5 * (attempt + 1)
            time.sleep(min(wait, 60))
    raise RuntimeError("unreachable")


def get_json(url: str) -> dict:
    return json.loads(fetch(url).decode())


def strip_tags(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def lead_image(title: str) -> str | None:
    q = urllib.parse.urlencode({"action": "query", "titles": title, "prop": "pageimages", "piprop": "name",
                                "redirects": 1, "format": "json"})
    pages = get_json(f"https://en.wikipedia.org/w/api.php?{q}")["query"]["pages"]
    return next(iter(pages.values())).get("pageimage")


def commons_info(filename: str) -> dict | None:
    q = urllib.parse.urlencode({"action": "query", "titles": f"File:{filename}", "prop": "imageinfo",
                                "iiprop": "url|extmetadata", "iiurlwidth": WIDTH, "format": "json"})
    pages = get_json(f"https://commons.wikimedia.org/w/api.php?{q}")["query"]["pages"]
    info = next(iter(pages.values())).get("imageinfo")
    return info[0] if info else None


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    credits = json.loads(CREDITS.read_text()) if CREDITS.exists() else {}
    for pid, title in ARTICLES.items():
        dest = OUT / f"{pid}.jpg"
        if dest.exists() and pid in credits:
            continue
        try:
            info = meta = None
            lic = ""
            for t in [title] + ([FALLBACKS[pid]] if pid in FALLBACKS else []):
                fname = lead_image(t)
                info = commons_info(fname) if fname else None
                if not info:
                    continue
                meta = info.get("extmetadata", {})
                lic = strip_tags(meta.get("LicenseShortName", {}).get("value", ""))
                if OK_LICENSE.match(lic):
                    title = t
                    break
                info = None
            if not info:
                print(f"  {pid}: no CC/public-domain image found (last license seen: '{lic}')")
                continue
            raw = fetch(info["thumburl"])
            img = Image.open(io.BytesIO(raw)).convert("RGB")       # validates it really is an image
            img.thumbnail((WIDTH, WIDTH))
            clean = Image.new("RGB", img.size)
            clean.paste(img)                                         # pixels only, no metadata
            clean.save(dest, "JPEG", quality=82)
            credits[pid] = {
                "file": f"{pid}.jpg", "article": title, "commons_file": fname,
                "author": re.sub(r"(.+?)\1+$", r"\1", strip_tags(meta.get("Artist", {}).get("value", "")))[:120]
                          or "Unknown",
                "license": lic, "license_url": meta.get("LicenseUrl", {}).get("value", ""),
                "source": info.get("descriptionurl", ""),
            }
            print(f"  {pid}: {dest.stat().st_size // 1000} KB · {lic} · {credits[pid]['author'][:40]}")
            time.sleep(2.0)  # be polite to Wikimedia's servers
        except Exception as e:  # keep going; the app falls back to an emoji icon
            print(f"  {pid}: failed ({type(e).__name__}: {e})")
    CREDITS.write_text(json.dumps(credits, indent=2, ensure_ascii=False))
    print(f"{len(credits)}/{len(ARTICLES)} plants have photos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
