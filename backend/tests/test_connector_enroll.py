"""Setup download: one exe, token only in the filename, hashed on the server."""
import hashlib
from datetime import timedelta
from pathlib import Path

from p2g.connector_auth import credential_hash
from p2g.connector_enroll import (
    ENROLL_MINUTES,
    PUBLIC_ENROLL_ERROR,
    SETUP_PREFIX,
    build_enrollment,
    choose_device,
    enrollment_download,
    enrollment_expiry,
    enrollment_rate_limited,
    enrollment_state,
    public_enrollment,
    published_connector_update,
    setup_filename,
    setup_token_from_filename,
    verify_sha256,
)


ROOT = Path(__file__).resolve().parents[2]
TOKEN = "setup-token-value-0123456789"


def test_enrollment_is_shop_bound_and_stores_only_a_hash():
    user = {"id": "admin-1", "shop_id": "shop-1", "role": "admin"}
    created = "2026-10-23T00:00:00+00:00"
    row = build_enrollment(user, TOKEN, created, enrollment_id="enroll-1", current_shop="shop-1")
    assert row["shop_id"] == "shop-1"
    assert row["created_by"] == "admin-1"
    assert row["token_hash"] == credential_hash(TOKEN)
    assert row["token_hash"] != TOKEN
    assert TOKEN not in row["token_hash"]
    assert "token" not in row
    assert row["audit"][0]["action"] == "created"
    expires = enrollment_expiry(created, ENROLL_MINUTES)
    assert expires > created
    assert expires <= "2026-10-23T00:30:00+00:00" or expires.startswith("2026-10-23T00:30")
    assert enrollment_state(row, created) == "open"
    assert enrollment_state(None, created) == "missing"
    assert enrollment_state({**row, "status": "used", "used_at": created}, created) == "used"
    assert enrollment_state({**row, "status": "revoked", "revoked_at": created}, created) == "revoked"
    assert enrollment_state(row, expires) == "expired"
    assert PUBLIC_ENROLL_ERROR == "This setup link is invalid or expired."


def test_sixth_download_in_ten_minutes_is_limited():
    start = "2026-10-23T00:00:00+00:00"
    stamps = [f"2026-10-23T00:0{index}:00+00:00" for index in range(5)]
    assert enrollment_rate_limited(stamps, "2026-10-23T00:09:00+00:00") is True
    assert enrollment_rate_limited(stamps[:4], "2026-10-23T00:09:00+00:00") is False
    old = (enrollment_expiry(start, 0))
    assert old
    assert enrollment_rate_limited(["2026-10-22T00:00:00+00:00"] * 6, start) is False


def test_one_computer_is_reused_and_the_download_is_the_same_exe():
    only = [{"_id": "device-1", "enabled": True}]
    assert choose_device(only, "device-new") == ("device-1", "rotate")
    assert choose_device(only, "device-1") == ("device-1", "rotate")
    assert choose_device([{"_id": "a", "enabled": True}, {"_id": "b", "enabled": True}], "device-new") == ("device-new", "create")
    payload = b"MZ-published-connector"
    body, filename = enrollment_download(payload, TOKEN)
    assert body == payload
    assert TOKEN.encode() not in body
    assert filename == f"{SETUP_PREFIX}{TOKEN}.exe"
    assert setup_token_from_filename(filename) == TOKEN
    assert setup_token_from_filename(r"C:\Users\Op\Downloads\\" + filename) == TOKEN
    assert setup_token_from_filename("MyraanaConnector-Setup.exe") == ""
    assert setup_filename(TOKEN) == filename


def test_public_row_and_update_manifest_hide_secrets():
    created = "2026-10-23T00:00:00+00:00"
    row = build_enrollment(
        {"id": "admin-1", "shop_id": "shop-1"}, TOKEN, created, enrollment_id="enroll-1",
    )
    public = public_enrollment(row, created)
    assert "token_hash" not in public
    assert TOKEN not in str(public)
    digest = hashlib.sha256(b"exe").hexdigest()
    manifest = published_connector_update({
        "CONNECTOR_UPDATE_URL": "https://github.com/example/releases/download/v1/MyraanaConnector.exe",
        "CONNECTOR_UPDATE_SHA256": digest,
        "CONNECTOR_UPDATE_VERSION": "1",
    })
    assert manifest["sha256"] == digest
    assert manifest["url"].startswith("https://")
    assert published_connector_update({"CONNECTOR_UPDATE_URL": "http://example.com/a.exe", "CONNECTOR_UPDATE_SHA256": digest}) is None
    assert published_connector_update({"CONNECTOR_UPDATE_URL": "https://example.com/a.exe"}) is None
    assert verify_sha256(b"exe", digest) is True
    assert verify_sha256(b"other", digest) is False


def test_site_asks_for_one_setup_file_and_keeps_the_hold_rules():
    server = (ROOT / "backend" / "server.py").read_text(encoding="utf-8")
    pairing = (ROOT / "backend" / "p2g" / "connector_pairing.py").read_text(encoding="utf-8")
    app = (ROOT / "frontend" / "src" / "App.js").read_text(encoding="utf-8")
    connector = (ROOT / "frontend" / "public" / "setup" / "myraana-connector.py").read_text(encoding="utf-8")
    build = (ROOT / "frontend" / "public" / "setup" / "build-myraana-connector.ps1").read_text(encoding="utf-8")
    assert '"/connector-enrollments"' in server
    assert "create_enrollment_package" in server
    assert 'action == "run-job"' in server
    assert "stage_fiery_hold" in server
    assert "Nothing was printed." in server
    assert "enrollment_download" in pairing
    assert "inject_enrollment" not in pairing
    assert "hotFolder" not in pairing
    assert "Connect this computer to your printers" in app
    assert "Connect this computer" in app
    assert "Open the file that just downloaded. That's it." in app
    assert "Other ways to connect" in app
    assert "This computer is connected · Fiery" in app
    assert "Automatic mode" in app
    assert "Run job" in app
    assert "Fix and retry" in app
    assert "Approved by customer" in app
    assert 'data-testid="connect-this-computer-button"' in app
    assert "MyraanaConnector-Setup-" in connector
    assert "Connected to Myraana. Fiery found." in connector
    assert "LOCALAPPDATA" in connector
    assert "MyraanaConnector.exe" in connector
    assert "--onefile" in build
    assert "hotFolder" not in connector.split("def perform_holds", 1)[1].split("\nRUN_KEY", 1)[0]
    mirror = (ROOT / "artifacts" / "myraana-windows-connector" / "myraana-connector.py").read_bytes()
    assert mirror == (ROOT / "frontend" / "public" / "setup" / "myraana-connector.py").read_bytes()
