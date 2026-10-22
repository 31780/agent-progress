import concurrent.futures
import importlib.util
import json
import os
from pathlib import Path
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


class ProgressTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"OMARCHY_PROGRESS_STATE": self.tmp.name})
        self.env.start()
        self.now = time.time()
        self.owner = p.process_identity(os.getpid())

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def event(self, name, sid="chat-a", turn="t1", at=0, **kwargs):
        event = {"hook_event_name": name, "session_id": sid, "turn_id": turn, "cwd": "/project", **kwargs}
        return p.ingest(event, self.now + at, self.owner)

    def test_simultaneous_chats_remain_independent(self):
        self.event("UserPromptSubmit")
        self.event("UserPromptSubmit", sid="chat-b")
        self.event("Stop", sid="chat-b", at=10)
        states = {x["id"]: x["status"] for x in p.snapshot(self.now + 11)["tasks"]}
        self.assertEqual(states, {"chat-a": "working", "chat-b": "response_finished"})

    def test_approval_not_cleared_by_unrelated_parallel_output(self):
        self.event("UserPromptSubmit")
        self.event("PermissionRequest", tool_name="Bash", tool_input={"command": "A", "description": "why"})
        self.event("PostToolUse", tool_name="Bash", tool_input={"command": "B"}, at=1)
        self.assertEqual(p.snapshot(self.now + 1)["tasks"][0]["status"], "waiting_approval")
        self.event("PostToolUse", tool_name="Bash", tool_input={"command": "A"}, at=2)
        self.assertEqual(p.snapshot(self.now + 2)["tasks"][0]["status"], "working")

    def test_multiple_pending_approvals(self):
        for command in ("A", "B"):
            self.event("PermissionRequest", tool_name="Bash", tool_input={"command": command})
        self.event("PostToolUse", tool_name="Bash", tool_input={"command": "A"})
        self.assertEqual(p.snapshot(self.now)["waiting"], 1)
        self.event("Interrupt", at=1)
        self.assertEqual(p.snapshot(self.now + 1)["waiting"], 0)

    def test_identical_concurrent_approvals_require_both_results(self):
        for _ in range(2):
            self.event("PermissionRequest", tool_name="Bash", tool_input={"command": "A"})
        self.event("PostToolUse", tool_name="Bash", tool_input={"command": "A"})
        self.assertEqual(p.snapshot(self.now)["waiting"], 1)
        self.event("PostToolUse", tool_name="Bash", tool_input={"command": "A"})
        self.assertEqual(p.snapshot(self.now)["waiting"], 0)

    def test_interrupt_sticky_to_late_tool_output(self):
        self.event("UserPromptSubmit")
        self.event("Interrupt", at=5)
        self.event("PostToolUse", tool_name="Bash", at=7)
        task = p.snapshot(self.now + 10)["tasks"][0]
        self.assertEqual((task["status"], task["elapsed"]), ("interrupted", 5))

    def test_old_turn_cannot_replace_new_turn(self):
        self.event("UserPromptSubmit")
        self.event("UserPromptSubmit", turn="t2", at=10)
        self.event("Stop", turn="t1", at=11)
        self.assertEqual(p.snapshot(self.now + 12)["tasks"][0]["status"], "working")

    def test_steering_does_not_reset_timer(self):
        self.event("UserPromptSubmit")
        self.event("UserPromptSubmit", at=10)
        self.assertEqual(p.snapshot(self.now + 12)["tasks"][0]["elapsed"], 12)

    def test_joining_mid_turn_marks_partial_elapsed(self):
        self.event("PreToolUse", tool_name="Bash")
        self.assertFalse(p.snapshot(self.now + 1)["tasks"][0]["elapsedExact"])
        self.event("UserPromptSubmit", turn="t2", at=2)
        self.assertTrue(p.snapshot(self.now + 3)["tasks"][0]["elapsedExact"])

    def test_crash_and_pid_reuse_unknown(self):
        self.event("UserPromptSubmit")
        with patch.object(p, "process_identity", return_value=None):
            self.assertEqual(p.snapshot(self.now + 1)["tasks"][0]["status"], "connection_unknown")
        with patch.object(p, "process_identity", return_value={**self.owner, "start": "wrong"}):
            self.assertEqual(p.snapshot(self.now + 1)["tasks"][0]["status"], "connection_unknown")

    def test_quiet_session_unknown_not_finished(self):
        self.event("UserPromptSubmit")
        task = p.snapshot(self.now + p.STALE_SECONDS + 1)["tasks"][0]
        self.assertEqual(task["status"], "connection_unknown")
        self.event("PreToolUse", at=200, tool_name="Bash")
        self.assertEqual(p.snapshot(self.now + 201)["active"], 1)

    def test_restart_reads_persisted_records(self):
        self.event("UserPromptSubmit")
        output = subprocess.check_output([sys.executable, str(ROOT / "src/progress.py"), "snapshot"])
        self.assertEqual(json.loads(output)["tasks"][0]["status"], "working")

    def test_end_without_stop_is_unknown(self):
        self.event("UserPromptSubmit")
        self.event("SessionEnd", turn="", at=3)
        self.assertEqual(p.snapshot(self.now + 4)["tasks"][0]["status"], "connection_unknown")

    def test_stop_means_only_response_finished(self):
        self.event("UserPromptSubmit")
        self.event("Stop", at=5, last_assistant_message="All tasks are complete!")
        self.event("SessionEnd", turn="", at=6)
        task = p.snapshot(self.now + 30)["tasks"][0]
        self.assertEqual(task["status"], "response_finished")
        self.assertEqual(task["elapsed"], 5)
        self.assertIsNone(task["milestone"])

    def test_plan_units_are_explicit_and_reset_per_turn(self):
        self.event("PostToolUse", tool_name="update_plan", tool_input={"plan": [
            {"step": "A", "status": "completed"}, {"step": "B", "status": "in_progress"}]})
        task = p.snapshot(self.now)["tasks"][0]
        self.assertEqual(task["milestone"]["done"], 1)
        self.assertEqual(task["milestone"]["total"], 2)
        self.event("UserPromptSubmit", turn="t2", at=1)
        self.assertIsNone(p.snapshot(self.now + 1)["tasks"][0]["milestone"])

    def test_sensitive_content_not_retained(self):
        self.event("UserPromptSubmit", prompt="SECRET PROMPT")
        self.event("PreToolUse", tool_name="Bash", tool_input={"command": "SECRET COMMAND"}, transcript_path="SECRET PATH")
        self.event("Stop", last_assistant_message="SECRET RESPONSE")
        with p.database() as conn:
            record = conn.execute("SELECT record FROM tasks").fetchone()[0]
        self.assertNotIn("SECRET", record)
        self.assertEqual((Path(self.tmp.name) / "tasks.sqlite3").stat().st_mode & 0o777, 0o600)

    def test_process_concurrency_no_lost_chats(self):
        def invoke(i):
            payload = {"session_id": f"chat-{i}", "turn_id": "turn", "hook_event_name": "UserPromptSubmit"}
            return subprocess.run([sys.executable, str(ROOT / "src/progress.py"), "hook"],
                                  input=json.dumps(payload), text=True, capture_output=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(invoke, range(24)))
        self.assertTrue(all(r.returncode == 0 and r.stdout.strip() == "{}" for r in results))
        self.assertEqual(len(p.snapshot()["tasks"]), 24)

    def test_hook_fails_open_on_invalid_input(self):
        r = subprocess.run([sys.executable, str(ROOT / "src/progress.py"), "hook"], input="bad", text=True, capture_output=True)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "{}\n", ""))

    def test_explicit_runtime_override_cannot_silently_fall_back(self):
        with patch.dict(os.environ, {"CODEX_PROGRESS_CODEX_BIN": "/nonexistent/panel-test-codex"}):
            with self.assertRaises(ValueError):
                p.codex_binary()
        with patch.dict(os.environ, {"CODEX_PROGRESS_CODEX_BIN": sys.executable}):
            self.assertEqual(p.codex_binary(), sys.executable)

    def test_finished_and_interrupted_chats_leave_current_for_history(self):
        self.event("UserPromptSubmit")
        self.event("Stop", at=2)
        self.event("Interrupt", sid="chat-b", at=3)
        data = p.snapshot(self.now + 4)
        self.assertEqual(data["current"], [])
        self.assertEqual([r["status"] for r in data["history"]], ["interrupted", "response_finished"])
        self.assertEqual((data["active"], data["waiting"]), (0, 0))

    def test_history_order_and_current_jobs_survive_more_than_ten_entries(self):
        for n in range(12):
            self.event("Stop", sid=f"finished-{n}", at=n)
            self.event("UserPromptSubmit", sid=f"current-{n}", at=n)
        data = p.snapshot(self.now + 13)
        self.assertEqual(len(data["current"]), 12)
        self.assertEqual([r["id"] for r in data["history"]], [f"finished-{n}" for n in reversed(range(12))])
        self.assertEqual(data["active"], 12)

    def test_history_retained_for_seven_days(self):
        self.event("Stop")
        self.assertEqual(len(p.snapshot(self.now + 2 * 86400)["history"]), 1)
        self.assertEqual(p.snapshot(self.now + p.RETENTION_SECONDS + 1)["history"], [])

    def test_dismiss_unknown_preserves_status_and_resumes_on_fresh_event(self):
        self.event("UserPromptSubmit")
        stale = self.now + p.STALE_SECONDS + 1
        p.dismiss("chat-a", self.now, stale)
        data = p.snapshot(stale)
        self.assertEqual((data["current"], data["unknown"]), ([], 0))
        self.assertEqual(data["history"][0]["status"], "connection_unknown")
        self.assertEqual(data["history"][0]["updated"], self.now)
        self.event("PreToolUse", at=p.STALE_SECONDS + 2, tool_name="Bash")
        data = p.snapshot(stale + 1)
        self.assertEqual(data["history"], [])
        self.assertEqual(data["current"][0]["status"], "working")

    def test_cannot_dismiss_working_approval_or_a_changed_observation(self):
        self.event("UserPromptSubmit")
        with self.assertRaises(ValueError):
            p.dismiss("chat-a", self.now, self.now)
        self.event("PermissionRequest", at=1, tool_name="Bash")
        with self.assertRaises(ValueError):
            p.dismiss("chat-a", self.now + 1, self.now + 1)
        self.event("SessionEnd", at=2)
        with self.assertRaises(ValueError):
            p.dismiss("chat-a", self.now + 1, self.now + 2)

    def test_resumed_history_chat_returns_to_current_with_new_turn(self):
        self.event("Stop")
        self.event("UserPromptSubmit", turn="t2", at=2)
        data = p.snapshot(self.now + 3)
        self.assertEqual(data["history"], [])
        self.assertEqual(data["current"][0]["status"], "working")

    def test_ready_can_be_dismissed_and_persists_across_readers(self):
        self.event("SessionStart", turn="")
        subprocess.check_call([sys.executable, str(ROOT / "src/progress.py"), "dismiss",
                               "--session", "chat-a", "--updated", str(self.now)])
        data = json.loads(subprocess.check_output([sys.executable, str(ROOT / "src/progress.py"), "snapshot"]))
        self.assertEqual(data["current"], [])
        self.assertEqual(data["history"][0]["status"], "idle")

    def test_runtime_falls_back_to_cli_when_bundle_is_absent(self):
        with patch.dict(os.environ, {"CODEX_PROGRESS_CODEX_BIN": ""}), \
             patch.object(p.Path, "is_file", return_value=False), \
             patch.object(p.shutil, "which", return_value="/usr/local/bin/codex"):
            self.assertEqual(p.codex_binary(), "/usr/local/bin/codex")


if __name__ == "__main__":
    unittest.main()
