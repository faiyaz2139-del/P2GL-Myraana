"""Windows connector: printer discovery, pairing, and HTTPS heartbeats.

The pairing code is created in one shop's settings and only joins that shop.
This program does not use CONNECTOR_SECRET. It never prints or releases jobs.
When Myraana asks, it can place a PRINT_READY file on a Fiery HOLD queue.
Build on Windows with the adjacent PowerShell script.
"""
import argparse
import hashlib
import importlib.util
import json
import queue
import re
import shutil
import subprocess
import sys
import threading
import urllib.parse
import os
import platform
import secrets
import socket
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

try:
    import keyring
except ImportError:
    keyring = None


STATE_PATH = os.path.join(os.environ.get("LOCALAPPDATA", "."), "Myraana", "connector.json")
SERVICE = "MyraanaConnector"
DEFAULT_WEBSITE = "https://myraana.com"
REPAIR_MESSAGE = (
    "This computer needs to be paired again. Create a pairing code in "
    "Myraana Shop settings and enter it here."
)
POLL_MISMATCH_MESSAGE = (
    "This pairing no longer matches. Create a new pairing code in "
    "Myraana Shop settings and enter it here."
)
CODE_FORMAT_MESSAGE = "The pairing code must be 8 characters."
CODE_EXPIRED_MESSAGE = (
    "That pairing code is invalid or expired. Create a new one in Myraana Shop settings."
)
WEBSITE_MESSAGE = "That website was not found. Check the Myraana website address."
HOLD_FOOTER = (
    "This connector finds your printers and can place approved PRINT_READY files "
    "on your Fiery HOLD queue. It never prints or releases jobs."
)
TOAST_MESSAGE = "Connected to Myraana. Fiery found."
SETUP_PREFIX = "MyraanaConnector-Setup-"
INSTALL_EXE_NAME = "MyraanaConnector.exe"
MISSING_SETUP_MESSAGE = "Download Connect this computer again. Open that file. Do not rename it."
UPDATE_INTERVAL_SECONDS = 24 * 60 * 60
ENROLL_ERROR = "This setup link is invalid or expired."
TRAILER_MAGIC = b"MYRAANA1"
EXPIRED_SETUP_TITLE = "This setup file has expired"
SETUP_COPY_ERROR = "The connector could not replace the installed copy."


