#!/usr/bin/env python3
"""Exercise real Codex hooks against a loopback-only deterministic model fixture.

Requires the installed hook definitions to have been trusted by the user.
No remote model calls, persisted test chats, real approval acceptance, or trust bypass.
"""
import http.server
import importlib.util
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import tempfile
import threading
import time
import tomllib
import uuid

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("progress", ROOT / "src/progress.py")
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


class Model(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        serialized = json.dumps(body.get("input", []))
        interrupted = "panel-test:interrupt" in serialized
        approval = "panel-test:approval" in serialized
        tool_done = any(x.get("type") == "function_call_output" for x in body.get("input", []))
        if interrupted and tool_done:
            # Hold model generation so the client can interrupt a real live turn,
            # even after unified exec yields a background-session handle.
            time.sleep(30)
        rid = "resp_" + uuid.uuid4().hex
        if not tool_done:
            arguments = {"cmd": "sleep 2", "yield_time_ms": 1000, "max_output_tokens": 50}
            if interrupted:
                arguments["cmd"] = "sleep 6"
            if approval:
                arguments.update(cmd="true", sandbox_permissions="require_escalated",
                                 justification="Progress panel test; the test client will decline this request.")
            item = {"id": "fc_" + uuid.uuid4().hex, "type": "function_call", "name": "exec_command",
                    "call_id": "call_" + uuid.uuid4().hex, "arguments": json.dumps(arguments)}
        else:
            item = {"id": "msg_" + uuid.uuid4().hex, "type": "message", "role": "assistant",
                    "status": "completed", "content": [{"type": "output_text", "text": "Panel runtime test finished.", "annotations": []}]}
        events = [{"type": "response.created", "response": {"id": rid}},
                  {"type": "response.output_item.done", "output_index": 0, "item": item},
                  {"type": "response.completed", "response": {"id": rid, "status": "completed", "output": [item],
                   "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}}]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            for event in events:
                self.wfile.write(("data: " + json.dumps(event) + "\n\n").encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


class Client:
    def __init__(self, url, state):
        self.queue = queue.Queue()
        self.saved = []
        self.seq = 0
        command = [p.codex_binary(), "app-server", "--stdio"]
        overrides = {
            "model_provider": '"panel_test"',
            "model_providers.panel_test.name": '"Local panel test fixture"',
            "model_providers.panel_test.base_url": json.dumps(url),
            "model_providers.panel_test.wire_api": '"responses"',
            "model_providers.panel_test.requires_openai_auth": "false",
            "features.apps": "false", "features.plugins": "false",
            "model": '"gpt-5.4"',
        }
        config_path = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "config.toml"
        if config_path.exists():
            config = tomllib.loads(config_path.read_text())
            for server in config.get("mcp_servers", {}):
                # CLI override paths split on dots and do not unquote key names.
                if not re.fullmatch(r"[A-Za-z0-9_-]+", server):
                    raise ValueError("Use a controlled test config with simple MCP server names")
                overrides["mcp_servers." + server + ".enabled"] = "false"
        for key, value in overrides.items():
            command += ["-c", key + "=" + value]
        self.log = open(ROOT / "work/runtime-stderr.log", "w")
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=self.log, text=True,
                                        env={**os.environ, "OMARCHY_PROGRESS_STATE": state})
        threading.Thread(target=self.read, daemon=True).start()
        self.call("initialize", {"clientInfo": {"name": "panel_runtime_test", "version": "0.1"},
                                 "capabilities": {"experimentalApi": True}})
        self.send({"method": "initialized"})

    def read(self):
        for line in self.process.stdout:
            try:
                self.queue.put(json.loads(line))
            except ValueError:
                pass

    def send(self, msg):
        self.process.stdin.write(json.dumps(msg) + "\n")
        self.process.stdin.flush()

    def wait(self, predicate, timeout=25):
        deadline = time.monotonic() + timeout
        for idx, msg in enumerate(self.saved):
            if predicate(msg):
                return self.saved.pop(idx)
        while time.monotonic() < deadline:
            try:
                msg = self.queue.get(timeout=max(.01, deadline-time.monotonic()))
            except queue.Empty:
                break
            if predicate(msg):
                return msg
            self.saved.append(msg)
        raise TimeoutError("Runtime event timed out: " + str([m.get("method", m.get("error")) for m in self.saved][-20:]))

    def call(self, method, params):
        self.seq += 1
        self.send({"id": self.seq, "method": method, "params": params})
        response = self.wait(lambda m: m.get("id") == self.seq and "method" not in m)
        if "error" in response:
            raise RuntimeError(response["error"])
        return response["result"]

    def start(self, scenario):
        result = self.call("thread/start", {"cwd": str(ROOT / "work"), "ephemeral": True,
                                            "approvalPolicy": "on-request", "sandbox": "read-only",
                                            "baseInstructions": "Use the supplied tools for the local runtime test.",
                                            "developerInstructions": "This is a deterministic local test fixture."})
        sid = result["thread"]["id"]
        tid = self.call("turn/start", {"threadId": sid, "input": [{"type": "text", "text": "panel-test:" + scenario}]})["turn"]["id"]
        return sid, tid

    def close(self):
        self.process.terminate()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        self.log.close()


def await_status(sid, status, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        tasks = p.snapshot()["tasks"]
        found = next((r for r in tasks if r["id"] == sid), None)
        if found and found["status"] == status:
            return found
        time.sleep(.05)
    raise AssertionError(f"Expected {status}, got {found}")


def main():
    (ROOT / "work").mkdir(exist_ok=True)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Model)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with tempfile.TemporaryDirectory(prefix="runtime-", dir=ROOT / "work") as state:
        os.environ["OMARCHY_PROGRESS_STATE"] = state
        client = Client(f"http://127.0.0.1:{server.server_port}/v1", state)
        try:
            hooks = client.call("hooks/list", {"cwds": [str(ROOT / "work")]})
            trusted = [h for layer in hooks["data"] for h in layer["hooks"] if h["trustStatus"] == "trusted"]
            assert len(trusted) >= 10, "Trust the installed panel hooks before running this test"
            first, first_turn = client.start("interrupt")
            await_status(first, "working")
            second, second_turn = client.start("approval")
            request = client.wait(lambda m: m.get("method") == "item/commandExecution/requestApproval")
            await_status(second, "waiting_approval")
            assert p.snapshot()["active"] == 2
            print("PASS simultaneous runtime chats and approval wait", flush=True)
            # Never accept an escalation; a decline should let the response finish.
            client.send({"id": request["id"], "result": {"decision": "decline"}})
            await_status(second, "response_finished")
            print("PASS declined approval and response finished", flush=True)
            client.call("turn/interrupt", {"threadId": first, "turnId": first_turn})
            await_status(first, "interrupted")
            print("PASS runtime interruption", flush=True)
            third, third_turn = client.start("interrupt")
            await_status(third, "working")
            # SIGTERM is a graceful interrupt in Codex. SIGKILL simulates loss
            # without a final hook and exercises the saved process identity.
            client.process.kill()
            client.process.wait(timeout=3)
            client.log.close()
            await_status(third, "connection_unknown")
            print("PASS runtime disappearance becomes connection unknown", flush=True)
            client = Client(f"http://127.0.0.1:{server.server_port}/v1", state)
            await_status(third, "connection_unknown")
            fourth, fourth_turn = client.start("finish")
            await_status(fourth, "response_finished")
            await_status(third, "connection_unknown")
            print("PASS restart retains unknown state and tracks new responses", flush=True)
            print("PASS", len(p.snapshot()["tasks"]), "isolated local task records", flush=True)
        finally:
            if client.process.poll() is None:
                client.close()
            server.shutdown()


if __name__ == "__main__":
    main()
