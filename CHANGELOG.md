# Changelog

## 0.2.23

- An unanswered questions-file entry on park-or-decide row 2-6 now holds its unit: it stays in
  `PARKED_IDS`, no merge gate is dispatched for it, and it is in no closing or arming field until
  `/stu:settle` answers and unparks it. The orchestrator may build the PR ahead and resumes from it
  after the unpark. `stu-run-check` reads the run's questions file and blocks a held unit that is
  armed (a gate field or `AFTER_PASS_FAILED`) or not parked (`owner-question-not-held`), and a
  question heading that names no unit (`owner-question-unreadable`). A missing row holds; a split
  unit's children inherit the hold. The check detects after the cycle, it does not prevent: on a
  block the supervisor disarms the PR with `stu-forge disarm`, and a merge already made goes to the
  owner. There is no "non-blocking" owner question.
- New family-only config key `owner_hold` (`owner-only`, default; `any-question`; `none`, the old
  behaviour), exported by `stu-env` as `OWNER_HOLD`.
- Fix: a settle reset a run's cycle count, so a fleet run with `Cycle cap: 2` ran three cycles
  across one settle. Resume now continues from `Cycles used:` in every run state except
  `fleet-relaunch`. Outside a fleet the owner raises `Cycle cap:` to grant more; inside one a cap-hit
  run can still be relaunched, and `fleet-relaunch` gets a fresh cap bounded by the cycle budget. `stu-fleet`'s `resume_count`
  follows the same rule.
- `stu-fleet brief` heads each run with the program's run slug (the one `answer` takes), not the
  settler's run-directory slug, says `1 ruling` for one, and builds the single-run `Answer:`
  example from the brief's own item numbers.
- The groomer writes only its report, the objective it feeds, filed issues and ledger-inbox files,
  never stray copies of its return block, and marks a program or scope instruction in an
  objective's rulings `(by: program)`, never `(by: owner)`. `(by: program)` joins the provenance
  marks in the handoff format.
- `docs/fleet-design.md` records an open problem: two runs that share a file can each finish
  `completion: ready` while the second PR goes CONFLICTING after the first lands, unnoticed.

## 0.2.22

- Fix: a run that finished every unit but whose handoffs carried `[skim]` decisions was marked done
  on the fleet board and its decisions were never shown to the owner. Its return now says
  `NEXT: settle` (the check requires it whenever `RUN-STATE` starts with `stopped`), the run skill
  prints the `/stu:settle` line for it, and the fleet settle loop accepts a run with no parked
  questions. When the owner's answer leaves no unit outstanding, parked or waiting, `board settled`
  ends the run as `done` (last line `done <slug>`) instead of requeuing it for a cycle that would do
  nothing.
- `board show` prints an indented `wait: fed by <job> (<state>)` line under a queued run that is
  waiting for a groom or audit job. The stored board line is unchanged.
- The fleet skill gives the exact dispatch lines for the groomer, designer and settler, copied from
  the agent files, and a content-lint check keeps the two in step.
- Returns the coordinator saves now live under `RUN_HOME/runs/<program name>/<slug>/`, so two
  programs that reuse a slug cannot collide.
- Removed an older duplicate `cmd_program` and `find_run` from `stu_fleet.py` (the later ones
  already won).

## 0.2.21

- New `stu:designer` agent: one decision-ready design round. It writes one question, two to four
  options (one recommended) and something to look at (rendered images when the project guide names
  a way to render, else a text-wireframe spec) under `OUTPUT/round-<n>/`, reads the owner's latest
  `VERDICT.md` entry as binding direction, checks claims with a verifier, and stops. Its context
  band is 120k/160k.
- The designer return's `OUTPUT:` is the job's OUTPUT directory (where `VERDICT.md` lives), not the
  round directory, so the owner's verdict stays where the next round reads it.
- The turn guard now watches the designer and the settler with a 120-turn backstop (the designer's
  context band was previously dead without a turn-budget row).
