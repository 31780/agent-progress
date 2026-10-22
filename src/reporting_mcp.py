#!/usr/bin/env python3
"""Write-only MCP stdio bridge. Expose only through a private, authenticated transport.

No listener, shell execution, file access tools, snapshots, or credentials are
exposed. The tunnel authenticates callers; run tokens only guard report ordering.
"""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

import progress

VERSION = "0.3.0"
PROTOCOLS = ("2025-11-25", "2025-06-18")
MAX_MESSAGE = 16384
INSTRUCTIONS = (
    "Use Agent Progress only when the user asks to track this task. Call begin_report once, "
    "retain its id/run, then update_report at meaningful transitions with increasing sequence. "
    "Each call needs a new request_id UUID; an immediate retry must reuse identical arguments. "
    "Never retry an old request after seven days. Quiet reports become unknown after three minutes. "
    "No artificial heartbeats, guessed percentages, approval claims, or reports for other chats. "
    "Source dot means ChatGPT's Dot; chatgpt means ChatGPT Work. Use the host task ID, or retain "
    "a reporter UUID if unavailable; never scrape transcripts. Titles must be non-sensitive. "
    "Use waiting_input only after asking the user, ready_for_review only when a deliverable is ready. "
    "A finished report moves to History. New work needs a fresh begin. If reporting fails, continue "
    "the user's task and explain once; do not retry in a loop or bypass a stale-run error."
)


def object_schema(properties, required):
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


def text_schema(limit):
    return {"type": "string", "minLength": 1, "maxLength": limit}


REQUEST_ID = {"type": "string", "format": "uuid", "minLength": 36, "maxLength": 36,
              "description": "New UUID per report; reuse only for an immediate retry of the exact same arguments."}
TOOLS = [
    {"name": "begin_report", "title": "Show this task in Agent Progress",
     "description": "Begin an explicit Dot or ChatGPT Work report on the owner's desktop panel. "
                    "Only when asked to track this task. This is agent-reported activity, not lifecycle monitoring. "
                    "Use a short non-sensitive title and retain the returned id/run. A new begin replaces the previous run.",
     "inputSchema": object_schema({"request_id": REQUEST_ID, "source": {"type": "string", "enum": ["dot", "chatgpt"]},
                                   "session": text_schema(200), "title": text_schema(160)},
                                  ["request_id", "source", "session", "title"]),
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}},
    {"name": "update_report", "title": "Update this task's reported progress",
     "description": "Report a meaningful work transition for the exact id/run returned by begin_report. "
                    "Increase sequence. working, waiting_input, or ready_for_review only. Milestones must come "
                    "from an explicit plan; omit to preserve, null to clear. Never fabricate a heartbeat or percentage.",
     "inputSchema": object_schema({"request_id": REQUEST_ID, "id": text_schema(200), "run": text_schema(100),
                                   "sequence": {"type": "integer", "minimum": 1, "maximum": 2**53 - 1},
                                   "status": {"type": "string", "enum": sorted(progress.REPORT_STATES)},
                                   "milestone": {"anyOf": [{"type": "null"}, object_schema({
                                       "done": {"type": "integer", "minimum": 0, "maximum": 1000},
                                       "total": {"type": "integer", "minimum": 1, "maximum": 1000}}, ["done", "total"])]}},
                                  ["request_id", "id", "run", "sequence", "status"]),
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}}
]


def error(rid, code, message):
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def tool_result(value, failed=False):
    result = {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=True)}], "isError": failed}
    if not failed:
        result["structuredContent"] = value
    return result


