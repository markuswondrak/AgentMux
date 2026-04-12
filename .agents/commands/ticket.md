---
description: Create a GitHub issue using the repository's issue templates
---

Help me create a GitHub issue for this repository using the official issue templates.

First, determine the issue type. If $ARGUMENTS is provided, use it directly. Otherwise, ask me which type of ticket to create:
- **bug** — Something isn't working as expected
- **feature** — Suggest an improvement or new capability

Current version: !`agentmux --version 2>/dev/null || echo "unknown"`

Recent commits for context:
!`git log --oneline -10`

---

If creating a **bug report**, gather these fields from me:
1. **Agentmux version** (pre-filled above if available)
2. **Provider(s)** — which providers are affected (claude, codex, gemini, opencode)
3. **OS / shell** — e.g. "Ubuntu 24.04 / zsh"
4. **What happened?** — description of the issue, including the command run and what went wrong
5. **What did you expect?** — expected behavior
6. **Steps to reproduce** — numbered steps
7. **Relevant logs or files** — content from state.json, created_files.log, or terminal output

If creating a **feature request**, gather these fields from me:
1. **What problem does this solve?** — the pain point or gap
2. **Proposed solution** — what should agentmux do differently
3. **Area** — one of: Workflow/state machine, Configuration, Init wizard, Resume, Providers/MCP, Monitor/UI, CLI/completions, Other

---

Once you have all the information, format the issue body matching the template structure and create it using:

```bash
gh issue create --title "<descriptive title>" --label "<bug or enhancement>" --body "<formatted body>"
```

For bug reports, use label `bug`. For feature requests, use label `enhancement`.

After creation, show me the issue URL and a summary of what was submitted.
