---
name: fleet
description: Use when the owner wants several objectives run at once from one coordinator session — /stu:fleet <program path>. Experimental. Interactive main session only; it launches one supervisor per objective, keeps the fleet board, and brings the owner what needs them.
allowed-tools:
  - Agent
  - TaskStop
  - Bash
  - Write
  - PushNotification
---

# `/stu:fleet` — one coordinator, several supervised runs

**Startup:** run `stu-env` once and keep its values: `RUN_HOME`, `WORKTREES_DIR`, `PROJECT_GUIDE`, `GITHUB_REPO`, `MAIN_CHECKOUT`. This file names them that way. `PROJECT_GUIDE` is a path under `MAIN_CHECKOUT`.

Experimental. The design is `docs/fleet-design.md` (the program file format is there). You are
the **coordinator**: the interactive main session. You never run a cycle yourself and never
write the main checkout. The scripts hold the state and make the decisions; you carry them out
and report. Everything runtime-specific is in "Runtime binding" at the end; the rest of this
file names seven **operations** and is otherwise about files, scripts and schemas.

The seven operations:

1. launch a supervisor;
2. dispatch a seat agent (verifier, settler, scout) with a model;
3. wait for a return or a deadline, whichever comes first, and re-arm the deadline;
4. list a supervisor's live descendants;
5. stop a supervisor;
6. send the owner a brief and receive their one-line answer;
7. notify the owner one-way.

## 1. Startup

1. Run `stu-fleet program check <program path>`. Exit 0 is required. Anything else: stop and
   show its `BLOCKED` lines verbatim. An unreadable path is a stop too.
2. Compare the program's `Merge lock:` line (absent means `on`) with `MERGE_LOCK` from
   `stu-env`. A gate reads only the config, never the program, so a program that wants the lock
   while the config says `off` would be silently ignored. When they disagree, stop and name the
   fix: set `merge_lock: on` (or `off`, to match the program) in the Stu config, or change the
   program's line. Do not edit either yourself.
3. Run `stu-fleet board show <program path>` and `stu-fleet spend <program path>` and report
   both to the owner in a few lines, plus `stu-fleet actuals <program path>` condensed to a few
   lines (agents, output tokens, and the off-route share, if `actuals` prints one; `actuals: none
   recorded` is just said). This is the wave report; repeat it at the start of each wave. The
   `budget:` and `judgment-jobs:` lines go in it. `spend` and `actuals` only report; the limits
   are enforced by `next` and the `board` commands (see "Limits" below).

## 2. The loop

Run `stu-fleet next <program path>` and read its **stdout**. It exits 12 with its full output
when the forge cannot answer for the merge lock's holder; that is not a failure here. Any other
nonzero exit from `stu-fleet` (1, 2, 3 or 13, from `program`, `board` or `next`) stops the loop:
show its `REFUSED` or `BLOCKED` lines to the owner as they are and do nothing else until they
answer. Act on the lines, then run `next` again after every state change.

- `start <slug>`: run `stu-fleet board launch <program path> --run <slug>` (it accepts only a
  `queued` run). Its **last stdout line** is `nonce: <nonce>`; launch a supervisor (operation 1)
  for that run with `STU-SUPERVISED: <nonce>` using exactly that nonce, never one you generate,
  and the objective path in its prompt, so it runs `/stu:run` in supervised mode. Keep its agent
  id and the nonce. Then wait (operation 3) with **one deadline per supervisor**, armed alongside
  the launch; never one shared deadline.
  **When the deadline fires,** check the supervisor's tree (operation 4). Alive: re-arm the
  deadline, with no bound on the number of re-arms, because a healthy supervisor legitimately
  runs 4 to 7 hours or more. Idle (nothing live and no return has arrived): first stop the old
  supervisor (operation 5), and only after it is stopped run
  `stu-fleet board idle <program path> --run <slug>`, then `next`. Never two supervisors on one
  unit list: `board idle` comes only after the stop. A refusal (13) goes to the owner as printed.
  The run skill's repair message, single restart and 6-hour re-arm bound are for orchestrators
  and do not apply to supervisors.
