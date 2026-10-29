# Objective, handoff, and questions — the three files a run writes

Read this when you are **writing** one of them. Not needed to dispatch a cycle.

All three are absolute paths. Objectives and questions live under `RUN_HOME/handoffs/`;
a campaign handoff lives under `<run-dir>` (`RUN_HOME/runs/<slug>/`, defined in
`orchestrator-charter.md`'s Artifacts section) — never the session's temp scratchpad. A resume
after that session's temp directory is gone (a reboot, a `/tmp` cleanup) must still find the
handoff, the briefs, and the ledger.

---

## 1. The objective file — written once, at startup, before any work

`RUN_HOME/handoffs/YYYY-MM-DD-<slug>-objective.md`

It exists so a session that dies leaves a recoverable objective on disk, and so the unit
list exists before there is any incentive to change it.

```markdown
# Objective: <one line>

Written <YYYY-MM-DD>. Mode: plain | overnight. Cycle cap: <n> (absent: the default in `SKILL.md`, "The cycle cap").
Max implementers: <n> (optional; absent: 2, `orchestrator-charter.md`), with the machine rule stated in the objective.
Base branch: [<repo>:] <branch>[, <branch> ...] [<note>] (optional; absent: each row's own base branch from `stu-env --repo <name>`. Every worktree's branch point and every diff base. An `origin/` prefix is stripped, a note after ` -- ` is ignored and must not contain a comma, an unprefixed branch belongs to the home row.)
Final unit: <id> (required under `completion: integrated`, else omit: the one unit whose PR targets the row's base branch.)
Integration lane: <agent name and charter> (required under `completion: integrated`, else omit: who merges units into the epic branch, and how.)
completion: ready | merged | integrated (default: the project default in `SKILL.md`, "Completion mode").
<`ready` — the run ends when every issued unit's PR is labelled at a verified SHA; auto-merge
merges on green, unattended. Only a label-handoff merge gate can produce it.
`merged` — the run keeps cycling and waits for the merge, confirming each unit's merge on
`<remote>/<base>` (the row's remote and base branch, from `stu-env --repo <name>`) before it can count as done. A labelled, not-yet-landed unit stays in
`REMAINING_IDS` in this mode, never counted done by the label alone (`SKILL.md` check 3,
check 5's carve-out).
`integrated` — units merge into the epic branch named by `Base branch:`. A non-FINAL unit
closes when its reviewed head SHA is verified an ancestor of that branch (`INTEGRATED_IDS`); the
`Final unit:` closes on the gate's `READY:` as under `ready` (`SKILL.md` check 3, check 5's
integration carve-out).>

## What done means

<Two or three sentences. Not a task list — the condition under which the run stops being
needed. An orchestrator given only progress invents its own definition of done, which is
why this file is passed on every dispatch.>

## Units — enumerated at cycle 1, held by the supervisor for the life of the run

| ID | What it is | Contended resource | repo | after |
|---|---|---|---|---|
| 42 | <one-line description of the issue> | <the directory, table, or worktree it touches> | <row name> | - |
| some-slug | <a unit with no issue number> | <resource> | <row name> | 42 (landed) |

`repo` and `after` are optional columns. Without `repo` every unit is the home row (legal only in
a one-row family); without `after` no unit has a predecessor. `after` is `<id> (landed)`,
`<id> (landed, tagged)`, or `-`/empty, and a unit and its predecessor share a lane under
`overnight`. `stu-run-check` reads `after:` from this table alone, so a unit a later cycle adds
(`UNITS_CHANGED` / `UNITS_ADDED`) is appended here as a row, with the repo and, for a substituted
child, the `after:` of its parent. The 3-column table is valid as it is.

The **ID column is the scoreboard's vocabulary** — every `CLOSED_IDS`, `REMAINING_IDS`,
`PARKED_IDS`, `MERGED_IDS`, `READY_IDS`, `INTEGRATED_IDS`, and `INTEGRATING_IDS` value comes
from here.

**Adding a unit later requires an explicit `UNITS_CHANGED: <parent id> -> <new ids> —
<reason>` line, or a `UNITS_ADDED: <new ids> — <reason>` line for a unit that is no piece of
an issued one,** naming every new ID; the supervisor blocks without it. Either way the
scoreboard, not this table, is the run's unit list from then on (the table still carries each
child's `repo` and `after`). Silent
decomposition is what defeats the non-convergence test: one issue split into eight
sub-units reports `CLOSED_IDS: <one>` honestly every cycle, with `REMAINING_IDS` falling,
while nine orchestrators spend the night on one issue.

**The tests a substitution or an addition (`UNITS_ADDED`) must pass, and the cap on additions,
are in `SKILL.md` check 2, which is the contract; this file does not restate them.** In short: parents currently issued and not
already closed or merged, children never issued by this run, at least one child. Two units
that turn out to be one are written `A,B -> AB-merged`. **Descoping is the owner's call**,
and it travels through the questions file and `PARKED_IDS`, never through this line.

## Rulings already given

<Anything the owner decided before or during the run, one per line. Constraints a later
cycle must not re-litigate.>

## Scoreboard — written by the supervisor every cycle and by /stu:settle between runs, never by an orchestrator

**The block below is the run's state; nothing else in the objective file is.** Rewrite it in
place each cycle. Run narrative (what a cycle did, why) goes in the handoffs, never appended
to the objective. A supervisor resuming from an objective that has grown anyway reads the
`## Scoreboard` block and the unit table, and ignores narrative below or beside them.

Run state:              running | stopped — <the BLOCKED/DONE line, verbatim> |
                         waiting-on-human |
                         settled <YYYY-MM-DD> — <what /stu:settle changed, one line>
                         (global, never per lane. `waiting-on-human`: nothing is outstanding or
                         parked, but a unit is Waiting or awaits approval. Precedence at the last
                         write: stopped > waiting-on-human > settled. The supervisor writes
                         `settled ... nothing to settle` only per the run skill's final-message
                         rule. /stu:settle edits this section,
                         only while this line reads stopped, waiting-on-human or settled, and only as its
                         step 5 lists: Run state, Parked, Outstanding, Closed for a
                         dropped unit, and the issued sets for a unit the owner adds.)
Cycles used:            <n>/<cap>
Lane state:             running | stopped — <that lane's BLOCKED/DONE line, verbatim>
                         (the only per-lane stop record. A stopped lane is never
                         dispatched until a resume finds it has units outstanding.)
Restarts used:          n/1   (per lane, written by the supervisor only. One fresh
                         re-dispatch per lane per run, after a failed liveness repair —
                         SKILL.md, "Restart once per lane". 1/1 means the next liveness
                         failure stops the lane BLOCKED. A lane block with no such line,
                         from before this field existed, reads 0/1.)
Units added:            n/3   (global; IDs accepted through UNITS_ADDED, SKILL.md check 2.
                         A unit the owner adds is a ruling and does not count.)
Model overrides:        n   (global, written by the supervisor only: cycle-2+ orchestrator
                         dispatches with a groomed brief whose `model` was not sonnet, each
                         with its `ESCALATION: condition <n>` line — SKILL.md, "Routing". A
                         file with no such line reads 0.)
Units issued:           <the run's vocabulary: the cycle-1 list, plus every child a
                         UNITS_CHANGED line added and every ID a UNITS_ADDED line or the owner
                         added, minus every parent a UNITS_CHANGED line retired.
                         Closing or merging an ID does NOT remove it from here.>
Ever issued:             <every ID this run has ever issued, including retired parents.
                         Never shrinks. New children are checked against THIS set.>
Closed:                 <the running union across every cycle so far, or NONE — a unit is
                         closed by the gate field its own row's merge mode names (MERGED_IDS,
                         READY_IDS, PASSED_IDS or APPROVAL_IDS; the closing table in
                         SKILL.md, "The return fields, as `stu-run-check` reads them"), or (completion: integrated) its
                         reviewed head SHA is verified an ancestor of the epic branch
                         (INTEGRATED_IDS; the Final unit closes as its row does), or its issue
                         closes directly with no PR (a legal CLOSED_IDS entry except on a
                         before-push row). READY: alone does NOT close a unit in completion:
                         merged mode — SKILL.md, "CLOSED_IDS, defined">
