# Stu fleet mode and judgment seats

Status: design, not built. Base: the 0.2.2 line. Every decision below is settled; the open items
are the questions the nesting spike exists to answer.

## Outcome

The owner stops typing `/stu:run` and `/stu:settle` once per cycle. One coordinator session runs
several objectives, relaunches them when they stop, and brings the owner one brief per wave that
they answer in a line. The owner still rules on everything the settle skill reserves for the
owner.

## Why

Evidence is one project's coordinator sessions over roughly two weeks of daily use.

- On the heaviest day the owner opened 11 `/stu:settle` and 9 `/stu:run` sessions by hand. Most
  settle answers were one word.
- Coordinator sessions the same week made 25 dispatches on 8 prompts, and 7 on 1.
- That saving is real but overstated. The owner also chased two stalled runs, and on the one
  parked question walked through in detail, chose differently from the recommendation. Their
  delegations ("you can decide") came after they saw each batch; they were not standing.

So the cost to remove is the typing and the session-juggling, not the owner's judgment.

## Shape

| Layer | Runs as | Holds | Model |
|---|---|---|---|
| Coordinator (`/stu:fleet`) | the main session, interactive only | the fleet board | top model |
| Supervisor (`/stu:run`) | background subagent, one per objective (pending the spike) | the unit scoreboard | top model |
| Orchestrator | subagent of the supervisor | briefs and cycle state | existing table |
| Workers | subagents of the orchestrator | one brief, one diff | existing table |

The supervisor layer stays: it keeps cycle returns out of the coordinator, and
`design-rationale.md` already rejected moving that role into the main session.

**Fallback if the spike fails.** The coordinator launches each supervisor as its own top-level
headless session instead of a subagent, and reads only its board line and final return. The
program file, board, budget, merge hold and settle brief are unchanged.

## The nesting spike (before any fleet code)

The subagent-supervisor shape assumes harness behaviour that Stu's own docs call unreliable or
unobserved. One throwaway run, with a toy objective, answers these:

1. Does a subagent supervisor's deadline timer wake it, and can it re-arm one? The timer maximum
   is 2 hours against supervisors that ran 4 to 7.
2. At depth 3, where do completion notifications land: the supervisor, or the coordinator?
3. Does `ListAgents` from the coordinator show a supervisor's children, so an idle-tree check is
   possible?
4. Can a supervisor measure its own context? `scripts/ctx.py` picks the transcript by session ID
   and skips sidechain records, so `stu-ctx` would report the coordinator's context.
5. Does the turn guard find the right transcript for a nested agent?
6. What cache lifetime does a subagent supervisor get? The content lint forbids the 1-hour
   `cacheTtl` outside the orchestrator.

Output: a short findings section in `design-rationale.md`, and a go or no-go on the subagent
shape.

## The program file

`/stu:fleet <program path>`. Rules for every workstream live here once and are read by path.

```
# Fleet program: <name>
Owner: <name>
Max live lanes: <n>            (optional; overrides the config default)
Cycle budget: <n> | none      (optional; see "Budget")
Judgment jobs: <n> | none     (optional)
Stop at: <time> | none        (optional)
Settle mode: draft | auto-narrow

## Runs
- <slug>: <objective path> | after: <slug or none> | resources: <names>

## Judgment work
- <slug>: <groom | audit | design> | scope: <one line> | output: <path> | feeds: <run slug or none>

## Excluded (owned by peer sessions)
## Machine limits
## Fleet board        (coordinator writes)
## Merge hold         (anyone may set; every merge gate reads)
```

- The cycle cap stays in each objective, which owns it. A fleet objective with no `Cycle cap:`
  is a startup stop.
- `resources:` names what actually conflicts: worktrees, databases, simulators, device runners,
  and migration numbers.
- The cap counts lanes, not supervisors. An `overnight` supervisor with three lanes counts three.
- The lane cap is `fleet_max_lanes` in the Stu config, default 4, and a program may override it.
  It has no hard ceiling: a team on an unmetered plan, or a week with spare quota, raises it.
  The effective cap is the lower of the configured value and any concurrency limit the runtime
  itself reports. Resources still gate: two runs naming the same resource never run together,
  whatever the cap.

## The coordinator

It dispatches, watches liveness, relaunches, assembles the brief, and reports.

- **Board, on disk.** One line per run: state, cycles and launches spent, last handoff path,
  last stop condition. A fresh coordinator resumes from the file alone.
- **Budget.** See "Budget" below. A settle never resets it, and only the owner raises it.
- **Liveness.** A notification without the return schema is interim: one line, no action. A
  relaunch happens only after the deadline, an idle-tree check, and an explicit stop of the old
  supervisor. Never two supervisors on one unit list.
