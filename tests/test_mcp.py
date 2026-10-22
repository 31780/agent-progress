"""MCP/report contract tests; no account, tunnel, desktop or production state."""
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import progress as p
import reporting_mcp as m


class McpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(os.environ, {"OMARCHY_PROGRESS_STATE": self.tmp.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.server = m.Server()
        self.initialize()

    def rpc(self, method, params=None, server=None):
        return (server or self.server).handle({"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})

    def initialize(self):
        result = self.rpc("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                                         "clientInfo": {"name": "fixture", "version": "1"}})
        self.server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return result

    def begin_args(self, **changes):
        return {"request_id": str(uuid.uuid4()), "source": "dot", "session": "fixture", "title": "Test only", **changes}

    def call(self, name, arguments):
        return self.rpc("tools/call", {"name": name, "arguments": arguments})

    def update_args(self, result, **changes):
        return {"request_id": str(uuid.uuid4()), "id": result["id"], "run": result["run"],
                "sequence": 1, "status": "working", **changes}

    def test_discovery_and_handshake_have_no_writes(self):
        tools = self.rpc("tools/list")["result"]["tools"]
        self.assertEqual([t["name"] for t in tools], ["begin_report", "update_report"])
        self.assertTrue(all(not t["annotations"]["readOnlyHint"] for t in tools))
        self.assertEqual(self.rpc("ping")["result"], {})
        self.assertFalse(Path(self.tmp.name, "tasks.sqlite3").exists())
        fresh = m.Server()
        self.assertIn("error", self.rpc("tools/list", server=fresh))
        result = self.rpc("initialize", {"protocolVersion": "future", "capabilities": {},
                                        "clientInfo": {"name": "fixture", "version": "1"}}, server=fresh)
        self.assertEqual(result["result"]["protocolVersion"], m.PROTOCOLS[0])

    def test_real_states_milestones_history_and_staleness(self):
        with patch.object(p.time, "time", return_value=1000):
            result = self.call("begin_report", self.begin_args())["result"]["structuredContent"]
        with patch.object(p.time, "time", return_value=1001):
            self.call("update_report", self.update_args(result, status="waiting_input", milestone={"done": 1, "total": 3}))
        snapshot = p.snapshot(1002)
        self.assertEqual((snapshot["waiting"], snapshot["inputWaiting"]), (0, 1))
        self.assertEqual(snapshot["current"][0]["source"], "dot")
        self.assertEqual(snapshot["current"][0]["milestone"]["done"], 1)
        self.assertEqual(p.snapshot(1182)["current"][0]["status"], "connection_unknown")
        with patch.object(p.time, "time", return_value=1183):
            self.call("update_report", self.update_args(result, sequence=2, status="ready_for_review"))
        self.assertEqual(p.snapshot(1184)["history"][0]["status"], "ready_for_review")

    def test_retry_receipts_survive_restart_without_refresh_or_revive(self):
        args = self.begin_args()
        with patch.object(p.time, "time", return_value=1000):
            first = self.call("begin_report", args)["result"]["structuredContent"]
        update = self.update_args(first, status="ready_for_review")
        with patch.object(p.time, "time", return_value=1001):
            self.call("update_report", update)
        self.server = m.Server()
        self.initialize()
        with patch.object(p.time, "time", return_value=1200):
            replay = self.call("begin_report", args)["result"]["structuredContent"]
            self.assertEqual(replay, first)
            self.assertFalse(self.call("update_report", update)["result"]["isError"])
        self.assertEqual(p.snapshot(1200)["current"], [])
        self.assertEqual(p.snapshot(1200)["history"][0]["updated"], 1001)

    def test_conflicting_request_id_and_superseded_run_rejected(self):
        args = self.begin_args()
        first = self.call("begin_report", args)["result"]["structuredContent"]
        self.assertTrue(self.call("begin_report", {**args, "title": "Different"})["result"]["isError"])
        second = self.call("begin_report", self.begin_args())["result"]["structuredContent"]
        self.assertNotEqual(first["run"], second["run"])
        self.assertTrue(self.call("update_report", self.update_args(first))["result"]["isError"])

    def test_concurrent_duplicate_begin_creates_one_run(self):
        args = self.begin_args()
        report = {k: v for k, v in args.items() if k != "request_id"}
        report["action"] = "begin"
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda _: p.observe(report, request_id=args["request_id"]), range(8)))
        self.assertEqual(len({r["run"] for r in results}), 1)
        self.assertEqual(len(p.snapshot()["tasks"]), 1)

    def test_write_notifications_and_unknown_methods_cannot_access_state(self):
        self.server.handle({"jsonrpc": "2.0", "method": "tools/call",
                            "params": {"name": "begin_report", "arguments": self.begin_args()}})
        for method in ("resources/read", "tasks/list", "exec", "snapshot"):
            self.assertEqual(self.rpc(method)["error"]["code"], -32601)
        self.assertFalse(Path(self.tmp.name, "tasks.sqlite3").exists())

    def test_invalid_data_cannot_impersonate_or_leak(self):
        first = self.call("begin_report", self.begin_args())["result"]["structuredContent"]
        for changes in ({"source": "codex"}, {"source": ["dot"]}, {"title": ""}, {"request_id": None},
                        {"request_id": "not-a-uuid"}, {"prompt": "PRIVATE_BODY"}):
            response = self.call("begin_report", self.begin_args(**changes))
            self.assertTrue("error" in response or response["result"]["isError"])
            self.assertNotIn("PRIVATE_BODY", json.dumps(response))
        for changes in ({"status": "waiting_approval"}, {"status": {}}, {"sequence": True},
                        {"milestone": {"done": 4, "total": 3}}, {"id": "codex-id"}, {"run": "wrong"}):
            self.assertTrue(self.call("update_report", self.update_args(first, **changes))["result"]["isError"])
        self.assertEqual(len(p.snapshot()["tasks"]), 1)

    def test_bounded_framing_invalid_json_and_eof(self):
        for payload in (b'{"a":1,"a":2}\n', b'{"n":NaN}\n', b'\xff\n', b'[' * 2000 + b'\n'):
            output = io.BytesIO()
            self.assertEqual(m.serve(io.BytesIO(payload), output), 0)
            self.assertEqual(json.loads(output.getvalue())["error"]["code"], -32700)
        output = io.BytesIO()
        self.assertEqual(m.serve(io.BytesIO(b"x" * (m.MAX_MESSAGE + 1)), output), 1)
        self.assertEqual(json.loads(output.getvalue())["error"]["code"], -32600)

    def test_stdio_subprocess_roundtrip(self):
        begin = self.begin_args(title="Unicode café")
        frames = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "fixture", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "begin_report", "arguments": begin}}]
        process = subprocess.run([sys.executable, str(ROOT / "src/reporting_mcp.py"), "--state-dir", self.tmp.name],
                                 input="".join(json.dumps(f) + "\n" for f in frames).encode(), capture_output=True, timeout=5)
        self.assertEqual(process.returncode, 0, process.stderr)
        replies = [json.loads(line) for line in process.stdout.splitlines()]
        self.assertEqual([r["id"] for r in replies], [1, 2])
        self.assertFalse(replies[1]["result"]["isError"])
        self.assertEqual(p.snapshot()["current"][0]["title"], "Unicode café")


if __name__ == "__main__":
    unittest.main()
