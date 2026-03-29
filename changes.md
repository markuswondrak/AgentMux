019e059 Merge pull request #66 from markuswondrak/feature/make-file-references-in-monitor-clickable
ef35b09 Add OSC 8 terminal hyperlinks to monitor file reference log entries for IDE Ctrl-click support
d89ef37 tweak product manager prompt
9211354 reworked colors
9c34c82 Merge pull request #65 from markuswondrak/feature/claude-research-mcp-not-working
418ff85 Fix Claude MCP research availability by passing --mcp-config at runtime and making persistent config setup idempotent
21cc1a3 Use dodger blue instead of magenta as logo secondary color
e8c9648 Merge pull request #63 from markuswondrak/feature/optimize-prompts-and-commands
275af90 feat: aktuell arbeiten die prompts die an die agenten geschickt... (#49)
fcf4c75 added headroom as context compresion
1993b65 Merge pull request #62 from markuswondrak/feature/add-onboarding-guide-for-new-users
d183787 Add Getting Started guide and link it from README
1f56848 Merge pull request #61 from markuswondrak/feature/add-welcome-and-goodbye-screen
fbcdde6 fix test
84ca657 tweak output
8fdcde8 tweak output
fc8b1f5 remove welcome screen
385233d fix rendering
203bec4 feat: add welcome and goodbye terminal screens with completion summary persistence
0f51271 Merge pull request #58 from markuswondrak/feature/enable-multiple-tmux-sessions
980314e feat: derive unique tmux session names from feature directory, enabling multiple concurrent agentmux sessions
1ebcf8e Merge pull request #56 from markuswondrak/feature/completing-phase-should-draft-a-commit-message-i
ec7d388 Remove legacy compatibility paths
181db28 feat: I dont like the changes in this branch:
5f17775 feat: completing phase should draft a commit message instead as... (#54)
4ea32d7 Merge pull request #55 from markuswondrak/feature/remove-docs-agent
439f811 Remove docs agent flow and fold docs work into implementation/review
15a2e2c Merge pull request #52 from markuswondrak/feature/tweak-coder-prompt
43422b7 Unify prompt placeholder syntax and tighten coder workflow contract
a2e23b4 fix agent pane kill was misinterpreted
f09ee36 Merge pull request #48 from markuswondrak/feature/human-review-after-completion-should-be-added-to
ccc505b fix launcher exit to ignore feature directory
7ee39c7 Centralize preference-memory guidance via shared prompt fragments
ae04094 fix failed merge error
b210bcf Refine architect/designer prompts and add designer prompt regression coverage
b263ea1 Merge pull request #44 from markuswondrak/feature/tweak-architect-prompt
d58fc72 Fix monitor import regression in tests
ce13547 Use structured agent labels in pane titles
08b22e8 Merge main into feature/tweak-architect-prompt and resolve conflicts
8b54325 Hide completed coder panes during implementation
38818ed Implement staged execution planning contract and monitor progress rendering
4d152bb Merge pull request #43 from markuswondrak/refactor-pipeline-components
780d155 Reorganize AgentMux into component packages
3d5758b Refactor pipeline into cohesive components
156b4b2 Merge pull request #41 from markuswondrak/feature/at-cancel-error-show-an-error-message
407d72b Add event bus and pane interruption handling
84e3141 Unify interruption/failure event handling and recovery messaging
edcb807 Merge pull request #38 from markuswondrak/feature/let-architect-decide-when-documentation-update-i
59246cc Let architect declare docs requirements
ac821ef Merge pull request #37 from markuswondrak/feature/product-manager-must-require-ui-design
c2da4c0 Require product manager to hand off UI design to designer agent
d5af54b Merge pull request #36 from markuswondrak/feature/change-session-directory-in-agentmux-folder
5481c77 Stop tracking .claude settings
13d1a5e Move pipeline session storage to .agentmux/.sessions
ce49658 Fix formatting of the project description in README
01c44d2 Add CI badge to README
3b586ff Merge pull request #34 from markuswondrak/feature/add-github-actions-ci-test-runs-on-push
fc363bd remove toml dependency
44b624b Merge origin/main into feature/add-github-actions-ci-test-runs-on-push
efa09c1 Fix CI test regressions
7d745dd Merge pull request #31 from markuswondrak/feature/add-files-to-logs
168e889 Show handover file events in monitor log
3cf90dd Add GitHub Actions CI to run tests on push and pull requests
d767008 Extract session file event handling
b24d20e Add session created-files logging via pipeline event dispatcher
1ca9c22 Merge pull request #28 from markuswondrak/feature/coder-prompt-must-include-relevant-research-file
0959b47 Include completed research handoff references in coder prompts
6a6c519 Merge pull request #26 from markuswondrak/feature/name-folder-with-phase-number
67f59e6 Name phase folders with phase numbers
5beaaea Merge pull request #24 from markuswondrak/feature/provide-researcher-agents-as-mcp-tools
f570ae6 fix monitor width
a3f8cc5 reworked research mcp servers
9320b5b Expose research dispatch as MCP tools for architect and product-manager
5d17d41 Merge pull request #22 from markuswondrak/feature/kill-product-manager-pane-when-phase-is-inactive
20d594a Kill single-use product-manager/docs panes when phase is inactive
29fe57b Merge remote-tracking branch 'origin/main' into feature/content-pane-broken
1b0eb27 redesigned monitor interface
4e3637d Merge pull request #19 from markuswondrak/feature/project-init
3fd2493 Delete logo.md
7196790 added logo to monitor
aa359b1 refactor content pane
99c800a fix logo
ed13c74 Add agentmux init command for project scaffolding
6eb2180 update README
dcfc61d Merge pull request #17 from markuswondrak/feature/make-system-installable-pip-setup
e6d7f00 Make system installable as pip package (agentmux)
22a9ef5 Merge branch 'main' of github.com:markuswondrak/AgentMux
7ca368e Pull latest main at startup and return to main after PR creation
7a0103a Merge pull request #14 from markuswondrak/feature/support-project-specific-agent-descriptions
beb82ce Add project-specific agent prompt extensions and early branch creation
80abea4 update readme
7847455 Add GitHub integration: --issue flag and post-completion PR creation
b9fa278 Merge branch 'main' of github.com:markuswondrak/AgentMux
4de6fa2 refactor config
ecfc8fd Kill coder panes when review passes
135597e Add image and enhance README formatting
cfa666e Fix formatting and capitalization in README.md
a64e473 added README
f44bd8f tweak context
0c322f3 add optional product-manager agent phase before planning
9a31254 tweak coder prompt
c49ebb6 add dedicated reviewer agent, architect shutdown, monitor filtering, and pane titles
fc3e89e send file references instead of full prompt text to agent panes
f482cca tweak architect research capabilities
2186ed1 organize feature directory files into phase subdirectories
7992b4c improve monitor display: hide optional phases, humanize events, add documents section
441c777 fix monitor
84cf39f hide researcher panes, batch-dispatch parallel, show per-topic status in monitor
