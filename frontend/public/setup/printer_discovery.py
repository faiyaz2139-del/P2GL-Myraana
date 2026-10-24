"""Find presses on the shop LAN and in the local print queues.

The connector runs this on the shop computer. Tests pass the network and
command results in, so nothing here contacts a printer unless a caller asks.
A printer is an EFI Fiery when its name matches a Fiery server (EX-Li, EX-i,
EX-P, EX … Server, PX300, Fiery, EFI, Command WorkStation), when another queue
shares that server's IP, or when https://<address>:443/live/api/v5 answers.
"""
import json
import platform
import re
import socket
import ssl
import struct
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request


SERVICE_TYPES = (
    "_ipp._tcp",
    "_ipps._tcp",
    "_printer._tcp",
    "_pdl-datastream._tcp",
)
FIERY_API_PATH = "/live/api/v5"
FIERY_API_PORT = 443
# Answers that mean this host is serving the Fiery API, not a missing page.
_FIERY_STATUSES = {200, 201, 204, 301, 302, 401, 403}
_WEAK_PROTOCOLS = {"", "queue", "usb"}


# Fiery EX-i, EX-Li, EX-P, EX … Server, PX300, and the EFI / Command WorkStation names.
_FIERY_NAME = re.compile(
    r"fiery|command\s+workstation|\befi\b|ex-li|ex-i\b|ex-p\b|\bpx\d{2,}\b|\bex\b[\w\s./()-]{0,48}\bserver\b",
    re.IGNORECASE,
)


def looks_like_fiery(*parts):
    blob = " ".join(str(part or "") for part in parts)
    return bool(_FIERY_NAME.search(blob))


def host_key(address):
    """IP or hostname used to group a Fiery server with the queues on that host."""
    text = str(address or "").strip().lower()
    if not text:
        return ""
    text = re.sub(r"^[a-z][a-z0-9+.-]*://", "", text)
    if text.startswith("ip_"):
        text = text[3:]
    text = text.split("/")[0].strip()
    if text.startswith("[") and "]" in text:
        return text[1:text.index("]")]
    if text.count(":") == 1:
        text = text.split(":")[0]
    return text


def mark_fiery_queues(rows):
    """A queue that shares an IP with a Fiery server is that Fiery's queue."""
    hosts = set()
    for row in rows or []:
        if not isinstance(row, dict) or not row.get("isFiery"):
            continue
        key = host_key(row.get("address"))
        if key:
            hosts.add(key)
    if not hosts:
        return rows
    for row in rows:
        if isinstance(row, dict) and host_key(row.get("address")) in hosts:
            row["isFiery"] = True
    return rows


def preferred_printer(rows):
    """The business-card press when the shop has exactly one Fiery host.

    Queues on that host count as the same Fiery. The server name is the one
    selected. The operator can still choose a different queue.
    """
    groups = {}
    for row in rows or []:
        if not isinstance(row, dict) or not row.get("isFiery"):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        key = host_key(row.get("address")) or name.lower()
        groups.setdefault(key, []).append(row)
    if len(groups) != 1:
        return None
    members = next(iter(groups.values()))
    servers = [
        row for row in members
        if looks_like_fiery(row.get("name"), row.get("model"), row.get("driver"))
    ]
    if not servers:
        return str(members[0].get("name") or "").strip() or None

    def rank(row):
        blob = f"{row.get('name') or ''} {row.get('model') or ''}".lower()
        score = 0
        if "server" in blob:
            score += 4
        if any(token in blob for token in ("ex-li", "ex-i", "ex-p", "px")):
            score += 2
        if "fiery" in blob or re.search(r"\befi\b", blob):
            score += 1
        return score

    chosen = max(servers, key=rank)
    return str(chosen.get("name") or "").strip() or None


def scan_is_due(settings, incoming_scanned=False):
    """True until the connector reports the scan the shop just requested."""
    if incoming_scanned:
        return False
    requested = str((settings or {}).get("scanRequestedAt") or "")
    fulfilled = str((settings or {}).get("scanFulfilledAt") or "")
    return bool(requested) and requested > fulfilled


