"""Submit a PRINT_READY PDF to a Fiery Hold queue. This never prints or releases.

The file goes to the published Hold queue: LPR queue "hold" (RFC 1179), then IPP
/ipp/hold or /hold, then the Windows share \\\\address\\hold. The Fiery API is used
only when the connector has an API key, user, and password. print and direct
are refused.
"""
import json
import os
import socket
import ssl
import time
import http.client
from pathlib import Path
from urllib.parse import urlparse


HOLD_QUEUE = "hold"
HOLD_STATUSES = {200, 201, 202, 204}
CONFIRMED_METHODS = {"lpr", "ipp", "smb", "api", "hot-folder"}
IPP_HOLD_PATHS = ("/ipp/hold", "/hold")
API_PATHS = {"/live/api/v5/login", "/live/api/v5/jobs"}


def hold_queue_name(queue):
    """The only queue this program may name. print and direct are refused."""
    name = str("hold" if queue is None or str(queue).strip() == "" else queue).strip().lower()
    if name != HOLD_QUEUE:
        raise RuntimeError("Refusing to print. Only the hold queue is allowed.")
    return HOLD_QUEUE


def hold_ipp_paths(queue="hold"):
    hold_queue_name(queue)
    paths = []
    for path in IPP_HOLD_PATHS:
        if path != "/hold" and not path.endswith("/hold"):
            raise RuntimeError("Refusing to print. Only the hold queue is allowed.")
        if "print" in path or "direct" in path:
            raise RuntimeError("Refusing to print. Only the hold queue is allowed.")
        paths.append(path)
    return tuple(paths)


def host_only(address):
    text = str(address or "").strip()
    if "://" in text:
        text = urlparse(text).hostname or ""
    if text.startswith("[") and "]" in text:
        text = text[1:text.index("]")]
    elif text.count(":") == 1:
        text = text.split(":", 1)[0]
    return text.strip()


def private_ipv4(address):
    """RFC1918 IPv4, written without leading zeros. Hostnames and public IPs are refused."""
    host = host_only(address)
    if not host or any(char in host for char in "\\/ \t"):
        return None
    parts = host.split(".")
    if len(parts) != 4:
        return None
    numbers = []
    for part in parts:
        if not part.isdigit() or part != str(int(part)) or int(part) > 255:
            return None
        numbers.append(int(part))
    first, second = numbers[0], numbers[1]
    if first == 10 or (first == 172 and 16 <= second <= 31) or (first == 192 and second == 168):
        return ".".join(str(number) for number in numbers)
    return None


def discovered_fiery_ips(printers):
    """Private addresses of Fiery printers this computer found. A public address is ignored."""
    allowed = []
    for item in printers or []:
        if not isinstance(item, dict) or not item.get("isFiery"):
            continue
        ip = private_ipv4(item.get("address") or "")
        if ip and ip not in allowed:
            allowed.append(ip)
    return allowed


def _unc_parts(text):
    raw = str(text or "").strip().replace("/", "\\")
    if not raw.startswith("\\\\"):
        return None
    pieces = raw[2:].split("\\")
    while pieces and pieces[-1] == "":
        pieces.pop()
    if not pieces or any(part == "" for part in pieces):
        return None
    return pieces


def hold_target(supplied, printers):
    """The only address a HOLD job may use: one private Fiery this computer discovered.

    A UNC path is accepted only as \\\\discovered-ip\\hold. Any other share, extra
    path, hostname, or public address is refused before a connection is opened.
    """
    allowed = discovered_fiery_ips(printers)
    if not allowed:
        raise RuntimeError("No Fiery was found on this computer. Nothing was printed.")
    text = str(supplied or "").strip()
    if not text:
        if len(allowed) == 1:
            return allowed[0]
        raise RuntimeError("This computer did not discover that Fiery. Nothing was printed.")
    pieces = _unc_parts(text)
    if pieces is not None:
        if len(pieces) != 2 or pieces[1].lower() != "hold":
            raise RuntimeError("This computer did not discover that Fiery. Nothing was printed.")
        ip = private_ipv4(pieces[0])
    elif text.startswith("\\") or text.startswith("//"):
        raise RuntimeError("This computer did not discover that Fiery. Nothing was printed.")
    else:
        ip = private_ipv4(text)
    if not ip or ip not in allowed:
        raise RuntimeError("This computer did not discover that Fiery. Nothing was printed.")
    return ip


