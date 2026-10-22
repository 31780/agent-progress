# Project instructions

This project builds Agent Progress, starting with Codex on Omarchy. Codex lifecycle monitoring is established; Dot and ChatGPT Work may use explicitly labeled experimental reports with local computer access. Automatic personal-account cloud monitoring remains unsupported.

- Follow the Omarchy skill for desktop customization. Never edit `/usr/share/omarchy/`.
- Keep source here, install into user-owned directories, and preserve unrelated hooks and bar settings.
- Hooks observe only. Never return permission decisions, continuation requests, or inferred task completion.
- Use supported hook payloads and metadata APIs; do not parse private transcripts or mutate Codex databases.
- Keep unknown work indeterminate. Milestones must come from explicit agent reports, never invented percentages.
- Keep reported states distinct from lifecycle observations. No silent updates, guessed approval waits, or claims of cloud liveness. Preserve source identity and reject stale report runs.
- Treat interruption, response finish, stale observations, and process disappearance as different states.
- Keep test state isolated. Do not bypass hook trust or accept elevated commands in runtime tests.
- Run relevant unit tests for state/preservation changes and the local runtime fixture when event handling changes. Validate QML in the installed shell or an isolated Quickshell preview.
- Use work/ for scratch files and outputs/ for the source bundle, verification report and preview.
- Make changes on a topic branch and open a pull request targeting protected `master`. Preserve branch protections; never bypass required checks or push directly to `master`.