def fiery_api_url(address):
    host = str(address or "").strip()
    if not host or any(mark in host for mark in " /\\?#"):
        return None
    if host.startswith("[") and "]" in host:
        host = host[:host.index("]") + 1]
    else:
        host = host.split("/")[0]
        if host.count(":") == 1:
            host = host.split(":")[0]
        elif host.count(":") > 1:
            host = f"[{host}]"
    if not host or host.lower() in {"localhost", "0.0.0.0"}:
        return None
    return f"https://{host}:{FIERY_API_PORT}{FIERY_API_PATH}"


def fiery_api_answered(status):
    try:
        return int(status) in _FIERY_STATUSES
    except (TypeError, ValueError):
        return False


def probe_fiery(address, timeout=1.0, opener=None):
    """True when the Fiery API on this address answers. Connection failures are not a match."""
    url = fiery_api_url(address)
    if not url:
        return False
    try:
        status = opener(url, timeout) if opener else _http_status(url, timeout)
    except urllib.error.HTTPError as error:
        status = error.code
    except Exception:
        return False
    if isinstance(status, bool):
        return status
    return fiery_api_answered(status)


def printer_record(name, model="", address="", protocol="", is_fiery=False, driver="", port=""):
    name = str(name or "").strip()[:120]
    model = str(model or "").strip()[:160]
    address = str(address or "").strip()[:200]
    protocol = str(protocol or "").strip()[:40] or "queue"
    driver = str(driver or "").strip()[:160]
    port = str(port or "").strip()[:160]
    record = {
        "name": name,
        "model": model,
        "address": address,
        "protocol": protocol,
        "isFiery": bool(is_fiery) or looks_like_fiery(name, model, driver),
    }
    if driver:
        record["driver"] = driver
    if port:
        record["port"] = port
    return record


def normalise_reported(items):
    rows = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        row = from_queue(item)
        if not row or not row.get("name"):
            continue
        if item.get("isFiery"):
            row["isFiery"] = True
        rows.append(row)
    return mark_fiery_queues(merge_printers(rows))[:50]


def merge_printers(rows):
    merged = {}
    order = []
    for row in rows:
        if not row or not row.get("name"):
            continue
        key = re.sub(r"[^a-z0-9]+", "", row["name"].lower()) or row["name"].lower()
        current = merged.get(key)
        if current is None:
            merged[key] = dict(row)
            order.append(key)
            continue
        for field in ("model", "driver", "port"):
            if not current.get(field) and row.get(field):
                current[field] = row[field]
        if _prefer_address(row.get("address"), current.get("address")):
            current["address"] = row["address"]
        if current.get("protocol") in _WEAK_PROTOCOLS and row.get("protocol") not in _WEAK_PROTOCOLS:
            current["protocol"] = row["protocol"]
        current["isFiery"] = bool(current.get("isFiery") or row.get("isFiery"))
    return [merged[key] for key in order]


def from_mdns(service):
    if not isinstance(service, dict):
        return None
    model = service.get("model") or model_from_txt(service.get("properties") or {})
    address = service.get("address") or service.get("host") or ""
    protocol = service.get("protocol") or protocol_for_service(service.get("service") or "")
    return printer_record(
        service.get("name"),
        model,
        address,
        protocol,
        is_fiery=service.get("isFiery"),
        driver=service.get("driver") or model,
        port=service.get("port") or address,
    )


def from_queue(item):
    if not isinstance(item, dict):
        return None
    model = item.get("model") or item.get("driver") or ""
    port = str(item.get("port") or "")
    address = str(item.get("address") or "")
    protocol = str(item.get("protocol") or "")
    parsed_address, parsed_protocol = address_and_protocol(item.get("uri") or port)
    if not address:
        address = parsed_address
    if not protocol:
        protocol = parsed_protocol
    return printer_record(
        item.get("name"),
        model,
        address,
        protocol or "queue",
        is_fiery=item.get("isFiery"),
        driver=item.get("driver") or model,
        port=port or address,
    )


