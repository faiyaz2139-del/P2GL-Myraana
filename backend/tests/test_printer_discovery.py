"""Printer discovery stays off the network: Bonjour, CUPS, and Get-Printer are mocked."""
import json
import socket
import struct
import urllib.error
from pathlib import Path

from p2g.printer_discovery import (
    SERVICE_TYPES,
    browse_mdns,
    decode_name,
    discover,
    encode_name,
    fiery_api_url,
    normalise_reported,
    os_queues,
    parse_get_printer,
    parse_lpstat,
    preferred_printer,
    probe_fiery,
    scan_is_due,
    services_from_packets,
)
from p2g.printers import filter_printers


def _message(questions, answers):
    body = b""
    for name in questions:
        body += encode_name(name) + struct.pack("!HH", 12, 1)
    for name, rtype, rdata in answers:
        body += encode_name(name) + struct.pack("!HHIH", rtype, 1, 120, len(rdata)) + rdata
    header = struct.pack("!HHHHHH", 0, 0x8400, len(questions), len(answers), 0, 0)
    return header + body


def _ptr(instance):
    return encode_name(instance)


def _srv(port, target):
    return struct.pack("!HHH", 0, 0, port) + encode_name(target)


def _txt(pairs):
    body = b""
    for key, value in pairs:
        chunk = f"{key}={value}".encode()
        body += bytes([len(chunk)]) + chunk
    return body


def test_bonjour_services_cover_ipp_ipps_lpd_and_raw():
    assert SERVICE_TYPES == (
        "_ipp._tcp",
        "_ipps._tcp",
        "_printer._tcp",
        "_pdl-datastream._tcp",
    )


def test_mdns_packets_identify_a_fiery_and_the_other_queue_protocols():
    packet = _message(
        [],
        [
            ("_ipp._tcp.local", 12, _ptr("Fiery EX._ipp._tcp.local")),
            ("Fiery EX._ipp._tcp.local", 33, _srv(631, "fiery.local")),
            ("fiery.local", 1, socket.inet_aton("10.0.0.8")),
            ("Fiery EX._ipp._tcp.local", 16, _txt([("ty", "EFI Fiery")])),
            ("_ipps._tcp.local", 12, _ptr("Office._ipps._tcp.local")),
            ("Office._ipps._tcp.local", 33, _srv(443, "office.local")),
            ("office.local", 1, socket.inet_aton("10.0.0.9")),
            ("_printer._tcp.local", 12, _ptr("Line._printer._tcp.local")),
            ("_pdl-datastream._tcp.local", 12, _ptr("Raw._pdl-datastream._tcp.local")),
            ("Raw._pdl-datastream._tcp.local", 1, socket.inet_aton("10.0.0.11")),
        ],
    )
    # A compressed pointer back to the first name still decodes.
    encoded = encode_name("_ipp._tcp.local")
    assert decode_name(encoded + b"\xc0\x00", len(encoded))[0] == "_ipp._tcp.local"
    found = {row["name"]: row for row in services_from_packets([packet])}
    assert found["Fiery EX"]["address"] == "10.0.0.8"
    assert found["Fiery EX"]["protocol"] == "ipp"
    assert found["Fiery EX"]["model"] == "EFI Fiery"
    assert found["Office"]["protocol"] == "ipps"
    assert found["Office"]["address"] == "10.0.0.9"
    assert found["Line"]["protocol"] == "lpd"
    assert found["Raw"]["protocol"] == "socket"
    assert found["Raw"]["address"] == "10.0.0.11"
    rows = discover(mdns_services=list(found.values()))
    fiery = next(row for row in rows if row["name"] == "Fiery EX")
    assert fiery["isFiery"] is True
    assert fiery["protocol"] == "ipp"
    assert next(row for row in rows if row["name"] == "Office")["isFiery"] is False


def test_browse_uses_the_injected_transport_and_all_four_service_types():
    seen = {}

    def transport(types, timeout):
        seen["types"] = list(types)
        seen["timeout"] = timeout
        return [_message([], [("_ipp._tcp.local", 12, _ptr("Press._ipp._tcp.local"))])]

    def browse():
        return browse_mdns(transport=transport, timeout=0.2)

    rows = discover(browse=browse, list_queues=lambda: [], probe=lambda address: False)
    assert seen["types"] == [
        "_ipp._tcp.local",
        "_ipps._tcp.local",
        "_printer._tcp.local",
        "_pdl-datastream._tcp.local",
    ]
    assert rows[0]["name"] == "Press"
    assert rows[0]["protocol"] == "ipp"


