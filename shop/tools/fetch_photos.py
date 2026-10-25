"""Download one freely licensed product photo per product from Wikimedia Commons.

Run on your own computer (the download needs internet; Wikimedia rate-limits shared servers):

    python -m shop.tools.fetch_photos              # all products without a photo (about 10-15 minutes)
    python -m shop.tools.fetch_photos --next 101 205   # replace these photos with the next candidate
    python -m shop.tools.fetch_photos --only 101       # (re)fetch only these products

For every product the first suitable search result is used: JPEG/PNG, at least 600 px wide,
licence CC0, public domain, CC BY or CC BY-SA, and not already used for another product.
The image is scaled into 500x375 px on a white background and saved as
``shop/static/products/<id>.jpg``. Author, licence and source are recorded in
``CREDITS.md`` (for the thesis appendix), and ``review.html`` shows all photos for checking.
Replace any photo that shows brand logos, readable text, prices or the wrong product type
with ``--next``.
"""

import argparse
import html
import io
import json
import re
import sys
import time
from pathlib import Path

import httpx

from shop import db

PHOTO_DIR = db.SHOP_DIR / "static" / "products"
QUERIES = db.SHOP_DIR / "data" / "photo_queries.json"
STATE = PHOTO_DIR / "photos.json"
API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "TechDeskThesisPrototype/1.0 (https://github.com/aditingale-hash/Thesis; research prototype, TU Chemnitz)"
SIZE = (500, 375)
LICENSES = re.compile(r"^(CC0|Public domain|PD\b|CC BY(-SA)? \d)", re.I)


def _clean(text) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


class Commons:
    """Minimal Wikimedia Commons client: polite (delay between requests) and patient on rate limits."""

    def __init__(self, transport=None, delay: float = 3.0, rate_limit_wait: float = 60.0):
        self.http = httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=True,
                                 transport=transport)
        self.delay, self.rate_limit_wait = delay, rate_limit_wait
        self.cache: dict[str, list[dict]] = {}

    def _get(self, url: str, **params) -> httpx.Response:
        for _ in range(6):
            r = self.http.get(url, params=params or None)
            if r.status_code in (403, 429):
                print(f"  Wikimedia asks to slow down; waiting {self.rate_limit_wait:.0f} s ...", flush=True)
                time.sleep(self.rate_limit_wait)
                continue
            r.raise_for_status()
            time.sleep(self.delay)
            return r
        raise RuntimeError("Wikimedia keeps refusing requests; try again later.")

    def search(self, query: str) -> list[dict]:
        """Suitable candidates for a search phrase, in search-ranking order."""
        if query not in self.cache:
            data = self._get(API, action="query", format="json", generator="search",
                             gsrsearch=f"{query} filetype:bitmap", gsrnamespace=6, gsrlimit=20,
                             prop="imageinfo", iiprop="url|extmetadata|size|mime", iiurlwidth=SIZE[0]).json()
            pages = sorted(data.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 0))
            found = []
            for page in pages:
                info = (page.get("imageinfo") or [{}])[0]
                meta = info.get("extmetadata", {})
                license_name = _clean(meta.get("LicenseShortName", {}).get("value"))
                if (info.get("mime") not in ("image/jpeg", "image/png") or info.get("width", 0) < 600
                        or not LICENSES.match(license_name) or not info.get("thumburl")):
                    continue
                found.append({
                    "title": page["title"],
                    "author": _clean(meta.get("Artist", {}).get("value")) or "unknown",
                    "license": license_name,
                    "source": info.get("descriptionurl", ""),
                    "thumb": info["thumburl"].replace("//thumb.wikimedia.org", "//upload.wikimedia.org"),
                    "query": query,
                })
            self.cache[query] = found
        return self.cache[query]

    def download(self, url: str) -> bytes:
        return self._get(url).content