def discover(mdns_services=None, os_queues=None, browse=None, list_queues=None, probe=None):
    """Merge Bonjour records and OS queues. Pass browse/list_queues/probe to hit the network."""
    services = [item for item in (mdns_services or []) if isinstance(item, dict)]
    queues = [item for item in (os_queues or []) if isinstance(item, dict)]
    if browse:
        try:
            services.extend(browse() or [])
        except Exception:
            pass
    if list_queues:
        try:
            queues.extend(list_queues() or [])
        except Exception:
            pass
    rows = []
    for service in services:
        row = from_mdns(service)
        if row and row.get("name"):
            rows.append(row)
    for queue in queues:
        row = from_queue(queue)
        if row and row.get("name"):
            rows.append(row)
    return mark_fiery_queues(mark_fiery_apis(merge_printers(rows), probe))


def mark_fiery_apis(rows, probe, limit=4):
    if not probe:
        return rows
    pending = [row for row in rows if not row.get("isFiery") and row.get("address")][:limit]
    if not pending:
        return rows
    from concurrent.futures import ThreadPoolExecutor

    def one(row):
        try:
            return bool(probe(row["address"]))
        except Exception:
            return False

    with ThreadPoolExecutor(max_workers=min(4, len(pending))) as pool:
        flags = list(pool.map(one, pending))
    for row, flag in zip(pending, flags):
        if flag:
            row["isFiery"] = True
    return rows


def protocol_for_service(service):
    text = str(service or "").lower()
    if "_ipps._tcp" in text:
        return "ipps"
    if "_ipp._tcp" in text:
        return "ipp"
    if "_printer._tcp" in text:
        return "lpd"
    if "_pdl-datastream._tcp" in text:
        return "socket"
    return "ipp"


def model_from_txt(props):
    if not isinstance(props, dict):
        return ""
    lowered = {str(key).lower(): str(value or "") for key, value in props.items()}
    for key in ("ty", "product", "usb_mdl"):
        if lowered.get(key):
            return lowered[key].strip().strip("()")
    maker = lowered.get("usb_mfg") or ""
    return maker.strip()


def address_and_protocol(value):
    text = str(value or "").strip()
    if not text:
        return "", ""
    if text.lower().startswith("ip_"):
        host = text[3:]
        if _is_ip(host):
            return host, "socket"
    if "://" not in text:
        host = text.split("/")[0]
        if _is_ip(host.split(":")[0]):
            return host.split(":")[0], "socket"
        return "", "usb" if text.lower().startswith("usb") else ""
    scheme, rest = text.split("://", 1)
    protocol = {
        "ipp": "ipp",
        "ipps": "ipps",
        "socket": "socket",
        "lpd": "lpd",
        "dnssd": "ipp",
        "usb": "usb",
    }.get(scheme.lower(), scheme.lower()[:40])
    rest = urllib.parse.unquote(rest)
    host = rest.split("/")[0].split("@")[-1]
    if host.startswith("[") and "]" in host:
        address = host[:host.index("]") + 1]
    else:
        address = host.split(":")[0]
    return address, protocol


def parse_lpstat(details, devices=""):
    """Read `lpstat -l -p` and `lpstat -v`."""
    current = None
    found = []
    for line in str(details or "").splitlines():
        if line.startswith("printer "):
            parts = line.split()
            name = parts[1] if len(parts) > 1 else ""
            current = {"name": name, "model": "", "uri": ""}
            found.append(current)
            continue
        stripped = line.strip()
        if current is not None and stripped.lower().startswith("description:"):
            current["model"] = stripped.split(":", 1)[1].strip()
    uris = {}
    for line in str(devices or "").splitlines():
        match = re.match(r"device for\s+(\S+)\s*:\s*(\S+)", line.strip(), re.I)
        if match:
            uris[match.group(1)] = match.group(2)
    rows = []
    for item in found:
        if not item["name"]:
            continue
        item["uri"] = uris.get(item["name"], "")
        address, protocol = address_and_protocol(item["uri"])
        rows.append({
            "name": item["name"],
            "model": item["model"],
            "driver": item["model"],
            "address": address,
            "protocol": protocol or "queue",
            "port": item["uri"],
            "uri": item["uri"],
        })
    return rows


