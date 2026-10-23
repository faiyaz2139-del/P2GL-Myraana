"""One-click connector setup. The token is stored as a hash and used once.

The download is the published connector exe unchanged. The single-use token is
only in the filename, MyraanaConnector-Setup-<token>.exe. Nothing is appended
to the file, because a PyInstaller onefile reads its archive from the end.
SMB paths and hot folders are not part of this file.
"""
import hashlib
import os
import tempfile
import urllib.request
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from p2g.connector_auth import credential_hash, pairing_shop_id


ENROLL_MINUTES = 30
ENROLL_LIMIT = 5
ENROLL_WINDOW = timedelta(minutes=10)
PUBLIC_ENROLL_ERROR = "This setup link is invalid or expired."
SETUP_PREFIX = "MyraanaConnector-Setup-"
SETUP_FILENAME = "MyraanaConnector-Setup.exe"
PREVIEW_EXE_URL = (
    "https://github.com/faiyaz2139-del/P2GL-Myraana/releases/download/"
    "windows-connector-preview/MyraanaConnector.exe"
)
PREVIEW_SHA_URL = (
    "https://github.com/faiyaz2139-del/P2GL-Myraana/releases/download/"
    "windows-connector-preview/MyraanaConnector.exe.sha256"
)
PREVIEW_REFRESH = timedelta(hours=1)


