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
   both to the owner in a few lines. This is the wave report; repeat it at the start of each
   wave. `spend` reports cycles and launches only and **does not enforce anything yet**.

## 2. The loop

Run `stu-fleet next <program path>` and read its **stdout**. It exits 12 with its full output
when the forge cannot answer for the merge lock's holder; that is not a failure here. Act on the
lines, then run `next` again after every state change.

- `start <slug>`: run `stu-fleet board launch <program path> --run <slug>`, then launch a
  supervisor (operation 1) for that run with a fresh `STU-SUPERVISED: <nonce>` line (a new
  random string per launch, never reused) and the objective path in its prompt, so it runs
  `/stu:run` in supervised mode. Keep its agent id and the nonce. Then wait (operation 3) with
  **one deadline per supervisor**, armed alongside the launch; never one shared deadline.
- `wait <slug> — <reason>`: nothing to do.
- `live <slug>`: nothing to do.
- `done <slug>`: nothing.
- `owner <slug> — needs <n> lanes, cap <cap>`: the run needs more lanes than the cap, so it can
  never start. Report it to the owner (operation 7 or 6) with the two fixes: raise
  `fleet_max_lanes` in the Stu config or the program's `Max live lanes:`, or split the objective.
  Never launch it. Lanes are counted from the objective's `Lane:` headings, minimum 1, so an
  `overnight` objective that has not written its lanes yet counts as 1 and can later hold more
  than the cap says; a launched run that turns out wider is the owner's to resize, not yours.
- `settle <slug>` and `settle <slug> owner-only`: **the settle brief loop is not built yet.**
  List it in the owner report (operation 7) with the objective path and the line
  `/stu:settle <objective path>`, and leave it unrequeued.
- `owner <slug> — <stop>` from the board: a stop that goes straight to the owner (conditions 4,
  7, 8, 9 and 11 of the run skill, or a wait on a merge, tag or approval). Send it to the owner
  as it is. Never relaunch it and never settle around it.
- `relaunch <slug> — <stop>`: **relaunch policy is not built yet.** Report it to the owner.
- `hold: set — <reason>`: the merge hold is set. Say so once in the wave report; gates refuse on
  their own.
- `lanes: <live>/<cap>`: the lane use. The cap counts lanes, not supervisors.

**A notification that carries no supervisor return block is interim:** one line, no action. A
supervisor return is the block that ends with `STU-RUN:` through `NEXT:` (`skills/run/handoff-format.md`,
section 4). When one arrives, write the block to a file under `RUN_HOME` (the run's own folder,
`RUN_HOME/runs/<slug>/`), then run
`stu-fleet board record <program path> --run <slug> --return <file>`. A refusal (exit 1 or 13)
goes to the owner as it is; do not edit the board to get past it. Then run `next`, which now
shows the board state `record` set.

`requeue` (`stu-fleet board requeue`) happens only after the owner has settled or answered,
never before, and never on your own judgment.

## 3. What you read, and what you do not

You read board lines, supervisor return blocks, and `next` and `spend` output. Not diffs, logs,
handoffs or reports. A fact you need that is not on those goes to a `stu:verifier` (operation
2), which returns HOLDS, STALE, WRONG or VACUOUS with evidence. You never run a cycle, groom a
brief, review a diff, merge, or write an objective, scoreboard or the main checkout. The board is
written only by `stu-fleet`.

## 4. Context and handoff

Hand off to a fresh coordinator at **120k context, at a wave boundary** (no supervisor
mid-return). The board is the resume state: a handoff names the program path and the supervisors
still live (their slugs, agent ids and nonces) and nothing else the board holds. The next
coordinator starts at "Startup", then `next`; for each live supervisor it re-arms one deadline
(operation 3) and checks it is still alive (operation 4).

## 5. Not built yet

Stated here so nothing assumes it:

- Liveness and relaunch: no idle-tree check or relaunch of a supervisor that stops silently, and
  no relaunch policy. A supervisor with no return is found by its deadline and reported to the
  owner, not restarted. (S10.)
- Budget enforcement and the loop guard: `spend` reports and nothing refuses. (S10.)
- The settle brief loop: settle and owner-only settle stops are listed for the owner. (S11.)
- Judgment seats other than the settler and verifier (groom, audit, design).
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
   exactly as the run skill's "Liveness" describes. Keep its task id, and `TaskStop` it when the
   return is accepted. When it fires, take operation 4 before doing anything else.
4. **List descendants:** `stu-tree --root <supervisor agent id>` (exit 0 means something in the
   tree is live). `ListAgents` is not available inside a subagent and is not used.
5. **Stop a supervisor:** `TaskStop` with its agent id.
6. **Owner brief and answer:** a message to the owner and their reply in the same session.
7. **One-way notify:** `PushNotification` if it is available, otherwise an ordinary message.
