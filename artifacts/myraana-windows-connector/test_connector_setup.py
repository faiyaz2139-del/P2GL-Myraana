import importlib.util
import pathlib
import threading
import unittest
from unittest.mock import patch

SOURCE = pathlib.Path(__file__).resolve().parents[2] / "frontend/public/setup/myraana-connector.py"
if not SOURCE.exists():
    SOURCE = pathlib.Path(__file__).with_name("myraana-connector.py")
spec = importlib.util.spec_from_file_location("connector", SOURCE)
connector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(connector)

class ConnectorSetupTests(unittest.TestCase):
    def test_rejects_invalid_websites(self):
        for url in ("http://example.com", "https://", "https://u:p@example.com",
                    "https://example.com/path", "https://example.com?q=1"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                connector.website_url(url)

    def test_pairing_then_heartbeat_and_no_secret_in_state(self):
        state = {}
        credentials = {}
        stop = threading.Event()
        calls = []
        saved = []
        def secret(name, value=None):
            if value is not None:
                credentials[name] = value
            return credentials.get(name)
        def request(url, path, payload, credential=None):
            calls.append((url, path, payload, credential))
            if path.endswith("/claim"):
                return {"id": "pair-1"}
            if path.endswith("/poll"):
                return {"credential": "test-token"}
            stop.set()
            return {}
        with patch.object(connector, "load_state", return_value=state), \
             patch.object(connector, "save_state", side_effect=lambda s: saved.append(dict(s))), \
             patch.object(connector, "secret", side_effect=secret), \
             patch.object(connector, "request", side_effect=request), \
             patch.object(connector, "inventory", return_value={"printers": []}), \
             patch.object(stop, "wait", return_value=False):
            connector.run("https://preview.example.com", "ABCDEF", lambda m: None, stop)
        self.assertEqual([c[1] for c in calls], [
            "/connector-pairings/claim", "/connector-pairings/pair-1/poll",
            "/connector-devices/heartbeat"])
        self.assertEqual(calls[1][2]["claimSecret"], credentials["claimSecret"])
        self.assertEqual(calls[2][3], "test-token")
        for entry in saved:
            self.assertNotIn("credential", entry)
            self.assertNotIn("claimSecret", entry)
        self.assertEqual(state["websiteUrl"], "https://preview.example.com")

    def test_reconnect_without_pairing_code(self):
        stop = threading.Event()
        with patch.object(connector, "load_state", return_value={"websiteUrl": "https://preview.example.com"}), \
             patch.object(connector, "save_state"), \
             patch.object(connector, "secret", side_effect=lambda name, value=None: "token" if name == "credential" else "claim"), \
             patch.object(connector, "inventory", return_value={}), \
             patch.object(connector, "request", side_effect=lambda *a, **kw: stop.set()) as request:
            connector.run("https://preview.example.com", report=lambda m: None, stop=stop)
        self.assertEqual(request.call_args.args[1], "/connector-devices/heartbeat")

    def test_host_change_never_reads_or_transmits_credentials(self):
        with patch.object(connector, "load_state", return_value={"websiteUrl": "https://old.example.com"}), \
             patch.object(connector, "secret") as secret, \
             patch.object(connector, "request") as request:
            with self.assertRaises(ValueError):
                connector.run("https://new.example.com")
        secret.assert_not_called()
        request.assert_not_called()

    def test_scan_request_discovers_again_and_marks_it_done(self):
        stop = threading.Event()
        calls = []
        scans = {"n": 0}

        def inventory():
            scans["n"] += 1
            return {"hostname": "press", "printers": [
                {"name": "Fiery EX", "model": "EFI Fiery", "address": "10.0.0.8",
                 "protocol": "ipps", "isFiery": True},
            ], "fiery_rip": [], "hot_folders": []}

        def request(url, path, payload, credential=None):
            calls.append(payload)
            if len(calls) == 1:
                return {"ok": True, "status": "Connected", "scan": True}
            stop.set()
            return {"ok": True, "scan": False}

        with patch.object(connector, "load_state", return_value={"websiteUrl": "https://preview.example.com"}), \
             patch.object(connector, "save_state"), \
             patch.object(connector, "secret", side_effect=lambda name, value=None: "token" if name == "credential" else "claim"), \
             patch.object(connector, "inventory", side_effect=inventory), \
             patch.object(connector, "request", side_effect=request), \
             patch.object(stop, "wait", return_value=False):
            connector.run("https://preview.example.com", report=lambda message: None, stop=stop)
        self.assertEqual(scans["n"], 2)
        self.assertNotIn("scanned", calls[0])
        self.assertIs(calls[1]["scanned"], True)
        self.assertEqual(calls[1]["inventory"]["printers"][0]["name"], "Fiery EX")
        self.assertEqual(calls[1]["inventory"]["printers"][0]["protocol"], "ipps")
        self.assertIs(calls[1]["inventory"]["printers"][0]["isFiery"], True)

    def test_discovery_module_merges_mocked_bonjour_and_queues(self):
        discovery = connector.load_discovery()
        rows = discovery.discover(
            browse=lambda: [{
                "name": "Fiery EX", "model": "EFI Fiery", "address": "10.4.4.5",
                "protocol": "ipps", "service": "_ipps._tcp",
            }],
            list_queues=lambda: [{
                "name": "Press", "model": "Ricoh", "address": "10.4.4.4", "protocol": "socket",
            }],
            probe=lambda address: address == "10.4.4.4",
        )
        found = {row["name"]: row for row in rows}
        for row in found.values():
            self.assertEqual(set(row) >= {"name", "model", "address", "protocol", "isFiery"}, True)
        self.assertIs(found["Fiery EX"]["isFiery"], True)
        self.assertEqual(found["Fiery EX"]["protocol"], "ipps")
        self.assertIs(found["Press"]["isFiery"], True)
        self.assertEqual(found["Press"]["address"], "10.4.4.4")
        self.assertEqual(discovery.SERVICE_TYPES, (
            "_ipp._tcp", "_ipps._tcp", "_printer._tcp", "_pdl-datastream._tcp",
        ))

    def test_unbound_legacy_token_is_not_transmitted(self):
        with patch.object(connector, "load_state", return_value={}), \
             patch.object(connector, "secret", return_value="old-token"), \
             patch.object(connector, "request") as request:
            with self.assertRaisesRegex(ValueError, "migration"):
                connector.run("https://preview.example.com")
        request.assert_not_called()

if __name__ == "__main__":
    unittest.main()