- `wait <slug> — <reason>`: nothing to do.
- `live <slug>`: nothing to do.
- `done <slug>`: nothing.
- `owner <slug> — needs <n> lanes, cap <cap>`: the run needs more lanes than the cap, so it can
  never start. Report it to the owner (operation 7 or 6) with the two fixes: raise
  `fleet_max_lanes` in the Stu config or the program's `Max live lanes:`, or split the objective.
  Never launch it. A Runs line declares `lanes: <n>`, required for an overnight objective (a
  run's lane count is the larger of that and its `Lane:` headings, minimum 1).
- `owner <slug> — cycle budget spent ...`, `owner <slug> — stop at ... passed` and
  `owner <slug> — loop guard ...`: a limit. Send the line to the owner with the fix: only the
  owner raises the cycle budget or `Stop at:` or edits the program, or looks at why two launches
  closed no unit. You never raise a limit or edit the program. Live supervisors are never
  stopped for a limit; only starts and relaunches are held.
- `settle <slug>` or `settle <slug> owner-only`: dispatch a `stu:settler` (operation 2) with
  `MODE: draft` and the objective path; the model is the judgment-model value (empty means
  opus). Several in one message when several runs are in `settle`. A settler dispatch is never
  counted as a judgment job. Save its return under `RUN_HOME/runs/<slug>/settle/`, then run
  `stu-fleet board draft <program path> --run <slug> --return <file>`. A `BLOCKED` settler
  return, a refusal, or a `board draft` refusal goes to the owner with the line
  `/stu:settle <objective path>`, and the run is left alone. `owner-only` changes nothing in
  draft mode (every item is drafted for the owner already); it matters only to the later
  auto-narrow mode.
- `brief <slug>`: once `next` shows no `settle` line still drafting (every pending draft is in),
  send the output of `stu-fleet brief <program path>` to the owner exactly as printed
  (operation 6). Other runs keep moving while it is open.
- **The owner's answer.** Run `stu-fleet answer <program path> --line "<reply verbatim>"`. Exit 1:
  show its `BLOCKED` lines and ask again. For each line
  `answer <slug> | draft: <path> | line: <text>`, dispatch a `stu:settler` with `MODE: write`,
  the draft path and the text verbatim; save its return under `RUN_HOME/runs/<slug>/settle/`; run
  `stu-fleet board settled <program path> --run <slug> --return <file>`. Its last line is
  `requeued <slug>` (the run is queued, and `next` starts it) or
  `pending <slug>: <ids>` (the run stays in the brief). An `unanswered <slug>` line from
  `answer` also stays in the brief.
- `talk about <n>`: discuss that item with the owner in this session, one question per message,
  as the settle skill's step 4 does (the worked example, the options, your recommendation first).
  It ends in a follow-up answer for that run, `<slug>: accept <n>` or
  `<slug>: reverse <n> <their words>`, which goes through `answer` and a write dispatch like any
  other.
- A `board settled` refusal (13), for an `add` or any other reason: give the owner the printed
  line, which names `/stu:settle <objective path>`. After the owner says that settle is done,
  run `stu-fleet board requeue <program path> --run <slug>`.
- You never write the objective or the scoreboard, and you never perform a `SCOREBOARD-TODO`
  yourself: `board settled` does.
- `owner <slug> — <stop>` from the board: a stop that goes straight to the owner (conditions 4,
  7, 8, 9 and 11 of the run skill, or a wait on a merge, tag or approval). Send it to the owner
  as it is. Never relaunch it and never settle around it.
- `relaunch <slug> — <stop>`: an instruction. Run
  `stu-fleet board relaunch <program path> --run <slug>`; it re-checks the limits under its lock,
  writes `Run state: fleet-relaunch <date>` into the objective (you never write the objective),
  goes live and prints the nonce as its last line. Then launch a supervisor with that nonce,
  exactly as for `start`, with its own deadline. A refusal (13) goes to the owner as printed.
- `notice: ...`: a limit passed 80% or 100% (or Stop at passed). Tell the owner once, as printed;
  the script prints each notice once ever.
- `budget: ...` and `judgment-jobs: ...`: go in the wave report.
- `lock: held by <pr> — <reason>; not released`: the merge lock holder could not be checked on
  the forge. Say so once in the wave report; the lock stays held and gates handle it.
- `hold: set — <reason>`: the merge hold is set. Say so once in the wave report; gates refuse on
  their own.
- `lanes: <live>/<cap>`: the lane use. The cap counts lanes, not supervisors.

**A notification that carries no supervisor return block is interim:** one line, no action. A
supervisor return is the block that ends with `STU-RUN:` through `NEXT:` (`skills/run/handoff-format.md`,
section 4). When one arrives, write the block to a file under `RUN_HOME` (the run's own folder,
`RUN_HOME/runs/<slug>/`), then run
`stu-fleet board record <program path> --run <slug> --return <file>`. A refusal (exit 1 or 13)
goes to the owner as it is; do not edit the board to get past it. Then run `next`, which now
shows the board state `record` set. If `record` or `idle` prints `actuals: unavailable — <reason>`,
report it once in the wave report; it is never a stop and the record still succeeded.

`requeue` (`stu-fleet board requeue`) is for a settle the owner did by hand with `/stu:settle`,
and only after they say it is done, never before and never on your own judgment. A settle done
through `answer` and `board settled` requeues itself.

## 3. What you read, and what you do not

You read board lines, supervisor return blocks, settler returns, and `next`, `spend`, `actuals`,
`brief` and `answer` output. Not diffs, logs, handoffs, reports or the settler's draft files. A fact you need that is not on those goes to a `stu:verifier` (operation
2), which returns HOLDS, STALE, WRONG or VACUOUS with evidence. You never run a cycle, groom a
brief, review a diff, merge, or write an objective, scoreboard or the main checkout. The board is
written only by `stu-fleet`.