- **Relaunch without a settle** only for a self-stop on context or growth, or a cycle cap hit
  with units left. Everything else waits for the brief.
- **Stops that go straight to the owner**, never relaunched or settled around: conditions 4, 7,
  8, 9 and 11 of the run skill (non-convergence, a guard would have to be weakened, a command
  that failed twice, a wrong premise, missing durable state).
- **What it reads.** Board lines, return schemas, the verifier's verdict on each ruling, and the
  brief it sends. Not diffs, logs or reports; a fact it needs goes to a `stu:verifier`.
- **Handoff** to a fresh coordinator at 120k, at a wave boundary.
- **Coordinator death** is not detected by anything. The board makes resuming cheap; noticing is
  still the owner's. Stated here so it is not assumed away.
- **Main checkout.** Never written.

## Budget

### What was measured

Five coordinator sessions over two days, from the subagent transcripts: 30 run launches that
reached an orchestrator, 75 orchestrator cycles, 872 agents in all.

| Per orchestrator cycle | Low quartile | Median | High quartile | Max |
|---|---|---|---|---|
| Output tokens | 51k | 89k | 122k | 263k |
| Cache-read tokens | 6.8M | 13.1M | 16.7M | 40.3M |
| Agents | 6 | 9 | 11 | 18 |

- **Cycles are the unit of spend.** Cost per cycle varies about 2x around the median, with a
  tail to 3x. Nothing else Stu can count tracks spend as well.
- **Launches are not spend.** 12 of 30 launches ran a single cycle and together made 8.5% of run
  output. A launch that does nothing costs a skill load. A launch count is a loop guard only.
- **The supervisor layer is cheap.** Supervisors' own turns were 5.9% of run output.
- **Judgment work is a quarter of the total.** 60 audit, groom, settle and deploy jobs made 2.8M
  output tokens against 8.2M for the runs. A cycle budget alone misses it.
- **Scale.** One coordinator ran 8 to 26 cycles in a day. All five together ran 75.

Not measured: what a cycle costs as a share of a plan's weekly limit. Nothing in the transcripts
reports quota, the limit weighs models differently, and the top model has its own allowance.
Stu cannot read remaining quota today, so a budget stated as a percentage of the plan is not
buildable.

Model mix, checked against each dispatch: the sonnet seats that ran on opus were all explicit
escalations. 16 of 183 implementers and 5 of 115 reviewers ran on opus, and every one was
dispatched with `model: opus` and an `ESCALATION:` line, as the orchestrator's rules require.
11 of the 16 were in one run of money-handling fixes. So the routing table held; a cycle budget
should expect roughly one implementer in ten to escalate, more on high-stakes work.

What did leave the table: 2 orchestrators and 9 verifiers or reviewers ran on the top model, all
under coordinators told to use it freely. Also, 12 orchestrators were dispatched by a supervisor
with no `model` passed, which the run skill counts as a skipped check on cycle 2 or later; which
cycle each was has not been checked.

### What the budget is for

Four different needs, which an earlier draft folded into one number:

1. **A ceiling that survives settling.** The cycle cap is per run and a settle resets it. In an
   ordinary week something has to say "this fleet may spend this much, total".
2. **A loop guard.** A run that relaunches without closing anything.
3. **A deadline.** Three of the big sessions were the opposite of a ceiling: spare quota and a
   reset hours away. The constraint there is the clock and the machine, not tokens.
4. **A cap on the top-model allowance.** Judgment jobs draw on a separate, smaller pool.

A team with unmetered tokens needs only the loop guard.

### Design

Every limit is optional, and they are separate:

- **`Cycle budget: <n> | none`.** Counts every orchestrator cycle of every run. When absent, the
  default is the sum of the runs' own cycle caps: the fleet may spend what the objectives already
  authorise, once, and a settle reset cannot exceed it. `none` removes the ceiling.
- **Loop guard, always on.** A run with two consecutive launches that close no unit stops and
  goes in the brief. This replaces a launch count; it cannot be configured off.
- **`Judgment jobs: <n> | none`.** Counts groom, audit and design dispatches, continuations
  included. Settler drafts are not counted: they are small (10k to 30k output each) and bounded
  by the number of stops. Default `none`.
- **`Stop at: <time> | none`.** No new dispatch after this time; cycles in flight finish. For the
  spare-quota case, set this and `Cycle budget: none`, and raise the lane cap.
- **Paid API spend** stays where it is, as a dollar line in the objective that incurs it.