Integrated:             <completion: integrated only: INTEGRATED_IDS as <id>@<unit head sha>, accumulated;
                         INTEGRATING_IDS as of the last return. Omit otherwise.>
Merged:                 <MERGED_IDS accumulated as <id>@<landed sha>, ... — evidence for WHY a
                         unit closed, not a second closed set. A `Merged/readied:` line from
                         before the split is read as both Merged and Readied.>
Readied:                <READY_IDS accumulated as <id>@<sha>, ... — evidence for why a unit is
                         labelled (or, in completion: merged, why a unit is still outstanding
                         despite being labelled)>
Passed:                 <PASSED_IDS accumulated as <id>@<slug>#<pr>@<sha>, ...>
Tagged:                 <TAGGED_IDS accumulated as <id>=<tag>@<sha>, ...>
Approved:               <accumulated <id>@<sha>, ... — a push approval the owner gave, recorded
                         by a resume (SKILL.md, "Resume") when `stu-run-check --approved`
                         reports it>
Awaiting approval:      <current state, not accumulated: <id>@<branch>@<sha>, ... — units
                         whose branch awaits the owner's push approval (APPROVAL_IDS), or NONE>
Waiting:                <current state: <id> needs: <action> <ref>; ... — <action> is
                         `merge <slug>#<pr>`, `tag <repo> at <sha>` or `approve <id> at <sha>`;
                         the accepted WAITING_IDS of the last return, or NONE. A Waiting unit
                         is neither Closed nor Outstanding.>
