---
name: agent-progress
description: Report Dot or ChatGPT Work activity to Agent Progress when requested for a task or covered by the user's standing reporting preference. Use connected MCP tools or local access to the panel computer. Codex already uses lifecycle hooks.
---

# Agent Progress reporting

Use this skill when asked to show this task in Agent Progress, including a
user-authorized standing preference covering future Dot tasks. The user need not
repeat that preference for every task. Respect a later opt-out. Installation
alone does not establish a standing preference. This is an
experimental, best-effort reporting workflow, not an automatic lifecycle feed.
Report work you perform or coordinate, based on your own actions or explicit
results. Do not impersonate workers, infer their liveness, monitor unrelated
chats or send messages to other chats as part of this skill.

If connected **Agent Progress** tools `begin_report` and `update_report` are
available, use them. They work through a configured private tunnel without
desktop-control access. Add a fresh `request_id` UUID to each call; omit `action`
and choose the corresponding tool. Retain that UUID and the exact arguments for
an immediate retry only. Never retry requests after seven days. Follow the same
source, state and milestone rules below. Do not create a tunnel, expose a server,
forward credentials or change account permissions as part of reporting.

Otherwise run `scripts/report.py` from this skill directory with Python 3, passing a JSON
object on standard input. Use the tools connected to the **computer running the
panel**. The script fails if the panel is not installed there; never install or
run a replacement in a cloud container, forward credentials, or change app
permissions to make reporting work. Without connected reporting tools or local
access, explain that reporting is unavailable. Codex tasks use their existing hooks instead.

Begin with:

```json
{"action":"begin","source":"dot","session":"actual-chat-or-task-id","title":"Short non-sensitive task title"}
```

Use `source: "chatgpt"` for ChatGPT Work and `"dot"` for Dot. Identify the source
from the current product context, not the model name. If unavailable, ask rather
than guess. Prefer a task ID supplied by the host. When none is available, create
a UUID specifically for this report and retain it; never present it as a real
chat ID. Don't inspect private databases or transcripts to find identifiers.

If one Dot conversation handles several distinct tasks, use a distinct task ID
or retained reporter UUID for each work item, not one global Dot conversation
ID. Keep each task's `id`, `run` and `sequence` separate. Reuse its report while
that task continues; begin a new run only for genuinely new or resumed work.
Delegated agents report their own source identity when instructed and able;
Codex workers retain their existing hook reports.

The script returns an `id`, `run` and `sequence`. Retain those in task context.
Send subsequent updates using that exact ID and run token with increasing integer
sequences (1, 2, ...):

```json
{"action":"update","id":"RETURNED_ID","run":"RETURNED_RUN","sequence":1,"status":"working","milestone":{"done":1,"total":3}}
```

Update at meaningful work transitions, using only these statuses:

- `working`: you are actively working on this task.
- `waiting_input`: you have asked the user for information or a decision. This
  does not assert that the app has a pending approval.
- `ready_for_review`: your deliverable is ready for the user to review. This
  closes this report into History; it does not claim a lifecycle Stop event or
  verified completion. Start a new run with `begin` when genuinely resuming work.

Include milestones only for an explicit plan whose counts you can substantiate.
Omit `milestone` to preserve it; send `null` to clear it. Never estimate percentages.
Keep titles non-sensitive; do not send prompts, commands, response text, file
contents, credentials or free-form logs. Only the documented fields are accepted.

No report for three minutes becomes unknown. Don't schedule artificial refreshes,
claim interruption after losing contact, or keep reporting while waiting only to
hold a green status. An interruption may prevent the final report; that's expected.
If reporting fails, continue the user's task, explain the panel limitation briefly,
and don't retry in a loop. Never begin a fresh run merely to bypass a stale-update
error. Skill availability and local access vary by product and account.
