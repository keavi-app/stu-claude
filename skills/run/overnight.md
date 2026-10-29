# `overnight` — fan-out

Read only when the literal trailing word `overnight` was present. Several orchestrators
run in parallel, each with a **disjoint unit-ID list**. The supervisor still reads nothing.

## Split by contended resource, not by function

A split by component still collides if both sides touch the same file, shared data, schema,
or worktree. Function describes the work; the resource is what actually conflicts — hence
the objective file's `Contended resource` column.

**Two units touching the same lines are one unit, one brief, one PR.** Reconciling two
branches that disagree costs more than the work did.

## Caps

| Cap | Value | Why |
|---|---|---|
| Concurrent orchestrators | **4** | Above this the merge queue serializes anyway and collisions cost more than the parallelism buys. |
| Cycles, all lanes | **8** (default; the objective's `Cycle cap:` overrides) | Bounds the night the owner authorised at a known fraction of a day's spend. |

The cycle cap is **global, not per lane.** Four lanes each spending eight is four times
the night the owner authorised.

## One writer per worktree — and DETECT, do not merely refrain

Your rules govern your own dispatches and nothing else. Another session on this machine
can reach the same worktree, and a clean tree, a green PR, and a pushed head look identical
whether or not someone else is mid-edit.

- **Ask first.** If another session may reach a worktree, message it and get ownership
  stated. One round-trip, and the only thing that actually establishes who writes.
- **Record `HEAD` before dispatching into an existing worktree, and compare before
  reporting.** A HEAD that moved with no agent of yours reporting a commit is an unowned
  writer — say so, rather than presenting the PR's green as evidence for code that green
  never covered.
- **This detects commits only.** A writer mid-edit, or one that edits and restores,
  never moves `HEAD`. Matching SHAs are **not** an all-clear.
- **Quiescence is not termination.** A clean tree, no open review jobs, and a pushed head
  describe an idle *moment*. The only reliable stop signal for a child you dispatched is that child's own completion notification.

## Scoreboard and stop rules under fan-out

- The scoreboard is **per lane**. Non-convergence (`CLOSED_IDS: NONE` twice, or
  `REMAINING_IDS` unchanged across three cycles) is evaluated **per lane**, and stops
  that lane. The other lanes continue.
- A lane's returns carry `UNITS_ADDED` and `MOVED_IDS` as any return does; `Units added` is global,
  `Last heads` per lane (`SKILL.md` checks 2 and 5).
- **`after:` links share a lane.** A unit and the predecessor its `after:` names are always in the
  same lane; a cross-lane `after:` is `BLOCKED: condition 11` at startup (`SKILL.md`, "Startup"),
  so the fan-out split never separates a unit from the check on its predecessor.
- **Holds.** A Waiting unit is held under the run's claims slug (`stu-claims hold`, `SKILL.md`,
  "Two sets") by the supervisor, once per accepted `WAITING_IDS` entry, whatever its lane; the
  hold is dropped when that unit leaves Waiting. A lane whose only open units are Waiting is
  dispatched on resume like any lane with work, and the run ends `waiting-on-human` only when no
  lane has anything outstanding.
- Every other fail-closed check is per return, unchanged.
- The **cycle cap** and the **context bands** are global to the session.
- The **liveness deadline timer** (`SKILL.md`, "Liveness: one deadline timer per dispatch") is
  per lane: each lane's orchestrator dispatch arms and re-arms its own timer, independently of
  the other lanes' timers.
- Four lanes means four sets of dispatch prompts and notifications per cycle, **and
  four premise verifications** — each lane's handoff carries its own `PREMISE_CLAIM`, and
  one lane's premise says nothing about another's. The 160k soft band is sized for that.

## Merging under fan-out

Still **one at a time**, through `stu:merge-gate`, confirmed landed on the row's `<remote>/<base>` (`stu-env --repo <name>`), with
every remaining PR re-checked after each merge. **Exempt: integration merges into an epic
branch** (`completion: integrated`, `SKILL.md`), which the objective's `Integration lane:` (the only lane that dispatches an integrator, and the
only writer of the epic branch) makes one at a time, by merge or fast-forward but never a
squash or rebase, without the gate; that lane's orchestrator records `INTEGRATED_IDS`. Lane unit sets are disjoint. Under `completion: integrated` the integration lane therefore owns every unit ID end to end, the `Final unit:` included. Its DONE check needs the FINAL ID in that lane's own `READY_IDS`/`MERGED_IDS`. Its orchestrator dispatches the implementers that produce each reviewed head (within its `Max implementers`) as well as the integrator. Each ID closes on its own scoreboard, where check 1 accepts it. So an integrated run is a single-lane run (`SKILL.md`, "Completion mode"); work lanes such as A/B/C are implementer worktrees under that one orchestrator. The FINAL PR, the one that takes the
epic branch to the row's base branch, goes through the gate exactly as above. Parallel lanes produce parallel PRs, not
parallel merges. If a PR's checks drop out of green after another lands, **stop** — do not
force it through.