def parse_get_printer(payload):
    """Read ConvertTo-Json output from Get-Printer."""
    text = str(payload or "").lstrip("\ufeff").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return []
    rows = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = item.get("Name") or item.get("name") or ""
        driver = item.get("DriverName") or item.get("driver") or ""
        port = item.get("PortName") or item.get("port") or ""
        host = item.get("Host") or item.get("PrinterHostAddress") or ""
        address, protocol = address_and_protocol(host or port)
        rows.append({
            "name": name,
            "model": driver,
            "driver": driver,
            "address": address,
            "protocol": protocol or "queue",
            "port": port,
        })
    return rows


def os_queues(run=None, system=None):
    system = system or platform.system()
    run = run or _run
    if system == "Windows":
        return parse_get_printer(run(["powershell", "-NoProfile", "-Command", _GET_PRINTER]))
    details = run(["lpstat", "-l", "-p"])
    devices = run(["lpstat", "-v"])
    return parse_lpstat(details, devices)


def browse_mdns(service_types=SERVICE_TYPES, timeout=1.0, transport=None):
    names = [_service_name(item) for item in service_types]
    if transport:
        packets = transport(names, timeout) or []
    else:
        packets = mdns_exchange(names, timeout)
    return services_from_packets(packets)


def services_from_packets(packets):
    ptrs = []
    srvs = {}
    addresses = {}
    txts = {}
    for packet in packets or []:
        for record in parse_mdns_message(packet):
            if record["type"] == 12:
                instance, _ = decode_name(packet, record["at"])
                ptrs.append((record["name"], instance))
            elif record["type"] == 33 and len(record["data"]) >= 6:
                target, _ = decode_name(packet, record["at"] + 6)
                _priority, _weight, port = struct.unpack_from("!HHH", record["data"], 0)
                srvs[record["name"].lower()] = {"target": target, "port": port}
            elif record["type"] == 1 and len(record["data"]) == 4:
                addresses.setdefault(record["name"].lower(), socket.inet_ntoa(record["data"]))
            elif record["type"] == 16:
                txts[record["name"].lower()] = parse_txt(record["data"])
    found = []
    for service, instance in ptrs:
        info = srvs.get(instance.lower(), {})
        host = info.get("target") or ""
        address = addresses.get(host.lower()) or addresses.get(instance.lower()) or ""
        props = txts.get(instance.lower(), {})
        label = _instance_label(instance, service)
        found.append({
            "name": label,
            "service": service,
            "host": host,
            "port": str(info.get("port") or ""),
            "address": address or host,
            "model": model_from_txt(props),
            "properties": props,
            "protocol": protocol_for_service(service),
        })
    return found


def parse_mdns_message(packet):
    if not packet or len(packet) < 12:
        return []
    counts = struct.unpack_from("!HHHH", packet, 4)
    offset = 12
    try:
        for _ in range(counts[0]):
            _name, offset = decode_name(packet, offset)
            offset += 4
        records = []
        for _ in range(counts[1] + counts[2] + counts[3]):
            if offset + 10 > len(packet):
                break
            name, offset = decode_name(packet, offset)
            rtype, _rclass, _ttl, length = struct.unpack_from("!HHIH", packet, offset)
            offset += 10
            if offset + length > len(packet):
                break
            records.append({
                "name": name,
                "type": rtype,
                "data": packet[offset:offset + length],
                "at": offset,
            })
            offset += length
        return records
    except (struct.error, IndexError):
        return []


def encode_name(name):
    labels = [part for part in str(name or "").strip(".").split(".") if part]
    body = b""
    for part in labels:
        raw = part.encode("utf-8")
        if len(raw) > 63:
            raise ValueError("DNS label is too long.")
        body += bytes([len(raw)]) + raw
    return body + b"\x00"