- `board judged` rejects a groomer or designer return whose `OUTPUT:` is not the job's program-line
  `output:` (exit 1, BLOCKED, job stays live). A designer's must equal it; a groomer's report may sit
  inside it.

## 0.2.20

- New `stu:groomer` agent, the second judgment seat. `KIND: groom` turns an audit report, epic or
  ledger batch into verified issues (filed only under the filing test, otherwise dropped or written
  to the ledger inbox) and, when it feeds a run, writes that run's objective at a new path.
  `KIND: audit` tries to break a stated invariant and reports what was tried, what held and what
  broke. It writes its report as it goes, returns `SPLIT` for an oversized scope, and carries
  context bands of 120k/160k in the turn guard. Codex: fleet is still not bound.

## 0.2.19

- The fleet board now tracks judgment jobs. Each line under `## Judgment work` gets a job line
  (queued, live, verdict, owner or done), and `stu-fleet next` prints `judge <slug>` for a queued
  job, `owner job ...` when a job needs the owner or judgment work is paused, and `verdict job ...`
  when a design round waits for an answer. `feeds: <run>` now means the job writes that run's
  objective: the run waits (`wait <run> — fed by <job>`) instead of failing the program check.
- New `stu-fleet board judged` (folds a groomer or designer return), `board verdict` (writes the
  owner's answer to the round's `VERDICT.md`), and `--job` forms of `board requeue` and `board idle`.
  A usage-limit return pauses all judgment jobs until the owner lifts it with `board requeue --job`.
- Groomer and designer return blocks are defined in the handoff format, and `stu-run-check` has
  `--groomer-return` and `--designer-return` to check them. The groomer and designer agents
  themselves are not built yet.

## 0.2.18

- `/stu:fleet` now runs the settle brief loop. A run in `settle` gets a `stu:settler` draft, the
  drafts of a wave go to the owner as one brief, the owner's one-line answer goes through
  `stu-fleet answer`, the settler writes the rulings, and `stu-fleet board settled` applies the
  scoreboard changes and requeues the run. An `add` that `board settled` refuses is sent to `/stu:settle`.
- The settler's `SCOREBOARD-TODO:` lines are `unpark`, `drop` or `add`, and it no longer emits a
  `Run state` line. A write dispatch on a partly written draft skips items already answered.

## 0.2.17

- `stu-fleet` now carries a stopped run's settle through to the next launch. `board draft` records
  the settler's drafted return against a run in `settle`; `next` then says `brief <slug>`; `brief`
  prints every draft as one owner brief, hiding items already written; `answer` splits the owner's
  one-line reply per run and checks the item numbers; `board settled` takes the settler's written
  return, moves unparked and dropped units on the scoreboard itself, writes the `Run state:` line,
  and requeues the run once nothing is left unanswered. A new unit the owner asks for is refused
  there and stays with the interactive `/stu:settle`.
- A `SCOREBOARD-TODO:` line from the settler is now exactly `unpark <id>`, `drop <id>` or
  `add <id> — <one line>`; the settler no longer returns a `Run state` line.
- The board line gains `draft:` and `written:` after `out:`. A 0.2.16 board reads as none and gains
  the fields on its next write.

## 0.2.16

- `/stu:fleet` now acts on what `stu-fleet` decides: it launches with the nonce `board launch`
  prints, runs `board relaunch` for a `relaunch` line, stops an idle supervisor and then runs
  `board idle`, sends limit and loop-guard `owner` lines and `notice:` lines to the owner, runs
  `board judgment` before any groom, audit or design dispatch, and adds `stu-fleet actuals` to the
  wave report. The "not built yet" list shrinks to the settle brief loop, the groom, audit and
  design seats, and Codex.

## 0.2.15

- The fleet board now records actuals. `board record` and `board idle` read the launch's
  supervisor tree from the agent transcripts (found by its launch nonce in any session) and add
  its agent count and output tokens to the run line as `agents: <n> | out: <n>`, cumulative across
  launches; the fleet line carries the totals. A board from 0.2.14 reads as 0 and gains the fields
  on its next write. When the transcripts cannot be found, or the nonce matches zero or several
  agents, the command prints `actuals: unavailable — <reason>` and still succeeds.