def test_lpstat_reads_the_queue_model_and_address():
    details = "\n".join([
        "printer Fiery_EX is idle.  enabled since today",
        "\tDescription: EFI Fiery EX",
        "printer Office is idle.  enabled since today",
        "\tDescription: HP LaserJet",
    ])
    devices = "\n".join([
        "device for Fiery_EX: ipps://10.1.2.3/ipp/print",
        "device for Office: socket://10.1.2.9:9100",
    ])
    found = {row["name"]: row for row in parse_lpstat(details, devices)}
    assert found["Fiery_EX"]["model"] == "EFI Fiery EX"
    assert found["Fiery_EX"]["address"] == "10.1.2.3"
    assert found["Fiery_EX"]["protocol"] == "ipps"
    assert found["Office"]["address"] == "10.1.2.9"
    assert found["Office"]["protocol"] == "socket"
    calls = []

    def run(args):
        calls.append(list(args))
        if args[:2] == ["lpstat", "-l"]:
            return details
        if args[:2] == ["lpstat", "-v"]:
            return devices
        raise AssertionError(args)

    rows = {row["name"]: row for row in os_queues(run=run, system="Darwin")}
    assert calls[0][0] == "lpstat"
    assert "powershell" not in str(calls)
    merged = discover(os_queues=list(rows.values()))
    fiery = next(row for row in merged if row["name"] == "Fiery_EX")
    assert fiery["isFiery"] is True
    assert fiery["address"] == "10.1.2.3"


def test_windows_get_printer_marks_a_fiery_driver_and_keeps_the_host():
    payload = json.dumps([
        {"Name": "BackOffice", "DriverName": "HP Universal", "PortName": "USB001", "Host": ""},
        {
            "Name": "Fiery Queue",
            "DriverName": "EFI Fiery Printer Driver",
            "PortName": "IP_10.0.0.5",
            "Host": "10.0.0.5",
        },
    ])

    def run(args):
        assert args[0] == "powershell"
        assert "Get-Printer" in args[-1]
        return payload

    rows = {row["name"]: row for row in os_queues(run=run, system="Windows")}
    assert rows["BackOffice"]["protocol"] == "usb"
    assert rows["Fiery Queue"]["address"] == "10.0.0.5"
    discovered = discover(os_queues=list(rows.values()), probe=lambda address: False)
    fiery = next(row for row in discovered if row["name"] == "Fiery Queue")
    assert fiery["isFiery"] is True
    assert fiery["model"] == "EFI Fiery Printer Driver"
    assert parse_get_printer("") == []
    assert parse_get_printer("{") == []


def test_fiery_api_probe_uses_port_443_and_ignores_a_missing_path():
    seen = []

    def opener(url, timeout):
        seen.append((url, timeout))
        if url.endswith("10.9.9.9:443/live/api/v5"):
            return 401
        raise TimeoutError("down")

    assert fiery_api_url("10.9.9.9") == "https://10.9.9.9:443/live/api/v5"
    assert probe_fiery("10.9.9.9", timeout=0.4, opener=opener) is True
    assert seen[0][0] == "https://10.9.9.9:443/live/api/v5"
    assert probe_fiery("10.9.9.10", timeout=0.4, opener=lambda url, timeout: 404) is False
    assert probe_fiery("10.9.9.11", timeout=0.4, opener=opener) is False
    error = urllib.error.HTTPError("https://10.9.9.12:443/live/api/v5", 401, "unauthorized", hdrs=None, fp=None)

    def raise_http(url, timeout):
        raise error

    assert probe_fiery("10.9.9.12", opener=raise_http) is True
    rows = discover(
        os_queues=[{"name": "Press", "model": "Ricoh", "address": "10.9.9.9", "protocol": "ipp", "driver": "Ricoh"}],
        probe=lambda address: probe_fiery(address, opener=opener),
    )
    assert rows[0]["name"] == "Press"
    assert rows[0]["isFiery"] is True
    assert rows[0]["protocol"] == "ipp"


def test_reported_printers_drop_virtual_queues_and_merge_the_same_press():
    raw = [
        {"name": "Microsoft Print to PDF", "driver": "Microsoft Print To PDF", "port": "PORTPROMPT:"},
        {"name": "Fiery EX", "model": "EFI Fiery", "address": "10.0.0.8", "protocol": "ipps", "isFiery": True},
        {"name": "Fiery_EX", "driver": "EFI Fiery", "port": "ipps://fiery.local/ipp/print"},
    ]
    rows = normalise_reported(filter_printers(raw))
    assert [row["name"] for row in rows] == ["Fiery EX"]
    assert rows[0]["isFiery"] is True
    assert rows[0]["protocol"] == "ipps"
    assert rows[0]["address"] == "10.0.0.8"
    assert preferred_printer(rows) == "Fiery EX"
    assert preferred_printer(rows + [{"name": "Other", "isFiery": True}]) is None
    assert preferred_printer([]) is None


def test_scan_now_stays_due_until_the_connector_reports_it():
    assert scan_is_due({}) is False
    assert scan_is_due({"scanRequestedAt": "2026-01-02T00:00:00+00:00"}) is True
    done = {
        "scanRequestedAt": "2026-01-02T00:00:00+00:00",
        "scanFulfilledAt": "2026-01-02T00:00:01+00:00",
    }
    assert scan_is_due(done) is False
    again = {
        "scanRequestedAt": "2026-01-03T00:00:00+00:00",
        "scanFulfilledAt": "2026-01-02T00:00:00+00:00",
    }
    assert scan_is_due(again) is True
    assert scan_is_due(again, incoming_scanned=True) is False


def test_connector_ships_the_same_discovery_module():
    root = Path(__file__).resolve().parents[2]
    original = (root / "backend" / "p2g" / "printer_discovery.py").read_text(encoding="utf-8")
    shipped = (root / "frontend" / "public" / "setup" / "printer_discovery.py").read_text(encoding="utf-8")
    assert original == shipped
