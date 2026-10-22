# Private reporting from ChatGPT Dot

The optional MCP bridge lets **ChatGPT's Dot** or ChatGPT Work send explicit
progress reports to this computer through OpenAI's Secure MCP Tunnel. Dot does
not need desktop-control access. It must have the connected plugin and actually
call its reporting tools. This does not discover all chats or monitor a personal
account automatically.

```text
Dot / ChatGPT Work → private OpenAI tunnel → tunnel-client → reporting_mcp.py
                                                               ↓
                                                        local SQLite state
                                                               ↓
                                                        Agent Progress panel
```

The tunnel client makes outbound HTTPS connections. The reporting bridge uses
stdin/stdout and opens no network listener. The computer must be awake, online
and running the tunnel client. Reports are not queued indefinitely for an offline
computer. A quiet report becomes unknown after three minutes; reconnecting the
tunnel alone never refreshes a task or marks it complete.

**Verification status:** version 0.3.1 passes isolated contract tests and an
interoperability check using the official Python MCP client SDK. ChatGPT has
successfully discovered both tools through a private tunnel. A real Dot report
still needs live verification; tool discovery and local test reports are not
evidence of Dot activity.

## 1. Install the bridge

On the Omarchy computer hosting the panel:

```sh
python3 install.py install --with-mcp-bridge --with-reporting-skill
```

This installs `reporting_mcp.py` beside `progress.py` in
`$XDG_DATA_HOME/omarchy-agent-progress` (normally
`~/.local/share/omarchy-agent-progress`). Updates preserve the selection. It does
not create credentials, grant cloud access, start a tunnel, or change hook
definitions. The optional local skill knows how to prefer connected MCP tools.
The MCP server also supplies its own instructions, so cloud use does not depend
on discovering a local skill.

The bridge itself needs Python 3.11+ and no third-party Python packages. Its
portable tests run on Linux, macOS and Windows. The desktop panel and installer
still require Omarchy.

## 2. Connect a private tunnel