- Each of those commands also appends one JSON line per launch to `<program>.actuals.jsonl`, with
  turns and output tokens by seat and model.
- New `stu-fleet actuals PROGRAM` (read-only) prints, per run and for the fleet, launches, agents,
  output tokens, a seat/model table, and each `stu:` seat's share of turns off its routed model.
  `spend` adds `agents` and `out`. Actuals are a report; the cycle budget stays the only limit.

## 0.2.14

- `stu-fleet` now decides relaunches and enforces limits. `next` prints `relaunch <slug>` for a run
  whose supervisor stopped with units left, and turns any start or relaunch into an `owner` line
  once the cycle budget is spent or the program's `Stop at:` has passed. A live run is never
  stopped by a limit. Each limit prints one `notice:` line at 80% and at 100%, once per program.
- New `board idle` (for a supervisor that went quiet and was stopped without returning),
  `board relaunch` (re-checks the limits under the lock, writes `Run state: fleet-relaunch <date>`
  into the objective, then launches), and `board judgment` (counts one groom, audit or design job
  against `Judgment jobs:`). `spend` now reports judgment jobs, `Stop at` and each run's dry count.
- A loop guard, always on: two launches in a row that close no unit stop the relaunching and send
  the run to the owner.
- Each launch gets a nonce, printed last by `board launch` and `board relaunch`, for the
  coordinator to put in the supervisor's `STU-SUPERVISED:` line.
- A Runs line takes `| lanes: <n>`; an overnight objective must declare it. The board lines gain
  `closed`, `dry` and `nonce` fields and a final `fleet` line; boards from 0.2.12 still read. An existing program with an overnight
  run fails `program check` until its Runs line adds `| lanes: <n>`.

## 0.2.13

- New experimental skill `/stu:fleet <program path>`. It runs several objectives from one
  coordinator session: it checks the program with `stu-fleet program check`, stops when the
  program's `Merge lock:` disagrees with the config's `merge_lock`, then loops on `stu-fleet next`,
  launching one supervised run per `start` line, recording each supervisor's return on the board,
  and listing everything that needs the owner. It reads board lines and return blocks only.
- Not built yet, and the skill says so: relaunching a stopped supervisor, enforcing the cycle
  budget and the loop guard, and the settle brief loop. `spend` reports at each wave and enforces
  nothing. A run that needs more lanes than the cap goes to the owner instead of starting.
- The fleet skill names Claude tools only inside its "Runtime binding" section, and the content
  lint now fails if one appears anywhere else in it. The Codex adapter does not render the skill,
  and a test pins that, so `fleet: not bound yet` stays true.
- The fleet design now says the program's `Merge lock:` line is checked against the config and
  never overrides it.
## 0.2.12

- `stu-fleet` can now read a fleet program file. `stu-fleet program check <program>` validates it
  (header lines, runs, judgment work) and prints a one-line-per-field summary, or one `BLOCKED`
  line per problem: a missing owner or settle mode, a bad number or time, an objective that is not
  an absolute existing path, a run whose objective has no `Cycle cap:` line, an unknown or circular
  `after:`.
- The program file's `## Fleet board` section is the board, one line per run with its state,
  fleet-cumulative cycles, launches, the count the current launch resumed from, last handoff and
  last stop. Only `stu-fleet` writes it, under a lock and by atomic replace, and never touches
  anything outside that section. `board show`, `launch`, `record` and `requeue` read and move it:
  a live or done run is never launched, a return is checked with the same validator as
  `stu-run-check --supervisor-return` before its cycles are counted, and a negative cycle delta is
  refused rather than clamped. A board line that names no run, or is malformed, is an error.
- `stu-fleet spend <program>` reports cycles and launches per run and the fleet's cycle budget (the
  program's `Cycle budget:`, or by default the sum of the runs' caps). It reports only; enforcement
  and judgment-job counting come later, and the output says so.
