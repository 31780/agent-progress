import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("progress", ROOT / "src/progress.py")
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"OMARCHY_PROGRESS_STATE": self.tmp.name})
        self.env.start()
        self.now = time.time()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def begin(self, source="dot", session="same-id", at=0):
        return p.observe({"action": "begin", "source": source, "session": session, "title": "Example task"}, self.now + at)

    def update(self, report, sequence=1, status="working", at=1, **fields):
        return p.observe({"action": "update", "id": report["id"], "run": report["run"],
                          "sequence": sequence, "status": status, **fields}, self.now + at)

    def test_sources_and_codex_ids_do_not_collide(self):
        self.begin()
        self.begin("chatgpt")
        p.ingest({"hook_event_name": "UserPromptSubmit", "session_id": "same-id", "turn_id": "turn"},
                 self.now, p.process_identity(os.getpid()))
        tasks = p.snapshot(self.now)["tasks"]
        self.assertEqual(len({t["id"] for t in tasks}), 3)
        self.assertEqual({t["source"] for t in tasks}, {"codex", "dot", "chatgpt"})
        self.assertEqual({t["observation"] for t in tasks}, {"hook", "agent_report"})
        self.assertEqual(sum(t["status"] == "working" for t in tasks if t["source"] != "codex"), 2)

    def test_reports_expire_without_claiming_cloud_process_death(self):
        report = self.begin()
        with patch.object(p, "process_identity", side_effect=AssertionError("No local cloud process")):
            self.assertEqual(p.snapshot(self.now + 2)["tasks"][0]["status"], "working")
            task = p.snapshot(self.now + 181)["tasks"][0]
        self.assertEqual(task["status"], "connection_unknown")
        self.assertIn("No agent report", task["activity"])
        p.dismiss(report["id"], self.now, self.now + 181)
        self.assertEqual(len(p.snapshot(self.now + 182)["history"]), 1)
        self.update(report, at=183)
        self.assertEqual(len(p.snapshot(self.now + 184)["current"]), 1)

    def test_reported_input_is_not_a_native_approval(self):
        self.update(self.begin(), status="waiting_input")
        snapshot = p.snapshot(self.now + 2)
        self.assertEqual((snapshot["waiting"], snapshot["inputWaiting"]), (0, 1))
        self.assertEqual(snapshot["tasks"][0]["label"], "Waiting for input")
        self.assertEqual(p.snapshot(self.now + 182)["unknown"], 1)

    def test_ready_for_review_is_distinct_and_sticky_until_new_run(self):
        report = self.begin()
        self.update(report, status="ready_for_review")
        snapshot = p.snapshot(self.now + 10)
        self.assertEqual(snapshot["current"], [])
        self.assertEqual(snapshot["history"][0]["status"], "ready_for_review")
        with self.assertRaises(ValueError):
            self.update(report, sequence=2)
        new = self.begin(at=11)
        self.assertNotEqual(report["run"], new["run"])
        self.assertEqual(len(p.snapshot(self.now + 12)["current"]), 1)
        with self.assertRaises(ValueError):
            self.update(report, sequence=3, at=13)

    def test_out_of_order_report_cannot_refresh_liveness_or_revive_dismissed_entry(self):
        report = self.begin()
        self.update(report, sequence=3)
        for seq in (1, 2, 3):
            with self.assertRaises(ValueError):
                self.update(report, sequence=seq, at=200)
        p.dismiss(report["id"], self.now + 1, self.now + 200)
        self.assertEqual(p.snapshot(self.now + 201)["history"][0]["updated"], self.now + 1)

    def test_only_explicit_valid_milestones_and_no_payload_logs(self):
        report = self.begin()
        self.update(report, milestone={"done": 2, "total": 4})
        task = p.snapshot(self.now + 2)["tasks"][0]
        self.assertEqual(task["milestone"]["done"], 2)
        self.assertFalse(task["elapsedExact"])
        self.update(report, sequence=2, milestone=None)
        self.assertIsNone(p.snapshot(self.now + 2)["tasks"][0]["milestone"])
        for milestone in ({"done": True, "total": 4}, {"done": 3, "total": 2}, {"done": 1.5, "total": 3},
                          {"done": 0, "total": 0}, {"done": 1, "total": 1001}):
            with self.assertRaises(ValueError):
                self.update(report, sequence=3, milestone=milestone)
        with self.assertRaises(ValueError):
            self.update(report, sequence=3, prompt="SECRET")
        with p.database() as conn:
            self.assertNotIn("SECRET", conn.execute("SELECT record FROM tasks").fetchone()[0])

    def test_reports_cannot_impersonate_hooks_or_update_codex(self):
        with self.assertRaises(ValueError):
            self.begin("codex")
        report = self.begin()
        for status in ("waiting_approval", "response_finished", "interrupted"):
            with self.assertRaises(ValueError):
                self.update(report, status=status)
        with self.assertRaises(ValueError):
            p.ingest({"hook_event_name": "Stop", "session_id": report["id"]}, self.now)
        with self.assertRaises(ValueError):
            self.update({"id": "real-codex-id", "run": report["run"]})

    def test_metadata_lookup_excludes_reported_chats(self):
        self.begin()
        with patch.object(p, "Rpc", side_effect=AssertionError("No Codex lookup for cloud report")):
            p.titles()

    def test_report_cli_roundtrip_uses_installed_computer_and_persists(self):
        data = Path(self.tmp.name) / "share" / "omarchy-agent-progress"
        data.mkdir(parents=True)
        shutil.copy2(ROOT / "src/progress.py", data / "progress.py")
        reporter = ROOT / "skills/agent-progress/scripts/report.py"
        env = {**os.environ, "XDG_DATA_HOME": str(data.parent)}
        payload = {"action": "begin", "source": "chatgpt", "session": "fixture", "title": "Fixture"}
        def send(message):
            return subprocess.run([sys.executable, str(reporter)], input=json.dumps(message), text=True,
                                  capture_output=True, env=env, timeout=5)
        self.assertNotEqual(send(payload).returncode, 0)
        (data / "install.json").write_text("{}")
        result = send(payload)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        result = send({"action": "update", "id": report["id"], "run": report["run"], "sequence": 1,
                       "status": "ready_for_review"})
        self.assertEqual(result.returncode, 0, result.stderr)
        output = subprocess.check_output([sys.executable, str(data / "progress.py"), "snapshot"], env=env)
        self.assertEqual(json.loads(output)["history"][0]["status"], "ready_for_review")


if __name__ == "__main__":
    unittest.main()
