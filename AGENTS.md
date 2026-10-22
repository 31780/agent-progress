# Project instructions

This project builds the Omarchy Codex progress widget. Keep DOT and ChatGPT integrations out of scope until Codex behavior is established.

- Follow the Omarchy skill for desktop customization. Never edit `/usr/share/omarchy/`.
- Keep source here, install into user-owned directories, and preserve unrelated hooks and bar settings.
- Hooks observe only. Never return permission decisions, continuation requests, or inferred task completion.
- Use supported hook payloads and metadata APIs; do not parse private transcripts or mutate Codex databases.
- Keep unknown work indeterminate. Milestones must come from explicit agent reports, never invented percentages.
- Treat interruption, response finish, stale observations, and process disappearance as different states.
- Keep test state isolated. Do not bypass hook trust or accept elevated commands in runtime tests.
- Run relevant unit tests for state/preservation changes and the local runtime fixture when event handling changes. Validate QML in the installed shell or an isolated Quickshell preview.
- Use work/ for scratch files and outputs/ for the source bundle, verification report and preview.
