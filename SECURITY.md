# Security policy

Agent Progress is an early project. Security fixes target the latest code on `master`; older snapshots are not maintained separately. Supported operation is currently Omarchy/Linux.

## Report a vulnerability privately

Use GitHub's [Report a vulnerability](https://github.com/31780/agent-progress/security/advisories/new) form. This repository has private vulnerability reporting enabled. Please do not open a public issue with exploit details or exposed private information.

Include the affected revision, the impact, and the smallest safe reproduction you can provide. Use synthetic data. Do not send live credentials, private transcripts, unredacted hook payloads or your state database. If the private report form is unavailable, open a public issue asking for a private contact route without disclosing the vulnerability.

The maintainer will assess reports and coordinate fixes and disclosure through the private advisory. This volunteer project cannot promise a response deadline or a bounty. Test only systems and data you are authorized to use.

## Expected behavior

Observer hooks should never approve or deny an agent action, request continuation, or retain prompts, command bodies, tool output or assistant replies. Local titles and workspace paths are private data. Installation and removal must preserve unrelated hooks and desktop settings.

If a report concerns Codex, Omarchy or another dependency rather than this project's code, use that project's security reporting process.