Parked:                 <ids, or NONE>
Outstanding:            <issued minus closed, parked and Waiting, or NONE — closed already covers
                         MERGED_IDS in both modes and READY_IDS in completion: ready mode,
                         per the definition above, and a verified INTEGRATED_IDS entry in
                         completion: integrated; a readied-but-unlanded unit in
                         completion: merged mode is not closed and stays outstanding>
Cycles with no close:   <n>   (check 5, trigger 1: fires at 2 consecutive — exempt in
                         completion: merged while every remaining ID is in the accumulated
                         READY_IDS, the same carve-out as trigger 2, below; in
                         completion: integrated on a cycle whose INTEGRATING_IDS lists a
                         remaining ID, only while this counter is below 3; and on a cycle
                         whose verified MOVED_IDS lists a remaining ID, same bound)
REMAINING_IDS was:      <last cycle's value> — unchanged <n> cycles, all of them in
                         `READY_IDS`, with no new `LANDED:` in that span
                         (check 5, trigger 2: fires at 3 — same carve-out and the same
                         three-cycle bound as trigger 1, above; past the bound the
                         SUPERVISOR itself — not the orchestrator — runs the read-only
                         PR status commands and stops BLOCKED naming what is stuck,
                         SKILL.md check 5)
Last heads:             <id>@<sha>, ... — each unit's branch head as of the last cycle's
                         rev-parse-verified MOVED_IDS entries only, the baseline the next cycle's `git merge-base
                         --is-ancestor` runs against (SKILL.md check 5, moving-branch carve-out)
Last handoff:           /absolute/path.md

(Under `overnight`, repeat every field above **once per lane**, under a `Lane: <name>`
heading. Only `Run state`, `Cycles used`, `Units added` and `Model overrides` are global — the cap is counted across all lanes, while the
held list, the union, both counters, and the handoff path are per lane, exactly as
`overnight.md` evaluates them. One merged block cannot reconstruct several lanes.)
```

The warning and the ID-column sentence sit **inside** the template on purpose. The
objective file is carried on every dispatch; `handoff-format.md` is not. Moving them out
of the fence is how an orchestrator stops being told the rule before it breaks it.

**The `## Scoreboard` block is the supervisor's own state, and it is the only thing that
survives the supervisor's death.** The unit list drifts from the table above the moment a
`UNITS_CHANGED` or `UNITS_ADDED` line is accepted or the owner adds a unit, and the closed/merged union and both of check 5's
counters exist nowhere else — not in the handoff, not in the objective's original table. A
supervisor that does not write this back leaves its successor restarting checks 1, 3 and 5
against state that looks complete and is not. **An orchestrator never writes this block**;
reading it is fine.

**Check 5 has two independent triggers and therefore needs two records.** "No close twice
running" and "`REMAINING_IDS` unchanged for three cycles" catch different stagnation: the
second is the one that fires when an orchestrator keeps closing trivial IDs while the
genuinely blocked unit never moves. Persist only the first and a resumed supervisor
silently resets the second to zero. In `completion: merged` mode, both share one
carve-out — waiting on auto-merge while every remaining ID is already `READY_IDS` is not
stagnation — so both records exist regardless, but neither fires on that basis alone.

---

## 2. The handoff — appended every cycle, the only thing that crosses the boundary

Prose summaries drop exactly the load-bearing constraints that took the most turns to
establish, and nothing reports the loss. So it is structured state.

```markdown
# Handoff: <objective slug> — cycle <n>

PREMISE: <the ONE claim that, if false, invalidates the work handed over>
```