def load_state():
    try:
        with open(STATE_PATH, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as handle:
        json.dump(state, handle)


def secret(name, value=None):
    if not keyring:
        raise RuntimeError("Windows Credential Manager support is required.")
    if value is not None:
        keyring.set_password(SERVICE, name, value)
        return value
    return keyring.get_password(SERVICE, name)


def forget_secret(name):
    """Drop one saved credential. A missing entry is already forgotten."""
    if not keyring:
        return
    try:
        keyring.delete_password(SERVICE, name)
    except Exception:
        return


def load_fiery_credentials():
    """Optional Fiery API login. Blank means the Hold queue is used on its own."""
    try:
        api_key = secret("fiery-api-key") or ""
        username = secret("fiery-username") or ""
        password = secret("fiery-password") or ""
    except Exception:
        return None
    return load_fiery_hold().fiery_credentials(
        {"apiKey": api_key, "username": username, "password": password}
    )


def remember_fiery_login(api_key, username, password):
    """Save a complete API login. Blank fields keep whatever was already saved."""
    api_key = str(api_key or "").strip()
    username = str(username or "").strip()
    password = str(password or "")
    if not api_key or not username or not password.strip():
        return
    try:
        secret("fiery-api-key", api_key)
        secret("fiery-username", username)
        secret("fiery-password", password)
    except Exception:
        return


def normalize_code(value):
    """Pairing codes are shown in groups. Spaces and dashes are not part of the code."""
    return str(value or "").upper().replace(" ", "").replace("-", "").strip()


def module_candidates(filename):
    """Frozen bundle first (_MEIPASS, then the exe directory), then the script directory."""
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            candidates.append(os.path.join(meipass, filename))
        candidates.append(os.path.join(os.path.dirname(sys.executable), filename))
    candidates.append(os.path.join(here, filename))
    backend = os.path.join("backend", "p2g", filename)
    candidates.append(os.path.normpath(os.path.join(here, "..", "..", "..", backend)))
    candidates.append(os.path.normpath(os.path.join(here, "..", "..", backend)))
    return candidates


def load_python_module(filename, module_name):
    for candidate in module_candidates(filename):
        if os.path.isfile(candidate):
            spec = importlib.util.spec_from_file_location(module_name, candidate)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    return None


_DISCOVERY = None
_FIERY = None


def load_discovery():
    """The discovery module ships beside this script and in the frozen bundle."""
    global _DISCOVERY
    if _DISCOVERY is not None:
        return _DISCOVERY
    module = load_python_module("printer_discovery.py", "myraana_printer_discovery")
    if module is None:
        raise RuntimeError("Printer discovery is unavailable.")
    _DISCOVERY = module
    return module


def printers():
    """Windows spooler queues. Get-Printer and Bonjour run in discover_printers."""
    if platform.system() != "Windows":
        return []
    try:
        import win32print
    except ImportError:
        return []
    found = []
    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    for item in win32print.EnumPrinters(flags):
        name = item[2]
        handle = win32print.OpenPrinter(name)
        try:
            details = win32print.GetPrinter(handle, 2)
            found.append({"source": "windows_spooler", "name": name,
                          "driver": details.get("pDriverName", ""),
                          "port": details.get("pPortName", ""),
                          "status": str(details.get("Status", ""))})
        finally:
            win32print.ClosePrinter(handle)
    return found


def discover_printers():
    """Bonjour plus the OS queues. Failures become an empty list so the heartbeat still runs."""
    try:
        discovery = load_discovery()

        def queues():
            found = []
            try:
                found.extend(discovery.os_queues() or [])
            except Exception:
                pass
            found.extend(printers())
            return found

        return discovery.discover(
            browse=lambda: discovery.browse_mdns(timeout=1.0),
            list_queues=queues,
            probe=lambda address: discovery.probe_fiery(address, timeout=1.0),
        ) or []
    except Exception:
        return []


def reported_capabilities():
    """This program places PRINT_READY files on Fiery HOLD. It does not need a drop folder."""
    return ["fiery_hold"]


def inventory():
    found = discover_printers()
    fiery = [item for item in found if item.get("isFiery")]
    return {"hostname": socket.gethostname(), "printers": found,
            "fiery_rip": fiery, "hot_folders": [], "capabilities": reported_capabilities()}


def request(api_url, path, payload, credential=None):
    headers = {"Content-Type": "application/json"}
    if credential:
        headers["Authorization"] = f"Bearer {credential}"
    body = json.dumps(payload).encode("utf-8")
    call = urllib.request.Request(api_url + path, data=body, headers=headers)
    with urllib.request.urlopen(call, timeout=20) as response:
        return json.load(response)


def request_bytes(api_url, path, credential):
    headers = {"Authorization": f"Bearer {credential}"}
    call = urllib.request.Request(api_url + path, headers=headers)
    with urllib.request.urlopen(call, timeout=60) as response:
        return response.read()


def load_fiery_hold():
    """Same lookup as discovery: frozen bundle, exe directory, then this script."""
    global _FIERY
    if _FIERY is not None:
        return _FIERY
    module = load_python_module("fiery_hold.py", "myraana_fiery_hold")
    if module is None:
        raise RuntimeError("Fiery hold support is unavailable.")
    _FIERY = module
    return module


def exercise_bundled_modules():
    """Import discovery and Fiery HOLD. The packaged exe must be able to do both."""
    discovery = load_discovery()
    fiery = load_fiery_hold()
    if not hasattr(discovery, "discover") or not hasattr(fiery, "submit_hold"):
        raise RuntimeError("Connector bundle is missing discovery or Fiery hold support.")
    return discovery, fiery


def exercise_tray_support():
    """Import the tray libraries. The frozen Windows exe must include both."""
    import pystray
    from PIL import Image
    if not hasattr(pystray, "Icon") or not hasattr(Image, "new"):
        raise RuntimeError("Tray support is unavailable.")
    return pystray


def perform_holds(api_url, credential, result, opener=None, printers=None):
    """Submit queued PRINT_READY files to a Fiery this computer discovered.

    A server address, UNC path, or hot folder is not used unless the address is a
    private Fiery in ``printers``. The file is never printed.
    """
    holds = result.get("holds") if isinstance(result, dict) else None
    if not holds:
        return None
    fiery = load_fiery_hold()
    printers = printers if isinstance(printers, list) else []
    reports = []
    for item in holds:
        if not isinstance(item, dict) or not item.get("jobId"):
            continue
        try:
            address = fiery.hold_target(item.get("address") or "", printers)
        except Exception as error:
            message = str(error).strip() or "This computer did not discover that Fiery. Nothing was printed."
            reports.append({
                "jobId": item["jobId"],
                "ok": False,
                "held": False,
                "printed": False,
                "method": "",
                "error": message,
            })
            continue
        try:
            pdf = request_bytes(api_url, f"/connector-devices/holds/{item['jobId']}", credential)
            outcome = fiery.submit_hold(
                address=address,
                filename=item.get("filename") or "artwork_PRINT_READY.pdf",
                preset=item.get("preset") or "London BC",
                stock=item.get("stock") or "",
                pdf=pdf,
                job_name=item.get("jobName") or "",
                job_id=item.get("jobId") or "",
                credentials=load_fiery_credentials(),
                printers=printers,
                opener=opener,
            )
        except Exception:
            outcome = {
                "ok": False,
                "held": False,
                "printed": False,
                "method": "api",
                "error": "The hold could not be submitted.",
            }
        if outcome.get("printed") or outcome.get("release") or outcome.get("released"):
            outcome = {
                "ok": False,
                "held": False,
                "printed": False,
                "method": "api",
                "error": "Refused a print or release. The job stays on HOLD.",
            }
        reports.append({"jobId": item["jobId"], **outcome})
    return reports or None


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "MyraanaConnector"
TRAY_MENU = ("Open", "Scan again", "Start with Windows", "Quit")


def launch_command():
    """How Windows should start this connector. A per-user path, no admin."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    return f'"{sys.executable}" "{os.path.abspath(__file__)}"'


def _winreg():
    if platform.system() != "Windows":
        return None
    try:
        import winreg
    except ImportError:
        return None
    return winreg


def set_startup(enabled, registry=None):
    """Per-user Run key. HKCU does not need an administrator."""
    registry = _winreg() if registry is None else registry
    if registry is None:
        return False
    with registry.CreateKey(registry.HKEY_CURRENT_USER, RUN_KEY) as key:
        if enabled:
            registry.SetValueEx(key, RUN_VALUE, 0, registry.REG_SZ, launch_command())
        else:
            try:
                registry.DeleteValue(key, RUN_VALUE)
            except OSError:
                return False
    return True


def startup_enabled(registry=None):
    registry = _winreg() if registry is None else registry
    if registry is None:
        return False
    try:
        with registry.OpenKey(registry.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _kind = registry.QueryValueEx(key, RUN_VALUE)
    except OSError:
        return False
    return bool(str(value or "").strip())


def ensure_default_startup(state, registry=None):
    """After a pairing, start with Windows unless the operator turned it off."""
    if state.get("startWithWindows") is False:
        return False
    state["startWithWindows"] = True
    save_state(state)
    set_startup(True, registry=registry)
    return True


def remember_startup(state, enabled, registry=None):
    state["startWithWindows"] = bool(enabled)
    save_state(state)
    set_startup(bool(enabled), registry=registry)
    return state["startWithWindows"]


def should_reconnect(state, credential, pairing_code):
    """A paired computer opens straight into the heartbeat. No code is asked again."""
    return bool(not normalize_code(pairing_code) and (state or {}).get("websiteUrl") and credential)


def handle_window_close(root, stop, self_test=False):
    """Closing the window keeps heartbeats running. Quit is the tray action that stops them."""
    if self_test:
        stop.set()
        root.destroy()
        return "quit"
    root.withdraw()
    return "hide"


def quit_connector(root, stop, icon=None):
    stop.set()
    if icon is not None:
        try:
            icon.stop()
        except Exception:
            pass
    try:
        root.destroy()
    except Exception:
        pass


def tray_image():
    from PIL import Image, ImageDraw
    image = Image.new("RGB", (64, 64), "#12315c")
    draw = ImageDraw.Draw(image)
    draw.ellipse((8, 8, 56, 56), fill="#2f6fed")
    return image


def build_tray_menu(pystray, actions):
    return pystray.Menu(
        pystray.MenuItem("Open", actions["open"], default=True),
        pystray.MenuItem("Scan again", actions["scan"]),
        pystray.MenuItem(
            "Start with Windows",
            actions["toggle_startup"],
            checked=lambda item: actions["startup_checked"](),
        ),
        pystray.MenuItem("Quit", actions["quit"]),
    )


def start_tray(root, actions):
    try:
        import pystray
    except ImportError:
        return None
    try:
        image = tray_image()
        menu = build_tray_menu(pystray, actions)
    except Exception:
        return None
    icon = pystray.Icon("MyraanaConnector", image, "Myraana Connector", menu)
    threading.Thread(target=icon.run, name="myraana-tray", daemon=True).start()
    return icon


def install_root():
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
    return os.path.join(base, "Myraana")


def installed_exe():
    return os.path.join(install_root(), INSTALL_EXE_NAME)


def _token_ok(token):
    text = str(token or "")
    if not 20 <= len(text) <= 200:
        return False
    return all(char.isalnum() or char in "-_" for char in text)


def _download_stem(name):
    """Drop duplicate .exe suffixes and browser copy markers such as ' (1)'."""
    base = os.path.basename(str(name or "").replace("\\", "/")).strip()
    if not base or len(base) > 400 or not base.lower().endswith(".exe"):
        return ""
    stem = base
    for _ in range(8):
        while stem.lower().endswith(".exe"):
            stem = stem[:-4]
        updated = stem
        while True:
            copied = re.sub(r"(?i)\s+-\s+copy$", "", updated)
            numbered = re.sub(r"\s+\(\d+\)$", "", copied)
            if numbered == updated:
                break
            updated = numbered
        if updated == stem:
            return stem
        stem = updated
    return stem


def setup_token_from_filename(name):
    """The setup download carries the token in its name. The installed exe does not."""
    stem = _download_stem(name)
    prefix = SETUP_PREFIX
    if not stem.lower().startswith(prefix.lower()):
        return ""
    token = stem[len(prefix):]
    return token if _token_ok(token) else ""


def append_setup_trailer(payload, token):
    """Magic, token, then the token length. Tests and the server use the same layout."""
    text = str(token or "").strip()
    if not _token_ok(text):
        raise ValueError("Enrollment token is missing.")
    encoded = text.encode("ascii")
    return bytes(payload or b"") + TRAILER_MAGIC + encoded + len(encoded).to_bytes(4, "big")


def setup_token_from_trailer_bytes(payload):
    data = bytes(payload or b"")
    if len(data) < len(TRAILER_MAGIC) + 20 + 4:
        return ""
    length = int.from_bytes(data[-4:], "big")
    if not 20 <= length <= 200:
        return ""
    end = len(data) - 4
    start = end - length
    magic_at = start - len(TRAILER_MAGIC)
    if magic_at < 0 or data[magic_at:start] != TRAILER_MAGIC:
        return ""
    try:
        token = data[start:end].decode("ascii")
    except UnicodeDecodeError:
        return ""
    return token if _token_ok(token) else ""


def setup_token_from_trailer(path):
    """Read only the tail. A renamed download still carries the token here."""
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            tail = min(size, len(TRAILER_MAGIC) + 200 + 4)
            if tail < len(TRAILER_MAGIC) + 20 + 4:
                return ""
            handle.seek(size - tail)
            return setup_token_from_trailer_bytes(handle.read(tail))
    except OSError:
        return ""


def setup_token_from_executable(path):
    """The trailer wins. The filename is the fallback when no trailer is present."""
    token = setup_token_from_trailer(path)
    if token:
        return token
    return setup_token_from_filename(path)


def stop_other_connectors():
    """Stop an installed MyraanaConnector.exe so this setup can replace it.

    The setup download is named MyraanaConnector-Setup-<token>.exe, so this
    does not stop the setup process itself. Other platforms do nothing.
    """
    if platform.system() != "Windows":
        return
    creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.run(
        ["taskkill", "/F", "/IM", INSTALL_EXE_NAME],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation,
        check=False,
    )


def copy_into_install(source, dest=None, replace=None, stopper=None):
    """Install beside the connector state. The copy is named without the token.

    When the installed file is in use, stop the older connector and copy again.
    """
    dest = dest or installed_exe()
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.normcase(os.path.abspath(source)) == os.path.normcase(os.path.abspath(dest)):
        return dest
    writer = replace or shutil.copyfile

    def _write():
        writer(source, dest)

    try:
        _write()
    except OSError:
        if stopper is None:
            stop_other_connectors()
        else:
            stopper()
        _write()
    return dest


def handoff_setup(source, token, dest=None, spawn=None, stopper=None, replace=None):
    """Copy this file into LocalAppData and start that copy once with the token."""
    dest = copy_into_install(source, dest, replace=replace, stopper=stopper)
    env = os.environ.copy()
    if token:
        env["MYRAANA_ENROLL_TOKEN"] = token
    else:
        env.pop("MYRAANA_ENROLL_TOKEN", None)
    launcher = spawn or spawn_detached
    launcher([dest], env)
    return dest


def spawn_detached(argv, env):
    kwargs = {"env": env, "close_fds": True}
    if platform.system() == "Windows":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        kwargs["creationflags"] = flags
    subprocess.Popen(argv, **kwargs)


def running_from_install():
    if not getattr(sys, "frozen", False):
        return False
    return os.path.normcase(os.path.abspath(sys.executable)) == os.path.normcase(os.path.abspath(installed_exe()))


def fiery_found(found):
    printers = (found or {}).get("printers") if isinstance(found, dict) else None
    if not isinstance(printers, list):
        return False
    return any(isinstance(item, dict) and item.get("isFiery") for item in printers)


def _parse_moment(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def sha256_matches(payload, expected):
    digest = str(expected or "").strip().lower()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        return False
    if not isinstance(payload, (bytes, bytearray)):
        return False
    actual = hashlib.sha256(bytes(payload)).hexdigest()
    mismatch = 0
    for left, right in zip(actual, digest):
        mismatch |= ord(left) ^ ord(right)
    return mismatch == 0 and len(actual) == len(digest)


def update_is_due(state, manifest, moment=None):
    digest = str((manifest or {}).get("sha256") or "")
    if len(digest) != 64:
        return False
    moment = moment or datetime.now(timezone.utc)
    checked = _parse_moment((state or {}).get("updateCheckedAt"))
    recent = checked is not None and (moment - checked).total_seconds() < UPDATE_INTERVAL_SECONDS
    if recent and (state or {}).get("updateSha") == digest:
        return False
    if recent and (state or {}).get("updateRejected") == digest:
        return False
    return True


def fetch_https(url):
    parsed = urllib.parse.urlsplit(str(url or ""))
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("The update address is not a secure download.")
    request_obj = urllib.request.Request(url, headers={"User-Agent": "MyraanaConnector"})
    with urllib.request.urlopen(request_obj, timeout=60) as response:
        return response.read()


def apply_staged_update():
    """Replace the installed exe with a verified download. The running process keeps going."""
    pending = installed_exe() + ".new"
    current = installed_exe()
    if not os.path.isfile(pending):
        return False
    try:
        os.replace(pending, current)
    except OSError:
        return False
    return True


def stage_update_bytes(payload):
    """Write a verified update beside the install. Only a frozen Windows exe swaps."""
    if not getattr(sys, "frozen", False) or platform.system() != "Windows":
        return ""
    folder = install_root()
    os.makedirs(folder, exist_ok=True)
    dest = os.path.join(folder, INSTALL_EXE_NAME + ".new")
    with open(dest, "wb") as handle:
        handle.write(payload)
    return dest


def consider_update(manifest, state, report=lambda *_args: None, fetcher=None, writer=None, moment=None):
    """Download an update only when the server publishes a SHA-256 and it matches."""
    if not isinstance(manifest, dict) or not update_is_due(state, manifest, moment):
        return False
    url = str(manifest.get("url") or "")
    digest = str(manifest.get("sha256") or "").strip().lower()
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return False
    fetcher = fetcher or fetch_https
    payload = fetcher(url)
    moment = moment or datetime.now(timezone.utc)
    state["updateCheckedAt"] = moment.isoformat()
    if not sha256_matches(payload, digest):
        state["updateRejected"] = digest
        save_state(state)
        report("The update did not match. This computer was left unchanged.")
        return False
    writer = stage_update_bytes if writer is None else writer
    writer(payload)
    state["updateSha"] = digest
    state.pop("updateRejected", None)
    state["updateVersion"] = str(manifest.get("version") or "")[:80]
    save_state(state)
    report("Myraana Connector updated.")
    return True


def show_toast(root, message):
    import tkinter as tk
    from tkinter import ttk
    toast = tk.Toplevel(root)
    toast.overrideredirect(True)
    try:
        toast.attributes("-topmost", True)
    except Exception:
        pass
    ttk.Label(toast, text=message, padding=16).pack()
    toast.update_idletasks()
    width = max(toast.winfo_width(), 280)
    height = max(toast.winfo_height(), 48)
    screen_w = toast.winfo_screenwidth()
    screen_h = toast.winfo_screenheight()
    toast.geometry(f"{width}x{height}+{max(0, screen_w - width - 24)}+{max(0, screen_h - height - 72)}")
    root.after(6000, toast.destroy)
    return toast


def website_url(value):
    value = value.strip().rstrip("/")
    parsed = urllib.parse.urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ("", "/")):
        raise ValueError("A valid HTTPS Myraana website URL is required.")
    return value


def run(url=None, code=None, report=print, stop=None, scan_now=None):
    stop = stop or threading.Event()
    scan_now = scan_now or threading.Event()
    state = load_state()
    state.setdefault("deviceId", str(uuid.uuid4()))
    enroll_token = str(os.environ.get("MYRAANA_ENROLL_TOKEN") or "").strip()
    supplied = url or os.environ.get("MYRAANA_URL", "") or state.get("websiteUrl", "")
    if not supplied and enroll_token:
        supplied = DEFAULT_WEBSITE
    url = website_url(supplied or input("Enter your Myraana HTTPS website URL: "))
    if state.get("websiteUrl") and state["websiteUrl"] != url:
        raise ValueError("This connector is already linked to a different website.")
    api_url = url + "/api"
    claim_secret = secret("claimSecret") or secret("claimSecret", secrets.token_urlsafe(48))
    credential = secret("credential")
    # Older installations do not record their host. Require a new pairing rather
    # than transmitting an existing bearer token to an unconfirmed website.
    if credential and not state.get("websiteUrl"):
        raise ValueError("Existing connection needs migration before using this setup window.")
    state["websiteUrl"] = url
    state.pop("claimSecret", None)
    state.pop("credential", None)
    save_state(state)
    code = normalize_code(code or os.environ.get("MYRAANA_PAIRING_CODE", ""))
    if code and len(code) != 8:
        raise ValueError(CODE_FORMAT_MESSAGE)
    # A typed code replaces a saved credential. The old token may belong to a
    # device the shop removed, or to a database that was reset.
    if code and credential:
        forget_secret("credential")
        credential = None
        state.pop("pairingId", None)
        save_state(state)
    startup_ready = False

    def arm_startup():
        nonlocal startup_ready
        if startup_ready:
            return
        startup_ready = True
        ensure_default_startup(state)

    if credential:
        arm_startup()
        if enroll_token:
            os.environ.pop("MYRAANA_ENROLL_TOKEN", None)
            enroll_token = ""
    if enroll_token and not credential:
        found = inventory()
        redeemed = request(api_url, "/connector-enrollments/redeem", {
            "token": enroll_token,
            "deviceId": state["deviceId"],
            "hostname": (found or {}).get("hostname") or "",
            "inventory": found,
        })
        os.environ.pop("MYRAANA_ENROLL_TOKEN", None)
        enroll_token = ""
        if not isinstance(redeemed, dict) or not redeemed.get("credential"):
            raise ValueError(ENROLL_ERROR)
        credential = secret("credential", redeemed["credential"])
        arm_startup()
        report(TOAST_MESSAGE if fiery_found(found) else "Connected to Myraana.")
    while not stop.is_set():
        try:
            if credential:
                forced = scan_now.is_set()
                scan_now.clear()
                found = inventory()
                body = {"inventory": found}
                if forced:
                    body["scanned"] = True
                result = request(api_url, "/connector-devices/heartbeat", body, credential)
                report(f"Connected. {len(found.get('printers') or [])} printer(s) found.")
                if isinstance(result, dict) and result.get("update"):
                    try:
                        consider_update(result.get("update"), state, report=report)
                    except Exception:
                        report("The update did not match. This computer was left unchanged.")
                if forced:
                    report("Scanned again for printers.")
                elif isinstance(result, dict) and result.get("scan"):
                    found = inventory()
                    result = request(api_url, "/connector-devices/heartbeat",
                            {"inventory": found, "scanned": True}, credential)
                    report("Scanned again for printers.")
                local_printers = found.get("printers") if isinstance(found, dict) else None
                reports = perform_holds(api_url, credential, result, printers=local_printers or [])
                if reports:
                    request(api_url, "/connector-devices/heartbeat",
                            {"inventory": found, "holds": reports}, credential)
                    failed = [item for item in reports if not item.get("ok") or not item.get("held")]
                    if failed:
                        report(failed[0].get("error") or "The Fiery Hold queue did not confirm the file. Nothing was printed.")
                    else:
                        methods = ", ".join(sorted({str(item.get("method") or "hold") for item in reports}))
                        report(f"Sent the PRINT_READY file to the Fiery hold queue via {methods}. It was not printed.")
            else:
                if not state.get("pairingId"):
                    if not code:
                        raise ValueError("Enter the pairing code shown in Myraana.")
                    claimed = request(api_url, "/connector-pairings/claim", {
                        "code": code, "deviceId": state["deviceId"],
                        "claimSecret": claim_secret, "inventory": inventory(),
                    })
                    state["pairingId"] = claimed["id"]
                    save_state(state)
                    report("Printer found. Approve this computer in Myraana.")
                result = request(api_url,
                    f"/connector-pairings/{state['pairingId']}/poll",
                    {"claimSecret": claim_secret},
                )
                if result.get("credential"):
                    credential = secret("credential", result["credential"])
                    state.pop("pairingId", None)
                    save_state(state)
                    arm_startup()
                    report("Approved. Checking connection...")
            stop.wait(8)
        except urllib.error.HTTPError as error:
            if error.code == 401 and credential:
                forget_secret("credential")
                credential = None
                state.pop("pairingId", None)
                save_state(state)
                raise ValueError(REPAIR_MESSAGE)
            if error.code == 401:
                state.pop("pairingId", None)
                save_state(state)
                raise ValueError(POLL_MISMATCH_MESSAGE)
            if error.code == 400:
                raise ValueError(CODE_FORMAT_MESSAGE)
            if error.code == 409:
                state.pop("pairingId", None)
                save_state(state)
                raise ValueError(CODE_EXPIRED_MESSAGE)
            if error.code == 404:
                raise ValueError(WEBSITE_MESSAGE)
            if error.code == 403:
                raise ValueError("Myraana refused this connection. Check the website and try again.")
            report(f"Service unavailable (HTTP {error.code}). Retrying automatically.")
            stop.wait(8)
        except (urllib.error.URLError, KeyError, OSError) as error:
            report(f"Offline or waiting for service ({type(error).__name__}). Retrying automatically.")
            stop.wait(8)


def scrub_setup_text(value, token=""):
    """The diagnostic and the window must not repeat the token or a password."""
    text = str(value or "")
    secret = str(token or "").strip()
    if secret:
        text = text.replace(secret, "[redacted]")
    return re.sub(
        r"(?i)(password|credential|claimsecret|api[_-]?key|token)\s*[:=]\s*\S+",
        lambda match: match.group(1) + "=[redacted]",
        text,
    )


def connect_page_url(website=None):
    """The myraana.com page that shows Connect this computer."""
    try:
        origin = website_url(str(website or DEFAULT_WEBSITE))
    except Exception:
        origin = DEFAULT_WEBSITE
    return origin + "/jobs"


def _hostname():
    try:
        return (socket.gethostname() or "Windows computer")[:120]
    except Exception:
        return "Windows computer"


def setup_failure_view(message, *, token="", reason="", detail="", website=None, host=""):
    """Visible setup failure. Missing, expired, and used tokens share one window."""
    text = str(message or "")
    cause = str(reason or text)
    expired = cause in {EXPIRED_SETUP_TITLE, ENROLL_ERROR, MISSING_SETUP_MESSAGE} or "expired" in cause.lower()
    shown = EXPIRED_SETUP_TITLE if expired else (text or "Setup could not finish.")
    safe_reason = EXPIRED_SETUP_TITLE if expired else (scrub_setup_text(cause, token).strip()[:180] or shown)
    safe_detail = scrub_setup_text(detail or text or shown, token).strip()[:2000]
    if token and token in safe_detail:
        safe_detail = safe_detail.replace(token, "[redacted]")
    if token and token in safe_reason:
        safe_reason = safe_reason.replace(token, "[redacted]")
    return {
        "expired": expired,
        "title": EXPIRED_SETUP_TITLE if expired else "Myraana Connector",
        "message": shown,
        "reason": safe_reason,
        "detail": safe_detail or shown,
        "host": (host or _hostname())[:120],
        "actions": ["Get a new one", "Type pairing code instead", "Copy details"],
        "connectUrl": connect_page_url(website),
        "token": token if _token_ok(token) else "",
    }


def diagnostic_body(view):
    body = {
        "host": view["host"],
        "reason": view["reason"],
        "detail": view["detail"],
    }
    if view.get("token"):
        body["token"] = view["token"]
    return body


def post_setup_diagnostic(website, body):
    try:
        origin = website_url(str(website or DEFAULT_WEBSITE))
    except Exception:
        origin = DEFAULT_WEBSITE
    url = origin + "/api/connector-setup-diagnostics"
    data = json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "MyraanaConnector"},
    )
    with urllib.request.urlopen(request, timeout=8) as response:
        response.read()


def open_connect_page(url=None):
    import webbrowser
    webbrowser.open(url or connect_page_url())


def _tk_failure_window(view, opener=None, copier=None, show_pairing=None):
    import tkinter as tk
    from tkinter import ttk
    root = tk.Tk()
    root.title(view["title"])
    root.geometry("460x240")
    frame = ttk.Frame(root, padding=24)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text=view["message"], wraplength=400).pack(anchor="w")

    def get_new():
        (opener or open_connect_page)(view["connectUrl"])

    def type_code():
        root.destroy()
        os.environ.pop("MYRAANA_ENROLL_TOKEN", None)
        if show_pairing:
            show_pairing()
        else:
            setup_window()

    def copy_details():
        text = view.get("detail") or view["message"]
        if copier:
            copier(text)
            return
        root.clipboard_clear()
        root.clipboard_append(text)

    ttk.Button(frame, text="Get a new one", command=get_new).pack(anchor="w", pady=(16, 0))
    ttk.Button(frame, text="Type pairing code instead", command=type_code).pack(anchor="w", pady=(8, 0))
    ttk.Button(frame, text="Copy details", command=copy_details).pack(anchor="w", pady=(8, 0))
    root.mainloop()


def present_setup_failure(
    message, *, token="", reason="", detail="", website=None, host=None,
    poster=None, window=None, opener=None, copier=None, show_pairing=None,
):
    """Show the failure and post a diagnostic that does not contain the token."""
    view = setup_failure_view(
        message, token=token, reason=reason, detail=detail, website=website, host=host or "",
    )
    body = diagnostic_body(view)
    try:
        if poster:
            poster(body)
        else:
            post_setup_diagnostic(website, body)
    except Exception:
        pass
    if window is not None:
        window(view)
        return view
    _tk_failure_window(view, opener=opener, copier=copier, show_pairing=show_pairing)
    return view


def _notice_window(message):
    import tkinter as tk
    from tkinter import ttk
    root = tk.Tk()
    root.title("Myraana Connector")
    root.geometry("420x160")
    frame = ttk.Frame(root, padding=24)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text=message, wraplength=360).pack(anchor="w")
    ttk.Button(frame, text="Close", command=root.destroy).pack(anchor="w", pady=(16, 0))
    root.mainloop()


def enroll_quietly():
    """Enrol, start with Windows, and sit in the tray. No code and no website field."""
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    events = queue.Queue()
    stop = threading.Event()
    icon = {"current": None}
    scan_now = threading.Event()
    failure = {}

    def work():
        try:
            run(report=lambda message: events.put(("status", message)), stop=stop, scan_now=scan_now)
        except Exception as error:
            message = str(error) if isinstance(error, (ValueError, RuntimeError)) else ENROLL_ERROR
            events.put(("error", message))
        finally:
            events.put(("done", ""))

    def poll():
        try:
            while True:
                kind, message = events.get_nowait()
                if message == TOAST_MESSAGE:
                    show_toast(root, TOAST_MESSAGE)
                if kind == "error":
                    try:
                        failure["website"] = load_state().get("websiteUrl") or ""
                    except Exception:
                        failure["website"] = ""
                    failure["message"] = message
                    failure["token"] = os.environ.pop("MYRAANA_ENROLL_TOKEN", "")
                    root.destroy()
                    return
                if kind == "done":
                    return
        except queue.Empty:
            pass
        root.after(200, poll)

    def show_window():
        root.deiconify()
        try:
            root.lift()
        except Exception:
            pass

    def startup_checked():
        current = load_state()
        if "startWithWindows" in current:
            return bool(current.get("startWithWindows"))
        return startup_enabled()

    tray_actions = {
        "open": lambda _icon, _item: root.after(0, show_window),
        "scan": lambda _icon, _item: scan_now.set(),
        "toggle_startup": lambda _icon, _item: root.after(0, lambda: remember_startup(load_state(), not startup_checked())),
        "quit": lambda _icon, _item: root.after(0, lambda: quit_connector(root, stop, icon["current"])),
        "startup_checked": startup_checked,
    }
    icon["current"] = start_tray(root, tray_actions)
    threading.Thread(target=work, name="myraana-enroll", daemon=True).start()
    poll()
    root.mainloop()
    if failure.get("message"):
        present_setup_failure(
            failure["message"],
            token=failure.get("token") or "",
            reason=failure["message"],
            detail=failure["message"],
            website=failure.get("website") or "",
        )


def setup_window(self_test=False, notice=""):
    if self_test:
        exercise_bundled_modules()
        exercise_tray_support()
    elif notice:
        _notice_window(notice)
        return
    elif os.environ.get("MYRAANA_ENROLL_TOKEN"):
        enroll_quietly()
        return
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title("Myraana Connector")
    root.geometry("560x680")
    root.resizable(False, False)
    frame = ttk.Frame(root, padding=24)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="Connect your Windows computer",
              font=("Segoe UI", 16, "bold")).pack(anchor="w")
    ttk.Label(frame, text="Use your Myraana website and its pairing code.").pack(anchor="w", pady=(8, 18))
    state = load_state()
    ttk.Label(frame, text="Myraana website").pack(anchor="w")
    url = tk.StringVar(value=os.environ.get("MYRAANA_URL") or state.get("websiteUrl") or DEFAULT_WEBSITE)
    url_entry = ttk.Entry(frame, textvariable=url, width=64)
    url_entry.pack(fill="x", pady=(4, 12))
    ttk.Label(frame, text="Pairing code (leave blank when reconnecting)").pack(anchor="w")
    code = tk.StringVar(value=os.environ.get("MYRAANA_PAIRING_CODE", ""))
    code_entry = ttk.Entry(frame, textvariable=code, width=64)
    code_entry.pack(fill="x", pady=(4, 12))
    ttk.Label(frame, text="Fiery API (optional)").pack(anchor="w")
    ttk.Label(
        frame,
        text="Leave blank to send the PDF to the Fiery Hold queue. Fill in an API key, user, and password only if this Fiery requires them.",
        wraplength=500,
    ).pack(anchor="w", pady=(4, 8))
    ttk.Label(frame, text="Fiery API key").pack(anchor="w")
    fiery_key = tk.StringVar()
    fiery_key_entry = ttk.Entry(frame, textvariable=fiery_key, width=64)
    fiery_key_entry.pack(fill="x", pady=(4, 8))
    ttk.Label(frame, text="Fiery user").pack(anchor="w")
    fiery_user = tk.StringVar()
    fiery_user_entry = ttk.Entry(frame, textvariable=fiery_user, width=64)
    fiery_user_entry.pack(fill="x", pady=(4, 8))
    ttk.Label(frame, text="Fiery password").pack(anchor="w")
    fiery_password = tk.StringVar()
    fiery_password_entry = ttk.Entry(frame, textvariable=fiery_password, width=64, show="\u2022")
    fiery_password_entry.pack(fill="x", pady=(4, 12))
    status = tk.StringVar(value="Ready to connect.")
    events = queue.Queue()
    stop = threading.Event()
    worker = None

    def work(address, pairing_code):
        try:
            run(address, pairing_code, lambda message: events.put(("status", message)), stop, scan_now)
        except Exception as error:
            message = str(error) if isinstance(error, (ValueError, RuntimeError)) else "Setup could not complete. Check your connection and try again."
            events.put(("error", message))
        finally:
            events.put(("done", ""))

    def connect():
        nonlocal worker
        try:
            address = website_url(url.get())
        except ValueError as error:
            status.set(str(error))
            return
        stop.clear()
        remember_fiery_login(fiery_key.get(), fiery_user.get(), fiery_password.get())
        button.configure(state="disabled")
        url_entry.configure(state="disabled")
        code_entry.configure(state="disabled")
        fiery_key_entry.configure(state="disabled")
        fiery_user_entry.configure(state="disabled")
        fiery_password_entry.configure(state="disabled")
        status.set("Connecting...")
        pairing_code = code.get()
        code.set("")
        worker = threading.Thread(target=work, args=(address, pairing_code), daemon=True)
        worker.start()

    button = ttk.Button(frame, text="Connect", command=connect)
    button.pack(anchor="w", pady=(0, 12))
    ttk.Label(frame, textvariable=status, wraplength=500).pack(anchor="w")
    ttk.Label(frame, text=HOLD_FOOTER, wraplength=500).pack(anchor="w", pady=(16, 0))
    scan_now = threading.Event()
    icon = {"current": None}

    def poll():
        try:
            while True:
                kind, message = events.get_nowait()
                if kind in ("status", "error"):
                    status.set(message)
                if kind == "done":
                    button.configure(state="normal")
                    url_entry.configure(state="normal")
                    code_entry.configure(state="normal")
                    fiery_key_entry.configure(state="normal")
                    fiery_user_entry.configure(state="normal")
                    fiery_password_entry.configure(state="normal")
        except queue.Empty:
            pass
        root.after(200, poll)

    def show_window():
        root.deiconify()
        try:
            root.lift()
        except Exception:
            pass

    def saved_credential():
        try:
            return secret("credential")
        except Exception:
            return None

    def close():
        if self_test or icon["current"] is None:
            quit_connector(root, stop, icon["current"])
            return
        handle_window_close(root, stop)

    def startup_checked():
        current = load_state()
        if "startWithWindows" in current:
            return bool(current.get("startWithWindows"))
        return startup_enabled()

    tray_actions = {
        "open": lambda _icon, _item: root.after(0, show_window),
        "scan": lambda _icon, _item: request_scan(),
        "toggle_startup": lambda _icon, _item: root.after(0, toggle_startup),
        "quit": lambda _icon, _item: root.after(0, lambda: quit_connector(root, stop, icon["current"])),
        "startup_checked": startup_checked,
    }

    def request_scan():
        scan_now.set()
        root.after(0, lambda: status.set("Scanning again for printers."))

    def toggle_startup():
        current = load_state()
        remember_startup(current, not startup_checked())
        status.set("Start with Windows is on." if current.get("startWithWindows") else "Start with Windows is off.")

    root.protocol("WM_DELETE_WINDOW", close)
    if self_test:
        # Discovery, Fiery HOLD, and tray support were loaded above. Close without connecting.
        root.update()
        root.after(100, close)
    else:
        icon["current"] = start_tray(root, tray_actions)
        poll()
        if should_reconnect(load_state(), saved_credential(), code.get()):
            root.after(200, connect)
    root.mainloop()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--console", action="store_true", help="Use console setup")
    parser.add_argument("--self-test", action="store_true", help="Check setup window without connecting")
    args = parser.parse_args(argv)
    if args.self_test:
        setup_window(self_test=True)
        return 0
    if running_from_install():
        apply_staged_update()
    if getattr(sys, "frozen", False) and not running_from_install():
        token = setup_token_from_executable(sys.executable)
        if not token:
            present_setup_failure(
                EXPIRED_SETUP_TITLE,
                reason=EXPIRED_SETUP_TITLE,
                detail="The setup filename and trailer did not contain a token.",
            )
            return 0
        try:
            handoff_setup(sys.executable, token)
        except Exception as error:
            present_setup_failure(
                SETUP_COPY_ERROR,
                token=token,
                reason=SETUP_COPY_ERROR,
                detail=str(error),
            )
            return 0
        return 0
    if args.console:
        run()
    else:
        setup_window(self_test=False)
    return 0


if __name__ == "__main__":
    main()
