# Stu fleet mode and judgment seats

Status: design, partly built (S1 to S11). Base: the 0.2.2 line. The owner's decisions are listed
under "Decisions". The nesting spike (S3) chose subagent supervisors, with two binding changes for
S8; findings in `design-rationale.md`, "Fleet nesting spike".

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
| Coordinator (`/stu:fleet`) | the main session, interactive only | the fleet board | the run skill's supervisor model |
| Supervisor (`/stu:run`) | background subagent, one per objective (spike: go) | the unit scoreboard | unchanged |
| Orchestrator | subagent of the supervisor | briefs and cycle state | existing table |
| Workers | subagents of the orchestrator | one brief, one diff | existing table |

The supervisor layer stays rather than folding into the coordinator: it keeps every cycle return
out of the coordinator's context, which is what lets one coordinator hold several runs.

**Fallback if the spike had failed** (it did not: see "The nesting spike"; kept as the binding for a runtime without nested agents). The coordinator launches each supervisor as its own top-level
headless session instead of a subagent, and reads only its board line and final return. The
program file, board, budget, merge hold and settle brief are unchanged. Three operations change
binding, and one rule weakens:

- **Wait** is the process exiting or its return file appearing, not a completion notification.
- **List live descendants** is not available: the coordinator cannot see a headless session's
  subagents. Liveness becomes the session's process plus the age of its transcript's last write.
- **Stop** is a signal to the session's process.
- **The idle-tree check before a relaunch** becomes "process gone, or process alive with no
  transcript write for longer than the deadline, then stopped". That is weaker: a supervisor
  waiting quietly on a long child looks the same as a hung one. So in the fallback, a relaunch on
  the quiet rule goes in the brief instead of happening on its own.

## The nesting spike (done: S3, go)

Answered 2026-11-12; findings in `design-rationale.md`, "Fleet nesting spike". The questions as posed:

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
Merge lock: on | off          (optional; default on, see "Merge hold and lock")

## Runs
- <slug>: <objective path> | after: <slug or none> | resources: <names> [| lanes: <n>]

## Judgment work
- <slug>: <groom | audit | design> | scope: <one line> | output: <path> | feeds: <run slug or none>

