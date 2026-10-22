# Architecture and portability roadmap

The aim is a shared local activity model with interchangeable agent inputs and desktop interfaces. The current implementation is an Omarchy/Linux prototype, not an OS-agnostic application.

## Current boundaries

```text
Codex lifecycle hooks ──> event reducer ──> SQLite records ──> JSON snapshot
                              ↑                                  │
                        Linux /proc                        Omarchy panel

Codex metadata API ──> chat titles
```

`src/progress.py` currently contains the event reducer, storage, Linux process inspection, metadata client and command interface. `plugin/` renders the snapshot through Omarchy's QML components. `install.py` manages Omarchy settings and user hook registration.

The JSON snapshot provides a useful interface boundary, but version 1 is provisional. Preserve its state meanings while refactoring. Do not advertise other platforms as supported merely because the Python reducer runs there.

## Phase 1 — strengthen Codex on Omarchy

- Collect normal-use feedback on approval waits, quiet long-running work and resumed sessions.
- Improve diagnostics for missing hooks without retaining raw payloads.
- Define subagent grouping and refine the Current/History views based on feedback.
- Maintain tests for state transitions, concurrent writes, uninstall preservation and runtime restarts.

## Phase 2 — extract a portable core

Separate these responsibilities into testable modules:

| Component | Responsibility |
| --- | --- |
| Event model and reducer | Session/turn identity, ordering, statuses, explicit milestones; no desktop or OS imports |
| Storage and snapshots | Transactions, retention, schema versioning and consumer-facing records |
| Agent adapter | Translate supported Codex events and retrieve metadata; future sources remain independent |
| Platform adapter | Find executables, choose user data directories, identify/check owner processes and provide safe local transport |
| Desktop interface | Display states and activity; never infer lifecycle or completion from visual progress |
| Installer | Register only its own observer definitions and integrate the chosen interface reversibly |

Portability work must replace the current `/proc` PID/start-time/boot identity, POSIX shell quoting, `/usr/bin/python3`, Linux paths and `select()` on child-process pipes. It must also define file access controls and cleanup on each supported OS. Simply changing the QML interface is insufficient.

Start with cross-platform tests for the pure reducer and snapshot contract. Use platform-specific process identity implementations only when they can distinguish a restarted or reused process. If liveness cannot be established, report unknown.

## Phase 3 — additional desktop interfaces

| Target | Work needed before support can be claimed |
| --- | --- |
| Other Linux desktops | Reusable tray/popup interface or desktop-specific adapter, installation and session-start integration |
| macOS | Menu-bar interface, executable discovery, process identity, native data directories, launch behavior and packaging |
| Windows | Tray interface, executable/command handling, process identity, local pipe transport, access controls and packaging |

Choose UI tooling after the core boundary is tested and contributor requirements are known. A common tray interface may cover several platforms, while native interfaces may fit their desktops better. No framework or delivery date is committed yet.

Each target needs clean-install/update/remove checks, real approval/interruption/restart checks and screenshot review. Keep the current Omarchy interface working throughout this work.

## Phase 4 — additional agent sources

DOT and ChatGPT integrations remain deferred until Codex is reliable. New adapters must use supported event interfaces, preserve source/session/turn identity, expose their capability gaps, and avoid scraping private internal databases or transcripts.

Across every phase: animation means activity, steps require explicit reports, a finished response is not task completion, and unknown stays visible.
