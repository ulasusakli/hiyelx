import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STUDIO = ROOT / "studio"

P1_HASHES = {
    "index.html": "b53a73f667a22caeb5c98f7ac57f51d444311f95f65bf53005723ba09c608660",
    "studio.css": "16e5d0d4545a123c1ccd2a08449f3c8863304735a75f011f130f20f92d20ea01",
    "fixtures.js": "19a6f1382780e6e39e961c8498c8cc9fb2030f382003dda931d2a33da806f864",
    "app.js": "9b15474eee9dea77371caffedbb3cedf1c2542a5fd9870be105e0518f599d9ca",
}


def test_accepted_p1_assets_remain_byte_identical() -> None:
    assert {
        name: hashlib.sha256((STUDIO / name).read_bytes()).hexdigest()
        for name in P1_HASHES
    } == P1_HASHES


def test_p2_controller_is_a_separate_uncomposed_asset() -> None:
    assert (STUDIO / "host-client.js").is_file()
    for name in P1_HASHES:
        assert "host-client.js" not in (STUDIO / name).read_text()
