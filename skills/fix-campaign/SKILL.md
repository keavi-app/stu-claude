---
name: fix-campaign
description: Use when the owner asks to triage open issues and fix them, work through recently filed issues, drain and triage the observation ledger into real issues, or run an orchestrated multi-issue fix campaign that drives PRs to merge.
allowed-tools:
  - Agent
  - SendMessage
  - Bash
  - Read
  - Write
  - Edit
  - Grep
  - Glob
---

# Fix Campaign

**Startup:** run `stu-env` once and keep its values: `RUN_HOME`, `WORKTREES_DIR`, `PROJECT_GUIDE`, `GITHUB_REPO`, `MAIN_CHECKOUT`, `TRIAGE_EXTRA`. This file names them that way. This call stays unflagged because it is the family-level read; every later `stu-env section` call names the unit's row with `--repo`. `PROJECT_GUIDE` is a path under `MAIN_CHECKOUT`.

Triage → groom → implement → review → merge, run by an orchestrator subagent so the
main session stays clean.

**Core principle: a claim is a hypothesis until checked against code on the base branch.** That
applies to issue bodies, ledger entries, code comments, agent reports, and closed issues.
On project A's first campaign, five ledger claims were wrong in two days,
two handoff premises were wrong, and three code comments described guards that did not
exist.

## Phase 1 — Triage (you do this, not a subagent)

```bash
SINCE=$(date -u -v-7d +%F)         # macOS. Linux: date -u -d '7 days ago' +%F
EXTRA="<TRIAGE_EXTRA>"             # extra search qualifiers from the config; often empty
```

List the open issues from the last week with the forge's own CLI:

```
# GitHub example
gh issue list --repo GITHUB_REPO \
  --search "is:issue state:open no:parent-issue created:>$SINCE $EXTRA" \
  --json number,title,labels --limit 100
```

```bash
ls "<RUN_HOME>"/ledger-inbox/      # drain FIRST — the count isn't honest otherwise
```

**Compute the date in the shell. Do NOT write `created:>@today-1w`.** GitHub's `@today`
relative-date syntax works in Projects filters but **not** in issue search — it does not
error, it silently matches **nothing**. A first run of this skill read that zero as "no
recent issues" and nearly ended the campaign before it began.

**A filter returning zero is a hypothesis, not a result.** If any query here comes back
empty, drop one clause at a time until it isn't, and find out which clause lied. That is
the same defect class this whole campaign exists to catch: a check that cannot fail
correctly reads exactly like a clean bill of health.

**Be brutal with the ledger.** Every entry is either promoted to an issue, or dropped.
"Carry it another week" is the failure mode — a ledger that only grows stops being read.

File an issue **only** when the filing test in `PROJECT_GUIDE` passes — it wins wherever
it differs from the default below, and may route to a dedicated issues guide; read it there
rather than working from this summary. With no such test, the default is all three of:
1. a defect — not an improvement, metric, or future cleanup;
2. user-reachable, **or** corrupts data, **or** is a broken safety net;
3. exists on the base branch today, **verified against code**.

Everything else is dropped, and say so. Merge survivors into `RUN_HOME/ledger.md` with
IDs (IDs are assigned at merge — that is what makes collisions impossible). **Never append
to `ledger.md`**; new observations are new files in `RUN_HOME/ledger-inbox/`.

Then order the work: security/data-loss → broken safety nets → correctness → polish.
Two issues touching the same lines are **one** brief, one PR, or they conflict.

## Phase 2 — Dispatch the orchestrator

Dispatch **one** orchestrator, `subagent_type: "stu:orchestrator"`, pointed at
`${CLAUDE_PLUGIN_ROOT}/skills/fix-campaign/orchestrator-charter.md` plus your ordered issue list with
per-issue traps. That agent definition carries its own model and effort — **do not pass
`model`**.

It dispatches the rest of the fleet by name: `stu:scout` (locate), `stu:verifier` (premise),
`stu:implementer` (build), `stu:reviewer` (review), `stu:merge-gate` (merge). Each carries its own
model, so an un-overridden dispatch does not silently inherit the session model.

**Never dispatch a `fork` as the orchestrator.** Forks are forbidden from spawning
subagents, so a fork given this job silently implements the entire campaign itself, and its
reports route to the main conversation instead of to it.

Then stay out of the way. Your job for the rest of the run is: relay misrouted reports,
verify load-bearing claims yourself, decide merges, and **respawn the orchestrator when it
hands off.**

### Respawning is yours, and a campaign stalls without it

The orchestrator has a hard budget of 120 turns — its cost grows with the square of its
run. So it will return **with work outstanding**, reporting a handoff path. That is the
design working, not a finished campaign.

An orchestrator does not spawn its own successor: nesting the role would defeat the budget.
**You do.** On a return that names a handoff path and lists outstanding work:

1. Read the handoff. Not the source files, worktrees, or diffs it names.
2. Dispatch **one** fresh `stu:orchestrator` carrying the **original campaign objective and
   issue list** *and* the **absolute handoff path**. Both, every time — the handoff holds
   progress, the objective holds what "done" means, and an orchestrator given only progress
   invents its own definition of done.
3. Record the new agent's ID.

Do not pass `model`. Do not dispatch two. If a third orchestrator would be needed for the
same issue list with no issues closed in between, stop and say the campaign is not
converging.

## Phase 3 — The merge gate

