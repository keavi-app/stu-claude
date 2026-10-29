---
name: settle
description: Use when a /stu:run has stopped and the owner wants to settle its parked questions before the next round — /stu:settle <objective path | handoff path | run slug>. Also use when the owner asks "any questions to settle?", "what do you need from me before the next run?", or pastes a supervisor's `Next: /stu:settle` line.
---

# `/stu:settle` — answer a stopped run's questions, then hand back one line

**Startup:** run `stu-env` once and keep its values: `RUN_HOME`, `WORKTREES_DIR`, `PROJECT_GUIDE`, `GITHUB_REPO`, `MAIN_CHECKOUT`. This file names them that way. `PROJECT_GUIDE` is a path under `MAIN_CHECKOUT`.

A fresh session, opened only to settle a stopped run. You read two small files the run wrote
decision-ready, walk the owner through what only the owner can answer, write the answers back where the
next supervisor reads them, and end with the exact `/stu:run` line to paste. **You never
run the work:** no orchestrators, no code, no merges.

## 1. Find the run

| Argument | Objective file |
|---|---|
| a path ending `-objective.md` | that file |
| any other `.md` path (a handoff) | `grep -l '<that path>' RUN_HOME/handoffs/*-objective.md` — the scoreboard's `Last handoff:` names it |
| a slug | `RUN_HOME/handoffs/*-<slug>-objective.md` |
| omitted | the newest objective whose `Run state:` reads `stopped` or `waiting-on-human`; if two qualify, ask which |

The questions file is the same path with `-questions.md`. **A run that parked nothing has
none, and a missing file is an empty question set**, not an error. Read both whole. From the
latest handoff for every lane (the scoreboard's `Last handoff:` lines), read
`## Decisions taken`, plus the `PER UNIT` rows of any readied unit (they carry its PR number).
Nothing else yet.

## 2. Check that the run is stopped

Read `Run state:` in the scoreboard.

- `stopped`, `waiting-on-human` or `settled` — go on. `waiting-on-human` means nothing is
  outstanding or parked, but a unit is Waiting or awaits the owner's push approval: the owner
  has actions to take, listed below.
- `running` — **stop here.** The supervisor may still write the objective, and answers
  recorded anywhere it does not read would be lost. Tell the owner the run is still going, and to
  settle once it prints its `Next: /stu:settle` line.
- missing (a run from before this field existed) — ask the owner once whether that session has
  ended, and treat the answer as the state.

Then check what is not a question, read-only, and report it in one short list: for every readied
unit that has not landed, the PR's state, labels, auto-merge request and merge state, taking `<n>`
from that unit's `PER UNIT` row. The command comes from `stu-env section auto-merge-setup --repo
<name>`; if it printed nothing and exited 0, use:

```
# GitHub example
gh pr view <n> --json state,labels,autoMergeRequest,mergeStateStatus
```

Report; never rerun, rebase, or relabel.

**Human actions.** `<run-dir>` is `RUN_HOME/runs/<slug>/`, the slug being the objective filename
minus `-objective.md`. Read the scoreboard's two lists, per lane:

- **`Awaiting approval:`** (`<id>@<branch>@<sha>`) is the list of approvals to give: a unit whose
  branch the run built and gated but may not push until the owner approves that exact sha. For each,
  show the gate summary read from `<run-dir>/gate/<id>@<sha>.txt`, labelled "relayed by the
  orchestrator" (the orchestrator saved it; the settle session did not check it). A missing file
  means no summary was saved: say so and give the entry without one.
- **`Waiting:`** (`<id> needs: <action> <ref>`) is the list of other human actions, in the
  `<action>` vocabulary: `merge <slug>#<pr>` (merge that passed PR), `tag <repo> at <sha>` (cut that
  tag), `approve <id> at <sha>`. Print each as the owner would read it.

For each approval the owner wants, print exactly this line, with the plugin root's absolute path
resolved (the value of `${CLAUDE_PLUGIN_ROOT}`), for the owner to type:

```
! "<plugin root>/bin/stu-approve" <id> <sha>
```

**Settle never writes an approval itself.** The approval is the owner's act, and the publish guard
refuses any tool call that writes it, so the line is for the owner to run. After it is recorded, the
next `/stu:run` resume (`stu-run-check --approved`) reopens the unit.

## 3. Sort what is waiting