class PackageUnavailable(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


def https_website(value):
    """An origin the connector may call. Paths, users, and plain HTTP are refused."""
    text = str(value or "").strip().rstrip("/")
    parsed = urlsplit(text)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        return ""
    return f"https://{parsed.hostname}" if not parsed.port else f"https://{parsed.hostname}:{parsed.port}"


def enrollment_website(candidates):
    for value in candidates or []:
        website = https_website(value)
        if website:
            return website
    return "https://myraana.com"


def _moment(value):
    if isinstance(value, datetime):
        moment = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def enrollment_expiry(created_at, minutes=ENROLL_MINUTES):
    moment = _moment(created_at) or datetime.now(timezone.utc)
    return (moment + timedelta(minutes=minutes)).isoformat()


def build_enrollment(user, token, created_at, *, enrollment_id, current_shop=None):
    """Shop-bound enrollment row. The raw token is not stored."""
    shop_id = pairing_shop_id(user, current_shop)
    if not shop_id or not user or not user.get("id") or not str(token or "").strip():
        return None
    return {
        "_id": enrollment_id,
        "shop_id": shop_id,
        "token_hash": credential_hash(token),
        "created_by": user["id"],
        "created_at": created_at,
        "expires_at": enrollment_expiry(created_at),
        "used_at": "",
        "revoked_at": "",
        "status": "open",
        "device_id": "",
        "audit": [{"at": created_at, "action": "created", "actor": user["id"]}],
    }


def enrollment_state(record, at):
    if not record:
        return "missing"
    if record.get("status") == "revoked" or record.get("revoked_at"):
        return "revoked"
    if record.get("status") == "used" or record.get("used_at"):
        return "used"
    expires = str(record.get("expires_at") or "")
    if not expires or expires <= str(at or ""):
        return "expired"
    if record.get("status") != "open":
        return "invalid"
    return "open"


def enrollment_rate_limited(created_ats, at, limit=ENROLL_LIMIT, window=ENROLL_WINDOW):
    moment = _moment(at) or datetime.now(timezone.utc)
    cutoff = (moment - window).isoformat()
    recent = [stamp for stamp in created_ats or [] if str(stamp or "") > cutoff]
    return len(recent) >= limit


def choose_device(devices, device_id):
    """Reuse this computer, or the shop's only computer. Otherwise create one."""
    enabled = [item for item in devices or [] if isinstance(item, dict) and item.get("enabled") is not False]
    wanted = str(device_id or "")
    for item in enabled:
        ident = str(item.get("_id") or item.get("id") or "")
        if ident and ident == wanted:
            return ident, "rotate"
    if len(enabled) == 1:
        ident = str(enabled[0].get("_id") or enabled[0].get("id") or "")
        if ident:
            return ident, "rotate"
    return wanted, "create"


def _token_ok(token):
    text = str(token or "")
    if not 20 <= len(text) <= 200:
        return False
    return all(char.isalnum() or char in "-_" for char in text)


def setup_filename(token):
    """Filename that carries the token. The exe bytes do not."""
    text = str(token or "").strip()
    if not _token_ok(text):
        raise ValueError("Enrollment token is missing.")
    return f"{SETUP_PREFIX}{text}.exe"


def setup_token_from_filename(name):
    """Read the token back from a setup download name. A bare exe has none."""
    base = os.path.basename(str(name or "").replace("\\", "/"))
    if len(base) > 240:
        return ""
    prefix = SETUP_PREFIX
    if not base.lower().startswith(prefix.lower()) or not base.lower().endswith(".exe"):
        return ""
    token = base[len(prefix):-4]
    return token if _token_ok(token) else ""


def enrollment_download(package_bytes, token):
    """Return the published exe unchanged, named with the one-time token."""
    payload = bytes(package_bytes or b"")
    return payload, setup_filename(token)


def enrollment_config(website, token, shop_id):
    return {
        "websiteUrl": https_website(website) or "https://myraana.com",
        "enrollmentToken": str(token),
        "shopId": str(shop_id or ""),
    }


def public_enrollment(record, at):
    state = enrollment_state(record, at)
    if state == "expired" and record and record.get("status") == "open":
        state = "expired"
    return {
        "id": (record or {}).get("_id") or (record or {}).get("id") or "",
        "status": state if state in {"open", "used", "revoked", "expired"} else "expired",
        "created_at": (record or {}).get("created_at") or "",
        "expires_at": (record or {}).get("expires_at") or "",
        "created_by": (record or {}).get("created_by") or "",
        "device_id": (record or {}).get("device_id") or "",
    }


def _sha256_hex(value):
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        return ""
    return text


def https_download_url(value):
    """HTTPS URL of a file. A path is allowed. Userinfo and plain HTTP are not."""
    text = str(value or "").strip()
    parsed = urlsplit(text)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return ""
    return text


def published_connector_update(env=None):
    """The update the server is willing to vouch for. A missing checksum means no update."""
    env = os.environ if env is None else env
    digest = _sha256_hex(env.get("CONNECTOR_UPDATE_SHA256"))
    url = https_download_url(env.get("CONNECTOR_UPDATE_URL"))
    if not url or not digest:
        return None
    version = str(env.get("CONNECTOR_UPDATE_VERSION") or digest[:12]).strip()[:80]
    return {"url": url, "sha256": digest, "version": version}


def parse_sha256_asset(text):
    """A checksum file is either a bare hash or 'hash  filename'."""
    if isinstance(text, (bytes, bytearray)):
        text = bytes(text).decode("utf-8", "replace")
    for token in str(text or "").replace(",", " ").split():
        digest = _sha256_hex(token)
        if digest:
            return digest
    return ""


def connector_cache_dir(env=None):
    env = os.environ if env is None else env
    configured = str(env.get("CONNECTOR_PACKAGE_CACHE") or "").strip()
    if configured:
        return configured
    return os.path.join(tempfile.gettempdir(), "myraana-connector-preview")


def fetch_https(url, timeout=120):
    """Download one HTTPS URL. A redirect that leaves HTTPS is refused."""
    cleaned = https_download_url(url)
    if not cleaned:
        raise PackageUnavailable("The connector setup file could not be downloaded.")
    request = urllib.request.Request(cleaned, headers={"User-Agent": "Myraana"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            final = str(response.geturl() or "")
            if urlsplit(final).scheme != "https":
                raise PackageUnavailable("The connector setup file could not be downloaded.")
            return response.read()
    except PackageUnavailable:
        raise
    except Exception as error:
        raise PackageUnavailable("The connector setup file could not be downloaded.") from error


def _cache_paths(cache_dir):
    exe_path = os.path.join(cache_dir, "MyraanaConnector.exe")
    return exe_path, exe_path + ".sha256", exe_path + ".checked"


def _read_verified_cache(cache_dir):
    exe_path, sha_path, checked_path = _cache_paths(cache_dir)
    try:
        with open(exe_path, "rb") as handle:
            payload = handle.read()
        with open(sha_path, encoding="ascii") as handle:
            digest = parse_sha256_asset(handle.read())
        with open(checked_path, encoding="ascii") as handle:
            checked = handle.read().strip()
    except OSError:
        return b"", "", ""
    if not payload or not verify_sha256(payload, digest):
        return b"", "", ""
    return payload, digest, checked


def _write_verified_cache(cache_dir, payload, digest, checked_at):
    os.makedirs(cache_dir, exist_ok=True)
    exe_path, sha_path, checked_path = _cache_paths(cache_dir)
    temporary = exe_path + ".part"
    with open(temporary, "wb") as handle:
        handle.write(payload)
    os.replace(temporary, exe_path)
    with open(sha_path, "w", encoding="ascii") as handle:
        handle.write(digest + "\n")
    with open(checked_path, "w", encoding="ascii") as handle:
        handle.write(str(checked_at) + "\n")


def _cache_is_fresh(checked, now, max_age):
    moment = _moment(checked)
    current = _moment(now) or datetime.now(timezone.utc)
    if moment is None:
        return False
    return current - moment < max_age


def published_connector_package(
    cache_dir,
    fetcher,
    now,
    exe_url=PREVIEW_EXE_URL,
    sha_url=PREVIEW_SHA_URL,
    max_age=PREVIEW_REFRESH,
):
    """The preview exe, checked against the published SHA-256.

    A fresh cache is served as-is. After an hour the published hash is read
    again. A new hash downloads a new exe. A mismatch is not cached.
    """
    cached, cached_digest, checked = _read_verified_cache(cache_dir)
    if cached and _cache_is_fresh(checked, now, max_age):
        return cached
    checked_at = (_moment(now) or datetime.now(timezone.utc)).isoformat()
    try:
        published = parse_sha256_asset(fetcher(sha_url))
    except Exception:
        if cached:
            return cached
        raise PackageUnavailable("The connector setup file could not be downloaded.")
    if not published:
        if cached:
            return cached
        raise PackageUnavailable("The connector setup file could not be downloaded.")
    if cached and published == cached_digest:
        _write_verified_cache(cache_dir, cached, cached_digest, checked_at)
        return cached
    try:
        payload = fetcher(exe_url)
    except PackageUnavailable:
        raise
    except Exception as error:
        raise PackageUnavailable("The connector setup file could not be downloaded.") from error
    if not isinstance(payload, (bytes, bytearray)):
        payload = b""
    payload = bytes(payload)
    if not verify_sha256(payload, published):
        raise PackageUnavailable("The published connector did not match its checksum.")
    _write_verified_cache(cache_dir, payload, published, checked_at)
    return payload


def local_connector_package(path):
    if not path or not os.path.isfile(path):
        raise PackageUnavailable("The connector setup file is not on this server yet.")
    with open(path, "rb") as handle:
        payload = handle.read()
    if not payload:
        raise PackageUnavailable("The connector setup file is not on this server yet.")
    return payload


def connector_package_bytes(env, cache_dir, fetcher, now):
    """A configured file wins. Otherwise use the published preview exe."""
    path = str((env or {}).get("CONNECTOR_PACKAGE_PATH") or "").strip()
    if path:
        return local_connector_package(path)
    return published_connector_package(cache_dir, fetcher, now)


def verify_sha256(payload, expected):
    digest = _sha256_hex(expected)
    if not digest or not isinstance(payload, (bytes, bytearray)):
        return False
    actual = hashlib.sha256(bytes(payload)).hexdigest()
    if len(actual) != len(digest):
        return False
    # Compare without short-circuiting on the first differing character.
    mismatch = 0
    for left, right in zip(actual, digest):
        mismatch |= ord(left) ^ ord(right)
    return mismatch == 0
