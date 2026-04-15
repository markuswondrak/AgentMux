## Submitting Your Architecture

Write `02_architecting/architecture.md` as a Markdown document describing your technical design, then call `mcp__agentmux__submit_architecture()` to signal completion.

The document is free-form Markdown — include whatever sections are appropriate (Solution Overview, Components, Interfaces, Data Models, Technology Choices, Risks, etc.).

After writing the file, call `mcp__agentmux__submit_architecture()` to signal completion.

### Reviewer Nomination

Optionally, you can nominate which reviewer roles should evaluate the implementation.
Pass the `reviewers` argument with a list of one or more of these values:

| Role | Purpose |
|---|---|
| `reviewer_logic` | Checks alignment to plan and functional correctness |
| `reviewer_quality` | Checks code quality, style, and maintainability |
| `reviewer_expert` | Checks security, performance, and edge cases |

Example: `mcp__agentmux__submit_architecture(reviewers=["reviewer_logic", "reviewer_expert"])`

If you omit `reviewers` or pass an empty list, only `reviewer_logic` will run by default.