At 80% of any limit the coordinator says so once. At 100% it dispatches nothing new, lets cycles
in flight finish, and reports. It never raises a limit.

**The board records actuals** per run and for the fleet: cycles, launches, agents, output
tokens, and turns by seat and model, read from the transcripts by a script. That is what makes
the next budget a number chosen from evidence, and it shows the escalation rate and any seat
running off its routed model without a transcript dig.

Planning figures until there is more data: a cycle is about 90k output tokens and 9 agents; a
six-unit lane took 4 to 9 cycles; a full day of four lanes is 25 to 50 cycles.

## Settling

### Draft mode (default)

When a run stops with parked questions, a `stu:settler` drafts a ruling for each, with a
recommendation, a reversal line, and any deploy precondition. A `stu:verifier` checks each
drafted ruling against the project guide and the spec it touches. The coordinator batches them
into one brief per wave:

```
Run <slug>: 4 rulings drafted
1. <question in plain language> -> recommend <x>. Reverses if <y>.
2. ...
Answer: fine | reverse 2, 5 | talk about 3
```

On "fine" the settler writes the rulings and the run relaunches. Other runs keep moving while a
brief is open. This is the settle skill's existing skim-list shape, moved from one session per
objective to one brief per wave.

### Auto-narrow mode (opt-in per program)