Under `/stu:run`, merging is `stu:merge-gate`'s job and it collects its own evidence.
**If the gate runs in label-handoff mode, read "When the gate runs in label-handoff mode,"
below, before this table** — it changes the rows and what "merged" means, and nothing in
this campaign ever merges directly through the forge in that mode.
Outside a supervised run, apply the same rows yourself:

| Gate | Why |
|---|---|
| CI green at the head SHA | — |
| Independent review verdict recorded at that SHA | Green ≠ reviewed. A PR has passed every check while its review still said approve-with-fixes. |
| Approve-with-fixes → fixes landed **and** re-reviewed | Not just re-run |
| You have seen the evidence | Counts from artifacts, not adjectives |

Merge one at a time; after each, confirm it landed on the unit row's `<remote>/<base>` and re-check every
remaining PR. (Exempt: integration merges into an epic branch under a `/stu:run`
`completion: integrated` objective — the objective's integrator makes those without the gate;
the FINAL PR to the base branch goes through it as above.) If one drops out of green, **stop** — don't force through.

**After every merge, query the state of EVERY issue the PR referenced.** `Refs` does not
prevent auto-closing — GitHub matches branch names and body patterns.

### When the gate runs in label-handoff mode

If `stu:merge-gate` runs in label-handoff mode (`agents/merge-gate.md`, "Merge mode"), the
table above changes and so does what "merged" means here.

**No CI row, when the label also gates CI.** Label-gated CI posts nothing about a PR before
it carries the label — the gate's own evidence, and this table, are about whether the SHA is
*review-done*, not whether CI already ran. That CI run is the CI evidence, and it is
gathered later, once the PR has actually merged (moment two, below).

This is two moments, not one — do not conflate applying the label with confirming it
worked. **Only `stu:merge-gate` ever applies the merge label in a campaign — never this
session, by hand, and never `stu:implementer`.** One applier per delivery mode: outside a
campaign the PR's own author applies it once the review is clean; inside one, only the gate
does, because only the gate re-checks the head immediately before applying it. (Integration
merges into an epic branch involve no label and are not the gate's; the FINAL PR to the base branch is.)

**Moment one — dispatch the gate.** One PR at a time: dispatch `stu:merge-gate` with the PR
number and worktree path, nothing else (never logs, verdicts, or a summary of the work —
that defeats its independence). On `PASS` it re-checks the head SHA itself and applies the
label at that exact SHA (enabling GitHub auto-merge too, where the `merge-mode` config section says so),
returning `READY: #<n> at <sha>`; CI tests the merge of that head into the current base branch and the
auto-merge actor (a daemon, or GitHub native auto-merge) merges on green, unattended — neither
this campaign nor the gate ever merges directly. Move to the next PR; if the gate returns `FAIL` for
one, **stop** on that PR — don't force through. A PR counts as labelled here, never as
merged.

**Moment two — dispatch the gate again, later, to confirm.** Applying the label does not
merge the PR, so checking issue state right after labelling would read stale data. Once you
have reason to believe auto-merge acted (a later check-in, a fresh triage pass), dispatch
`stu:merge-gate` again on the same PR — it sees `state: MERGED`, confirms the merge commit is
actually on `<remote>/<base>` itself (never trusting the PR's own `mergedAt` alone), verifies
the CI evidence (the gating check) at the merged SHA, and only then runs the issue-state audit.
A PR counts as merged only after the gate returns `LANDED: <sha>` — never on a PR's own
`mergedAt`, and never on an author's report.

**Escalate rather than decide** anything that is a product or design-system call. Give
the owner one question in prose, with the measurement settled and only the remedy open.

## Traps that bit a real run

Run `stu-env section tooling-traps --repo <the unit's row>` and treat each row it lists as part of this table. If it
printed nothing and exited 0, this table is the whole list; a nonzero exit is a stop, reported with its stderr.

| Trap | Do this |
|---|---|
| A red gating check tempts a rerun | Read the failing log first; rerun only on evidence of a flake unrelated to the change, stated in a PR comment |
| A CI retry can no-op while the badge shows stale red | Re-trigger and confirm from a fresh live log |
| A saved log can be from an earlier run | Read the live log for the head SHA |
| A later run can overwrite earlier results | Cite the results for this PR's head SHA |
| Backticks / `$(...)` / `$VAR` in an issue or PR **title** execute as shell | Re-read every title after creating it |
| Subagent **type** names aren't addressable | Record each agent's ID at dispatch |
| An unexplained red tempts blaming your branch | Reproduce on a clean checkout of `<remote>/<base>` first, in a fresh detached worktree (never a live one); the recipe is in the charter, "Worktree ownership — never write in a tree you did not create" (mutation-testing paragraph). The same red there means the base is red, not your change |

## Common mistakes

- **Implementing before verifying the premise.** Cheapest step in the campaign; catches ~20%.
- **Letting one agent write and review its own diff.** The reviewer must not be the author —
  every comment-decay and overclaiming-guard finding on the first campaign came from someone
  else.
- **A guard written from the author's mental model.** It tests the model, not the code.
  Derive from production's own constants, and assert both directions.
- **Accepting "tests pass" for a visual or absence defect.** A visual defect needs a measured
  check and a screenshot the owner can open; absence needs a metric before a fix.
- **Batching review fixes into a follow-up PR.** Same branch, always.
