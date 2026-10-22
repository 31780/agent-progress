#!/usr/bin/env python3
"""Local Codex lifecycle observer. Never returns policy decisions or reads transcripts."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import select
import shutil
import sqlite3
import subprocess
import sys
import time

EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PermissionRequest",
          "PostToolUse", "PreCompact", "PostCompact", "Stop", "Interrupt", "SessionEnd")
ACTIVE = {"working", "waiting_approval"}
TERMINAL = {"response_finished", "interrupted"}
LABELS = {"working": "Working", "waiting_approval": "Waiting for approval",
          "interrupted": "Interrupted", "response_finished": "Response finished",
          "connection_unknown": "Connection unknown", "idle": "Ready"}
STALE_SECONDS = 180
RETENTION_SECONDS = 7 * 86400


def codex_binary():
    """Use an explicit runtime, the Omarchy bundle, or the CLI on PATH."""
    override = os.environ.get("CODEX_PROGRESS_CODEX_BIN")
    if override:
        resolved = shutil.which(override)
        if not resolved:
            raise ValueError("CODEX_PROGRESS_CODEX_BIN must name an executable")
        return resolved
    bundled = Path("/usr/lib/chatgpt/resources/codex")
    if bundled.is_file() and os.access(bundled, os.X_OK):
        return str(bundled)
    resolved = shutil.which("codex")
    if not resolved:
        raise FileNotFoundError("Codex not found; set CODEX_PROGRESS_CODEX_BIN or add codex to PATH")
    return resolved


def state_dir():
    return Path(os.environ.get("OMARCHY_PROGRESS_STATE", "") or
                (Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) /
                 "omarchy-agent-progress"))


def clean(value, limit=160):
    return " ".join(str(value or "").split())[:limit]


@contextlib.contextmanager
def database():
    os.umask(0o077)
    root = state_dir()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    conn = sqlite3.connect(root / "tasks.sqlite3", timeout=0.1)
    try:
        # Simultaneous first hooks can race while enabling WAL. SQLite may
        # return BUSY immediately for that transition despite busy_timeout.
        deadline = time.monotonic() + 0.4
        while True:
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, updated REAL, record TEXT)")
                conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
                break
            except sqlite3.OperationalError as exc:
                if (getattr(exc, "sqlite_errorcode", 0) & 255) not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED) or time.monotonic() >= deadline:
                    raise
                time.sleep(0.01)
        conn.execute("PRAGMA busy_timeout=400")
        with conn:
            yield conn
    finally:
        conn.close()


def process_identity(pid):
    try:
        stat = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        if stat[0] == "Z":
            return None
        return {"pid": int(pid), "start": stat[19],
                "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip()}
    except (OSError, ValueError, IndexError):
        return None


def codex_owner():
    pid = os.getppid()
    for _ in range(12):
        try:
            if Path(f"/proc/{pid}/comm").read_text().strip() == "codex":
                return process_identity(pid)
            pid = int(Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[1])
            if pid <= 1:
                break
        except (OSError, ValueError, IndexError):
            break
    return None


def tool_key(event):
    args = event.get("tool_input")
    if isinstance(args, dict):
        # Approval requests can add a description to the original arguments.
        args = {k: v for k, v in args.items() if k != "description"}
    blob = json.dumps([event.get("tool_name"), args], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def activity(tool):
    if tool in ("Bash", "exec_command"):
        return "Running a command"
    if tool in ("apply_patch", "Edit", "Write"):
        return "Editing files"
    if tool == "update_plan":
        return "Updating the plan"
    if "request_user_input" in tool:
        return "Requesting your input"
    if tool.startswith("mcp__"):
        return "Using a connected tool"
    return "Using " + clean(tool, 70) if tool else "Working"


def reduce_event(old, event, now, owner):
    name = event.get("hook_event_name")
    sid = event.get("session_id")
    if name not in EVENTS or not isinstance(sid, str) or not sid or len(sid) > 200:
        raise ValueError("Unsupported event or missing session_id")
    r = dict(old or {"id": sid, "status": "idle", "started": None, "ended": None,
                     "title": "", "turn": "", "seen_turns": [], "pending": {},
                     "milestone": None, "activity": "Session opened", "elapsed_exact": False})
    turn = str(event.get("turn_id") or "")
    current = r["turn"]
    if turn and turn != current:
        if turn in r["seen_turns"]:
            return old  # Late events from an older turn cannot revive it.
        r.update(turn=turn, seen_turns=(r["seen_turns"] + [turn])[-64:],
                 started=now, ended=None, pending={}, milestone=None, status="working",
                 elapsed_exact=name == "UserPromptSubmit")
    elif name == "UserPromptSubmit" and r["status"] in TERMINAL:
        r.update(started=now, ended=None, pending={}, milestone=None, status="working", elapsed_exact=True)
    elif name in ("PreToolUse", "PostToolUse", "PermissionRequest", "Stop") and r["status"] in TERMINAL:
        return old  # In-flight tool output arriving after Stop/Interrupt is stale.
    r.update(updated=now, last_event=name, owner=owner, cwd=clean(event.get("cwd"), 500))
    r.pop("dismissed_at", None)  # Fresh observed activity returns a dismissed chat.
    pending = dict(r["pending"])
    if name == "SessionStart":
        if event.get("source") == "compact":
            r["activity"] = "Context compacted"
        elif old and r["status"] in ACTIVE:
            r.update(status="connection_unknown", activity="Session reopened; waiting for activity")
        else:
            r["activity"] = "Session opened"
    elif name == "UserPromptSubmit":
        r.update(status="waiting_approval" if pending else "working", activity="Preparing response")
        if r["started"] is None:
            r["started"] = now
    elif name in ("PreToolUse", "PostToolUse", "PermissionRequest"):
        key = tool_key(event)
        tool = str(event.get("tool_name") or "")
        if name == "PermissionRequest":
            pending[key] = {"at": now, "tool": clean(tool, 70),
                            "count": pending.get(key, {}).get("count", 0) + 1}
        elif name == "PostToolUse":
            if key in pending and pending[key].get("count", 1) > 1:
                pending[key] = {**pending[key], "count": pending[key]["count"] - 1}
            else:
                pending.pop(key, None)
        r.update(pending=pending, status="waiting_approval" if pending else "working",
                 activity="Approval requested; outcome not yet observed" if pending else
                          (activity(tool) if name == "PreToolUse" else "Processing tool result"))
        if r["started"] is None:
            r["started"] = now
        # A supported plan tool explicitly reports units, never a guessed percentage.
        if name == "PostToolUse" and tool == "update_plan":
            args = event.get("tool_input")
            plan = args.get("plan") if isinstance(args, dict) else None
            if isinstance(plan, list) and 0 < len(plan) <= 100 and all(
                    isinstance(x, dict) and x.get("status") in ("pending", "in_progress", "completed") for x in plan):
                r["milestone"] = {"done": sum(x["status"] == "completed" for x in plan),
                                  "total": len(plan), "source": "Agent-reported plan"}
    elif name in ("PreCompact", "PostCompact"):
        r.update(status="waiting_approval" if pending else "working",
                 activity="Compacting context" if name == "PreCompact" else "Context compacted")
    elif name in ("Stop", "Interrupt"):
        r.update(status="response_finished" if name == "Stop" else "interrupted",
                 activity="Response ended; task completion is not inferred" if name == "Stop" else "Turn interrupted",
                 ended=now, pending={})
    elif name == "SessionEnd":
        if r["status"] not in TERMINAL:
            r.update(status="connection_unknown", activity="Session ended; no final response event observed")
        r["session_ended"] = now
    return r


def ingest(event, now=None, owner=None):
    now = time.time() if now is None else now
    with database() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT record FROM tasks WHERE id=?", (str(event.get("session_id", "")),)).fetchone()
        record = reduce_event(json.loads(row[0]) if row else None, event, now, owner)
        conn.execute("INSERT OR REPLACE INTO tasks VALUES (?, ?, ?)",
                     (record["id"], record["updated"], json.dumps(record)))
        conn.execute("DELETE FROM tasks WHERE updated < ?", (now - RETENTION_SECONDS,))
    return record


def observed_status(record, now):
    status, detail = record["status"], record["activity"]
    if status in ACTIVE:
        owner = record.get("owner")
        if owner is None or process_identity(owner["pid"]) != owner:
            return "connection_unknown", "Codex process unavailable; last seen " + LABELS[status].lower()
        if now - record["updated"] > STALE_SECONDS:
            return "connection_unknown", "No hook event for 3 minutes; last seen " + LABELS[status].lower()
    return status, detail


def dismiss(session, updated, now=None):
    """Move an unchanged unknown/ready observation to history, without ending it."""
    now = time.time() if now is None else now
    with database() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT record FROM tasks WHERE id=?", (session,)).fetchone()
        if not row:
            raise ValueError("No observed session with that id")
        record = json.loads(row[0])
        if record["updated"] != updated or observed_status(record, now)[0] not in ("connection_unknown", "idle"):
            raise ValueError("The job changed; refresh before dismissing")
        record["dismissed_at"] = now
        conn.execute("UPDATE tasks SET record=? WHERE id=?", (json.dumps(record), session))


def snapshot(now=None):
    now = time.time() if now is None else now
    with database() as conn:
        rows = conn.execute("SELECT record FROM tasks WHERE updated >= ? ORDER BY updated DESC LIMIT 200",
                            (now - RETENTION_SECONDS,)).fetchall()
    tasks = []
    for row in rows:
        r = json.loads(row[0])
        status, detail = observed_status(r, now)
        age = max(0, now - r["updated"])
        end = r.get("ended") or (now if status in ACTIVE else r["updated"])
        elapsed = max(0, end - r["started"]) if r.get("started") else 0
        tasks.append({"id": r["id"], "title": r["title"] or
                      (Path(r.get("cwd") or "/").name or "Codex") + " · " + r["id"][:8],
                      "titleKnown": bool(r["title"]), "status": status, "label": LABELS[status],
                      "activity": detail, "elapsed": int(elapsed), "age": int(age),
                      "elapsedExact": r.get("elapsed_exact", False),
                      "milestone": r.get("milestone"), "updated": r["updated"],
                      "inHistory": status in TERMINAL or r.get("dismissed_at") is not None,
                      "historyAt": r.get("dismissed_at") or r.get("ended") or r["updated"]})
    rank = {"waiting_approval": 0, "working": 1, "connection_unknown": 2, "interrupted": 3, "response_finished": 4, "idle": 5}
    tasks.sort(key=lambda r: (rank[r["status"]], -r["updated"]))
    current = [t for t in tasks if not t["inHistory"]]
    history = sorted((t for t in tasks if t["inHistory"]), key=lambda t: t["historyAt"], reverse=True)
    return {"schemaVersion": 1, "generated": now, "tasks": tasks,
            "current": current, "history": history,
            "active": sum(t["status"] in ACTIVE for t in current),
            "waiting": sum(t["status"] == "waiting_approval" for t in current),
            "unknown": sum(t["status"] == "connection_unknown" for t in current)}


class Rpc:
    """Short-lived metadata-only connection; never resume or start a thread."""
    def __enter__(self):
        self.p = subprocess.Popen([codex_binary(), "app-server", "--stdio"], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.seq, self.buffer = 0, b""
        try:
            self.call("initialize", {"clientInfo": {"name": "omarchy_progress", "version": "0.1.0"},
                                     "capabilities": {"experimentalApi": True}})
        except Exception:
            self.__exit__()
            raise
        self.p.stdin.write(b'{"method":"initialized"}\n')
        self.p.stdin.flush()
        return self

    def call(self, method, params):
        self.seq += 1
        self.p.stdin.write((json.dumps({"id": self.seq, "method": method, "params": params}) + "\n").encode())
        self.p.stdin.flush()
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            if b"\n" not in self.buffer:
                ready, _, _ = select.select([self.p.stdout], [], [], max(0, deadline - time.monotonic()))
                if not ready:
                    break
                chunk = os.read(self.p.stdout.fileno(), 65536)
                if not chunk:
                    raise RuntimeError("Metadata service closed")
                self.buffer += chunk
                continue
            raw, self.buffer = self.buffer.split(b"\n", 1)
            message = json.loads(raw)
            if message.get("id") == self.seq:
                if "error" in message:
                    raise RuntimeError("Metadata request rejected")
                return message.get("result", {})
        raise TimeoutError("Metadata request timed out")

    def __exit__(self, *args):
        self.p.terminate()
        try:
            self.p.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.p.kill()
            self.p.wait()


def titles():
    with database() as conn:
        ids = [r[0] for r in conn.execute("SELECT id FROM tasks WHERE updated >= ? ORDER BY updated DESC LIMIT 200",
                                        (time.time() - RETENTION_SECONDS,))]
    if not ids:
        return
    with Rpc() as rpc:
        deadline = time.monotonic() + 12
        for sid in ids:
            if time.monotonic() > deadline:
                break
            try:
                title = clean(rpc.call("thread/read", {"threadId": sid, "includeTurns": False}).get("thread", {}).get("name"))
            except TimeoutError:
                break
            except RuntimeError:
                continue
            if not title:
                continue
            with database() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute("SELECT record FROM tasks WHERE id=?", (sid,)).fetchone()
                if row:
                    record = json.loads(row[0])
                    record["title"] = title
                    conn.execute("UPDATE tasks SET record=? WHERE id=?", (json.dumps(record), sid))


def report(args):
    if args.done < 0 or args.total < 1 or args.done > args.total:
        raise ValueError("Milestones require 0 <= done <= total and total > 0")
    with database() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT record FROM tasks WHERE id=?", (args.session,)).fetchone()
        if not row:
            raise ValueError("No observed session with that id")
        r = json.loads(row[0])
        if args.turn != r["turn"]:
            raise ValueError("Report does not match the current observed turn")
        r["milestone"] = {"done": args.done, "total": args.total, "source": "Agent-reported plan"}
        conn.execute("UPDATE tasks SET record=? WHERE id=?", (json.dumps(r), args.session))


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("hook", "snapshot", "titles", "hooks"):
        sub.add_parser(name)
    dismiss_parser = sub.add_parser("dismiss")
    dismiss_parser.add_argument("--session", required=True)
    dismiss_parser.add_argument("--updated", type=float, required=True)
    report_parser = sub.add_parser("report")
    for name in ("session", "turn"):
        report_parser.add_argument("--" + name, required=True)
    for name in ("done", "total"):
        report_parser.add_argument("--" + name, type=int, required=True)
    args = parser.parse_args()
    try:
        if args.command == "hook":
            # Bound input size; discard prompts, commands, responses and transcript paths.
            raw = sys.stdin.buffer.read(8 * 1024 * 1024 + 1)
            if len(raw) > 8 * 1024 * 1024:
                raise ValueError("Hook input too large")
            ingest(json.loads(raw), owner=codex_owner())
        elif args.command == "snapshot":
            print(json.dumps(snapshot()))
        elif args.command == "titles":
            titles()
        elif args.command == "hooks":
            with Rpc() as rpc:
                print(json.dumps(rpc.call("hooks/list", {"cwds": [os.getcwd()]}), indent=2))
        elif args.command == "report":
            report(args)
        elif args.command == "dismiss":
            dismiss(args.session, args.updated)
    except Exception as exc:
        if args.command == "hook":
            # Observation must not block/deny a user action on a storage failure.
            pass
        else:
            print(f"Progress panel: {exc}", file=sys.stderr)
            return 1
    finally:
        if args.command == "hook":
            print("{}")  # Valid no-op output even for Stop; never a policy decision.
    return 0


if __name__ == "__main__":
    sys.exit(main())
