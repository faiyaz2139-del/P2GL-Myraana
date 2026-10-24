"""Setup download: verified exe plus a token trailer, hashed on the server."""
import hashlib
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from p2g.connector_auth import credential_hash
from p2g.connector_enroll import (
    DIAGNOSTIC_LIMIT,
    ENROLL_MINUTES,
    PREVIEW_EXE_URL,
    PREVIEW_SHA_URL,
    PUBLIC_ENROLL_ERROR,
    SETUP_PREFIX,
    TRAILER_MAGIC,
    PackageUnavailable,
    build_enrollment,
    choose_device,
    connector_package_bytes,
    enrollment_download,
    enrollment_expiry,
    enrollment_rate_limited,
    enrollment_state,
    fetch_https,
    prepare_setup_diagnostic,
    public_enrollment,
    public_setup_failure,
    published_connector_package,
    published_connector_update,
    setup_filename,
    setup_token_from_filename,
    setup_token_from_trailer_bytes,
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
    digest = hashlib.sha256(payload).hexdigest()
    body, filename = enrollment_download(payload, TOKEN, expected_sha256=digest)
    assert body.startswith(payload)
    assert hashlib.sha256(body[:len(payload)]).hexdigest() == digest
    assert TOKEN.encode() not in body[:len(payload)]
    assert setup_token_from_trailer_bytes(body) == TOKEN
    assert body.endswith(len(TOKEN.encode()).to_bytes(4, "big"))
    assert TRAILER_MAGIC in body[len(payload):]
    assert filename == f"{SETUP_PREFIX}{TOKEN}.exe"
    assert setup_token_from_filename(filename) == TOKEN
    assert setup_token_from_filename(r"C:\Users\Op\Downloads\\" + filename) == TOKEN
    assert setup_token_from_filename("MyraanaConnector-Setup.exe") == ""
    assert setup_filename(TOKEN) == filename
    try:
        enrollment_download(payload, TOKEN, expected_sha256="ab" * 32)
    except PackageUnavailable as error:
        assert error.message == "The published connector did not match its checksum."
    else:
        raise AssertionError("a checksum mismatch must not append a trailer")


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
    assert "connector_package_bytes" in pairing
    assert "PackageUnavailable" in pairing


def _expect_unavailable(action, message):
    try:
        action()
    except PackageUnavailable as error:
        assert error.message == message
        return
    raise AssertionError(message)


def test_unset_path_fetches_the_published_exe_and_checks_its_hash():
    """No CONNECTOR_PACKAGE_PATH: download the preview, trust only a matching SHA-256."""
    assert PREVIEW_EXE_URL == (
        "https://github.com/faiyaz2139-del/P2GL-Myraana/releases/download/"
        "windows-connector-preview/MyraanaConnector.exe"
    )
    assert PREVIEW_SHA_URL == (
        "https://github.com/faiyaz2139-del/P2GL-Myraana/releases/download/"
        "windows-connector-preview/MyraanaConnector.exe.sha256"
    )
    workflow = (ROOT / ".github" / "workflows" / "build-windows-connector.yml").read_text(encoding="utf-8")
    assert "MyraanaConnector.exe.sha256" in workflow
    assert 'github.ref == \'refs/heads/main\'' in workflow
    assert "gh release upload windows-connector-preview $package $checksum $exe $exeChecksum --clobber" in workflow

    class Preview:
        def __init__(self):
            self.calls = []
            self.exe = b"MZ-preview-onefile"
            self.mode = "ok"

        def __call__(self, url):
            self.calls.append(url)
            if self.mode == "boom":
                raise OSError("offline")
            if url == PREVIEW_SHA_URL:
                if self.mode == "garbage":
                    return b"not-a-hash"
                if self.mode == "mismatch":
                    return hashlib.sha256(b"other-file").hexdigest().upper()
                return f"{hashlib.sha256(self.exe).hexdigest().upper()}  MyraanaConnector.exe\n".encode()
            if url == PREVIEW_EXE_URL:
                if self.mode == "mismatch":
                    return b"tampered-bytes"
                return self.exe
            raise AssertionError(url)

    preview = Preview()
    start = datetime(2026, 10, 23, 0, 0, tzinfo=timezone.utc)
    with tempfile.TemporaryDirectory() as cache:
        body = connector_package_bytes(
            {"CONNECTOR_PACKAGE_PATH": "   "}, cache, preview, start,
        )
        assert body == preview.exe
        assert preview.calls == [PREVIEW_SHA_URL, PREVIEW_EXE_URL]
        served, filename = enrollment_download(body, TOKEN)
        assert served.startswith(preview.exe)
        assert TOKEN.encode() not in served[:len(preview.exe)]
        assert setup_token_from_trailer_bytes(served) == TOKEN
        assert filename == f"{SETUP_PREFIX}{TOKEN}.exe"
        assert (Path(cache) / "MyraanaConnector.exe").read_bytes() == preview.exe

        preview.calls.clear()
        again = published_connector_package(cache, preview, start + timedelta(minutes=30))
        assert again == preview.exe
        assert preview.calls == []

        hour_later = published_connector_package(cache, preview, start + timedelta(hours=1))
        assert hour_later == preview.exe
        assert preview.calls == [PREVIEW_SHA_URL]

        preview.calls.clear()
        preview.exe = b"MZ-preview-onefile-v2"
        updated = published_connector_package(cache, preview, start + timedelta(hours=2))
        assert updated == b"MZ-preview-onefile-v2"
        assert preview.calls == [PREVIEW_SHA_URL, PREVIEW_EXE_URL]
        assert (Path(cache) / "MyraanaConnector.exe").read_bytes() == updated

        preview.calls.clear()
        preview.mode = "mismatch"
        _expect_unavailable(
            lambda: published_connector_package(cache, preview, start + timedelta(hours=3)),
            "The published connector did not match its checksum.",
        )
        assert (Path(cache) / "MyraanaConnector.exe").read_bytes() == updated
        assert not (Path(cache) / "MyraanaConnector.exe.part").exists()

        preview.calls.clear()
        preview.mode = "boom"
        assert published_connector_package(cache, preview, start + timedelta(hours=4)) == updated

        preview.mode = "garbage"
        assert published_connector_package(cache, preview, start + timedelta(hours=5)) == updated

    with tempfile.TemporaryDirectory() as empty:
        preview.calls.clear()
        preview.mode = "boom"
        _expect_unavailable(
            lambda: published_connector_package(empty, preview, start),
            "The connector setup file could not be downloaded.",
        )
        assert not (Path(empty) / "MyraanaConnector.exe").exists()
        preview.mode = "garbage"
        _expect_unavailable(
            lambda: published_connector_package(empty, preview, start),
            "The connector setup file could not be downloaded.",
        )
        assert preview.calls
        assert PREVIEW_EXE_URL not in preview.calls

    with tempfile.TemporaryDirectory() as folder:
        local = Path(folder) / "local.exe"
        local.write_bytes(b"local-package")
        preview.calls.clear()
        served = connector_package_bytes(
            {"CONNECTOR_PACKAGE_PATH": str(local)}, folder, preview, start,
        )
        assert served == b"local-package"
        assert preview.calls == []
        missing = str(Path(folder) / "missing.exe")
        _expect_unavailable(
            lambda: connector_package_bytes(
                {"CONNECTOR_PACKAGE_PATH": missing}, folder, preview, start,
            ),
            "The connector setup file is not on this server yet.",
        )
        empty = Path(folder) / "empty.exe"
        empty.write_bytes(b"")
        _expect_unavailable(
            lambda: connector_package_bytes(
                {"CONNECTOR_PACKAGE_PATH": str(empty)}, folder, preview, start,
            ),
            "The connector setup file is not on this server yet.",
        )
        assert preview.calls == []

    _expect_unavailable(
        lambda: fetch_https("http://github.com/faiyaz2139-del/P2GL-Myraana/releases/download/x"),
        "The connector setup file could not be downloaded.",
    )
    _expect_unavailable(
        lambda: fetch_https("https://user:pass@github.com/faiyaz2139-del/P2GL-Myraana/x.exe"),
        "The connector setup file could not be downloaded.",
    )


def test_renamed_filenames_and_setup_diagnostics_keep_the_token_out_of_the_shop():
    names = [
        f"{SETUP_PREFIX}{TOKEN} (1).exe",
        f"{SETUP_PREFIX}{TOKEN} - Copy.exe",
        f"{SETUP_PREFIX}{TOKEN}.exe.exe",
        f"{SETUP_PREFIX}{TOKEN} (1).exe.exe",
        f"{SETUP_PREFIX}{TOKEN} - Copy (2).exe",
        f"{SETUP_PREFIX}{TOKEN} (1) - Copy.exe",
        f"myraanaconnector-setup-{TOKEN} (1).EXE",
    ]
    for name in names:
        assert setup_token_from_filename(name) == TOKEN
    assert setup_token_from_filename("MyraanaConnector.exe") == ""
    assert setup_token_from_filename(f"{SETUP_PREFIX}{TOKEN} (1).txt") == ""
    payload = {
        "host": "P2GL-2",
        "reason": "This setup file has expired.",
        "detail": f"password=hunter2 credential=secret token={TOKEN}",
        "token": TOKEN,
    }
    created = "2026-10-24T00:00:00+00:00"
    used = {"shop_id": "shop-1", "status": "used", "used_at": created, "token_hash": "hash"}
    stored = prepare_setup_diagnostic(payload, used, 0, created)
    assert stored["shop_id"] == "shop-1"
    assert stored["host"] == "P2GL-2"
    assert stored["reason"] == "This setup file has expired."
    assert TOKEN not in stored["detail"]
    assert TOKEN not in stored["reason"]
    assert "hunter2" not in stored["detail"]
    assert "secret" not in json_blob(stored)
    assert "token" not in stored
    assert "token_hash" not in stored
    assert prepare_setup_diagnostic(payload, None, 0, created) is None
    assert prepare_setup_diagnostic(payload, {"shop_id": ""}, 0, created) is None
    assert prepare_setup_diagnostic(payload, used, DIAGNOSTIC_LIMIT, created) is None
    expired = {"shop_id": "shop-9", "status": "expired"}
    assert prepare_setup_diagnostic(payload, expired, 1, created)["shop_id"] == "shop-9"
    assert public_setup_failure(stored) == {
        "host": "P2GL-2",
        "reason": "This setup file has expired.",
        "created": created,
    }
    assert "detail" not in public_setup_failure(stored)
    server = (ROOT / "backend" / "server.py").read_text(encoding="utf-8")
    pairing = (ROOT / "backend" / "p2g" / "connector_pairing.py").read_text(encoding="utf-8")
    app = (ROOT / "frontend" / "src" / "App.js").read_text(encoding="utf-8")
    tenancy = (ROOT / "backend" / "p2g" / "tenancy.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "build-windows-connector.yml").read_text(encoding="utf-8")
    route = server.split('@api.post("/connector-setup-diagnostics")', 1)[1].split("\n@api.", 1)[0]
    assert "assert_origin" not in route
    assert "record_setup_diagnostic" in route
    assert '"setupFailure": await latest_setup_failure()' in server
    heartbeat = pairing.split("async def heartbeat", 1)[1].split("\nasync def ", 1)[0]
    assert "clear_setup_failures()" in heartbeat
    assert "setup_diagnostics" in tenancy
    assert 'data-testid="setup-failure-banner"' in app
    assert "Setup on {failure.host} failed: {failure.reason}" in app
    assert "Setup on {settings.setupFailure.host} failed: {settings.setupFailure.reason}" in app
    assert 'data-testid="setup-failure-retry"' in app
    assert 'data-testid="settings-setup-retry"' in app
    assert "MyraanaConnector-trailer.exe" in workflow
    assert "Frozen connector failed after an appended setup trailer" in workflow
    assert "gh release upload windows-connector-preview $package $checksum $exe $exeChecksum --clobber" in workflow
    connector = (ROOT / "frontend" / "public" / "setup" / "myraana-connector.py").read_text(encoding="utf-8")
    assert 'TRAILER_MAGIC = b"MYRAANA1"' in connector
    main = connector.split("def main", 1)[1]
    assert main.find("args.self_test") < main.find("setup_token_from_executable")


def json_blob(value):
    return str(value)