- `stu-fleet next <program>` says what to do for each run (`start`, `wait` with the reason,
  `settle`, `owner`, `relaunch`, `live`, `done`), then the merge hold and the live lane count. It
  first releases a merge lock whose PR has merged, closed or lost its label.
- New family-only config key `fleet_max_lanes` (positive integer, default 4, no ceiling), exposed by
  `stu-env` as `FLEET_MAX_LANES`. A program's `Max live lanes:` overrides it.

## 0.2.11

- The content lint that checks every repo-scoped `stu-env` call in `agents/` carries `--repo` now
  reads the full list of family-only sections. It used to read only the first line of that list,
  so `judgment-model` counted as repo-scoped and a correct call without `--repo` would have failed
  the lint. A new check fails if any section the config template calls family-only is missing from
  the set the lint reads.

## 0.2.10

- New `stu:settler` agent, the first judgment seat. Given a stopped run's objective in draft mode,
  it drafts a ruling for every unanswered question (a plain-language question, a recommendation, a
  "reverses if" line, any deploy precondition, which park-or-decide row it falls on, and flags),
  has a `stu:verifier` check each one against the project guide and the code on the base branch,
  saves the draft to the run's `settle/` folder, and returns one brief the owner answers in a line:
  `fine`, `reverse 2, 5` or `talk about 3`.
- In write mode it takes the owner's line and does the ruling writes only (settle step 5a): an
  accepted ruling is marked `(by: settler; owner-approved <date>)`, a reversed one is written as
  the opposite and marked `(by: owner)`, and a deploy precondition goes to the merge hold. It never
  touches the scoreboard; it hands back `SCOREBOARD-TODO` lines for the dispatcher to do.
- Rows 2 to 6 of park-or-decide, a possible stop-condition-2 disagreement (which implies
  `owner-only`), and any reversal of an earlier ruling are always flagged for the owner. Bare `fine`
  covers only unflagged items and items flagged only `owner-only`; a `reversal` or `sc2-candidate`
  item, or one whose verifier verdict is not `HOLDS` (verdicts now include `PARTIAL` and
  `UNVERIFIED`), needs an explicit `accept <n>` in the answer line, which is now
  `fine | accept 2 | reverse 2, 5 | talk about 3`. The return check also rejects a brief line that
  omits a flag its `R` line carries.
- The settler's return is a fixed block, defined in the handoff format and checked by a new
  `stu-run-check --settler-return FILE` mode. The settle skill gains a short "Drafting by
  `stu:settler`" section; the interactive `/stu:settle` path is unchanged. The run skill's routing
  row now lists the settler as built. Codex: fleet is still not bound.

## 0.2.9

- `/stu:run` now has a supervised mode for a fleet coordinator: a run whose prompt carries a
  `STU-SUPERVISED: <nonce>` line never asks the owner anything and ends with a fixed return block
  (`STU-RUN`, `RUN-STATE`, `STOP-CONDITION`, `CYCLES`, `PARKED`, `NEXT` and the rest). A table maps
  each stop condition to what should happen next: settle, relaunch or the owner.
  `stu-run-check --supervisor-return PATH` validates the block. New agent `stu:supervisor` runs it
  as a background subagent, with a 1-hour prompt cache like the orchestrator; it takes its
  launcher's model.
- New `stu-tree` lists a subagent's live descendants by parent id. The run skill uses it for its
  deadline-timer tree check, the "is it still running" answer and the restart idle test, in place
  of `ListAgents`, which does not exist inside a subagent.
- `stu-ctx --nonce <n>` measures a subagent's own transcript, found by a `STU-NONCE` or
  `STU-SUPERVISED` line in its prompt, instead of the root session's. Every orchestrator dispatch
  now carries a fresh `STU-NONCE` line. Zero or several matches is an error, never a fallback.
- New run state `fleet-relaunch <date>`, written only by a fleet coordinator. A run resuming from
  it starts its cycle count at `0/<cap>`, and `/stu:settle` treats it like `settled`.

## 0.2.7