def _operator_hold_folder(folder):
    """A drop folder the operator chose on this computer. A UNC path is refused."""
    text = str(folder or "").strip()
    if not text:
        return None
    if text.startswith("\\\\") or text.startswith("//") or text.startswith("\\") or "://" in text:
        raise RuntimeError("The Hold folder must be a folder on this computer. Nothing was printed.")
    return text


def pdf_filename(filename):
    name = Path(str(filename or "")).name
    if not name or name in {".", ".."} or any(char in name for char in "\\/\x00\r\n"):
        name = "artwork_PRINT_READY.pdf"
    if not name.lower().endswith(".pdf"):
        name = "artwork_PRINT_READY.pdf"
    return name[:180]


def job_label(job_name="", job_id="", filename=""):
    """The name Command WorkStation shows for this held job."""
    parts = []
    for value in (job_name, job_id):
        text = "".join(char if ord(char) >= 32 else " " for char in str(value or ""))
        text = " ".join(text.split())
        if text and text not in parts:
            parts.append(text)
    label = " ".join(parts).strip()
    if not label:
        label = pdf_filename(filename)[:-4]
    return label[:120] or "Myraana"


def hold_payload(filename, preset, stock, job_name=""):
    """Attributes for a hold submission. print and release stay false."""
    payload = {
        "filename": pdf_filename(filename),
        "queue": HOLD_QUEUE,
        "preset": str(preset or "London BC")[:80],
        "stock": str(stock or "")[:120],
        "jobName": job_label(job_name, "", filename),
        "print": False,
        "release": False,
    }
    if payload["print"] or payload["release"] or payload["queue"] != HOLD_QUEUE:
        raise RuntimeError("Refusing to print.")
    return payload


def fiery_credentials(value):
    """API login is used only when the key, user, and password are all set."""
    if not isinstance(value, dict):
        return None
    api_key = str(value.get("apiKey") or value.get("api_key") or value.get("apikey") or "").strip()
    username = str(value.get("username") or value.get("user") or "").strip()
    password = str(value.get("password") or "")
    if not api_key or not username or not password.strip():
        return None
    return {"apiKey": api_key, "username": username, "password": password}


def assert_pinned_peer(expected, actual):
    """A self-signed Fiery certificate is accepted only for this one address."""
    if not expected or str(actual) != str(expected):
        raise RuntimeError("Refusing a certificate that is not pinned to the Fiery address.")


def hold_method_label(method):
    return {
        "lpr": "LPR",
        "ipp": "IPP",
        "smb": "SMB",
        "api": "the Fiery API",
        "hot-folder": "the Hold folder",
    }.get(method, "the Hold queue")


def _failed(method, detail):
    text = " ".join(str(detail or "Fiery did not accept the hold.").split())
    if "Nothing was printed" not in text and "stays on HOLD" not in text:
        text = text.rstrip(".") + ". Nothing was printed."
    return {
        "ok": False,
        "held": False,
        "printed": False,
        "method": method if method in CONFIRMED_METHODS else "",
        "error": text[:500],
    }


def _confirmed(method):
    if method not in CONFIRMED_METHODS:
        raise RuntimeError("Refusing to print. Only the hold queue is allowed.")
    return {"ok": True, "held": True, "printed": False, "method": method, "error": ""}


