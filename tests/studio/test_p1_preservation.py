import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STUDIO = ROOT / "studio"

PRESERVED_ASSET_HASHES = {
    "studio.css": "16e5d0d4545a123c1ccd2a08449f3c8863304735a75f011f130f20f92d20ea01",
    "fixtures.js": "19a6f1382780e6e39e961c8498c8cc9fb2030f382003dda931d2a33da806f864",
    "host-client.js": "eeeb5cebe3f3439c1c0e56c42386af21b85f82ca87c3a1a71009d4f3db2a056f",
}
P3_3_AUTHORIZED_COMPOSITION_ASSETS = ("index.html", "app.js")


def test_accepted_p1_and_p2_assets_outside_composition_remain_byte_identical() -> None:
    assert {
        name: hashlib.sha256((STUDIO / name).read_bytes()).hexdigest()
        for name in PRESERVED_ASSET_HASHES
    } == PRESERVED_ASSET_HASHES


def test_p3_3_authorizes_only_html_and_application_composition_assets() -> None:
    assert set(P3_3_AUTHORIZED_COMPOSITION_ASSETS).isdisjoint(PRESERVED_ASSET_HASHES)
    assert all((STUDIO / name).is_file() for name in P3_3_AUTHORIZED_COMPOSITION_ASSETS)
    html = (STUDIO / "index.html").read_text()
    assert html.index('src="host-client.js"') < html.index('src="app.js"')
