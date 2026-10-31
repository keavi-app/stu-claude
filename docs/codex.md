# Stu on Codex

Stu keeps one set of safety contracts and helpers for Claude Code and local Codex.
The Claude package remains in `.claude-plugin/`, `skills/`, `agents/`, and
`hooks/hooks.json`. Codex selects its own skill wrappers and hooks through
`.codex-plugin/plugin.json`. There is no MCP server or additional service to run.

## Install

Requires local Codex with plugin skills, native nested subagents and command hooks,
Python 3.9+, git 2.31+, bash, and authenticated `gh` for GitHub work. macOS, Linux,
and WSL are supported. Initial integration testing uses Codex CLI 0.166.0; other
clients and older versions must pass the same capability checks before a run.

From a checkout containing Codex support:

```sh
codex plugin marketplace add /absolute/path/to/stu-claude
codex plugin add stu@keavi
```

After the change is released on the repository's default branch, use the GitHub
source instead:

```sh
codex plugin marketplace add keavi-app/stu-claude
codex plugin add stu@keavi
```

Start a new Codex session. Review and trust Stu's two hooks through `/hooks` before
running it. Installing/enabling a plugin does not trust its hooks. Review new hook
versions again when Codex requests it; do not bypass trust as a normal setup step.

Use `$stu:init` to configure a repository, `$stu:run` to start or resume work,
`$stu:settle` to answer parked questions, and `$stu:fix-campaign` for issue triage.
For example:

```text
$stu:run "Fix issue #123, with independent review and the configured merge gate"
```

The wrapper resolves its installed package root from its own skill path. Helpers
are called with absolute paths and an explicit PATH/runtime environment; a Codex
install does not need to add `bin/` to your shell profile. For diagnostics, run
`/absolute/installed/plugin/bin/stu-codex doctor`. It reports dependencies and
telemetry, but cannot certify native agent availability or persisted hook trust.

## Existing configurations and approval

Codex reuses `<main checkout>/.claude/stu.md` and `~/.stu/<project>/stu.md`.
New Codex configurations may use `<main checkout>/.stu/stu.md`. Set `STU_CONFIG`
to use a particular file. If both local configurations exist at different paths,
Codex requires an explicit selection rather than silently creating two policies.
Claude keeps its existing lookup order. Use one shared config for a shared run;
claims, objectives, handoffs and approvals remain compatible across runtimes.
Explicit `guide:` is respected; otherwise Codex prefers `AGENTS.md` when present.

For public or `before-push` repositories, setup still offers installation of
`stu-pre-push` and runs only after the owner accepts. The git hook enforces exact
commit approval and scans public pushes for configured private names. Both Claude
and Codex process markers trigger agent-only approval checks. Markers can be
stripped, so they are a cooperative guardrail rather than an identity boundary.

The tool hook protects the approval file, rejects supported hook bypasses, and
checks supported forge publishing calls. It understands Codex patch targets,
including moves and symlink aliases. An owner approves from their own terminal:

```sh
STU_CONFIG=/absolute/path/to/stu.md /absolute/installed/plugin/bin/stu-approve '<unit-id>' '<full-sha>'
```

The agent must never execute that command or write approvals itself. Shell editing
and tool paths outside hook coverage remain known limits; use operating-system or
forge permissions for adversarial security requirements.

## Runtime differences

The supervisor still holds unit IDs and paths. It dispatches a fresh orchestrator,
which dispatches fresh implementers, reviewers and gates. The source contracts
remain in `skills/` and `agents/`; `stu-codex contract <role>` renders them with
Codex dispatch, waiting, model selection and helper paths. Changed runtime sections
fail closed until the adapter is updated. Shared policy changes render live.

Codex role names are logical procedures, not automatically registered Claude
agents. Workers load their own rendered role in a clean context. Native tool
names and available models are inspected in the active session. Optional
`STU_CODEX_MODEL` and `STU_CODEX_SCOUT_MODEL` select supported driver/locator IDs;
unavailable configured models stop the run. Without an override the caller's
supported inherited/default model is used. Slot limits can serialize workers.
Read-only roles are behavioral policy, not separate Codex permission sandboxes.
Reviewers still use independent detached checkouts of the named commit.

`stu-ctx` reads the exact current Codex session's usage, never the newest session
by modification time. Cached input is already included in Codex input tokens.
The parser targets observed rollout JSONL; that format is not a stable API.
Missing, ambiguous or malformed supervisor telemetry is a hard handoff condition.
Ephemeral sessions without a persisted transcript cannot supply this meter.

The separate Codex budget hook verifies child identity, a Stu seat name and a live
configured run before warning. It skips ambiguous attribution, including a parent
transcript; it never silently charges the supervisor's usage to a worker. These
warnings are advisory. Claude's native `maxTurns` and cache-TTL settings do not
create equivalent guarantees on Codex. The startup settings read explicitly allows a recognized GitHub Free private-repository
rules capability error to report `merge_queue unknown`, never `off`. Authentication, rate
limits and partial-data errors still stop startup; the default Claude settings command is
unchanged.

Source context bands remain conservative
handoff thresholds until longer Codex runs provide calibration evidence.

## Distribution and maintenance

Keep the full Claude package at the repository root for Anthropic directory
submission. The Codex manifest explicitly selects `codex/skills/` and
`codex/hooks.json`; Claude's manifest and default hook discovery are unchanged.
Adding Codex files does not itself establish directory approval: validation,
security scanning and policy review still apply.

OpenAI currently excludes hook-containing plugins from its public directory, so
this version uses repository distribution on Codex. Do not strip safety hooks to
obtain a directory listing. Official references:

- [OpenAI plugin packaging](https://developers.openai.com/plugins/build/plugins)
- [Codex lifecycle hooks](https://learn.chatgpt.com/docs/hooks)
- [Anthropic directory checklist](https://claude.com/docs/plugins/pre-submission-checklist)

Run `make test` after changes. It exercises both adapters and the shared suites.
Validate Claude packaging with `claude plugin validate /absolute/path/to/stu-claude --strict`.
The [validation record](codex-validation.md) describes the tested clients and native run.
For Codex packaging, install from a local marketplace and start a fresh session;
the real loader and a bounded run are the integration check.