Follow the current [official Secure MCP Tunnel setup](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)
and [tunnel-client onboarding](https://github.com/openai/tunnel-client/blob/master/docs/onboarding.md).
Use the official download in [Platform tunnel settings](https://platform.openai.com/settings/organization/tunnels)
or the [latest official release](https://github.com/openai/tunnel-client/releases/latest).
Match the binary to your OS/architecture and verify the release checksum.

- Create or reuse a **private personal tunnel** for Agent Progress. Associate it
  with the Platform organization and ChatGPT workspace you actually use.
- Creating/managing it requires Tunnels Read + Manage. The runtime key and the
  person connecting the plugin need Tunnels Read + Use. Custom MCP availability
  also depends on ChatGPT workspace permissions.
- Use a restricted runtime key, never an admin key for the running service.
  Enter it locally using a secure prompt or secret manager. Keep it out of chat,
  shell history, command arguments, screenshots and committed files. The client
  supports `env:VARIABLE` and `file:/private/path` references. Keep key files
  owner-readable only; on Windows use an appropriate user-only ACL.
- Do not reuse a tunnel shared with untrusted users: every authorized caller can
  submit reports to this panel. This bridge is for one owner's private panel;
  it does not implement multi-user ownership or authorization itself.

After setting the `CONTROL_PLANE_API_KEY` environment variable securely, the
official CLI supports a named stdio profile. Replace the example ID and paths
with the real values. Quote each path inside the command if it contains spaces.

```sh
tunnel-client help quickstart
tunnel-client init --sample sample_mcp_stdio_local --profile agent-progress \
  --tunnel-id YOUR_TUNNEL_ID \
  --mcp-command 'python3 /absolute/path/to/omarchy-agent-progress/reporting_mcp.py'
tunnel-client doctor --profile agent-progress --explain
tunnel-client run --profile agent-progress
```

Keep the foreground client running during connection and use. For a managed
background runtime, use the supported `tunnel-client runtimes connect` flow
instead of `nohup`. Check the installed client's help before setting it up:

```sh
tunnel-client runtimes connect --help
tunnel-client runtimes connect --alias agent-progress --profile agent-progress \
  --tunnel-id YOUR_TUNNEL_ID \
  --runtime-api-key env:CONTROL_PLANE_API_KEY \
  --mcp-command 'python3 /absolute/path/to/omarchy-agent-progress/reporting_mcp.py'
tunnel-client runtimes status agent-progress --json
```

A managed runtime needs its key reference to remain resolvable after restart.
The `file:/private/path` reference or your secret manager may fit better than a
terminal-only environment variable. A started process is insufficient: verify
`process_running`, `healthy`, and `ready` before claiming a working connection.
Leave the client's admin/health UI on its default loopback address.

After ChatGPT discovers the tools, also check `/health/mcp` at the local health
address. It should show successful initialization and both `begin_report` and
`update_report`. A healthy tunnel alone does not establish MCP compatibility.
Version 0.3.1 allows ChatGPT to initialize the same stdio process again during
discovery or reconnection. Each valid handshake resets only transport readiness
and requires a fresh `notifications/initialized`; it never creates, refreshes or
reopens a task report.

## 3. Add the plugin to ChatGPT

In [ChatGPT Plugins](https://chatgpt.com/plugins), select **+ → Add custom MCP
server → Connection: Tunnel** and choose the same tunnel. Name it **Agent
Progress**. The stdio bridge has no separate OAuth server; its access boundary
is the private tunnel's organization/workspace permissions. Do not publish it
through an unauthenticated public HTTP proxy.

Review the two tools and connect/install the private plugin. Account permission
prompts must be completed by the account owner as required. The tools are:

| Tool | What it can do |
| --- | --- |
| `begin_report` | Start a report for this Dot or ChatGPT Work task |
| `update_report` | Update that report's state or explicit milestone counts |

There are no tools for reading chat lists, transcripts, snapshots, files,
credentials, or executing commands. `tools/list` and `ping` do not write task
state. Connecting/disconnecting the transport never writes a progress report.

Once the tools are available to Dot, ask it:

> Use Agent Progress to show this task in my desktop panel. Send updates at
> meaningful work transitions and mark it ready for review when the deliverable
> is ready. Do not send artificial heartbeats.

The expected evidence is an actual successful tool call followed by a
**Dot · Agent-reported** card with the task title. A ready-for-review report
belongs in History. If the tools are unavailable in that Dot context, do not
substitute a fake report or claim the tunnel observes it automatically.

## Report contract and retry behavior

`begin_report` accepts `request_id`, `source`, `session`, and `title`.
`update_report` accepts `request_id`, `id`, `run`, `sequence`, `status`, and an
optional `milestone`. These use the [local report contract](REPORTING.md), without
an `action` property. Both are writes and declare that in their MCP annotations.

Use a new canonical UUID `request_id` for each deliberate report. An immediate
retry must use the **same UUID and identical arguments**. A transaction stores
the state change and its acknowledgement together. A retry returns the original
acknowledgement without resetting the run, refreshing age, changing history or
reopening a finished report. Reusing a UUID with changed arguments fails.
Receipts contain a payload hash and acknowledgement, retained for seven days.
Never retry a request after that retention window. An old acknowledgement is
not evidence that its run is still current; new updates must pass run/sequence
checks. Receipt cleanup occurs on a subsequent MCP report.

Only explicit `working`, `waiting_input`, and `ready_for_review` states are
accepted. Native approval/interruption/response-finish states cannot be reported
through this bridge. Unknown fields and invalid counts are rejected. Input is
bounded to 16 KiB per MCP message. Errors do not echo report payloads or local
paths. The server supports the 2025-06-18 and 2025-11-25 MCP stdio handshakes;
it does not provide HTTP, SSE, resources, sampling or background tasks.

The bridge does not upload existing local records. Reports necessarily pass
through OpenAI and may appear in its normal tool-call records. Keep titles
non-sensitive. The local store follows the existing seven-day/200-visible-record
policy. Run tokens prevent stale writers, not hostile users with access to the
same tunnel or local OS account.

## Verify, update or disconnect

The dependency-free tests run with the normal suite. The official SDK check is
optional and isolated from your installed panel:

```sh
python3 -m unittest discover -s tests -p test_mcp.py -v
python3 -m venv work/mcp-sdk-venv
work/mcp-sdk-venv/bin/python -m pip install 'mcp>=1.20,<2'
work/mcp-sdk-venv/bin/python tests/mcp_client_check.py
```

On Windows use the virtualenv's `Scripts/python.exe`. Pass `--server` with the
installed bridge's absolute path to verify an installed copy. The check still
uses temporary state and makes no cloud call.

Restart the tunnel runtime after updating the bridge so existing stdio processes
load the new code. Before removing the panel, stop/disconnect its runtime with
the client's supported `runtimes` commands and disconnect the ChatGPT plugin.
Revoke an unused runtime key in Platform. Panel removal backs up local files; it
does not delete cloud tunnels, credentials or unrelated runtime profiles.