- `/stu:settle` now writes its results in two named parts. Ruling writes (the answers, the
  rulings, what the owner reviewed, and any deploy precondition, which goes to the merge hold with
  `stu-fleet hold set` rather than a notes file) are safe for a settler agent to do. Scoreboard
  writes stay with the settle session itself, or the fleet coordinator, and are never done by an
  agent that drafted rulings.
- Every line under `Rulings already given` now ends in a mark saying who ruled: `(by: owner)`,
  or `(by: settler; owner-approved <date>)`. A later reversal names the ruling it reverses. Old
  lines with no mark read as the owner's. Nothing parses these lines, so older runs are unaffected.
- The settle skill lists what is always the owner's: reversing any ruling, deciding whether a
  question is a stop-condition-2 disagreement, and promoting ledger entries.

## 0.2.6

- New family-only config section `judgment-model`: one model (a runtime alias such as `opus` or an
  exact model ID) for the judgment seats that later fleet work adds (settler, groomer/auditor,
  designer). Empty means `opus`. A repo row cannot override it.
- The run skill's routing table gains one row for judgment seats, reading that section. The
  coordinator and supervisor never read it, and a seat that falls back to a lower model on a
  usage limit may only draft, never auto-apply.
- The content lint now checks the judgment row exists and that no agent or skill names a literal
  Claude model ID.

## 0.2.5

- New `stu-fleet` helper keeps one merge hold and one merge lock in a single file under the run
  home. `stu-fleet hold set --reason ...` makes every merge gate refuse to label or merge until
  `hold clear`; it also prints the one armed PR, if any, that must be disarmed. The lock lets only
  one PR sit between label and landing at a time, taken and released through `stu-fleet lock`.
- The merge gate checks the hold (and, with the new `merge_lock: on` config key, takes the lock)
  immediately before it labels or merges, and releases the lock when it confirms the landing. A
  refused gate returns `GATE: FAIL` with a `fleet-hold:` or `fleet-lock:` reason, which the
  orchestrator and supervisor treat as "try again later", not a failure or a stop.
- The gate gains a `revoke-only` dispatch that disarms one PR without evaluating it. `merge_lock`
  defaults to off for plain runs; a fleet program will turn it on. Codex notes `fleet: not bound yet`.

## 0.2.4

- A run no longer stops at startup just because the repo's config file is behind the base branch
  in the main checkout. When the checkout only lags (no local edits), the run prints one note
  naming the file and the base-branch commits it is missing, then goes on; every agent of the run
  reads the same file, so the run stays consistent. A config that is ahead, diverged, or edited
  still stops. A run whose objective names a repo row the on-disk config lacks still stops on the
  "no repo row matches" error.

## 0.2.3

- A label-handoff unit under `completion: ready` now closes on a landed `MERGED_IDS` entry as well
  as on `READY_IDS`. When the auto-merge actor merges the PR before the merge gate returns, the gate
  reports `LANDED:` rather than `READY:`, and the checker used to block that unit as the wrong field
  so it could never close. The landed sha is verified on the base exactly as on a direct row; a sha
  that did not land is still blocked.

## 0.2.2

- Every command stu hands the owner to paste (`/stu:settle`, the `/stu:run` that resumes a run,
  the first `/stu:run` after `/stu:init`) prints alone on its own line, under a short lead-in such
  as `Next up, settle in a new session with:`, so a triple-click copies exactly the command. The
  old `Next: ` prefix and trailing note are gone, and the content lint keeps them out.

## 0.2.1

