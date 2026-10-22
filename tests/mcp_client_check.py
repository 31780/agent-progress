#!/usr/bin/env python3
"""Optional interoperability check with the official Python MCP client SDK.

Install mcp>=1.20,<2 in a disposable virtualenv. All reports use temporary state.
This verifies stdio delivery, not a live ChatGPT account or cloud tunnel.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def check(server):
    with tempfile.TemporaryDirectory(prefix="agent-progress-mcp-") as state:
        env = {**os.environ, "OMARCHY_PROGRESS_STATE": state}
        params = StdioServerParameters(command=sys.executable, args=[str(server)], env=env)
        async with stdio_client(params) as streams:
            async with ClientSession(*streams) as session:
                initialized = await session.initialize()
                tools = await session.list_tools()
                assert {t.name for t in tools.tools} == {"begin_report", "update_report"}
                begin = {"request_id": str(uuid.uuid4()), "source": "dot", "session": "sdk-fixture",
                         "title": "Isolated MCP fixture"}
                first = await session.call_tool("begin_report", begin)
                assert not first.isError
                report = first.structuredContent
                assert report["sequence"] == 0
                replay = await session.call_tool("begin_report", begin)
                assert replay.structuredContent == report
                update = {"request_id": str(uuid.uuid4()), "id": report["id"], "run": report["run"],
                          "sequence": 1, "status": "waiting_input", "milestone": {"done": 1, "total": 2}}
                assert not (await session.call_tool("update_report", update)).isError
                def snapshot():
                    return json.loads(subprocess.check_output([sys.executable, str(server.with_name("progress.py")),
                                                              "snapshot"], env=env))
                current = snapshot()
                assert current["waiting"] == 0 and current["inputWaiting"] == 1
                assert current["current"][0]["observation"] == "agent_report"
                assert not (await session.call_tool("update_report", {**update, "request_id": str(uuid.uuid4()),
                                          "sequence": 2, "status": "ready_for_review"})).isError
                assert snapshot()["history"][0]["status"] == "ready_for_review"
                await session.initialize()
                assert len((await session.list_tools()).tools) == 2
                assert (await session.call_tool("begin_report", begin)).structuredContent == report
                assert snapshot()["current"] == []
                assert not (await session.call_tool("begin_report", {**begin, "request_id": str(uuid.uuid4())})).isError
                stale = await session.call_tool("update_report", {**update, "request_id": str(uuid.uuid4()), "sequence": 3})
                assert stale.isError
                print(json.dumps({"passed": True, "protocol": initialized.protocolVersion,
                                  "checks": ["discovery", "begin", "retry", "waiting_input", "milestone",
                                             "snapshot", "history", "reinitialize", "new_run", "stale_run_rejected"],
                                  "isolated": True}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", type=Path, default=Path(__file__).resolve().parents[1] / "src/reporting_mcp.py")
    asyncio.run(check(parser.parse_args().server.resolve()))