## 4. Context and handoff

Hand off to a fresh coordinator at **120k context, at a wave boundary** (no supervisor
mid-return). The board is the resume state: a handoff names the program path and the supervisors
still live (their slugs, agent ids and nonces) and nothing else the board holds. The next
coordinator starts at "Startup", then `next`; for each live supervisor it re-arms one deadline
(operation 3) and checks it is still alive (operation 4).

## 5. Judgment jobs

Before any groom, audit or design dispatch (none exist yet), run
`stu-fleet board judgment <program path> --job <slug>`; a refusal means do not dispatch, and show it to the owner as printed. Settler
drafts and verifier or scout dispatches are never counted.

## 6. Not built yet

Stated here so nothing assumes it:

- Judgment seats other than the settler and verifier (groom, audit, design).
- Auto-narrow settle mode (a program that asks for it behaves as draft mode).
- Codex: there is no Codex binding for this skill; `codex/runtime.md` says `fleet: not bound yet`.

## Runtime binding

This is the only section that names a Claude tool or agent-invocation detail. A runtime that is
not Claude Code writes its own seven lines in `codex/runtime.md`.

1. **Launch a supervisor:** a background `Agent` call with `subagent_type: "stu:supervisor"`,
   `run_in_background: true`, and a prompt of the `STU-SUPERVISED: <nonce>` line plus the
   objective path. No `model` is passed: a supervisor inherits the launcher's model.
2. **Dispatch a seat:** an `Agent` call with the seat's `stu:` type (`stu:verifier`,
   `stu:settler`, `stu:scout`) and its `model`. The settler's model is the value of
   `stu-env section judgment-model`; empty means `opus`. Verifier and scout use the models the run
   skill's routing table gives them.
3. **Wait:** the completion notification of the background `Agent` call, plus one background
   `Bash` command per supervisor (`sleep 5400` with `run_in_background` and `timeout: 5500000`),
   the same arming as the run skill's "Liveness" (timer arming and `TaskStop` on return only).
   Keep its task id, and `TaskStop` it when the return is accepted. When it fires, take
   operation 4 and apply the supervisor rule in "The loop": re-arm with no bound while the tree is
   alive, stop it (operation 5) and run `board idle`, as in "The loop". The run skill's repair, restart and 6-hour bound do not
   apply to supervisors.
4. **List descendants:** `stu-tree --root <supervisor agent id>` (exit 0 means something in the
   tree is live). `ListAgents` is not available inside a subagent and is not used.
5. **Stop a supervisor:** `TaskStop` with its agent id.
6. **Owner brief and answer:** a message to the owner and their reply in the same session.
7. **One-way notify:** `PushNotification` if it is available, otherwise an ordinary message.