def submit_hold(
    address,
    filename,
    preset,
    stock,
    pdf,
    opener=None,
    hot_folder=None,
    timeout=8.0,
    job_name="",
    job_id="",
    credentials=None,
    queue="hold",
    lpr=None,
    ipp=None,
    smb=None,
    api=None,
    printers=None,
    operator_folder=None,
):
    """Put the PDF on the Fiery Hold queue. A transport must confirm before this returns held.

    opener is ignored. hot_folder is ignored: a path supplied by the server is never
    written. operator_folder is used only when this computer passes a local folder.
    When printers is set, the address must be a private Fiery in that list.
    The API is used only when credentials contains an API key, user, and password,
    and only after the Hold queue transports fail.
    """
    del opener
    del hot_folder
    try:
        queue = hold_queue_name(queue)
        payload = hold_payload(filename, preset, stock, job_label(job_name, job_id, filename))
        if printers is not None:
            address = hold_target(address, printers)
    except RuntimeError as error:
        return _failed("", str(error))
    pdf = pdf or b""
    label = payload["jobName"]
    errors = []

    def attempt(method, func):
        try:
            outcome = func()
        except Exception as error:
            errors.append(f"{method}: {error}")
            return None
        if (
            isinstance(outcome, dict)
            and outcome.get("ok") is True
            and outcome.get("held") is True
            and outcome.get("printed") is not True
            and outcome.get("release") is not True
            and outcome.get("released") is not True
        ):
            return _confirmed(method)
        errors.append(f"{method}: the transport did not confirm the hold.")
        return None

    lpr_fn = lpr or send_lpr
    held = attempt("lpr", lambda: lpr_fn(address, pdf, label, payload["filename"], timeout, queue))
    if held:
        return held
    ipp_fn = ipp or send_ipp
    held = attempt("ipp", lambda: ipp_fn(address, pdf, label, payload["filename"], timeout, queue))
    if held:
        return held
    allowed = discovered_fiery_ips(printers) if printers is not None else None

    def run_smb():
        if smb is not None:
            return smb(address, pdf, payload["filename"], timeout, queue)
        return send_smb(address, pdf, payload["filename"], timeout, queue, allowed=allowed)

    held = attempt("smb", run_smb)
    if held:
        return held
    if operator_folder:
        held = attempt("hot-folder", lambda: _commit_hot_folder(operator_folder, payload["filename"], pdf))
        if held:
            return held
    creds = fiery_credentials(credentials)
    if creds:
        api_fn = api or fiery_api_submit
        held = attempt("api", lambda: api_fn(address, pdf, payload, creds, timeout))
        if held:
            return held
    detail = "The Fiery Hold queue did not confirm the file."
    if errors:
        detail = detail + " " + " ".join(errors)
    return _failed("", detail)