def to_product_image(data: bytes) -> bytes:
    """Scale the photo into 500x375 px on white (keeping its proportions) and return JPEG bytes."""
    from PIL import Image

    image = Image.open(io.BytesIO(data)).convert("RGB")
    scale = min(SIZE[0] / image.width, SIZE[1] / image.height)
    image = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))), Image.LANCZOS)
    canvas = Image.new("RGB", SIZE, "white")
    canvas.paste(image, ((SIZE[0] - image.width) // 2, (SIZE[1] - image.height) // 2))
    out = io.BytesIO()
    canvas.save(out, "JPEG", quality=85)
    return out.getvalue()


def fetch_one(commons: Commons, product: dict, queries: list[str], state: dict, photo_dir: Path) -> dict | None:
    """Find, download and save the photo of one product; return its state entry (None if nothing found)."""
    pid = str(product["id"])
    used = {entry["title"] for key, entry in state.items() if key != pid and "title" in entry}
    rejected = set(state.get(pid, {}).get("rejected", []))
    for query in queries:
        for candidate in commons.search(query):
            if candidate["title"] in used or candidate["title"] in rejected:
                continue
            try:
                image = to_product_image(commons.download(candidate["thumb"]))
            except Exception as e:  # broken file or download error: try the next candidate
                print(f"  {pid}: skipped {candidate['title']} ({e})", flush=True)
                rejected.add(candidate["title"])
                continue
            (photo_dir / f"{pid}.jpg").write_bytes(image)
            return {**candidate, "product": product["name"], "rejected": sorted(rejected)}
    return None


def write_credits(state: dict, products: list[dict], photo_dir: Path) -> None:
    lines = ["# Product photo credits", "",
             "All photos are from Wikimedia Commons, scaled to 500x375 px on a white background.", "",
             "| Product | Photo | Author | Licence |", "|---|---|---|---|"]
    for p in products:
        e = state.get(str(p["id"]))
        if e and "title" in e:
            author = e["author"].replace("|", "/").replace("\n", " ")
            lines.append(f"| {p['id']} {p['name']} | [{e['title']}]({e['source']}) | {author} | {e['license']} |")
    (photo_dir / "CREDITS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_review(state: dict, products: list[dict], photo_dir: Path) -> None:
    cards = []
    for p in products:
        pid = str(p["id"])
        img = f'<img src="{pid}.jpg" alt="" width="250">' if (photo_dir / f"{pid}.jpg").exists() else "<p>(no photo)</p>"
        cards.append(f"<figure>{img}<figcaption><b>{pid}</b> {html.escape(p['name'])}</figcaption></figure>")
    (photo_dir / "review.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>Product photos</title>"
        "<style>body{font-family:sans-serif;display:flex;flex-wrap:wrap;gap:12px}figure{margin:0;width:250px}"
        "img{border:1px solid #ccc}</style>"
        "<h1 style='width:100%'>Check every photo: no logos, no readable text, no prices, right product type. "
        "Replace bad ones with: python -m shop.tools.fetch_photos --next &lt;ids&gt;</h1>" + "".join(cards),
        encoding="utf-8")


def run(only=None, replace=None, commons: Commons | None = None, photo_dir: Path = PHOTO_DIR) -> dict:
    """Fetch missing photos (or ``only`` / ``replace`` the given ids) and update credits and review page."""
    catalogue = json.loads(db.CATALOGUE_PATH.read_text(encoding="utf-8"))
    queries = json.loads(QUERIES.read_text(encoding="utf-8"))
    photo_dir.mkdir(parents=True, exist_ok=True)
    state_path = photo_dir / STATE.name
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    commons = commons or Commons()
    targets = {str(i) for i in (only or []) + (replace or [])}
    for pid in map(str, replace or []):
        if "title" in state.get(pid, {}):  # remember the rejected photo so it is not chosen again
            state[pid] = {"rejected": state[pid]["rejected"] + [state[pid]["title"]]}
    for product in catalogue["products"]:
        pid = str(product["id"])
        if targets and pid not in targets:
            continue
        if not targets and "title" in state.get(pid, {}) and (photo_dir / f"{pid}.jpg").exists():
            continue
        print(f"{pid} {product['name']} ...", flush=True)
        entry = fetch_one(commons, product, queries["products"][pid] + [queries["categories"][product["category"]]],
                          state, photo_dir)
        if entry is None:
            print(f"  {pid}: no suitable photo found; the category illustration stays", flush=True)
            state[pid] = {"rejected": state.get(pid, {}).get("rejected", [])}
        else:
            state[pid] = entry
        state_path.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")
    write_credits(state, catalogue["products"], photo_dir)
    write_review(state, catalogue["products"], photo_dir)
    found = sum("title" in e for e in state.values())
    print(f"{found}/{len(catalogue['products'])} products have a photo. Check {photo_dir / 'review.html'}")
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description="Download product photos from Wikimedia Commons")
    parser.add_argument("--next", nargs="+", type=int, default=[], help="replace these products' photos")
    parser.add_argument("--only", nargs="+", type=int, default=[], help="(re)fetch only these products")
    args = parser.parse_args()
    run(only=args.only, replace=args.next)
    return 0


if __name__ == "__main__":
    sys.exit(main())
