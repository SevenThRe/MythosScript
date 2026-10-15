"""Observation connection policy and real stdio startup, without Minecraft."""
import importlib.util
import io
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/mythosscript-mcp/scripts/client.py"
spec = importlib.util.spec_from_file_location("observer_client", SCRIPT)
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)


class Backend:
    def __init__(self, result=None):
        self.requests = []
        self.result = result if result is not None else {"ok": True}

    def send(self, message):
        self.requests.append(message)
        return {"jsonrpc": "2.0", "id": message["id"], "result": self.result}


def call(name, arguments=None):
    return {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}}}


class ObserverTest(unittest.TestCase):
    def test_hidden_gameplay_and_packet_replay_never_reach_backend(self):
        backend = Backend()
        observer = client.ObservationClient(backend)
        for name in ("mythos_run", "mythos_client", "mythos_inventory", "mythos_navigation",
                     "mythos_config", "mythos_kill_aura", "unknown"):
            result = observer.send(call(name, {"actions": [{"type": "send_packet"}]}))
            self.assertEqual(-32601, result["error"]["code"])
        self.assertEqual([], backend.requests)

    def test_operation_checks_block_clear_and_gui_input(self):
        backend = Backend()
        observer = client.ObservationClient(backend)
        for name, operation in (("mythos_packets", "clear"), ("mythos_packets", "send"),
                                ("mythos_gui", "click"), ("mythos_gui", "key"),
                                ("mythos_events", "unknown")):
            self.assertIn("error", observer.send(call(name, {"operation": operation})))
        self.assertEqual([], backend.requests)

    def test_capture_and_event_controls_forward_original_arguments(self):
        backend = Backend()
        observer = client.ObservationClient(backend)
        for name, args in (("mythos_packets", {"operation": "capture_start"}),
                           ("mythos_packets", {"operation": "list", "direction": "S2C", "offset": 5}),
                           ("mythos_packets", {"operation": "capture_stop"}),
                           ("mythos_events", {"operation": "read", "afterId": 17, "waitMs": 25000}),
                           ("mythos_events", {}), ("mythos_gui", {"operation": "inspect"}),
                           ("mythos_snapshot", {"groups": ["player", "inventory"]})):
            request = call(name, args)
            self.assertNotIn("error", observer.send(request))
            self.assertEqual(request, backend.requests[-1])

    def test_filters_offline_and_live_catalog_without_mutating_original(self):
        catalog = {"tools": client.OFFLINE_TOOLS + [{"name": "mythos_client"}]}
        original = json.dumps(catalog)
        result = client.ObservationClient(Backend(catalog)).send(
            {"id": 1, "method": "tools/list"})["result"]
        self.assertEqual(client.ObservationClient.TOOLS, {t["name"] for t in result["tools"]})
        packets = next(t for t in result["tools"] if t["name"] == "mythos_packets")
        self.assertNotIn("clear", packets["inputSchema"]["properties"]["operation"]["enum"])
        self.assertFalse(packets["annotations"]["readOnlyHint"])
        gui = next(t for t in result["tools"] if t["name"] == "mythos_gui")
        self.assertEqual(["inspect"], gui["inputSchema"]["properties"]["operation"]["enum"])
        self.assertEqual(original, json.dumps(catalog))

    def test_notification_is_silent_and_invalid_arguments_do_not_forward(self):
        backend = Backend()
        observer = client.ObservationClient(backend)
        request = call("mythos_run")
        del request["id"]
        self.assertIsNone(observer.send(request))
        request = call("mythos_packets")
        request["params"]["arguments"] = []
        self.assertEqual(-32602, observer.send(request)["error"]["code"])
        self.assertEqual([], backend.requests)

    def test_real_stdio_offline_startup_and_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            requests = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                dict(call("mythos_run"), id=3),
                dict(call("mythos_status"), id=4),
            ]
            run = subprocess.run([sys.executable, str(SCRIPT), "--auto-discover", "--observe-only",
                                  "--discovery-file", str(pathlib.Path(tmp) / "missing.json"), "stdio"],
                                 input="\n".join(json.dumps(x) for x in requests) + "\n",
                                 text=True, encoding="utf-8", capture_output=True, timeout=15)
            self.assertEqual(0, run.returncode, run.stderr)
            responses = [json.loads(line) for line in run.stdout.splitlines()]
            self.assertEqual([1, 2, 3, 4], [row["id"] for row in responses])
            self.assertIn("Observation-only", responses[0]["result"]["instructions"])
            self.assertEqual(10, len(responses[1]["result"]["tools"]))
            self.assertEqual(-32601, responses[2]["error"]["code"])
            self.assertTrue(responses[3]["result"]["isError"])
            self.assertIn("GAME_NOT_RUNNING", json.dumps(responses[3]))


if __name__ == "__main__":
    unittest.main()