Collect every questions-file entry that has no line in a `## Answers` section yet, and run
each through the park-or-decide test (`${CLAUDE_PLUGIN_ROOT}/agents/orchestrator.md`, "Park or
decide"). The test applies to questions written before it existed, too:

- **Rows 2-6 — ask the owner**, in this order: row 5 (surfaces) and 6 (scope) first, since those
  are where the owner most often chooses differently; then 4 (visual), then 3 (core semantics); row 2
  (production writes, credentials) last, each as its own message (step 4).
- **Row 1 or 7 — do not ask.** Decide it; step 4's skim filter says whether the owner sees it.

## 4. Walk the owner through it

**One question per message**, in plain product language:

1. What happened, with the worked example from the entry ("Before the change the screen showed X...").
2. The `Look at:` path. Show an image with the OS opener (`open <path>` on macOS, `xdg-open`
   on Linux) **and** Read it. Read alone is invisible to the owner: it feeds only the model, so
   the opener is what they see.
3. The options, one line each.
4. Your recommendation first, with its strength and one line of why. Say that "yes" takes it (row 2 excepted: only `authorize` does).

If the entry has no recommendation, form one before asking. When a recommendation turns on
a fact you do not have, one or two quick reads are fine; anything larger is a `stu:scout` or
`stu:verifier` dispatch. A recommendation you formed yourself that touches core domain semantics (row 3)
always gets a `stu:verifier` check first, never a quick read.

**Bundles.** An approval carrying N independent choices is N questions, or one bundle labelled
as such that the owner can split ("reply 1 yes, 2 no"). Never one "yes" over several choices.

**Row 2 (production write, credential).** Each authorisation is its own message, ending
"Reply `authorize` to approve". Any other reply is not consent: say so and ask again or park
it. Never send one in the same message as the skim list.

After the questions, show the **skim list** in one message. Candidates: every row-1/7 item
from step 3, and every `## Decisions taken` line not already in the objective's
`## Decisions reviewed` section (a handoff carries earlier decisions forward, so that section,
not the handoff, says the owner has seen one). **Show only `[skim]`-tagged handoff lines** (tag defined in
handoff-format.md, "Decisions taken") and row-1/7 items that meet the same test. The
rest goes to `## Decisions reviewed` as one line, `Not shown: <n> decisions, dated <date>`
(the dated heading is their watermark). Moot and n/a are never shown. Give each shown item a number, the decision,
and its `reverse by:` action. The owner says "fine" or "reverse 2, 5". If nothing passes the filter
and no question waits, the run needed no settle.

## 5. Write it back

**Questions file.** Append `## Answers — <YYYY-MM-DD>`, one line per unit: the answer, and
the owner's own words whenever they went beyond "yes" (an amendment, a third option, a reason).

**Objective file:**

- `## Rulings already given`: one line per answer and per reversal, dated.
- `## Decisions reviewed` (create it if absent): every skim-list decision the owner saw, one line
  each, as written in the handoff, under a dated heading, plus the `Not shown` line. This is the watermark the next
  settle checks against.
- Scoreboard, per lane:
  - An answered unit moves from `Parked` to `Outstanding`. That is a status change, not a
    membership change.
  - A unit the owner drops goes to `Closed` with `(dropped by the owner <date>)`. It stays in
    `Units issued`.
  - New work the owner asks for gets a new ID. Add it to the `## Units` table, `Units issued`,
    `Ever issued`, and `Outstanding`, and cite the owner's words in its ruling. Under `overnight`,
    it joins the lane whose contended resource it shares, since lanes must stay disjoint. If
    it shares none, ask the owner which lane in one line. Check it against
    `Ever issued` first: a reused ID is exactly what the supervisor's check 2 refuses.
  - Set `Run state: settled <date> — <one line: n answered, n unparked, n added, n dropped>`,
    **unless a unit is still Waiting or awaits approval**: then `Run state:` stays
    `waiting-on-human` (the answers above are still written) until they resolve.

Do not touch `Cycles used`, `Model overrides`, or the check-5 counters. They belong to
the supervisor, and the next `/stu:run` starts a fresh cycle count (the run skill's SKILL.md, "The cycle cap").

## 6. Hand back one line

```
/stu:run <Last handoff path> [overnight]
```

- **Path:** the scoreboard's `Last handoff:`. Under `overnight`, use the first lane that
  still has outstanding units; the supervisor reads every lane from the objective.
- **`overnight`:** include it exactly when the objective says `Mode: overnight`, even if
  only one lane has work left. Its scoreboard is lane-structured, and only an `overnight`
  supervisor reads lanes.
- **Nothing left:** if every unit is closed and nothing is outstanding, Waiting or awaiting
  approval, say the run is done and print no line. A Waiting unit is not done: a run that still
  has any is never reported done; tell the owner which actions remain and that the run resumes
  after them.

Tell the owner to run it in a fresh session (`/clear` first).

## Common mistakes

| Mistake | Instead |
|---|---|
| Asking a row-7 question because the run parked it | Decide it; show it only if it passes the skim filter |
| A question with no recommendation | Form one first. A lean counts. |
| Settling while `Run state: running` | Stop and tell the owner to settle after the run prints its `Next:` line |
| Deleting a dropped unit from `Units issued` | Close it with the dropped note; it stays issued |
| Fixing a stuck PR you found in step 2 | Report it; the next run or the owner acts on it |
| Recording an approval for the owner | Print the `stu-approve` line; only the owner types it |
| Several questions in one message | One at a time. No exceptions: a row-2 authorisation is its own message too. |
