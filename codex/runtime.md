# Stu runtime binding: Codex

This binding supplies runtime mechanics. The canonical contract rendered below owns the
objective, scoreboard, return schema, gates, money and data safety, and handoff requirements.
Read the whole rendered contract before acting. Logical names `stu:<role>` identify contracts,
not registered agent types. Follow project law via the resolved `PROJECT_GUIDE`.

Package root: `@STU_ROOT@`. Every shell invocation of a Stu helper, including in child
prompts, must explicitly carry `PATH=@STU_BIN@:$PATH STU_RUNTIME=codex`, plus
`STU_CONFIG=<CONFIG_PATH>` once resolved. Never assume plugin installation changes PATH.
Run helpers from the target repository's absolute cwd; use `git -C <absolute worktree>`.

Codex startup uses `stu-forge repo-settings --allow-unavailable-rules` for the known GitHub Free private-repository plan limitation.
The narrow, documented plan-403 response reports merge-queue capability as unknown, never disabled;
it does not establish that merge queues are off. Authentication, rate-limit and partial-data errors still stop
the run. No other API failure is suppressed and all ordinary startup checks still apply.

## Native dispatch and independent contexts

Use the tools actually exposed by the caller. Native V2 is `collaboration.spawn_agent`,
`collaboration.send_message`, `collaboration.followup_task`, `collaboration.list_agents`,
`collaboration.wait_agent`, and `collaboration.interrupt_agent`. A V1 surface may expose
`spawn_agent`, `send_message`, `resume_agent`, `list_agents`, `wait`, and `close_agent`
instead: inspect names and schemas, map their capabilities explicitly, and never invent a
missing capability. If nested dispatch, clean contexts, live descendant status, or safe
interruption cannot be established, stop with a concrete handoff instead of assuming support.

Generic Codex workers inherit the caller's permissions; role restrictions below are policy,
not a promise of a filesystem sandbox or blocked tools. Inspect actual available tools and
permissions. `Read`, `Grep`, `Glob`, `Write`, `Edit`, and `LSP` in shared prose describe
operations: use the caller's real file/search/image/language-server tools, or shell equivalents
when appropriate. If no language server is exposed, follow the contract's incomplete-search
fallback and label its evidence accordingly; never invent an LSP call.

Maintain supervisor -> orchestrator -> workers. The supervisor spawns an orchestrator; that
orchestrator spawns its workers, records their returned IDs, and receives their reports.
Set `task_name` explicitly to `stu_<role>` with hyphens converted to underscores, optionally
suffixed `_cycle_<n>` (for example `stu_orchestrator_cycle_2`, `stu_implementer`). Use a
new suffix for each new dispatch of a role, including different units or review rounds within
one supervisor cycle, so task names stay unique. Never reuse a completed reviewer for a new
review that requires a fresh context. This lets the advisory usage hook identify the seat. Respect the live concurrency slot cap, including
supervisor and orchestrators; sequence workers when necessary and never bypass the limit by
running another untracked session. Always request a fresh context with `fork_turns: "none"` when that field is supported.
On a V1 surface whose default is a fresh context, omit history inheritance explicitly; if its
semantics cannot be verified, hand off. No worker inherits the author's review context.

Each dispatch prompt carries: the logical role, repo row, absolute worktree/objective/brief/
handoff/report paths as applicable, `STU_CONFIG=<CONFIG_PATH>`, and this exact startup action
with the intended role substituted:

```
PATH=@STU_BIN@:$PATH STU_RUNTIME=codex STU_CONFIG=<CONFIG_PATH> @STU_HELPER@ contract <role>
```

The fresh worker must run that helper, read the complete output, and follow its role contract.
The parent must supply all applicable inputs: a contract selector alone is not a brief.
A reviewer is always an independent fresh worker, receives the exact SHA captured with the
diff, and reads its own detached checkout of that SHA. Never infer reviewed SHA from HEAD.

## Models and effort

Use only model IDs and reasoning settings explicitly available in the caller's live tool
metadata. `STU_CODEX_MODEL` optionally selects the driver model; `STU_CODEX_SCOUT_MODEL`
optionally selects the locator model. Validate configured IDs against that live inventory
before dispatch; an unavailable configured ID is a stop with the unsupported value reported.
Without a configured ID, use the caller's supported inherited/default model; do not guess a
model name. Select low effort for pure location, medium for ordinary bounded implementation,
and high for orchestration, independent review and load-bearing verification when supported.
Record the selected model/default and effort. Unsupported effort values are omitted with a
note, never sent speculatively. Escalation still requires a canonical numbered condition and
the literal `ESCALATION: condition <n> — <specific>` line, and increments `Model overrides`;
choose only among caller-supported models/efforts. Price-based deep-pass selection applies
only with current verified prices and available IDs; no provider-specific config value is
silently treated as a Codex model. A named role never implies model metadata or hard limits.

## Waiting, liveness and budgets

Use bounded `collaboration.wait_agent` (at most 60 seconds per call) and inspect
`collaboration.list_agents` when a wait returns, a status is requested, or a deadline is due.
Use the available clock tool or a foreground timestamp command. Persist each dispatch's
start, next 90-minute check, first check, repair-used state, repair deadline and restart count
in the objective's runtime state; preserve the canonical scoreboard fields. Repeated bounded
waits keep control available; do useful independent work between returns when possible.
A parent's completed status is never enough while a descendant is live. Inspect the entire
known tree. Unknown descendant state is not idle and never authorizes a second writer.

At each dispatch's 90-minute deadline, inspect the tree. With live work, advance its check by
90 minutes, up to the canonical bound of six hours from its first liveness check. With no
schema and idle work, or past that overall bound, spend the cycle's single repair using the
observed state; use `followup_task` to activate an idle orchestrator and `send_message` for a
running one. Give that repair one final 90-minute deadline. No accepted schema by then means
BLOCKED and a persisted handoff, never an unbounded wait. A repair already spent means no
second repair. Restart once per lane only after the canonical quiescence checks establish no
live children; interrupt the old orchestrator before spawning the successor. If safe shutdown
cannot be confirmed, park the lane and preserve ownership; do not start a second writer.
Only the current orchestrator's schema is its return. Nested worker reports belong to their
parent and never advance the supervisor's scoreboard. Do not build notification relay loops.

Run long shell commands with `exec_command`. If it yields a session ID, retain it and collect
completion with bounded `write_stdin` calls. An exit code alone is not a CI verdict; preserve
`stu-ci-wait`'s terminal line contract. Do not finish a role while its shell session or children
still own work; resolve them or make an explicit tracked handoff under the deadline rules.

The canonical context and turn bands remain handoff policy. Codex does not obtain hard agent
limits or cache guarantees from another runtime's frontmatter. Check `stu-ctx` on returns;
Codex usage hooks, when installed, are advisory. Unknown, failed or unparseable context usage
is hard-exceeded: stop new dispatch, collect in-flight returns under bounded deadlines, write
a handoff and stop. Never claim a hook enforces a budget if this session has no such hook.