## Excluded (owned by peer sessions)
## Machine limits
## Fleet board        (coordinator writes)
```

The merge hold is not a section of this file; it lives in its own file (see "Merge hold and
lock"), so a merge gate that has no program path can still read it.

- The program's `Merge lock:` line is checked against the Stu config's `merge_lock` at startup and
  never overrides it: a gate reads only the config, so a disagreement stops the coordinator rather
  than being ignored. The line defaults to on while the config key defaults to off.
- The cycle cap stays in each objective, which owns it. A fleet objective with no `Cycle cap:`
  is a startup stop.
- `resources:` names what actually conflicts: worktrees, databases, simulators, device runners,
  and migration numbers.
- The cap counts lanes, not supervisors. An `overnight` supervisor with three lanes counts three.
- `| lanes: <n>` on a Runs line declares the run's lanes (positive integer). A run's lane count is
  the larger of the declared number, the objective's counted `Lane:` headings, and 1, so an
  overnight objective that has not written its lane blocks yet cannot make `next` over-start.
  `program check` blocks an objective whose header says `Mode: overnight` without it, and a
  `plain` objective that declares anything but 1. Lanes are declared in the program, never in
  the objective. `fleet` is reserved as a run slug.
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
- **Relaunch without a settle** only for a self-stop on context or growth (condition 6, or a
  `self-stop:` lane), or a cycle cap hit with units left (condition 10). Today's count rule does
  not fit the cap-hit case: a clean cap hit ends `settled <date> — nothing to settle`, and Resume
  continues the count, so a relaunch would start exhausted. Supervised mode (S8) therefore adds one
  explicit rule: a relaunch by the coordinator writes `Run state: fleet-relaunch <date>`, and a
  run resuming from that state starts at `0/<cap>`. The objective's cap becomes per launch, and the
  fleet's cycle budget bounds the total. The coordinator never edits an objective's cap. With no
  cycle budget room left, a cap hit goes in the brief. Under the default budget (the sum of the
  runs' caps), the only room a cap-hit relaunch has is cycles other runs left unspent; a program
  that wants cap-hit relaunches as a matter of course sets a larger budget or `none`.
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
11 of the 16 were in one run. So the routing table held; a cycle budget should expect roughly
one implementer in ten to escalate, more on high-stakes work.

What did leave the table: 2 orchestrators and 9 verifiers or reviewers ran on the top model, all
under coordinators told to use it freely. Also, 12 orchestrators were dispatched by a supervisor
with no `model` passed, which the run skill counts as a skipped check on cycle 2 or later; which
cycle each was has not been checked.

### What the budget is for

Four different needs:

1. **A ceiling that survives settling.** The cycle cap is per run and a settle resets it. In an
   ordinary week something has to say "this fleet may spend this much, total".
2. **A loop guard.** A run that relaunches without closing anything.
3. **A deadline.** Three of the big sessions were the opposite of a ceiling: spare quota and a
   reset hours away. The constraint there is the clock and the machine, not tokens.
4. **A cap on the top-model allowance.** Judgment jobs draw on a separate, smaller pool. Stu
   cannot read that pool, so the judgment-jobs count below is the proxy for it.

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
six-unit lane took 4 to 9 cycles, so one pass of four lanes is 16 to 36 cycles. The busiest
single coordinator ran 26 in a day.

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

`stu-fleet` holds the state this needs, so the coordinator edits no scoreboard. `board draft`
records the settler's drafted return against a `settle` run (`next` then says `brief <slug>`);
`brief` prints every recorded draft as one block, hiding items already written; `answer` splits
the owner's reply into per-run segments and checks the item numbers; the settler's write mode
returns a `WRITTEN` block and `board settled` applies it: it moves `unpark` and `drop` units on
the scoreboard, refuses an `add` (new units need the interactive `/stu:settle`), writes `Run
state:`, and requeues the run once no question is unanswered. A partial answer leaves the run in
`settle` with its draft, and `next` asks for the brief again. Between those calls the ids already
named by `unpark` and `drop` live in the sidecar `<program>.settle.json`, cleared when the draft is
replaced or the settle finishes.

### Auto-narrow mode (opt-in per program)

The settler may apply a ruling without waiting only when all hold: the question is row 7 of the
park-or-decide table ("anything else": implementation approach, wording inside an approved
surface, order of work), which the settle skill already decides without asking; the verifier
passed it; it amends no spec, public
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

One file under the run home holds both, so a gate with no program path can read it. Both are read
from disk at the gate, so they do not depend on a message reaching each layer.

- **One writer at a time.** Every change to the file (setting or clearing the hold, taking or
  releasing the lock) happens under an exclusive file lock held by `stu-fleet`, so the reads and
  writes below are ordered, never interleaved.
- **Hold.** Any session or the owner sets it with a reason, through `stu-fleet hold`. A gate
  refuses while it is set.
- **Lock.** One PR at a time between label and landing, across the fleet. Before it labels or
  merges, a gate asks `stu-fleet` for the lock. In one locked step `stu-fleet` refuses if the hold
  is set or the lock is held, and otherwise records the PR, head SHA and time as the lock holder.
  The gate labels only after that step succeeds. This serialises landings, not just labelling, and
  it closes the race between reading the hold and labelling: a hold set after the lock is taken
  finds that PR recorded as the holder.
- **Disarm on hold.** Refusing new labels does not stop a PR already armed: under label-handoff
  the gate labels and an auto-merge actor merges later. Setting the hold returns the lock
  holder, if any, as the one PR to disarm. Disarming is not reimplemented in `stu-fleet`: the
  coordinator dispatches a `stu:merge-gate` in a new revoke-only mode for that PR, which runs the
  gate's existing "Revoke a claim" sequence (stop the daemon if it is acting, then
  `stu-forge disarm`). A peer session that sets the hold without a coordinator gets the PR number
  back and is told to dispatch the same revoke. Releasing the hold re-arms nothing: the PR goes
  back through a fresh gate dispatch at its current head. A PR that lands before the revoke is
  recorded as landed-during-hold, never hidden.
- **Release.** Under `completion: merged` the gate's landing confirmation releases the lock.
  Under `completion: ready` no later gate confirms a landing, so release is by observation: before
  taking the lock, any gate, and `stu-fleet next` on every coordinator wake, checks the holder on
  the forge and releases it when the PR has merged or closed, or its label is gone. Landing
  throughput is then one PR per auto-merge cycle plus the gap until the next gate or coordinator
  wake notices. That is the price of serialising landings into a base branch that deploys
  unpinned; a program whose base does not deploy on merge may turn the lock off.
- **With the lock off**, the hold still makes every gate refuse to label or merge, but no armed
  PR is recorded, so setting the hold disarms nothing: a PR labelled before the hold may still
  land. A program that needs a hold to stop armed PRs keeps the lock on.
- **Stale lock.** A lock older than the run deadline with its PR still open and labelled goes in
  the brief; nothing clears that one on its own.

## Judgment seats

A `judgment_model` key in the Stu config names the model. This adds a row to the routing table,
which is itself a check, so the row and its lint land together.

| Seat | Agent | Job | Ends in |
|---|---|---|---|
| Settler | `stu:settler` | Drafts rulings for one stopped objective | a ruling list for the brief |
| Groomer | `stu:groomer` | Turns an audit, epic or ledger batch into groomed issues and objectives | issue numbers, objective paths |
| Auditor | `stu:groomer`, `audit` scope | Tries to break a stated invariant | a report, filed issues, ledger entries |
| Designer | `stu:designer` | One decision-ready design round | an image set or spec, then stops |

Coordinator and supervisor do not read `judgment_model`; both are relays and keep the model the
run skill already gives the supervisor, even when the two keys name the same model.

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
- **The skill names seven operations and nothing runtime-specific outside them:**
  1. launch a supervisor;
  2. dispatch a seat agent (settler, verifier, groomer, designer, scout) with a model;
  3. wait for a return or a deadline, whichever comes first, and re-arm the deadline;
  4. list a supervisor's live descendants (in the subagent shape, the descendant-tree script, since `ListAgents` is not available inside a subagent; absent in the headless fallback; see "Shape");
  5. stop a supervisor;
  6. send the owner a brief and receive their one-line answer;
  7. notify the owner one-way (a limit reached, a stop that goes straight to them).

  Everything else in `skills/fleet` is prose about files and schemas.
- **One "Runtime binding" section** maps those seven to the Claude tools. Codex later adds its own
  seven lines to `codex/runtime.md`. A content lint fails if a Claude tool name appears in the
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

   Today's probe cannot make that split: `behind=0` covers both "checkout behind" and "local
   edits". The fix adds a `git diff --quiet HEAD -- <config>` test, so "strictly behind" means
   `HEAD` is an ancestor of `<remote>/<base>` and the file has no uncommitted change.

   What running behind costs: every agent of the run reads the same older file, so the run is
   consistent, but a row or key added on the base branch is not seen until the owner pulls. The
   one-line note names the base-branch commit range for the file, so the owner sees what the run
   is missing. A run whose objective names a repo row the on-disk config lacks still stops, on
   `stu-env`'s own "no repo row matches" error.
3. **Explicit cycle cap.** Covered by the program-file rule above; no change to plain runs.

## Build order

Each unit carries its own changelog entry, version bump, lint-list and test updates, and its
Codex note in the same PR.

| Unit | Change | Depends on |
|---|---|---|
| S1 | Fix 1: ready-mode `MERGED_IDS` | none |
| S2 | Fix 2: stale-config stop | none |
| S3 | Nesting spike and its findings section | none |
| S4 | Merge hold and lock file; `stu-fleet` created with only its `hold` and `lock` subcommands; the gate's lock step and its revoke-only mode. Also settles what a gate returns when refused the lock, and whether a gate re-run on the lock-holder PR re-enters it | none |
| S5 | `judgment_model` key, routing row, lint | none |
| S6 | Settle skill refactor: ruling provenance mark, settler-safe writes | none |
| S7 | `stu:settler` in draft mode, with ruling verification | S5, S6 |
| S8 | Supervised mode for `/stu:run`: return schema, own-context measurement by agent id (`ctx.py`), a descendant-tree script replacing all four `ListAgents` uses in the run skill (allowed-tools, timer tree check, owner liveness answer, restart idle-tree test), agent-transcript lookup by a prompt nonce, `agents/supervisor.md` with `cacheTtl: 1h` (the lint's second role), and the `fleet-relaunch` run state with every reader of `Run state:` (the handoff format's grammar, Resume's count rule, `/stu:settle`) | S3 |
| S9 | Fleet: program file, board, `stu-fleet` `board`, `spend` and `next` (extending S4's script), `fleet_max_lanes` key, runtime-binding lint | S4, S8 |
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

- The spike's own gaps: a wait longer than one timer, an overnight supervisor, overage.
- Which cycle each of the 12 model-less orchestrator dispatches was.
