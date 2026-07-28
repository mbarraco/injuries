import os

from app.main import HERE

VENDOR_COMMAND = ("curl -L -o app/static/htmx.min.js "
                  "https://unpkg.com/htmx.org@2.0.4/dist/htmx.min.js")


def test_htmx_is_vendored():
    """Vendored rather than loaded from a CDN, matching chart.min.js.

    A CDN tag would make every page view a request to a third party carrying
    the referring URL — which player, which team — and would break the app
    entirely offline.
    """
    path = os.path.join(HERE, "static", "htmx.min.js")
    assert os.path.exists(path), f"htmx is not vendored yet — run: {VENDOR_COMMAND}"
    assert os.path.getsize(path) > 10_000, "file is too small to be htmx; the download probably failed"


def test_pages_load_htmx(client):
    assert "/static/htmx.min.js" in client.get("/").text