**`PREMISE:` is mandatory, exactly one line, and only the outgoing writer can produce
it** — you know what was load-bearing; the next orchestrator is guessing. Return the same
string as `PREMISE_CLAIM` so the supervisor holds it.

**You never verify your own claim.** Who verifies it instead depends on who dispatched
you, and **this file does not decide that** — it defines the field only. The test is a
literal `SUPERVISED:` line on the dispatch prompt, stated in
`agents/orchestrator.md`. Do not read this file as saying the check is always
handled for you; reading it that way is the silent total skip the stamp prevents. What is
invariant is only this: **the party that makes a claim never certifies it.**

Then, per the orchestrator charter's structure:

```
GOAL:        the objective, verbatim
CONSTRAINTS: every ruling given or escalated-and-answered, one per line
DECIDED:     decisions made and not to be revisited, each with its reason
PER UNIT:    id | premise verdict | worktree abs path | branch | PR | state
             | reviewed SHA | last agent ID | what is left
OPEN:        questions parked, each with the measurement already settled
NEXT:        the ordered next actions, specific enough to act on without re-deriving
WRONG:       any premise found false, so the successor does not re-test it
```

### Every load-bearing claim carries an epistemic tag

`VERIFIED` / `INFERRED` / `ASSUMED`. This prevents an inference hardening into a fact as
it is copied forward; by cycle 4 nothing on disk remembers a claim was a guess.

`VERIFIED` carries its evidence inline, and the two kinds take different evidence:

| Claim | Evidence |
|---|---|
| positive ("X does Y at Z") | `file:line` |
| **negative** ("X has no such value") | the **exact search command, the ref, the output, and the exit status** — never a `file:line`, which cannot exist for something absent |

Match the search's scope to the claim's scope. `git grep <pat> <ref> -- wrong/path` exits
1 cleanly, indistinguishably from a true absence. "Does not exist anywhere" requires an
**unscoped** search; "does not exist in `<path>`" requires the scoped search **plus**
`git ls-tree -r --name-only <ref> -- <pathspec>` showing the scope is non-empty, and the
claim must never be generalised beyond it.

### `## Decisions taken`

Every decision made in the owner's absence:

```
- [skim]? <decision> — <one line of reasoning> — reverse by: <the specific action>
```

The orchestrator starts the line with a literal `[skim] ` only when the decision is still
reversible AND touches core domain semantics, a user-visible surface or data; otherwise it writes no tag.
Untagged is never shown at settle. **This is the one definition of the tag.** Each handoff
carries forward every earlier `[skim]` line of the run that the objective's `## Decisions
reviewed` does not yet list, cumulatively, so a lane's `Last handoff:` alone holds all of that
lane's unreviewed tagged decisions (a resumed run does not recount what the owner already saw). The supervisor counts tags over
exactly those files, one per lane, and never opens them.

---

## 3. The questions file — one per run, appended, never blocking

`RUN_HOME/handoffs/YYYY-MM-DD-<slug>-questions.md`

A question parks **one unit** and the run continues. Only a question the park-or-decide test
parks belongs here (`agents/orchestrator.md`, "Park or decide"); a row-7
decision goes to `## Decisions taken` in the handoff instead. Each entry:

```markdown
## <unit id> — <the question in one line>

**Why it is the owner's:** row <2-6> — <production write | core semantics | visual | surface | scope>
**How it arose:** <one or two sentences, in plain product language>
**Already measured:** <what is settled, so the owner is not re-deriving it>
**Look at:** <an absolute path to something openable — a screenshot, a rendered
prototype, a diff file. A reference the owner cannot open is not a reference.>
**Options:** <at most three, each one line>
**Recommendation:** <one option> — strong | lean — <one line of why>
```

`/stu:settle` reads the `Why it is the owner's:` row to order the walk-through and the
`Recommendation:` line to offer the one-word answer, so both are required.
Answers are appended below the questions by `/stu:settle`, under
`## Answers — <YYYY-MM-DD>`: one line per unit, with the owner's own words whenever they went beyond
taking the recommendation.

Plain language, not session shorthand: translate internal vocabulary into what the user
sees, and ask with a worked example rather than a principle — "Before the change the screen
showed X; after it, the same screen shows Y. Which should it be?" lands where a doctrine
name does not.

The supervisor pushes this path to the owner and keeps relaying. **The run stops only when
every remaining unit is parked.**
