# Contributing

Agent Progress currently supports Codex on Omarchy/Linux. Small fixes, reproducible bug reports and tests for lifecycle edge cases are welcome. Discuss larger desktop or agent integrations in an issue first; see the [roadmap](docs/ROADMAP.md).

## Working locally

Use Python 3.11+ and run:

```sh
python3 -m unittest discover -s tests -v
```

For changes to hook handling, also run `python3 tests/runtime_check.py` on a controlled Linux machine with Codex and the installed hooks already trusted. Validate QML with `omarchy plugin validate plugin` and an isolated preview or the installed shell. Keep test records separate using `OMARCHY_PROGRESS_STATE`. Never bypass hook trust or accept elevated commands in runtime tests.

Include the affected OS/desktop, Codex version, expected behavior and sanitized reproduction steps in bug reports. Do not attach raw transcripts, auth files, unredacted hook payloads, or your state database.

## Design rules

- Observe supported events; do not control agent permissions or parse private transcripts.
- Preserve unknown states. A missing event must not become a completion claim.
- Keep explicit milestones separate from lifecycle status.
- Preserve unrelated user hooks and settings; maintain a reversible installation path.
- Put OS-specific process checks, installation and UI behavior behind separate interfaces as the architecture evolves.
- Add coverage for meaningful state transitions and regressions, including concurrent events and late results.

Contributions are made under this repository's MIT license. Keep changes focused and explain how they were verified.