class Server:
    def __init__(self):
        self.initialized = False
        self.ready = False

    def handle(self, message):
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
            return error(None, -32600, "Invalid request")
        rid, method = message.get("id"), message["method"]
        if "id" in message and (type(rid) not in (str, int) or isinstance(rid, str) and len(rid) > 200):
            return error(None, -32600, "Invalid request id")
        params = message.get("params", {})
        if "id" not in message:
            # A notification must never perform a write or produce a response.
            if method == "notifications/initialized" and self.initialized and isinstance(params, dict):
                self.ready = True
            return None
        if not isinstance(params, dict):
            return error(rid, -32602, "Expected object params")
        if method == "initialize":
            client = params.get("clientInfo")
            if (self.initialized or not isinstance(params.get("protocolVersion"), str)
                    or not isinstance(params.get("capabilities"), dict) or not isinstance(client, dict)
                    or not isinstance(client.get("name"), str) or not isinstance(client.get("version"), str)):
                return error(rid, -32602, "Invalid or repeated initialization")
            self.initialized = True
            version = params["protocolVersion"] if params["protocolVersion"] in PROTOCOLS else PROTOCOLS[0]
            result = {"protocolVersion": version, "capabilities": {"tools": {"listChanged": False}},
                      "serverInfo": {"name": "agent-progress", "version": VERSION}, "instructions": INSTRUCTIONS}
        elif method == "ping":
            result = {}
        elif not self.ready:
            return error(rid, -32000, "Initialize the MCP session first")
        elif method == "tools/list":
            if set(params) - {"_meta"}:
                return error(rid, -32602, "This server has no additional tool pages")
            result = {"tools": TOOLS}
        elif method == "tools/call":
            definition = next((t for t in TOOLS if t["name"] == params.get("name")), None)
            if definition is None:
                return error(rid, -32602, "Unknown tool")
            args = params.get("arguments")
            schema = definition["inputSchema"]
            if (set(params) - {"name", "arguments", "_meta"} or not isinstance(args, dict)
                    or set(args) - set(schema["properties"]) or set(schema["required"]) - set(args)):
                return error(rid, -32602, "Invalid tool arguments")
            try:
                report = {k: v for k, v in args.items() if k != "request_id"}
                report["action"] = "begin" if definition["name"] == "begin_report" else "update"
                # Keep request_id mandatory here even though local observations
                # can use the original CLI without a network retry receipt.
                if not isinstance(args["request_id"], str) or len(args["request_id"]) != 36:
                    raise ValueError("request_id must be a canonical UUID")
                result = tool_result(progress.observe(report, request_id=args["request_id"]))
            except (ValueError, TypeError, AttributeError):
                result = tool_result({"error": "Invalid, stale, closed, or conflicting report. Check the documented fields, "
                                     "retain the current run and increase sequence. Do not begin just to bypass this error."}, True)
            except (OSError, sqlite3.Error):
                result = tool_result({"error": "Local report storage unavailable. Continue the task; do not retry in a loop."}, True)
        else:
            return error(rid, -32601, "Method not found")
        return {"jsonrpc": "2.0", "id": rid, "result": result}


def reject_constant(value):
    raise ValueError("Non-JSON number")


def unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("Duplicate JSON key")
        obj[key] = value
    return obj


def serve(reader, writer):
    server = Server()
    while True:
        line = reader.readline(MAX_MESSAGE + 1)
        if not line:
            return 0
        if len(line) > MAX_MESSAGE:
            # End this channel rather than buffer or misinterpret a large tail.
            response = error(None, -32600, "Message exceeds 16 KiB")
        else:
            try:
                message = json.loads(line.decode("utf-8"), parse_constant=reject_constant, object_pairs_hook=unique_object)
                response = server.handle(message)
            except (ValueError, UnicodeError, RecursionError):
                response = error(None, -32700, "Invalid JSON")
        if response is not None:
            writer.write((json.dumps(response, ensure_ascii=True, separators=(",", ":")) + "\n").encode("utf-8"))
            writer.flush()
        if len(line) > MAX_MESSAGE:
            return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, help="Explicit state directory; default is the installed panel's state")
    args = parser.parse_args()
    if args.state_dir:
        import os
        os.environ["OMARCHY_PROGRESS_STATE"] = str(args.state_dir.resolve())
    try:
        return serve(sys.stdin.buffer, sys.stdout.buffer)
    except (BrokenPipeError, KeyboardInterrupt):
        return 0


if __name__ == "__main__":
    sys.exit(main())