- A `fix-when-touched` record's `resolve:` command can use `{pr}` (the unit's PR number, digits
  only) and `{sha}` (the unit's head commit SHA when resolve runs, full length) next to
  `{finding}`. Both are optional; a record that omits them is unchanged. If the record uses one
  and the orchestrator has no value for it (the unit has no PR yet), it does not run the command,
  reports the finding as unresolved, and never passes the literal placeholder.

## 0.2.0

- Add a separate Codex package with four skills, native nested-agent runtime bindings, session-specific context telemetry and advisory child budget hooks. Shared safety contracts remain canonical.
- Recognize Codex agent pushes and protect approval files through Codex patches, moves and aliases. Preserve the existing Claude hook declarations and runtime contracts.
- Use the existing shared config paths in both runtimes without changing Claude lookup, and add a shared `make test` entry point.


## 0.1.4

- `stu:orchestrator` writes its prompt cache with a 1-hour TTL (`experimental: cacheTtl: 1h`
  in its frontmatter), so a wait of 5 to 60 minutes on its children reads its context instead
  of rebuilding it. Every other role keeps the 5-minute default, and the content lint fails if
  another agent takes the key. Rationale, measurements and limits: `docs/design-rationale.md`,
  "Cache TTL".

## 0.1.3

- `stu-run-check` accepts `READY_IDS` for a unit still in `REMAINING_IDS` on a label-handoff row
  under `completion: merged`, as the run contract asks: the entry is checked as a labelled PR and
  the unit prints `OPEN ready-labelled:<slug>#<pr>,auto-merge-<on|off>` until `MERGED_IDS`
  records its landing. A `CLOSED_IDS` entry backed only by it is `BLOCKED
  tracking-field-does-not-close`, and a tracked unit outside `REMAINING_IDS` is `BLOCKED
  tracked-not-remaining`. Before-push, direct and report-only rows still reject it.

## 0.1.2

- The handoff format says run folders hold reports, briefs, logs and handoffs, never build products,
  derived data or source copies.
- The orchestrator no longer waits for CI before the gate on a label-handoff row where the merge
  label also gates CI; the CI evidence is read at the gate's confirm dispatch.
- `stu-run-check` reads a unit in both `CLOSED_IDS` and `MOVED_IDS` as CLOSED, not `OPEN moved`.

## 0.1.1

- `stu-run-check` blocks a return that lists an ID in `REMAINING_IDS` or `PARKED_IDS` and also in
  `CLOSED_IDS` or its row's closing field (`BLOCKED closed-but-remaining`), so a passed unit is
  closed in the cycle that passed it rather than one cycle later.
- The orchestrator puts an ID whose closing field it relays in `CLOSED_IDS`, never in
  `REMAINING_IDS`.
- A gate return saved in an earlier cycle may be relayed only when the unit's head is verified
  unchanged at the gate's sha in the current cycle.

## 0.1.0

- First release as a Claude Code plugin: install with `claude plugin install stu@keavi`.
- Skills `/stu:run`, `/stu:settle` and `/stu:fix-campaign`, and six agents namespaced `stu:`.
- `/stu:init` writes a per-repo config, kept in the repo or in `~/.stu/<project>/`, in place of
  hand-edited `PROJECT-SPECIFIC` blocks.
- The turn guard ships as a plugin hook, with a native `maxTurns` backstop on the
  orchestrator (190) and implementer (220).
- Helper commands on the plugin `PATH`: `stu-env`, `stu-claims`, `stu-ctx`, `stu-ci-wait`,
  `stu-approve`, `stu-forge`, `stu-pre-push`, `stu-run-check`, `stu-verify`.
- `stu-verify --retry` re-runs a failed commit's verification once; the merge gate uses it for a
  suspected flake and treats a second failure as final.
- In a headless session the supervisor relays a nested agent's completion to the orchestrator
  that dispatched it, without reading the agent's result.
- Multi-repo families: a `## repos` table with `### <name>` rows and `## <id> @<name>` sections,
  and merge modes `direct`, `label-handoff`, `report-only` and `direct-push` per row.
- New config keys: `host`, `initial_version`, `merge_method`, `ci_timeout`, `ci_triage_command`,
  `ci_triage_wait`, `ci_no_rerun_branch_prefix`, `ci_gate_source` and `ci_skipped_is_success`.
- The publish guard: a git `pre-push` hook on public and before-push repos (its approval rule
  applies to Claude Code pushes only; the leak scan applies to every push), and a `PreToolUse`
  hook that protects the approvals file.
- Minimum Claude Code version 2.1.310; macOS, Linux and WSL.
