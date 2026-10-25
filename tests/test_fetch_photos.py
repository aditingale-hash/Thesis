"""Photo script with a fake Wikimedia Commons (no internet): licence filter, no reuse, --next, credits."""

import io
import json

import httpx
import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402

from shop.tools import fetch_photos  # noqa: E402


def _jpeg(color, size=(800, 600)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, "JPEG")
    return out.getvalue()


def _page(i, title, license="CC BY-SA 4.0", mime="image/jpeg", width=1200):
    return {"index": i, "title": title, "imageinfo": [{
        "mime": mime, "width": width, "descriptionurl": f"https://commons.wikimedia.org/wiki/{title}",
        "thumburl": f"https://thumb.wikimedia.org/x/500px-{title}.jpg",
        "extmetadata": {"LicenseShortName": {"value": license}, "Artist": {"value": "<a href='u'>Jane Doe</a>"}}}]}


def fake_commons():
    """Every search returns the same 4 files: 1 good, 1 non-free, 1 too small, 2 more good ones."""
    pages = {"a": _page(1, "File:Good one.jpg"), "b": _page(2, "File:Non free.jpg", license="Fair use"),
             "c": _page(3, "File:Tiny.jpg", width=300), "d": _page(4, "File:Good two.jpg"),
             "e": _page(5, "File:Good three.jpg", license="CC0")}
    hosts = []

    def handler(request):
        hosts.append(request.url.host)
        if request.url.path.endswith("api.php"):
            return httpx.Response(200, json={"query": {"pages": pages}})
        return httpx.Response(200, content=_jpeg("red", (500, 300)))

    return fetch_photos.Commons(transport=httpx.MockTransport(handler), delay=0, rate_limit_wait=0), hosts


def test_licence_filter_and_thumb_host():
    commons, hosts = fake_commons()
    titles = [c["title"] for c in commons.search("mouse")]
    assert titles == ["File:Good one.jpg", "File:Good two.jpg", "File:Good three.jpg"]
    assert commons.search("mouse")[0]["author"] == "Jane Doe"
    assert all(c["thumb"].startswith("https://upload.wikimedia.org/") for c in commons.search("mouse"))


def test_image_is_padded_to_500x375_on_white():
    image = Image.open(io.BytesIO(fetch_photos.to_product_image(_jpeg("blue", (300, 600)))))
    assert image.size == (500, 375)
    assert image.getpixel((5, 187))[0] > 240  # white padding at the side


def test_run_assigns_distinct_photos_credits_review_and_next(tmp_path):
    commons, _ = fake_commons()
    only = [101, 102, 103]
    state = fetch_photos.run(only=only, commons=commons, photo_dir=tmp_path)
    titles = [state[str(i)]["title"] for i in only]
    assert titles == ["File:Good one.jpg", "File:Good two.jpg", "File:Good three.jpg"]   # never reused
    assert all((tmp_path / f"{i}.jpg").exists() for i in only)
    credits = (tmp_path / "CREDITS.md").read_text()
    assert "| 101 Wireless Mouse M2 | [File:Good one.jpg]" in credits and "CC BY-SA 4.0" in credits
    assert "Jane Doe" in credits
    assert "101.jpg" in (tmp_path / "review.html").read_text()
    # --next: product 103's photo is rejected; no free candidate is left, so it keeps no photo
    state = fetch_photos.run(replace=[103], commons=commons, photo_dir=tmp_path)
    assert "title" not in state["103"] and state["103"]["rejected"] == ["File:Good three.jpg"]
    # rejecting 101 makes "Good one" unusable for 101 but frees nothing else: 101 takes "Good three"
    state = fetch_photos.run(replace=[101], commons=commons, photo_dir=tmp_path)
    assert state["101"]["title"] == "File:Good three.jpg" and state["101"]["rejected"] == ["File:Good one.jpg"]
    assert json.loads((tmp_path / "photos.json").read_text())["101"]["title"] == "File:Good three.jpg"