def send_lpr(address, pdf, job_name, filename, timeout, queue="hold", port=515):
    """RFC 1179 receive-job for the hold queue. Every acknowledgement must be zero."""
    queue = hold_queue_name(queue)
    host = host_only(address)
    if not host:
        raise RuntimeError("No Fiery address.")
    title = job_label(job_name, "", filename)
    visible = title if title.lower().endswith(".pdf") else f"{title}.pdf"
    number = f"{(time.monotonic_ns() // 1_000_000) % 1000:03d}"
    control_host = "myraana"
    data_name = f"dfA{number}{control_host}"
    control_name = f"cfA{number}{control_host}"
    control = (
        f"H{control_host}\n"
        f"Pmyraana\n"
        f"J{title}\n"
        f"C{control_host}\n"
        f"N{visible[:120]}\n"
        f"l{data_name}\n"
        f"U{data_name}\n"
    ).encode("utf-8")
    pdf = pdf or b""
    with socket.create_connection((host, int(port)), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        _lpr_command(sock, b"\x02" + queue.encode("ascii") + b"\n")
        _lpr_command(sock, f"\x02{len(control)} {control_name}\n".encode("ascii"))
        sock.sendall(control + b"\x00")
        _lpr_ack(sock)
        _lpr_command(sock, f"\x03{len(pdf)} {data_name}\n".encode("ascii"))
        sock.sendall(pdf + b"\x00")
        _lpr_ack(sock)
    return _confirmed("lpr")


def _lpr_command(sock, packet):
    sock.sendall(packet)
    _lpr_ack(sock)


def _lpr_ack(sock):
    data = b""
    while len(data) < 1:
        chunk = sock.recv(1)
        if not chunk:
            raise RuntimeError("Fiery closed the LPR connection before confirming the hold.")
        data += chunk
    if data != b"\x00":
        raise RuntimeError(f"Fiery LPR refused the hold (code {data[0]}).")


def build_ipp_print_job(printer_uri, document_name, pdf):
    """Print-Job aimed at a Hold queue, with job-hold-until indefinite. It does not release."""
    if "/hold" not in str(printer_uri) or "print" in urlparse(printer_uri).path or "direct" in urlparse(printer_uri).path:
        raise RuntimeError("Refusing to print. Only the hold queue is allowed.")

    def attr(tag, name, value):
        name_b = name.encode("utf-8")
        value_b = value.encode("utf-8") if isinstance(value, str) else value
        return bytes([tag]) + len(name_b).to_bytes(2, "big") + name_b + len(value_b).to_bytes(2, "big") + value_b

    message = bytearray()
    message += bytes([0x01, 0x01, 0x00, 0x02, 0x00, 0x00, 0x00, 0x01])
    message += bytes([0x01])
    message += attr(0x47, "attributes-charset", "utf-8")
    message += attr(0x48, "attributes-natural-language", "en")
    message += attr(0x45, "printer-uri", printer_uri)
    message += attr(0x42, "requesting-user-name", "myraana")
    message += attr(0x42, "document-name", document_name)
    message += attr(0x49, "document-format", "application/pdf")
    message += bytes([0x02])
    message += attr(0x44, "job-hold-until", "indefinite")
    message += bytes([0x03])
    message += pdf or b""
    return bytes(message)


def ipp_confirmed(http_status, payload):
    """True only when IPP reports a successful-ok class status for the Hold job."""
    if int(http_status) != 200 or not payload or len(payload) < 8:
        return False
    status = int.from_bytes(payload[2:4], "big")
    return status <= 0x00FF


def send_ipp(address, pdf, job_name, filename, timeout, queue="hold", port=631, post=None):
    queue = hold_queue_name(queue)
    host = host_only(address)
    if not host:
        raise RuntimeError("No Fiery address.")
    title = job_label(job_name, "", filename)
    errors = []
    for path in hold_ipp_paths(queue):
        printer_uri = f"ipp://{host}{path}"
        body = build_ipp_print_job(printer_uri, title, pdf or b"")
        try:
            if post is not None:
                status, payload = post(host, path, body, timeout)
            else:
                status, payload = _ipp_post(host, int(port), path, body, timeout)
        except Exception as error:
            errors.append(f"{path}: {error}")
            continue
        if ipp_confirmed(status, payload):
            return _confirmed("ipp")
        errors.append(f"{path}: IPP did not confirm the hold.")
    raise RuntimeError("IPP did not confirm the hold. " + " ".join(errors))


def _ipp_post(host, port, path, body, timeout):
    if path not in hold_ipp_paths():
        raise RuntimeError("Refusing to print. Only the hold queue is allowed.")
    connection = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        connection.request(
            "POST",
            path,
            body=body,
            headers={"Content-Type": "application/ipp"},
        )
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def smb_hold_unc(address, filename, queue="hold", allowed=None):
    """Build \\\\discovered-ip\\hold\\file. An arbitrary UNC path is never returned."""
    hold_queue_name(queue)
    text = str(address or "").strip()
    if text.startswith("\\\\") or text.startswith("//") or text.startswith("\\"):
        raise RuntimeError("Refusing an SMB path that was not built from a discovered Fiery. Nothing was printed.")
    ip = private_ipv4(text)
    if not ip:
        raise RuntimeError("Refusing a Fiery address that is not a private network address. Nothing was printed.")
    allow = []
    for item in allowed or []:
        candidate = private_ipv4(item.get("address") if isinstance(item, dict) else item)
        if candidate and candidate not in allow:
            allow.append(candidate)
    if ip not in allow:
        raise RuntimeError("This computer did not discover that Fiery. Nothing was printed.")
    path = f"\\\\{ip}\\hold\\{pdf_filename(filename)}"
    lowered = path.lower()
    if not lowered.startswith(f"\\\\{ip}\\hold\\") or "\\print\\" in lowered or "\\direct\\" in lowered:
        raise RuntimeError("Refusing to print. Only the hold queue is allowed.")
    return path


def send_smb(address, pdf, filename, timeout, queue="hold", copy=None, allowed=None):
    """Copy onto \\\\discovered-ip\\hold. Used on the shop Windows computer."""
    del timeout
    path = smb_hold_unc(address, filename, queue, allowed=allowed)
    writer = copy or _copy_unc
    if copy is None and os.name != "nt":
        raise RuntimeError("SMB Hold copy is only used on the shop Windows computer.")
    writer(path, pdf or b"")
    return _confirmed("smb")


def _copy_unc(path, pdf):
    if "\\hold\\" not in path.lower():
        raise RuntimeError("Refusing to print. Only the hold queue is allowed.")
    target = Path(path)
    target.write_bytes(pdf)
    if target.stat().st_size != len(pdf) or target.read_bytes() != pdf:
        raise RuntimeError("The Hold share did not confirm the file.")


def _commit_hot_folder(folder, filename, pdf):
    local = _operator_hold_folder(folder)
    if not local:
        raise RuntimeError("The Hold folder must be a folder on this computer. Nothing was printed.")
    _write_hold_folder(local, filename, pdf)
    return _confirmed("hot-folder")


def _pinned_ipv4(address):
    host = host_only(address)
    parts = host.split(".")
    if len(parts) != 4:
        raise RuntimeError("Fiery API login is pinned to one IP address.")
    try:
        if any(not part.isdigit() or int(part) > 255 for part in parts):
            raise RuntimeError("Fiery API login is pinned to one IP address.")
    except RuntimeError:
        raise
    socket.inet_aton(host)
    return host


def fiery_api_submit(address, pdf, payload, credentials, timeout):
    """Login, then submit the hold. The self-signed certificate is pinned to this IP."""
    if payload.get("print") or payload.get("release") or payload.get("queue") != HOLD_QUEUE:
        raise RuntimeError("Refusing to print.")
    creds = fiery_credentials(credentials)
    if not creds:
        raise RuntimeError("Fiery API login needs an API key, user, and password.")
    host = _pinned_ipv4(address)
    token = _fiery_login(host, creds, timeout)
    status = _fiery_post_job(host, token, payload, pdf or b"", timeout)
    if int(status) not in HOLD_STATUSES:
        raise RuntimeError(f"Fiery answered {status}.")
    return _confirmed("api")


def _fiery_login(host, credentials, timeout):
    body = json.dumps(
        {
            "username": credentials["username"],
            "password": credentials["password"],
            "apikey": credentials["apiKey"],
            "apiKey": credentials["apiKey"],
        }
    ).encode("utf-8")
    status, payload = _pinned_request(
        host,
        "POST",
        "/live/api/v5/login",
        body,
        {"Content-Type": "application/json"},
        timeout,
    )
    if status not in HOLD_STATUSES:
        raise RuntimeError(f"Fiery login was refused ({status}).")
    try:
        data = json.loads(payload.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    for key in ("token", "session", "sessionId", "access_token", "accessToken"):
        if data.get(key):
            return str(data[key])
    raise RuntimeError("Fiery login did not return a session.")


def _fiery_post_job(host, token, payload, pdf, timeout):
    content_type, body = _job_body(payload, pdf)
    status, _payload = _pinned_request(
        host,
        "POST",
        "/live/api/v5/jobs",
        body,
        {"Content-Type": content_type, "Authorization": f"Bearer {token}"},
        timeout,
    )
    return status


def _pinned_request(host, method, path, body, headers, timeout):
    host = _pinned_ipv4(host)
    if path not in API_PATHS:
        raise RuntimeError("Refusing a Fiery call that is not login or a hold submission.")
    # The Fiery certificate is self-signed. Verification is the peer IP, not a public CA.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    connection = http.client.HTTPSConnection(host, 443, timeout=timeout, context=context)
    try:
        connection.connect()
        peer = connection.sock.getpeername()[0]
        assert_pinned_peer(host, peer)
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def _job_body(payload, pdf):
    if payload.get("print") or payload.get("release") or payload.get("queue") != HOLD_QUEUE:
        raise RuntimeError("Refusing to print.")
    boundary = "----myraana-hold"
    meta = json.dumps({key: value for key, value in payload.items() if key != "jobName"}).encode("utf-8")
    filename = payload["filename"]
    body = b"".join(
        [
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"attributes\"\r\nContent-Type: application/json\r\n\r\n".encode(),
            meta,
            b"\r\n",
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\nContent-Type: application/pdf\r\n\r\n".encode(),
            pdf or b"",
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return f"multipart/form-data; boundary={boundary}", body


def fiery_opener(url, payload, pdf, timeout, headers=None, pinned_ip=None):
    """POST a hold to one pinned Fiery IP. There is no print or release call."""
    if payload.get("print") or payload.get("release") or payload.get("queue") != HOLD_QUEUE:
        raise RuntimeError("Refusing to print.")
    host = urlparse(url).hostname or ""
    if not pinned_ip:
        raise RuntimeError("Fiery API requires a certificate pinned to the Fiery address.")
    assert_pinned_peer(pinned_ip, host)
    if urlparse(url).path not in API_PATHS:
        raise RuntimeError("Refusing a Fiery call that is not login or a hold submission.")
    content_type, body = _job_body(payload, pdf)
    request_headers = {"Content-Type": content_type}
    if headers:
        request_headers.update(headers)
    status, _payload = _pinned_request(host, "POST", urlparse(url).path, body, request_headers, timeout)
    return status


def interpret_hold_report(report):
    """A connector report may confirm a hold. A print, release, or unconfirmed method is refused."""
    if not isinstance(report, dict):
        return _failed("", "The connector report was empty.")
    if report.get("printed") is True or report.get("released") is True or report.get("release") is True:
        return _failed("", "Refused a print or release. The job stays on HOLD.")
    method = str(report.get("method") or "")
    if method not in CONFIRMED_METHODS:
        method = ""
    if report.get("ok") is True and report.get("held") is True and method:
        return _confirmed(method)
    if report.get("ok") is True and report.get("held") is True:
        return _failed("", "The hold was not confirmed by the Fiery Hold queue.")
    return _failed(method, report.get("error") or "Fiery did not accept the hold.")


def _write_hold_folder(folder, filename, pdf):
    folder = _operator_hold_folder(folder)
    if not folder:
        raise RuntimeError("The Hold folder must be a folder on this computer. Nothing was printed.")
    root = Path(folder).resolve()
    hold = root / "Hold"
    hold.mkdir(parents=True, exist_ok=True)
    safe = pdf_filename(filename)
    target = (hold / safe).resolve()
    if hold.resolve() not in target.parents:
        raise ValueError("path")
    target.write_bytes(pdf)
    if target.read_bytes() != pdf:
        raise RuntimeError("The Hold folder did not confirm the file.")