The settler may apply a ruling without waiting only when all hold: the question is row 1 of the
park-or-decide table (the project's to decide); the verifier passed it; it amends no spec, public
API contract or project-guide rule; and it carries no deploy precondition. Everything else is
drafted for the brief as above.

### Always the owner's

- Rows 2 to 6 of park-or-decide: accounts and production, core semantics, visual calls,
  user-visible surfaces, dropped scope.
- Whether a question is a stop-condition-2 disagreement (two sources of truth the project guide
  says never to pick a side on). The settler flags the candidate and the owner rules. In the evidence, a settler
  reclassified two such questions away on its own; that is the failure this row prevents.
- Any reversal of an earlier ruling, including a settler's.
- Promoting an observation-ledger entry to an issue, unless the program opts in.

### Writes

- A settler ruling is marked as the settler's in `Rulings already given`, so a later reversal is
  detectable.
- `## Decisions reviewed` records only what the owner saw.
- The settler never edits the scoreboard, `Readied` entries or any field `stu-run-check` reads.
  Two settlers did this by hand to get past the checker.
- A ruling's deploy precondition is written to the merge hold, not to a notes file. One such
  note was missed and the change reached a deployed environment first.
- The coordinator, not the settler, writes `Run state:` for a supervisor found dead.

## Merge hold and lock

Stu serialises merges inside one supervisor. A fleet has several, merging into a base branch
that may deploy unpinned. In the evidence, a peer session's hold request reached one
orchestrator after two PRs were already armed.

- **Hold.** One file under the run home. Any session or the owner may set it with a reason.
  Every merge gate reads it immediately before labelling or merging and refuses while it is set.
- **Lock.** One merge-gate label or merge at a time across the fleet, by the same file.
- Both are read from disk at the gate, so they do not depend on a message reaching each layer.

## Judgment seats

A `judgment_model` key in the Stu config names the model. This adds a row to the routing table,
which is itself a check, so the row and its lint land together.

| Seat | Agent | Job | Ends in |
|---|---|---|---|
| Settler | `stu:settler` | Drafts rulings for one stopped objective | a ruling list for the brief |
| Groomer | `stu:groomer` | Turns an audit, epic or ledger batch into groomed issues and objectives | issue numbers, objective paths |
| Auditor | `stu:groomer`, `audit` scope | Tries to break a stated invariant | a report, filed issues, ledger entries |
| Designer | `stu:designer` | One decision-ready design round | an image set or spec, then stops |

Coordinator and supervisor do not get the judgment model; both are relays.

Context discipline, since nearly every agent in one wave of judgment work hit its context
ceiling in under 20 minutes: a scope it can finish; locating goes to `stu:scout` and claim checks
to `stu:verifier`; the report is written as it goes with a "not reached" list; each seat has a
turn-guard band. The groomer splits an oversized scope and returns the split for parallel
dispatch.

Cap fallback: when a judgment dispatch fails on a usage limit, groom, audit and design work
pauses and the coordinator tells the owner once. A settler falling back to a lower model may only
draft, never auto-apply. Nothing redeems a usage-limit reset on the owner's behalf.

Design rounds always end in something to look at and wait for the owner's verdict.

## Built for a second runtime

Codex support is not in the first build, but adding it must be a binding, not a refactor. Stu
already has the pattern: canonical skill text states the contract, `codex/runtime.md` binds it
to Codex operations, and the adapter renders canonical text live and fails closed on drift.
Fleet follows it from the first PR.

- **State and rules live in files and scripts, not in tool calls.** The program file, board,
  merge hold, budget accounting, loop guard and the relaunch decision are plain files plus one
  `stu-fleet` script (`board`, `spend`, `hold`, `next`). Both runtimes call the same script, so
  the logic exists once.
- **The skill names five operations and nothing runtime-specific outside them:** launch a
  supervisor, wait for a return, list a supervisor's live descendants, stop a supervisor, notify
  the owner. Everything else in `skills/fleet` is prose about files and schemas.
- **One "Runtime binding" section** maps those five to the Claude tools. Codex later adds its own
  five lines to `codex/runtime.md`. A content lint fails if a Claude tool name appears in the
  fleet skill outside that section.
- **The supervisor launch is already abstract** because of the spike fallback: "background
  subagent" and "separate headless session" are two bindings of the same operation. Codex is a
  third.
- **Seats are roles.** `judgment_model` is read through `stu-env`, per runtime, the way the
  deep-pass model is. No agent definition or skill names a model ID.
- **Returns are schemas.** Supervisor, settler and groomer returns are fixed field blocks, the
  same kind `stu-run-check` parses, so nothing depends on how a runtime delivers a message.
- **The lane cap already defers to the runtime's own slot limit**, which Codex has and Claude
  does not.
- Each unit's PR states, in `codex/runtime.md`, "fleet: not bound yet", so the Codex adapter's
  drift check stays honest rather than silent.

## Fixes that stand alone

1. **`stu-run-check` and ready-mode rows.** `allowed_fields` in `scripts/run_check.py` allows
   only `READY_IDS` for a label-handoff row under `completion: ready`. The run skill says a gate
   return's `LANDED: <sha>` counts for `MERGED_IDS` whatever its verdict, so a PR the merge actor
   lands before the gate returns `READY:` cannot close. `test_close_paths` in
   `scripts/run_check_test.py` asserts the rejection, so the fix changes that test, the closing
   table and its copy in the run skill.
2. **Stale-config startup stop.** The stop is shell text in the run skill's startup
   ("Stale config"), not `stu_env.py`. Every agent re-reads the on-disk file, so reading the base
   branch in the supervisor alone would split the config. The fix: when the on-disk file is
   strictly behind the base branch with no local edits, proceed with a one-line note; keep
   stopping when it is ahead or edited.
3. **Explicit cycle cap.** Covered by the program-file rule above; no change to plain runs.

## Build order

Each unit carries its own changelog entry, version bump, lint-list and test updates, and its
Codex note in the same PR.

| Unit | Change | Depends on |
|---|---|---|
| S1 | Fix 1: ready-mode `MERGED_IDS` | none |
| S2 | Fix 2: stale-config stop | none |
| S3 | Nesting spike and its findings section | none |
| S4 | Merge hold and lock file, read by the merge gate | none |
| S5 | `judgment_model` key, routing row, lint | none |
| S6 | Settle skill refactor: ruling provenance mark, settler-safe writes | none |
| S7 | `stu:settler` in draft mode, with ruling verification | S5, S6 |
| S8 | Supervised mode for `/stu:run`: return schema, own-context measurement, `agents/supervisor.md` | S3 |
| S9 | Fleet: program file, board, `stu-fleet` script, `fleet_max_lanes` key, runtime-binding lint | S8 |
| S10 | Fleet: liveness and relaunch, budget limits and loop guard, actuals on the board | S9 |
| S11 | Fleet: settle brief loop | S7, S10 |
| S12 | `stu:groomer` | S5 |
| S13 | `stu:designer` | S5 |
| S14 | Auto-narrow settle mode | S11, after a few weeks of draft-mode briefs |

S1, S2 and S4 help today's hand-run coordinators at once. S7 alone removes most settle sessions:
a coordinator can dispatch it by hand before any fleet code exists.

## Decisions

- A separate `/stu:fleet` skill, not a mode of `/stu:run`.
- Lane cap defaults to 4 and is configurable, with no hard ceiling.
- Budget defaults: cycle budget is the sum of the runs' caps, judgment jobs and stop-at default
  to none, the loop guard is always on.
- Settling is draft-first; auto-narrow is a per-program opt-in.
- Judgment seats run on a configurable `judgment_model`.
- No Codex support in the first build; designed so adding it is a binding, not a refactor.

## Not verified

- Everything the spike exists to answer.
- Which cycle each of the 12 model-less orchestrator dispatches was.
