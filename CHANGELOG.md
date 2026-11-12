# Changelog

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