def decode_name(packet, offset):
    labels = []
    hopped = False
    end = offset
    seen = set()
    for _ in range(128):
        if offset >= len(packet) or offset in seen:
            break
        seen.add(offset)
        length = packet[offset]
        if length == 0:
            offset += 1
            if not hopped:
                end = offset
            break
        if length & 0xC0 == 0xC0:
            if offset + 1 >= len(packet):
                break
            if not hopped:
                end = offset + 2
            offset = ((length & 0x3F) << 8) | packet[offset + 1]
            hopped = True
            continue
        if length & 0xC0:
            break
        offset += 1
        labels.append(packet[offset:offset + length].decode("utf-8", "replace"))
        offset += length
        if not hopped:
            end = offset
    return ".".join(labels), end


def parse_txt(rdata):
    props = {}
    index = 0
    blob = bytes(rdata or b"")
    while index < len(blob):
        length = blob[index]
        index += 1
        chunk = blob[index:index + length].decode("utf-8", "replace")
        index += length
        if "=" in chunk:
            key, value = chunk.split("=", 1)
            props[key.lower()] = value
        elif chunk:
            props[chunk.lower()] = ""
    return props


def mdns_exchange(service_names, timeout):
    """Ask the LAN for the printer service types and collect unicast replies."""
    timeout = max(0.2, float(timeout or 1.0))
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.settimeout(timeout)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
        except OSError:
            pass
        sock.bind(("", 0))
        for name in service_names:
            # The high bit of the class asks responders to reply to our port.
            question = encode_name(name) + struct.pack("!HH", 12, 0x8001)
            packet = struct.pack("!HHHHHH", 0, 0, 1, 0, 0, 0) + question
            sock.sendto(packet, ("224.0.0.251", 5353))
        packets = []
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                data, _addr = sock.recvfrom(9000)
            except socket.timeout:
                break
            if data:
                packets.append(data)
        return packets
    except OSError:
        return []
    finally:
        sock.close()


_GET_PRINTER = (
    "$rows = @(Get-Printer | ForEach-Object { "
    "$port = Get-PrinterPort -Name $_.PortName -ErrorAction SilentlyContinue; "
    "[PSCustomObject]@{ Name=$_.Name; DriverName=$_.DriverName; PortName=$_.PortName; "
    "Host=$port.PrinterHostAddress; Comment=$_.Comment } }); "
    "$rows | ConvertTo-Json -Compress -Depth 4"
)


# The connector exe is a windowed app, so a console child such as PowerShell
# or taskkill would open its own black window. These values hide it.
CREATE_NO_WINDOW = 0x08000000
STARTF_USESHOWWINDOW = 0x00000001
SW_HIDE = 0


def hidden_window_kwargs(system=None):
    """subprocess keyword arguments that keep a child's console window hidden on Windows."""
    if (system or platform.system()) != "Windows":
        return {}
    kwargs = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", CREATE_NO_WINDOW)}
    startupinfo_type = getattr(subprocess, "STARTUPINFO", None)
    if startupinfo_type is not None:
        info = startupinfo_type()
        info.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", STARTF_USESHOWWINDOW)
        info.wShowWindow = SW_HIDE
        kwargs["startupinfo"] = info
    return kwargs


def _run(args):
    try:
        completed = subprocess.run(
            args,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            **hidden_window_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return completed.stdout or ""


def _http_status(url, timeout):
    context = ssl._create_unverified_context()
    opener = urllib.request.build_opener(_NoRedirect(), urllib.request.HTTPSHandler(context=context))
    request = urllib.request.Request(url, method="GET")
    try:
        with opener.open(request, timeout=timeout) as response:
            response.read(128)
            return getattr(response, "status", None) or response.getcode()
    except urllib.error.HTTPError as error:
        return error.code


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)


def _service_name(service):
    text = str(service or "").strip(".")
    if not text.endswith(".local"):
        text += ".local"
    return text


def _instance_label(instance, service):
    full = str(instance or "").strip(".")
    suffix = "." + str(service or "").strip(".")
    if suffix != "." and full.lower().endswith(suffix.lower()):
        return full[: -len(suffix)]
    return full.split("._")[0] or full


def _prefer_address(candidate, current):
    if not candidate:
        return False
    if not current:
        return True
    return _is_ip(candidate) and not _is_ip(str(current).strip("[]"))


def _is_ip(value):
    try:
        socket.inet_aton(str(value))
        return True
    except OSError:
        return False
