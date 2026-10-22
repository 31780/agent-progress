# Contributing

Welcome! Agent Progress currently supports Codex on Omarchy/Linux. Documentation fixes, reproducible bug reports, accessibility improvements and tests for lifecycle edge cases are all useful. You do not need permission to open a pull request for a small fix.

Discuss larger desktop or agent integrations in an issue or [Discussion](https://github.com/31780/agent-progress/discussions) first; see the [roadmap](docs/ROADMAP.md). Dot and ChatGPT Work have an experimental reporting adapter; see [its limitations](docs/REPORTING.md). Automatic cloud lifecycle monitoring remains unsupported.

## Make your first contribution

1. Search existing issues and pull requests for related work. Look for `good first issue` or `help wanted` labels when available.
2. Fork the repository on GitHub, clone your fork, and create a topic branch from `master`:

   ```sh
   git clone https://github.com/YOUR-USERNAME/agent-progress.git
   cd agent-progress
   git remote add upstream https://github.com/31780/agent-progress.git
   git fetch upstream
   git switch -c describe-your-change upstream/master
   ```

3. Make one focused change. Explain the problem and add a regression test when behavior changes.
4. Run the relevant checks below, commit, and push your branch to your fork.
5. Open a pull request targeting `31780/agent-progress:master`. Describe the result and how you verified it. Draft pull requests are welcome when you would like early feedback.

If you need help, say where you got stuck. Documentation contributions do not require a working Omarchy installation. No separate contributor agreement, signed commits or special commit-message format is required. You retain authorship of your contribution and contribute under the [MIT license](LICENSE).

## Working locally

Use Python 3.11+ on Linux. No third-party Python packages are required:

```sh
python3 -m unittest discover -s tests -v
```

For changes to hook handling, also run `python3 tests/runtime_check.py` on a controlled Linux machine with Codex and the installed hooks already trusted. Validate QML with `omarchy plugin validate plugin` and an isolated preview or the installed shell. Keep test records separate using `OMARCHY_PROGRESS_STATE`. Never bypass hook trust or accept elevated commands in runtime tests. Close preview processes when finished so simulated states cannot be confused with live chats.

If you cannot run a platform-specific check, state that in the pull request so a maintainer can help verify it. Do not mark an unrun check as passing.

GitHub Actions runs the unit suite on Python 3.11 and 3.14 for pull requests. A first-time contributor's workflow may wait for a maintainer to approve running it; this does not mean the contribution was rejected. Workflows use read-only repository permissions and do not need repository secrets.

## Review and merging

`master` is the default, protected branch. All changes, including maintainer changes, go through pull requests. Both unit-test jobs must pass against the latest `master`, and review conversations must be resolved. Force-pushes and deletion of `master` are disabled; the rules also apply to administrators. Pull requests are squash-merged, and merged branches in this repository are automatically removed.

The current maintainer is [@31780](https://github.com/31780). Only maintainers can merge; contributors can use forks without repository write access. Since there is currently one maintainer, a second person's approval is not mandatory. Maintainers review outside contributions before merging, and should reconsider mandatory independent approval when more maintainers join.

Keep discussion focused on the proposed change. A maintainer may request changes, ask to narrow scope or explain why a proposal does not fit the current roadmap. Small fixes need no prior issue; larger proposals benefit from agreement before implementation. There is no promised response time.

## Bug reports and security

Use the [issue templates](https://github.com/31780/agent-progress/issues/new/choose). Include the affected OS/desktop, Codex version, expected behavior and sanitized reproduction steps. Do not attach raw transcripts, auth files, unredacted hook payloads or your state database.

For a suspected vulnerability, use [private security reporting](SECURITY.md) rather than a public issue. Please follow the [community guidelines](CODE_OF_CONDUCT.md) in all project spaces.

## Design rules

- Observe supported events; do not control agent permissions or parse private transcripts.
- Preserve unknown states. A missing event must not become a completion claim.
- Keep explicit milestones separate from lifecycle status.
- Preserve unrelated user hooks and settings; maintain a reversible installation path.
- Put OS-specific process checks, installation and UI behavior behind separate interfaces as the architecture evolves.
- Add coverage for meaningful state transitions and regressions, including concurrent events and late results.
