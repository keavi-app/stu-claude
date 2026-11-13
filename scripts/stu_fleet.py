#!/usr/bin/env python3
"""stu-fleet: the merge hold and lock, and the fleet program, board, spend and next.

  stu-fleet hold set --reason TEXT      set the hold; prints the lock holder to disarm
  stu-fleet hold clear                  clear the hold; re-arms nothing
  stu-fleet hold status                 exit 10 while the hold is set, else 0
  stu-fleet lock take --slug OWNER/REPO --pr N --sha SHA [--label NAME]
                                        take the lock in one locked step
  stu-fleet lock release --pr N [--slug OWNER/REPO] [--landed]
                                        release it (idempotent); --landed records a landing
  stu-fleet lock status                 the holder, if any

  stu-fleet program check PROGRAM       parse and validate a fleet program file
  stu-fleet board show PROGRAM          print the board (a queued row for every run with none); under a
                                        queued run that `next` holds as fed, an indented
                                        `  wait: fed by <job> (<job state>)` line (display only)
  stu-fleet board launch PROGRAM --run SLUG
                                        mark a queued run live (any other state is refused 13); records the cycle count it resumes from
  stu-fleet board record PROGRAM --run SLUG --return FILE
                                        fold a supervisor return into the run's board line
  stu-fleet board requeue PROGRAM --run SLUG
                                        settle|relaunch|owner -> queued
  stu-fleet board idle PROGRAM --run SLUG
                                        a live supervisor found idle and stopped, no return -> relaunch
  stu-fleet board relaunch PROGRAM --run SLUG
                                        relaunch a run the policy allows now; prints the new nonce
  stu-fleet board judgment PROGRAM --job SLUG
                                        a queued groom, audit or design job -> live; counts one dispatch
  stu-fleet board judged PROGRAM --job SLUG --return FILE
                                        fold a live job's GROOMER or DESIGNER return (exit 1 unless it
                                        validates): done, owner, verdict, or queued on a usage limit
  stu-fleet board verdict PROGRAM --job SLUG --line TEXT [--done]
                                        append the owner's line, dated, to <output>/VERDICT.md; a verdict
                                        job -> done (--done) or queued (the next round)
  stu-fleet board requeue PROGRAM --job SLUG
                                        owner or verdict -> queued; requeuing the one job marked
                                        `usage limit` lifts the pause for every judgment job
  stu-fleet board idle PROGRAM --job SLUG
                                        a live job's seat found idle and stopped -> owner
  stu-fleet spend PROGRAM               cycles, launches, dry launches, agents and output tokens per
                                        run; budget, judgment jobs and Stop at
  stu-fleet actuals PROGRAM             read-only: per run and fleet, launches, agents, output tokens
                                        and a seat/model table from the detail log
  stu-fleet board draft PROGRAM --run SLUG --return FILE
                                        record a settle run's DRAFTED settler return (refused 13 unless
                                        settle with no draft; exit 1 unless it validates for the run)
  stu-fleet board settled PROGRAM --run SLUG --return FILE
                                        apply a WRITTEN settler return to the scoreboard and board
  stu-fleet brief PROGRAM               read-only: every drafted brief, written items hidden, one Answer line
  stu-fleet answer PROGRAM --line TEXT  read-only: route the owner's reply to the runs with drafts
  stu-fleet next PROGRAM                one decision line per run, notices, hold, lanes, limits

State: <RUN_HOME>/merge-hold.json (override: STU_FLEET_FILE), RUN_HOME from stu-env. Every
read-modify-write runs under an exclusive flock on a sibling `.lock` file and replaces the
state file atomically. An unreadable state file is an error (exit 3), never "no hold".

The program file (docs/fleet-design.md, "The program file") carries the board in its
`## Fleet board` section, one run line per run in Runs order, then one fleet line, always last:

  - <slug> | state: <queued|live|settle|relaunch|owner|done> | cycles: <n> | launches: <n> |
    from: <n> | closed: <n> | dry: <n> | nonce: <nonce|none> | agents: <n> | out: <n> |
    draft: <abs path|none> | written: <comma list of item numbers|none> |
    handoff: <abs path|none> | stop: <none|STOP-CONDITION verbatim>
  - fleet | judgment: <n> | agents: <n> | out: <n> | notices: <none|comma list of cycle-80,
    cycle-100,judgment-80,judgment-100,stop-at>

After the run lines and before the fleet line come the job lines (v5), one per `## Judgment work`
line, in that order:

  - job <slug> | state: <queued|live|verdict|owner|done> | dispatches: <n> | output: <abs path|none> |
    stop: <none|one line>

A v4 board (no job lines) reads as every job queued, dispatches 0; the next write emits v5. A job
line for a slug not under Judgment work, a run line after a job line, or a duplicate is exit 3. A
job slug equal to a run slug or `fleet` is a `program check` problem. `feeds: <run>` means the job
writes that run's objective: `program check` reports `run <slug>: objective pending (fed by <job>)`
instead of blocking a missing objective, `next` prints `wait <run> — fed by <job> (<state>)` until the
job is done, then `owner <run> — fed by <job>, objective missing or invalid: <detail>` if the file
fails the objective checks. `next` prints each job after the run lines: `judge <slug>` (queued, limits
allow), `owner job <slug> — <reason>` (owner state, spent judgment jobs, Stop at passed, or the
usage-limit pause: every queued job prints it, the one job marked `usage limit` says to requeue it),
`verdict job <slug> — <output>`, `live job <slug>`,
`done job <slug>`. `board judgment` is refused (13) on a job that is not queued or while paused;
`judged` on a job that is not live; `verdict` on a job not in verdict or whose output is not an
existing absolute directory; `requeue --job` on a job that is none of owner, verdict or the
marked usage-limit job; `judged` on a designer READY whose OUTPUT is not an existing directory
(exit 1, BLOCKED, the job stays live, nothing written); `idle --job`
on a job that is not live. `--run` and `--job` are mutually exclusive (exit 2).

(one physical line each; `|` inside copied text is written `/`). `fleet` is reserved: a run slug
named `fleet` is a `program check` problem. A v1 run line (the seven fields without closed, dry
and nonce) reads as closed 0, dry 0, nonce none, a v2 line (no agents, out) as agents 0, out 0,
and a missing fleet line as judgment 0, notices none; the next write emits v4. A v3 line (no
draft, written) reads as `draft: none`, `written: none`. Anything else malformed, a fleet line that is not last, a
duplicate, or an unknown notice id is exit 3. Only stu-fleet writes the section: under an
exclusive flock on `<program>.lock`, replacing the program file atomically and touching nothing
outside that section. `cycles` is fleet-cumulative; `from` is the count the current launch
resumed from, taken from the objective's `Run state:` and `Cycles used:` by `resume_count`
(the run skill's "The cycle cap"); `closed` is the number of distinct unit IDs in the
objective's `Closed:` lines (first word of each comma-separated item, union across `Lane:`
blocks, NONE is 0) when the current launch began; `dry` counts consecutive launches that ended
with no new closed unit; `nonce` is the current launch's. A board line naming a slug not in
Runs, or a malformed one, is an error (exit 3), never dropped. `program check` prints a
normalized summary, or one `line N BLOCKED: <detail>` per problem then `BLOCKED`. Every other
program command refuses a program with problems the same way (exit 1).

A Runs line takes an optional trailing `| lanes: <n>`. A run's lane count is
max(declared, counted `Lane:` headings, 1). `program check` blocks an objective whose header
says `Mode: overnight` without `lanes:`, and a plain objective declaring anything but 1.

`board launch` marks a run live, snapshots `from` and `closed`, stores a fresh random nonce
(`stu-<hex>`, agent_tree's NONCE_RE) and prints the board line, then `nonce: <nonce>` as its
last line. `board record` validates the return with `run_check.check_supervisor_return` (the
same validator as `stu-run-check --supervisor-return`), refuses a return for another objective,
and refuses unless the run is live and the cycle delta is not negative. `board record` and
`board idle` apply the loop guard (always on): the objective's closed count now, not greater than
the launch's `closed`, adds 1 to `dry`, else resets it; a resulting `relaunch` with dry >= 2
becomes `owner` with stop `loop guard — 2 launches closed no unit; last stop: <that stop>`.
`done`, `settle` and `owner` outcomes keep their state. `board idle` (refused 13 unless live)
is for a supervisor the coordinator found idle and already stopped: state relaunch, stop
`idle — no return`, handoff = the objective scoreboard's first `Last handoff:` (`none` if
absent), cycles += `Cycles used` numerator - `from` (a negative delta is refused, never clamped).

Actuals (docs/fleet-design.md, "The board records actuals"): `agents` and `out` (output tokens) are
cumulative across launches. `board record` and `board idle` call fleet_actuals.launch_actuals on
the launch's nonce (the supervisor is found in any session under the projects root; its tree is
every agent its `parentAgentId` chain reaches), add the launch's agent count and output tokens to
the run line, and append one JSON line to `<program>.actuals.jsonl`, under the same flock:
`{slug, nonce, recorded_at, agents, out, by_seat_model: [{seat, model, agents, turns, out}]}` or
`{slug, nonce, recorded_at, unavailable: <reason>}`. Unavailable actuals (no transcript, zero or
several nonce matches) add nothing, print `actuals: unavailable \u2014 <reason>` after the board line
and never fail the command. The fleet line's `agents` and `out` are the sums over the run lines,
recomputed at every write. `actuals` prints, from the log, for each run with entries and then the
fleet: `<run <slug>|fleet>: launches <n>, agents <n>, out <n>` (`, unavailable <n>` appended when
some launches were), the header `seat model agents turns out`, one `<seat> <model> <agents> <turns>
<out>` row per seat and model, then `off-route <seat>: <off>/<total> turns not on <family> (<pct>%)`
for each `stu:` seat whose `agents/<name>.md` names a `model:` (a model counts as on route when
its id contains the family name), and `routing unknown: <seats>` for the rest; an empty or absent
log prints `actuals: none recorded`. A damaged final log line is skipped with a printed warning
(a crash mid-append); a damaged line anywhere else is exit 3. A `stu:` seat whose routing a
dispatch can override (the settler) prints under `routing unknown`; records with no model are in
the table but not in the off-route share. Actuals are a report: nothing enforces on them.

`board relaunch` is refused (13) unless the run is `relaunch` and the `next` policy says
`relaunch` for it right now (re-evaluated under the lock, so a stale `next` cannot override a
limit). Then, in one step, it rewrites the first `Run state:` line inside the objective's
`## Scoreboard` to `fleet-relaunch <YYYY-MM-DD>` (the program clock's date) and launches as
`board launch` does (so `from` is 0), printing the board line and the nonce. This is one of
two places stu-fleet writes an objective (the other is `board settled`, below), both through one
writer: under a flock on `<objective>.lock`, atomic replace, nothing else in the file changes; an objective with no `## Scoreboard` or no `Run state:` there
is refused (13) before anything is written. It never edits a `Cycle cap:`.

The settle loop (docs/fleet-design.md, "Settling"). `draft` is the absolute path of the saved
DRAFTED settler return for the run's current settle, `written` the brief item numbers already
written from it; `board record`, `launch`, `relaunch`, `idle` and `requeue` reset both to none.
`board draft` is refused (13) unless the run is `settle` with `draft: none`; the return must
validate (settler_return.check), be `SETTLER: DRAFTED` and name the run's objective (exit 1,
`BLOCKED: <problem>` lines then `BLOCKED`, otherwise); it also clears the run's counts in the
sidecar `<program>.settle.json`. That sidecar holds, per run, the draft path and the SETS of ids
named by `unpark` and `drop` TODOs under it (applied or already done; the summary counts are the
set sizes, so a retry after a crash between the objective write and the board write counts the
same). `board settled` writes it when the run stays `settle`; `board draft` and a finishing
`board settled` clear the run's entry; it is the only place those ids live between calls. `next` prints `brief <slug>` for a
`settle` run with a draft, else `settle <slug>[ owner-only]` as before.
`board settled` is refused (13) unless the run is `settle` with a draft. The return must validate
as `SETTLER: WRITTEN` with the same OBJECTIVE and DRAFT as the stored drafted return (exit 1
otherwise). Under the program lock and a flock on `<objective>.lock` it checks everything before it
writes anything, then rewrites only scoreboard lines, atomically. Refused (13), nothing written: an
`add` TODO (`fleet-board: <slug> adds unit <id>; settle it with /stu:settle <objective path>`), an
`unpark` of an id in no lane's `Parked:` and not already `Outstanding:`, a `drop` of an id in no
lane's `Parked:`/`Outstanding:` and not already dropped in `Closed:`, an objective with no
`## Scoreboard` (or, finishing, no `Run state:` in it), a `Run state:` reading `running`. `unpark` and `drop` move the id between the
lane's `Parked:`/`Outstanding:`/`Closed:` lines (`NONE` when empty; a drop appends `<id> (dropped
by the owner <date>)` unless `Closed:` already has one); repeats are no-ops. `written` becomes its union with the return's WRITTEN
ids. With `UNANSWERED: none` the first `Run state:` in the scoreboard becomes `waiting-on-human`
when any lane's `Waiting:` or `Awaiting approval:` is not NONE, else `settled <date> — <w>
answered, <u> unparked, 0 added, <d> dropped`, and the run goes to `queued` with draft and
written reset, unless no unit is left Outstanding, Parked, Waiting or Awaiting approval in any
lane (a finished run whose only open items were `[skim]` decisions): then it goes to `done`, never
`requeued`, since a relaunch would spend a cycle on nothing. Otherwise the run stays `settle`. The
last stdout line is `requeued <slug>`, `done <slug>` or `pending <slug>: <unanswered R ids>`. `brief` (read-only) prints, for each run with a draft in
Runs order, the drafted BRIEF block without its `BRIEF:` label, its own `Answer:` line and the
numbered item lines already written, then a blank line, then one `Answer:` line for the whole
brief (`Answer: <slug>: fine | accept 2 | reverse 2, 5 | talk about 3` for one run, `Answer per
run, one per line or separated by ';': <slug>: <answer>` for several); `brief: none` with no
drafts. `answer` (read-only) splits `--line` on newlines and `;` into `<slug>: <answer>`
segments (a segment with no slug belongs to the only run with a draft); it prints `answer <slug>
| draft: <DRAFT path> | line: <answer>` for each answered run and `unanswered <slug>` for each
drafted run left out, or exit 1 with `BLOCKED: <detail>` lines then `BLOCKED` for an unknown or
draft-less slug, a slug twice, or an accept, reverse or talk about number outside 1..RULINGS or
already written. It does not interpret the answer further.

Limits, evaluated by one function for `next`, `spend`, `board relaunch` and `board judgment`:
the cycle budget (used = sum of board `cycles`; limit = `Cycle budget:`, default the sum of the
runs' caps, `none` = no limit; spent at used >= limit), judgment jobs (used = the fleet line's
`judgment`; `Judgment jobs:`, default none; spent at used >= limit) and `Stop at:` (passed when
the program clock is at or after it). Limits are never raised or edited here. `board judgment
--job SLUG` counts one dispatch (SLUG must be a `## Judgment work` line, else exit 1); it is
refused (13) when judgment jobs are spent or Stop at has passed; it prints
`judgment-jobs: <used>/<limit|none>`.

`next` prints, in Runs order, `start|wait|settle|owner|relaunch|live|done <slug>` lines (`—`
separates the reason). A queued run that would start, and a `relaunch` run, become
`owner <slug> — cycle budget spent <used>/<limit>` or `owner <slug> — stop at <time> passed`
(cycle budget first); otherwise a `relaunch` run prints `relaunch <slug> — <stop>`, after the
same `after:`, resource and lane checks as `start` (`wait` with the same reasons when they block).
A live run is never stopped by a limit. After the run lines: one `notice: cycle-budget|
judgment-jobs 80|100% (<used>/<limit>)` per limit at or over that mark and `notice: stop-at
passed (<time>)`, each printed once per program ever (recorded in the fleet line's `notices`
under the program lock, before printing); then `hold: set — <reason>` or `hold: clear`, then
`lanes: <live>/<cap>`, `budget: <used>/<limit|none>` and `judgment-jobs: <used>/<limit|none>`.
`spend` prints `run <slug>: cycles <n>, launches <n>, dry <n>, agents <n>, out <n>` per run,
`fleet: cycles <n>, agents <n>, out <n>`,
`budget: <used>/<limit> (<pct>%)` or `<used>/none`, `judgment-jobs: <used>/<limit|none>` and
`stop-at: <time|none> (passed|not passed)`. Before `next` prints anything else it observes the
merge lock holder on the forge and releases it when its PR merged, closed or lost its label
(`lock: released ...`); a holder the forge cannot answer for stays held, the full output is still
printed, and the exit is 12. The effective lane cap is the program's `Max live lanes:`, else
FLEET_MAX_LANES from stu-env (default 4), lowered by `runtime_lane_limit()` where a runtime
reports a slot limit (none on Claude).

`lock take`, in one locked step: if the lock is held by another PR, the holder is checked on
the forge (`stu-forge pr-state`) and released when its PR is merged or closed, or when its
merge label is gone, its auto-merge is off, and the lock is older than a grace period (a gate takes the lock before it
labels, so a fresh lock with no label yet is not abandoned). The forge being unreachable is a
refusal, never an assumption. Then it refuses if the hold is set, then if another PR still
holds the lock; otherwise it records slug, PR, sha and time (re-entrant for the same slug+PR).

The environment variables STU_FLEET_FILE, STU_FLEET_FORGE, STU_FLEET_NOW,
STU_FLEET_LABEL_GRACE, STU_FLEET_MAX_LANES and STU_FLEET_NONCE are TEST-ONLY hooks (state file
path, stand-in forge command, clock, grace, lane cap used when the program has no `Max live
lanes:`, a fixed launch nonce; STU_PROJECTS_ROOT, agent_tree's, points actuals at a fixture); nothing
in a real run sets them. `hold status` and `lock status` are read-only: they take no
flock (writes replace the file atomically) and never call the forge. `program check`,
`board show`, `spend` and `actuals` are read-only too.

Exit codes: 0 ok; 1 the program file or a supervisor return is invalid (BLOCKED lines);
2 usage; 3 error (state file, run home, unreadable program, malformed board); 10 refused, hold
set; 11 refused, lock held; 12 refused, holder not checkable on the forge; 13 refused, board
state (launching a run that is not queued, recording or idling a run that is not live, a negative cycle
delta, requeuing from a state that cannot be requeued, relaunching a run the policy does not
allow, a judgment job past its limit or Stop at, an objective with no `Run state:` to rewrite, `board draft` or `board settled` on a run in the wrong
state, a `board settled` that would move an id that is not there or add a unit). A refusal prints one line that
begins `REFUSED ` followed by the reason text a gate returns (`fleet-hold: ...`,
`fleet-lock: ...` or `fleet-board: ...`).
"""
import fcntl
import json
import os
import re
import secrets
import subprocess
import sys
import stat
import tempfile
import time
from datetime import datetime, timezone

EXIT_INVALID, EXIT_USAGE, EXIT_ERROR = 1, 2, 3
EXIT_HOLD, EXIT_LOCKED, EXIT_FORGE, EXIT_BOARD = 10, 11, 12, 13
FMT = "%Y-%m-%dT%H:%M:%SZ"
DEFAULT_GRACE = 900  # seconds a lock may sit without its label before it counts as abandoned
HERE = os.path.dirname(os.path.abspath(__file__))


class Fail(Exception):
    def __init__(self, code, msg):
        Exception.__init__(self, msg)
        self.code = code
        self.msg = msg


def now_epoch():
    override = os.environ.get("STU_FLEET_NOW")  # tests only
    return float(override) if override else time.time()


def stamp(epoch=None):
    return datetime.fromtimestamp(now_epoch() if epoch is None else epoch,
                                  timezone.utc).strftime(FMT)


def parse_stamp(text):
    return datetime.strptime(text, FMT).replace(tzinfo=timezone.utc).timestamp()


def state_path():
    override = os.environ.get("STU_FLEET_FILE")
    if override:
        return override
    sys.path.insert(0, HERE)
    try:
        import stu_env
        try:
            try:
                env = stu_env.resolve(require_config=True)
            except stu_env.NoConfig:
                env = stu_env.resolve(require_config=False)
        except stu_env.ConfigError as e:
            raise Fail(EXIT_ERROR, "cannot resolve RUN_HOME: %s" % e)
        except stu_env.NotInRepo as e:
            raise Fail(EXIT_ERROR, "cannot resolve RUN_HOME (%s); set STU_FLEET_FILE" % e)
        return os.path.join(env["RUN_HOME"], "merge-hold.json")
    except Fail:
        raise
    except Exception as e:
        raise Fail(EXIT_ERROR, "cannot resolve RUN_HOME: %s: %s" % (type(e).__name__, e))


def empty_state():
    return {"hold": None, "lock": None, "landed_during_hold": []}


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        return empty_state()
    except OSError as e:
        raise Fail(EXIT_ERROR, "cannot read %s: %s" % (path, e))
    try:
        doc = json.loads(text)
    except ValueError as e:
        raise Fail(EXIT_ERROR, "%s is not valid JSON (%s); fix or remove it" % (path, e))
    if not isinstance(doc, dict) or not isinstance(doc.get("landed_during_hold", []), list) \
            or not all(isinstance(doc.get(k), (dict, type(None))) for k in ("hold", "lock")):
        raise Fail(EXIT_ERROR, "%s has an unexpected shape; fix or remove it" % path)
    for k, v in empty_state().items():
        doc.setdefault(k, v)
    return doc


def atomic_write(path, text, prefix=".merge-hold-"):
    """Replace `path` with `text` atomically (temp file in the same directory, fsync, rename)."""
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix=prefix, dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.chmod(tmp, stat.S_IMODE(os.stat(path).st_mode))
        except OSError:
            pass
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save(path, doc):
    atomic_write(path, json.dumps(doc, indent=2, sort_keys=True) + "\n")


class Locked:
    """Exclusive flock on <state>.lock for the with-block; .doc is the loaded state."""

    def __init__(self, path):
        self.path = path

    def __enter__(self):
        d = os.path.dirname(self.path) or "."
        try:
            os.makedirs(d, exist_ok=True)
            self.fh = open(self.path + ".lock", "a")
            fcntl.flock(self.fh, fcntl.LOCK_EX)
        except OSError as e:
            raise Fail(EXIT_ERROR, "cannot lock %s: %s" % (self.path, e))
        try:
            self.doc = load(self.path)
        except BaseException:
            self.fh.close()
            raise
        return self

    def save(self):
        save(self.path, self.doc)

    def __exit__(self, *exc):
        self.fh.close()  # closing drops the flock
        return False


def ref(h):
    return "%s#%s" % (h["slug"], h["pr"])


# ---- forge ------------------------------------------------------------------------------


def forge_state(slug, pr):
    """-> (state, labels, auto_merge_on) of one PR via stu-forge pr-state; raises Fail(EXIT_FORGE)."""
    cmd = os.environ.get("STU_FLEET_FORGE")  # tests only: a stand-in for stu-forge
    argv = ([cmd] if cmd else [sys.executable, os.path.join(HERE, "stu_forge.py")]) + \
        ["pr-state", "--slug", slug, "--pr", str(pr)]
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=90,
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as e:
        raise Fail(EXIT_FORGE, "forge unreachable")
    lines = p.stdout.splitlines()
    if p.returncode != 0 or not lines or lines[-1] != "OK":
        detail = lines[-1] if lines else (p.stderr.strip().splitlines() or ["no output"])[-1]
        raise Fail(EXIT_FORGE, "forge unreachable (%s)" % " ".join(detail.split())[:120])
    got = {}
    for ln in lines[:-1]:
        k, _, v = ln.partition(" ")
        got[k] = v
    if got.get("STATE") not in ("open", "merged", "closed"):
        raise Fail(EXIT_FORGE, "forge unreachable (no PR state)")
    labels = [] if got.get("LABELS", "-") == "-" else got["LABELS"].split(",")
    return got["STATE"], labels, got.get("AUTO_MERGE") != "off"


def holder_gone(lock):
    """Observe the lock holder. -> (gone?, why) where why is merged|closed|label-gone|None."""
    state, labels, auto_on = forge_state(lock["slug"], lock["pr"])
    if state in ("merged", "closed"):
        return True, state
    label = lock.get("label") or ""
    # a PR with auto-merge still enabled is still armed, label or not
    if label and label not in labels and not auto_on:
        grace = float(os.environ.get("STU_FLEET_LABEL_GRACE", DEFAULT_GRACE))
        try:
            age = now_epoch() - parse_stamp(lock["taken_at"])
        except (KeyError, ValueError):
            age = 0.0
        if age > grace:
            return True, "label-gone"
    return False, None


def record_landing(doc, h, sha=None):
    if doc["hold"] is None:
        return False
    doc["landed_during_hold"].append({"slug": h["slug"], "pr": h["pr"],
                                      "sha": sha or h.get("sha") or "-", "at": stamp()})
    return True


# ---- hold -------------------------------------------------------------------------------


def disarm_line(lock):
    return "DISARM %s %s" % (ref(lock), lock.get("sha") or "-") if lock else "DISARM none"


def hold_status(doc):
    if doc["hold"] is None:
        print("HOLD none")
        return 0
    print("HOLD set %s (since %s)" % (doc["hold"]["reason"], doc["hold"].get("set_at", "?")))
    print(disarm_line(doc["lock"]))
    for e in doc["landed_during_hold"]:
        print("LANDED-DURING-HOLD %s#%s %s %s" % (e["slug"], e["pr"], e["sha"], e["at"]))
    return EXIT_HOLD


def cmd_hold(sub, a):
    if sub == "status":  # read-only: no flock, no forge (writes replace the file atomically)
        return hold_status(load(state_path()))
    with Locked(state_path()) as st:
        doc = st.doc
        if sub == "set":
            if not a.get("reason"):
                raise Fail(EXIT_USAGE, "hold set needs --reason")
            if doc["hold"] is None:
                doc["hold"] = {"reason": " ".join(a["reason"].split()), "set_at": stamp()}
                print("HOLD set %s" % doc["hold"]["reason"])
            else:
                print("HOLD already set %s" % doc["hold"]["reason"])
            doc["hold"]["disarm"] = (
                {"slug": doc["lock"]["slug"], "pr": doc["lock"]["pr"],
                 "sha": doc["lock"].get("sha")} if doc["lock"] else None)
            st.save()
            print(disarm_line(doc["lock"]))
            return 0
        if sub == "clear":
            if doc["hold"] is None:
                print("HOLD none")
            else:
                print("HOLD cleared; nothing re-armed")
            for e in doc["landed_during_hold"]:
                print("LANDED-DURING-HOLD %s#%s %s %s" % (e["slug"], e["pr"], e["sha"], e["at"]))
            doc["hold"] = None
            doc["landed_during_hold"] = []
            st.save()
            return 0
        raise Fail(EXIT_USAGE, "unreachable")


# ---- lock -------------------------------------------------------------------------------


def need(a, *names):
    for n in names:
        if not a.get(n):
            raise Fail(EXIT_USAGE, "missing --%s" % n)


def check_ids(a):
    if "pr" in a and not re.fullmatch(r"[0-9]+", a["pr"]):
        raise Fail(EXIT_USAGE, "--pr must be a number")
    if "slug" in a and not re.fullmatch(r"[^/\s]+/[^/\s]+", a["slug"]):
        raise Fail(EXIT_USAGE, "--slug must be owner/repo")
    if "sha" in a and not re.fullmatch(r"[0-9a-f]{7,64}", a["sha"]):
        raise Fail(EXIT_USAGE, "--sha must be hex")


def refuse(code, text):
    print("REFUSED " + text)
    return code


def cmd_lock(sub, a):
    check_ids(a)
    if sub == "status":
        doc = load(state_path())
        lock = doc["lock"]
        print("LOCK none" if not lock else "LOCK %s %s since %s" % (
            ref(lock), lock.get("sha") or "-", lock.get("taken_at", "?")))
        return 0
    if sub == "release":
        need(a, "pr")
        with Locked(state_path()) as st:
            lock = st.doc["lock"]
            if not lock or str(lock["pr"]) != a["pr"] or \
                    (a.get("slug") and lock["slug"] != a["slug"]):
                print("LOCK not held for PR %s" % a["pr"])
                return 0
            if a.get("landed") and record_landing(st.doc, lock):
                print("LANDED-DURING-HOLD %s" % ref(lock))
            st.doc["lock"] = None
            st.save()
            print("LOCK released %s" % ref(lock))
            return 0
    need(a, "slug", "pr", "sha")
    with Locked(state_path()) as st:
        doc, lock = st.doc, st.doc["lock"]
        same = lock and lock["slug"] == a["slug"] and str(lock["pr"]) == a["pr"]
        if lock and not same:
            try:
                gone, why = holder_gone(lock)
            except Fail as e:
                if doc["hold"] is None:
                    return refuse(EXIT_FORGE, "fleet-lock: held by %s, %s" % (ref(lock), e.msg))
                gone, why = False, None  # the hold refuses below; nothing to assume
            if gone:
                if why == "merged":
                    record_landing(doc, lock)
                print("LOCK released %s (%s)" % (ref(lock), why))
                doc["lock"] = lock = None
                st.save()
        if doc["hold"] is not None:
            return refuse(EXIT_HOLD, "fleet-hold: %s" % doc["hold"]["reason"])
        if lock and not same:
            return refuse(EXIT_LOCKED, "fleet-lock: held by %s" % ref(lock))
        doc["lock"] = {"slug": a["slug"], "pr": int(a["pr"]), "sha": a["sha"],
                       "label": a.get("label") or "",
                       "taken_at": lock["taken_at"] if same else stamp()}
        if same:
            doc["lock"]["updated_at"] = stamp()
        st.save()
        print("LOCK held %s %s" % (ref(doc["lock"]), a["sha"]))
        return 0


# ---- program file -----------------------------------------------------------------------

SLUG_RE = r"[A-Za-z0-9][A-Za-z0-9._-]*"
STATES = ("queued", "live", "settle", "relaunch", "owner", "done")
NEXT_STATE = {"none": "done", "settle": "settle", "relaunch": "relaunch", "owner": "owner"}
HEADER_KEYS = ("Owner", "Max live lanes", "Cycle budget", "Judgment jobs", "Stop at",
               "Settle mode", "Merge lock")
STOP_AT_RE = r"\d{4}-\d\d-\d\dT\d\d:\d\d(?::\d\d)?(?:Z|[+-]\d\d:\d\d)"
JUDGMENT_KINDS = ("groom", "audit", "design")
JOB_STATES = ("queued", "live", "verdict", "owner", "done")
USAGE_LIMIT_STOP = "usage limit"
SEC_RUNS, SEC_JUDGMENT, SEC_EXCLUDED, SEC_LIMITS, SEC_BOARD = (
    "runs", "judgment", "excluded", "limits", "board")


def section_of(heading):
    """Map a `## ...` heading to its section key, or None when it is not one of the five."""
    h = heading[2:].strip().lower()
    for key, word in ((SEC_RUNS, "runs"), (SEC_JUDGMENT, "judgment work"),
                      (SEC_EXCLUDED, "excluded"), (SEC_LIMITS, "machine limits"),
                      (SEC_BOARD, "fleet board")):
        if h == word or h.startswith(word + " ") or h.startswith(word + "("):
            return key
    return None


def read_text(path, what="file"):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError) as e:
        raise Fail(EXIT_ERROR, "cannot read %s %s: %s" % (what, path, e))


def objective_facts(path):
    """-> (cap or None, counted lanes, mode) from an objective file's header lines and scoreboard.
    counted lanes = the number of `Lane: <name>` headings, at least 1 (plain runs, and an
    overnight run that has not written its lane blocks yet, count as one lane); mode is
    `overnight` when the header says `Mode: overnight`, else `plain`."""
    text = read_text(path, "objective")
    head = []
    for ln in text.splitlines():
        if ln.startswith("## "):
            break
        head.append(ln)
    m = re.search(r"\bCycle cap:\s*(\d+)", "\n".join(head))
    cap = int(m.group(1)) if m and int(m.group(1)) >= 1 else None
    mm = re.search(r"\bMode:\s*(\w+)", "\n".join(head))
    mode = "overnight" if mm and mm.group(1) == "overnight" else "plain"
    lanes = len(re.findall(r"(?m)^\s*(?:#+\s*)?Lane:\s*\S", text))
    return cap, max(1, lanes), mode


def resume_count(text):
    """The count a supervisor resuming from this objective starts from (the run skill's "The
    cycle cap", At Resume): the scoreboard's `Cycles used:` numerator when `Run state:` reads
    `settled <date> -- nothing to settle`, or reads `stopped --` and any `Lane state:` line
    carries `self-stop:`; 0 otherwise, every other state (`fleet-relaunch`, `/stu:settle` lines,
    running) and any missing field included."""
    if "## Scoreboard" in text:
        text = text[text.index("## Scoreboard"):]
    dash = r"(?:—|–|--|-)"
    state = re.search(r"(?m)^\s*Run state:\s*(.*)$", text)
    used = re.search(r"(?m)^\s*Cycles used:\s*(\d+)\s*/\s*\d+", text)
    if not state or not used:
        return 0
    st = state.group(1).strip()
    cont = bool(re.match(r"settled\s+\S+\s*%s\s*nothing to settle" % dash, st))
    if not cont and re.match(r"stopped\s*%s" % dash, st):
        cont = any("self-stop:" in ln for ln in text.splitlines()
                   if re.match(r"\s*Lane state:", ln))
    return int(used.group(1)) if cont else 0


def split_list(v):
    return [x.strip() for x in v.split(",") if x.strip()]


NOTICE_IDS = ("cycle-80", "cycle-100", "judgment-80", "judgment-100", "stop-at")
V4_LINE = (r"- (%s) \| state: (\S+) \| cycles: (\d+) \| launches: (\d+) \| from: (\d+) \| "
           r"closed: (\d+) \| dry: (\d+) \| nonce: (\S+) \| agents: (\d+) \| out: (\d+) \| "
           r"draft: (.+?) \| written: (none|\d+(?:,\d+)*) \| handoff: (.+?) \| stop: (.+)" % SLUG_RE)
V3_LINE = (r"- (%s) \| state: (\S+) \| cycles: (\d+) \| launches: (\d+) \| from: (\d+) \| "
           r"closed: (\d+) \| dry: (\d+) \| nonce: (\S+) \| agents: (\d+) \| out: (\d+) \| "
           r"handoff: (.+?) \| stop: (.+)" % SLUG_RE)
V2_LINE = (r"- (%s) \| state: (\S+) \| cycles: (\d+) \| launches: (\d+) \| from: (\d+) \| "
           r"closed: (\d+) \| dry: (\d+) \| nonce: (\S+) \| handoff: (.+?) \| stop: (.+)" % SLUG_RE)
V1_LINE = (r"- (%s) \| state: (\S+) \| cycles: (\d+) \| launches: (\d+) \| from: (\d+) \| "
           r"handoff: (.+?) \| stop: (.+)" % SLUG_RE)
FLEET_LINE = r"- fleet \| judgment: (\d+) \| (?:agents: (\d+) \| out: (\d+) \| )?notices: (\S+)"


def parse_board_line(ln, where):
    """A v2 run line, or a v1 one (S9a's seven fields) read with closed 0, dry 0, nonce none."""
    ln = ln.rstrip("\n")
    m = re.fullmatch(V4_LINE, ln)
    if m and m.group(2) in STATES:
        g = m.groups()
        return {"slug": g[0], "state": g[1], "cycles": int(g[2]), "launches": int(g[3]),
                "from": int(g[4]), "closed": int(g[5]), "dry": int(g[6]), "nonce": g[7],
                "agents": int(g[8]), "out": int(g[9]), "draft": g[10],
                "written": [] if g[11] == "none" else [int(x) for x in g[11].split(",")],
                "handoff": g[12], "stop": g[13]}
    m = re.fullmatch(V3_LINE, ln)
    if m and m.group(2) in STATES:
        g = m.groups()
        return {"slug": g[0], "state": g[1], "cycles": int(g[2]), "launches": int(g[3]),
                "from": int(g[4]), "closed": int(g[5]), "dry": int(g[6]), "nonce": g[7],
                "agents": int(g[8]), "out": int(g[9]), "draft": "none", "written": [],
                "handoff": g[10], "stop": g[11]}
    m = re.fullmatch(V2_LINE, ln)
    if m and m.group(2) in STATES:
        g = m.groups()
        return {"slug": g[0], "state": g[1], "cycles": int(g[2]), "launches": int(g[3]),
                "from": int(g[4]), "closed": int(g[5]), "dry": int(g[6]), "nonce": g[7],
                "agents": 0, "out": 0, "draft": "none", "written": [], "handoff": g[8], "stop": g[9]}
    m = re.fullmatch(V1_LINE, ln)
    if m and m.group(2) in STATES:
        g = m.groups()
        return {"slug": g[0], "state": g[1], "cycles": int(g[2]), "launches": int(g[3]),
                "from": int(g[4]), "closed": 0, "dry": 0, "nonce": "none",
                "agents": 0, "out": 0, "draft": "none", "written": [], "handoff": g[5], "stop": g[6]}
    raise Fail(EXIT_ERROR, "%s: malformed board line %r; fix or delete it" % (where, ln.strip()))


JOB_LINE = (r"- job (%s) \| state: (\S+) \| dispatches: (\d+) \| output: (.+?) \| stop: (.+)"
            % SLUG_RE)


def parse_job_line(ln, where):
    m = re.fullmatch(JOB_LINE, ln.rstrip("\n"))
    if not m or m.group(2) not in JOB_STATES:
        raise Fail(EXIT_ERROR, "%s: malformed job line %r; fix or delete it" % (where, ln.strip()))
    return {"slug": m.group(1), "state": m.group(2), "dispatches": int(m.group(3)),
            "output": m.group(4), "stop": m.group(5)}


def job_line(j):
    clean = lambda v: str(v).replace("|", "/").replace("\n", " ")
    return "- job %s | state: %s | dispatches: %d | output: %s | stop: %s" % (
        j["slug"], j["state"], j["dispatches"], clean(j["output"]) or "none", clean(j["stop"]) or "none")


def parse_fleet_line(ln, where):
    m = re.fullmatch(FLEET_LINE, ln.rstrip("\n"))
    notices = [] if not m or m.group(4) == "none" else m.group(4).split(",")
    if not m or any(x not in NOTICE_IDS for x in notices) or len(set(notices)) != len(notices):
        raise Fail(EXIT_ERROR, "%s: malformed fleet line %r; fix or delete it" % (where, ln.strip()))
    # agents and out on the line are totals derived from the run lines at every write; read, not trusted
    return {"judgment": int(m.group(1)), "notices": notices}


def board_line(b):
    clean = lambda v: str(v).replace("|", "/").replace("\n", " ")
    return ("- %s | state: %s | cycles: %d | launches: %d | from: %d | closed: %d | dry: %d | "
            "nonce: %s | agents: %d | out: %d | draft: %s | written: %s | handoff: %s | stop: %s") % (
        b["slug"], b["state"], b["cycles"], b["launches"], b["from"], b["closed"], b["dry"],
        b["nonce"], b["agents"], b["out"], clean(b["draft"]) or "none",
        ",".join(str(n) for n in sorted(b["written"])) or "none",
        clean(b["handoff"]) or "none", clean(b["stop"]) or "none")


def fleet_line(f, board):
    """The fleet line; agents and out are the sums over the run lines `board`."""
    return "- fleet | judgment: %d | agents: %d | out: %d | notices: %s" % (
        f["judgment"], sum(b["agents"] for b in board), sum(b["out"] for b in board),
        ",".join(f["notices"]) or "none")


def parse_program(text):
    """The one parse function. -> program dict; problems (list of `line N BLOCKED: ...`) in
    prog["problems"]. Raises Fail(EXIT_ERROR) for a malformed or foreign board line."""
    lines = text.splitlines(keepends=True)
    prog = {"name": "", "header": {}, "runs": [], "judgment": [], "board": {}, "problems": [],
            "board_span": None, "lines": lines, "fleet": {"judgment": 0, "notices": []},
            "jobboard": {}}
    fleet_seen = False
    bad = prog["problems"]

    def block(n, detail):
        bad.append("line %d BLOCKED: %s" % (n, detail))

    sec, start = None, 0
    seen_sections = set()
    for i, raw in enumerate(lines):
        n, ln = i + 1, raw.rstrip("\n")
        if ln.startswith("## "):
            if sec == SEC_BOARD:
                prog["board_span"] = (start, i)
            sec = section_of(ln)
            if sec is None:
                block(n, "unknown section %r; use Runs, Judgment work, Excluded, Machine "
                         "limits or Fleet board" % ln.strip())
                continue
            if sec in seen_sections:
                block(n, "section %r appears twice" % ln.strip())
            seen_sections.add(sec)
            if sec == SEC_BOARD:
                start = i
            continue
        if not ln.strip():
            continue
        if sec is None and ln.startswith("# "):
            prog["name"] = ln[2:].replace("Fleet program:", "").strip()
            continue
        if sec is None:
            m = re.match(r"([A-Z][A-Za-z ]*?):\s*(.*)$", ln)
            if not m:
                continue  # prose before the first section is ignored
            k, v = m.group(1), m.group(2).strip()
            if k not in HEADER_KEYS:
                block(n, "unknown header %r; the keys are %s" % (k, ", ".join(HEADER_KEYS)))
            elif k in prog["header"]:
                block(n, "header %r appears twice" % k)
            else:
                prog["header"][k] = (v, n)
        elif sec == SEC_RUNS:
            m = re.fullmatch(r"- (%s): (\S+) \| after: ([^|]+?) \| resources: ([^|]+?)"
                             r"(?: \| lanes: (\d+))?" % SLUG_RE, ln)
            if not m:
                block(n, "run line must be '- <slug>: <objective path> | after: <slug or none> "
                         "| resources: <names> [| lanes: <n>]'")
                continue
            after = [] if m.group(3).strip() == "none" else split_list(m.group(3))
            res = [] if m.group(4).strip() == "none" else split_list(m.group(4))
            prog["runs"].append({"slug": m.group(1), "objective": m.group(2), "after": after,
                                 "resources": res, "line": n,
                                 "declared": int(m.group(5)) if m.group(5) else None})
        elif sec == SEC_JUDGMENT:
            m = re.fullmatch(r"- (%s): (\S+) \| scope: (.+?) \| output: (\S+) \| feeds: (\S+)"
                             % SLUG_RE, ln)
            if not m or m.group(2) not in JUDGMENT_KINDS:
                block(n, "judgment line must be '- <slug>: <groom|audit|design> | scope: <one "
                         "line> | output: <path> | feeds: <run slug or none>'")
                continue
            prog["judgment"].append({"slug": m.group(1), "kind": m.group(2), "scope": m.group(3),
                                     "output": m.group(4), "feeds": m.group(5), "line": n})
        elif sec == SEC_BOARD:
            if fleet_seen:
                raise Fail(EXIT_ERROR, "line %d: the fleet line must be the last line of the "
                                       "board; fix or delete the lines after it" % n)
            if re.match(r"- fleet\b", ln):
                prog["fleet"] = parse_fleet_line(ln, "line %d" % n)
                fleet_seen = True
                continue
            if re.match(r"- job ", ln):
                j = parse_job_line(ln, "line %d" % n)
                if j["slug"] in prog["jobboard"]:
                    raise Fail(EXIT_ERROR, "line %d: board names job %s twice; delete one line"
                               % (n, j["slug"]))
                prog["jobboard"][j["slug"]] = j
                continue
            if prog["jobboard"]:
                raise Fail(EXIT_ERROR, "line %d: a run line comes after a job line; the job lines "
                                       "follow the run lines" % n)
            b = parse_board_line(ln, "line %d" % n)
            if b["slug"] in prog["board"]:
                raise Fail(EXIT_ERROR, "line %d: board names %s twice; delete one line" % (n, b["slug"]))
            prog["board"][b["slug"]] = b
    if sec == SEC_BOARD:
        prog["board_span"] = (start, len(lines))
    validate_program(prog, block)
    for slug in prog["board"]:
        if slug not in [r["slug"] for r in prog["runs"]]:
            raise Fail(EXIT_ERROR, "board line for %r, which is not in Runs; delete the line "
                                   "or add the run" % slug)
    for slug in prog["jobboard"]:
        if slug not in [j["slug"] for j in prog["judgment"]]:
            raise Fail(EXIT_ERROR, "board line for job %r, which is not under Judgment work; "
                                   "delete the line or add the job" % slug)
    return prog


def validate_program(prog, block):
    h = prog["header"]
    if "Owner" not in h or not h["Owner"][0]:
        block(1, "Owner: is required")
    if "Settle mode" not in h or h["Settle mode"][0] not in ("draft", "auto-narrow"):
        block(h.get("Settle mode", ("", 1))[1], "Settle mode: is required, draft | auto-narrow")
    pos = lambda v: re.fullmatch(r"[0-9]+", v) and int(v) >= 1
    if "Max live lanes" in h and not pos(h["Max live lanes"][0]):
        block(h["Max live lanes"][1], "Max live lanes: must be a positive integer")
    for k in ("Cycle budget", "Judgment jobs"):
        if k in h and h[k][0] != "none" and not pos(h[k][0]):
            block(h[k][1], "%s: must be a positive integer or none" % k)
    if "Stop at" in h and h["Stop at"][0] != "none":
        v = h["Stop at"][0]
        ok = bool(re.fullmatch(STOP_AT_RE, v))
        if ok:
            try:
                datetime.fromisoformat(v.replace("Z", "+00:00"))
            except ValueError:
                ok = False
        if not ok:
            block(h["Stop at"][1], "Stop at: must be an ISO-8601 time with an offset "
                                   "(2026-11-12T18:00:00+00:00) or none")
    if "Merge lock" in h and h["Merge lock"][0] not in ("on", "off"):
        block(h["Merge lock"][1], "Merge lock: must be on or off")
    slugs = {}
    for r in prog["runs"]:
        if r["slug"] in slugs:
            block(r["line"], "run %s appears twice (first at line %d)" % (r["slug"], slugs[r["slug"]]))
        slugs[r["slug"]] = r["line"]
    if not prog["runs"]:
        block(1, "no runs: add '- <slug>: <objective path> | after: none | resources: none' "
                 "under '## Runs'")
    fed = {}
    for j in prog["judgment"]:
        if j["feeds"] != "none":
            fed.setdefault(j["feeds"], []).append(j["slug"])
    for r in prog["runs"]:
        if r["slug"] == "fleet":
            block(r["line"], "run slug 'fleet' is reserved for the board's fleet line")
        r["cap"], r["lanes"], r["mode"] = None, max(1, r["declared"] or 1), "plain"
        # a run some judgment line feeds waits for its objective: what is wrong with the file is
        # kept for `next` (r["obj_problem"]) instead of blocking the program
        r["fed_by"], r["obj_problem"], r["pending"] = fed.get(r["slug"], []), None, False
        deferred = []

        def flag(detail, r=r, deferred=deferred):
            if r["fed_by"]:
                deferred.append(detail)
            else:
                block(r["line"], "run %s: %s" % (r["slug"], detail))

        if not r["objective"].startswith("/"):
            block(r["line"], "run %s: objective path %r is not absolute" % (r["slug"], r["objective"]))
        elif not os.path.isfile(r["objective"]):
            r["pending"] = True
            flag("objective %s does not exist" % r["objective"])
        else:
            try:
                r["cap"], counted, r["mode"] = objective_facts(r["objective"])
                r["lanes"] = max(r["declared"] or 0, counted, 1)
            except Fail as e:
                flag(e.msg)
            else:
                if r["declared"] is not None and r["declared"] < 1:
                    flag("lanes: must be a positive integer")
                elif r["mode"] == "overnight" and r["declared"] is None:
                    flag("its objective is Mode: overnight, so the Runs line "
                         "must declare '| lanes: <n>'")
                elif r["mode"] == "plain" and r["declared"] not in (None, 1):
                    flag("a plain objective runs one lane, but the Runs line "
                         "declares lanes: %d" % r["declared"])
                if r["cap"] is None:
                    flag("objective has no 'Cycle cap: <n>' line; a fleet "
                         "objective states its cap (startup stop)")
        mx = h.get("Max live lanes")
        if mx and pos(mx[0]) and r["lanes"] > int(mx[0]):
            flag("its objective declares %d lanes but Max live lanes: is %s; "
                 "raise the cap or cut the lanes" % (r["lanes"], mx[0]))
        r["obj_problem"] = "; ".join(deferred) or None
        for a in r["after"]:
            if a not in slugs:
                block(r["line"], "run %s: after: names %r, which is not a run" % (r["slug"], a))
            elif a == r["slug"]:
                block(r["line"], "run %s: after: names itself" % r["slug"])
    cyc = after_cycle(prog["runs"])
    if cyc:
        block(slugs[cyc[0]], "after: cycle among runs: %s" % " -> ".join(cyc + cyc[:1]))
    judged = {}
    for j in prog["judgment"]:
        if j["slug"] in judged:
            block(j["line"], "judgment job %s appears twice" % j["slug"])
        judged[j["slug"]] = True
        if j["slug"] in slugs:
            block(j["line"], "judgment job %s has the same slug as a run" % j["slug"])
        if j["slug"] == "fleet":
            block(j["line"], "judgment job slug 'fleet' is reserved for the board's fleet line")
        if j["feeds"] != "none" and j["feeds"] not in slugs:
            block(j["line"], "judgment job %s: feeds: names %r, which is not a run" % (
                j["slug"], j["feeds"]))


def after_cycle(runs):
    """-> a list of slugs forming a cycle in the after: graph, or []."""
    deps = {r["slug"]: [a for a in r["after"]] for r in runs}
    state = {}

    def visit(s, path):
        state[s] = 1
        for d in deps.get(s, []):
            if d not in deps:
                continue
            if state.get(d) == 1:
                return path[path.index(d):] if d in path else [d]
            if d not in state:
                got = visit(d, path + [d])
                if got:
                    return got
        state[s] = 2
        return []

    for r in runs:
        if r["slug"] not in state:
            got = visit(r["slug"], [r["slug"]])
            if got:
                return got
    return []


def load_program(path):
    prog = parse_program(read_text(path, "program"))
    prog["path"] = path
    return prog


def need_valid(prog):
    if prog["problems"]:
        for p in prog["problems"]:
            print(p)
        print("BLOCKED")
        return EXIT_INVALID
    return 0


def effective_board(prog):
    """Board lines in Runs order, a queued row for every run that has none."""
    out = []
    for r in prog["runs"]:
        out.append(prog["board"].get(r["slug"]) or {
            "slug": r["slug"], "state": "queued", "cycles": 0, "launches": 0, "from": 0,
            "closed": 0, "dry": 0, "nonce": "none", "agents": 0, "out": 0, "draft": "none",
            "written": [], "handoff": "none", "stop": "none"})
    return out


def effective_jobs(prog):
    """Job lines in Judgment work order, a queued line for every job that has none (a v4 board)."""
    return [prog["jobboard"].get(j["slug"]) or {
        "slug": j["slug"], "state": "queued", "dispatches": 0, "output": "none", "stop": "none"}
        for j in prog["judgment"]]


def render_program(prog, board, fleet, jobs=()):
    """The program file text with its Fleet board section replaced by `board`, the job lines
    `jobs` and the fleet line."""
    lines = list(prog["lines"])
    body = ([board_line(b) + "\n" for b in board] + [job_line(j) + "\n" for j in jobs] +
            [fleet_line(fleet, board) + "\n"])
    if prog["board_span"] is None:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        return "".join(lines) + ("\n" if lines else "") + "## Fleet board\n" + "".join(body)
    a, b = prog["board_span"]
    heading = lines[a] if lines[a].endswith("\n") else lines[a] + "\n"
    tail = ["\n"] if b < len(lines) else []
    return "".join(lines[:a]) + heading + "".join(body) + "".join(tail) + "".join(lines[b:])


class ProgramLocked:
    """Exclusive flock on <program>.lock; .prog is the program re-read under the lock."""

    def __init__(self, path):
        self.path = path

    def __enter__(self):
        try:
            self.fh = open(self.path + ".lock", "a")
            fcntl.flock(self.fh, fcntl.LOCK_EX)
        except OSError as e:
            raise Fail(EXIT_ERROR, "cannot lock %s: %s" % (self.path, e))
        try:
            self.prog = load_program(self.path)
        except BaseException:
            self.fh.close()
            raise
        return self

    def write(self, board, jobs=None):
        atomic_write(self.path, render_program(
            self.prog, board, self.prog["fleet"],
            effective_jobs(self.prog) if jobs is None else jobs), prefix=".fleet-program-")

    def __exit__(self, *exc):
        self.fh.close()
        return False


# ---- program, board, spend, next --------------------------------------------------------


def scoreboard(text):
    """The objective text from `## Scoreboard` on (all of it when there is no such heading)."""
    return text[text.index("## Scoreboard"):] if "## Scoreboard" in text else text


def closed_ids(text):
    """The distinct unit IDs in an objective's `Closed:` lines (the union across `Lane:` blocks;
    `NONE` is none). The line is split on commas and the first word of each item is the ID.
    Annotated entries with inner commas, or a list wrapped onto a continuation line, miscount;
    that makes the loop guard trip earlier, never later."""
    ids = set()
    for m in re.finditer(r"(?m)^\s*Closed:[ \t]*(.*)$", scoreboard(text)):
        for item in m.group(1).split(","):
            word = item.split()[0] if item.split() else ""
            if word and word != "NONE":
                ids.add(word)
    return ids


def closed_count(text):
    return len(closed_ids(text))


def cycles_used(text):
    m = re.search(r"(?m)^\s*Cycles used:\s*(\d+)\s*/\s*\d+", scoreboard(text))
    return int(m.group(1)) if m else 0


def last_handoff(text):
    m = re.search(r"(?m)^\s*Last handoff:[ \t]*(\S.*?)\s*$", scoreboard(text))
    return m.group(1) if m else "none"


def new_nonce():
    override = os.environ.get("STU_FLEET_NONCE")  # tests only
    return override or "stu-" + secrets.token_hex(8)


def begin_launch(run, b):
    """What `board launch` does to a board line; -> the new nonce."""
    text = read_text(run["objective"], "objective")
    b["from"] = resume_count(text)
    b["closed"] = closed_count(text)
    b["state"] = "live"
    b["draft"], b["written"] = "none", []
    b["launches"] += 1
    b["nonce"] = new_nonce()
    return b["nonce"]


def loop_guard(run, b):
    """Always on. Count the closed IDs now; a launch that closed nothing new adds to `dry`.
    A `relaunch` outcome with dry >= 2 becomes `owner`."""
    now = closed_count(read_text(run["objective"], "objective"))
    b["dry"] = b["dry"] + 1 if now <= b["closed"] else 0
    if b["state"] == "relaunch" and b["dry"] >= 2:
        b["state"] = "owner"
        b["stop"] = "loop guard \u2014 2 launches closed no unit; last stop: %s" % b["stop"]


# ---- limits and the next policy ---------------------------------------------------------


def limits(prog, board, fleet):
    """The one evaluation of the program's limits. -> dict of
    cycle (used, limit or None, spent), judgment (same), stop (text or None, passed)."""
    h = {k: v[0] for k, v in prog["header"].items()}
    used = sum(b["cycles"] for b in board)
    raw = h.get("Cycle budget")
    # a run whose objective a judgment job has yet to write has no cap to add; with nothing known
    # there is no default limit yet (the budget is never 0)
    caps = sum(r["cap"] or 0 for r in prog["runs"])
    limit = None if raw == "none" else int(raw) if raw else caps or None
    jraw = h.get("Judgment jobs", "none")
    jlimit = None if jraw == "none" else int(jraw)
    stop = h.get("Stop at")
    if stop == "none":
        stop = None
    passed = bool(stop) and now_epoch() >= datetime.fromisoformat(
        stop.replace("Z", "+00:00")).timestamp()
    return {"cycle": (used, limit, limit is not None and used >= limit),
            "judgment": (fleet["judgment"], jlimit, jlimit is not None and fleet["judgment"] >= jlimit),
            "stop": (stop, passed)}


def limit_text(lim):
    """Why a new dispatch is refused, or None. Cycle budget first."""
    used, limit, spent = lim["cycle"]
    if spent:
        return "cycle budget spent %d/%d" % (used, limit)
    if lim["stop"][1]:
        return "stop at %s passed" % lim["stop"][0]
    return None


def fmt_limit(t):
    return "%d/%s" % (t[0], "none" if t[1] is None else t[1])


def decide(prog, board, cap, lim):
    """The one policy: -> [(slug, word, text)] in Runs order, and the live lane count.
    word is start|wait|settle|owner|relaunch|live|done."""
    runs = {r["slug"]: r for r in prog["runs"]}
    jobmap = {j["slug"]: j for j in effective_jobs(prog)}
    live, held = 0, {}
    for slug, b in board.items():
        if b["state"] == "live":
            live += runs[slug]["lanes"]
            for x in runs[slug]["resources"]:
                held.setdefault(x, slug)
    shown_live = live
    out = []
    for r in prog["runs"]:
        b, slug = board[r["slug"]], r["slug"]
        hold = fed_hold(r, jobmap) if b["state"] == "queued" else None
        if hold:
            out.append((slug,) + hold)
        elif b["state"] in ("queued", "relaunch"):
            pending = [x for x in r["after"] if board[x]["state"] != "done"]
            clash = [(x, held[x]) for x in r["resources"] if x in held]
            word = "start" if b["state"] == "queued" else "relaunch"
            if pending:
                out.append((slug, "wait", "after %s" % ",".join(pending)))
            elif clash:
                out.append((slug, "wait", "resource %s held by %s" % clash[0]))
            elif r["lanes"] > cap:
                out.append((slug, "owner", "needs %d lanes, cap %d" % (r["lanes"], cap)))
            elif live + r["lanes"] > cap:
                out.append((slug, "wait", "lane cap %d/%d" % (live, cap)))
            elif limit_text(lim):
                out.append((slug, "owner", limit_text(lim)))
            else:
                out.append((slug, word, b["stop"] if word == "relaunch" else ""))
                live += r["lanes"]
                for x in r["resources"]:
                    held.setdefault(x, slug)
        elif b["state"] == "settle" and b["draft"] != "none":
            out.append((slug, "brief", ""))
        elif b["state"] == "settle":
            out.append((slug, "settle", "owner-only" if re.match(r"[23]\b", b["stop"]) else ""))
        elif b["state"] == "owner":
            out.append((slug, "owner", b["stop"]))
        else:
            out.append((slug, b["state"], ""))
    return out, shown_live


def fed_hold(r, jobs):
    """-> (word, text) when a run fed by judgment jobs cannot start yet, else None. `jobs` maps a
    job slug to its board line. wait while a feeding job is not done; once they are, owner when
    the objective is missing or fails an objective check."""
    notdone = [j for j in r["fed_by"] if jobs[j]["state"] != "done"]
    if notdone:
        return "wait", "fed by %s (%s)" % (notdone[0], jobs[notdone[0]]["state"])
    if r["obj_problem"]:
        return "owner", "fed by %s, objective missing or invalid: %s" % (
            r["fed_by"][0], r["obj_problem"])
    return None


def decide_jobs(prog, lim):
    """-> the `next` lines for the judgment jobs, in Judgment work order. A queued job is
    `judge <slug>` unless a usage limit paused judgment work, judgment jobs are spent or Stop at
    passed. Jobs take no lane and name no resources."""
    jobs = effective_jobs(prog)
    paused = any(j["state"] == "queued" and j["stop"] == USAGE_LIMIT_STOP for j in jobs)
    out = []
    for j in jobs:
        slug, st = j["slug"], j["state"]
        if st == "queued":
            if paused and j["stop"] == USAGE_LIMIT_STOP:
                out.append("owner job %s \u2014 usage limit; requeue this job to lift the pause "
                           "for all judgment work" % slug)
            elif paused:
                out.append("owner job %s \u2014 usage limit; groom, audit and design paused" % slug)
            elif lim["judgment"][2]:
                out.append("owner job %s \u2014 judgment jobs spent %s" % (slug, fmt_limit(lim["judgment"])))
            elif lim["stop"][1]:
                out.append("owner job %s \u2014 stop at %s passed" % (slug, lim["stop"][0]))
            else:
                out.append("judge %s" % slug)
        elif st == "owner":
            out.append("owner job %s \u2014 %s" % (slug, j["stop"]))
        elif st == "verdict":
            out.append("verdict job %s \u2014 %s" % (slug, j["output"]))
        else:
            out.append("%s job %s" % (st, slug))
    return out


def decision_line(slug, word, text):
    if word == "settle":
        return "settle %s%s" % (slug, " " + text if text else "")
    if text:
        return "%s %s \u2014 %s" % (word, slug, text)
    return "%s %s" % (word, slug)


def new_notices(lim, seen):
    """-> [(id, text)] of the notices not yet in `seen`, in print order."""
    out = []
    for key, name, pre in (("cycle", "cycle-budget", "cycle"), ("judgment", "judgment-jobs", "judgment")):
        used, limit, _ = lim[key]
        if limit is None:
            continue
        for pct in (80, 100):
            nid = "%s-%d" % (pre, pct)
            if used * 100 >= pct * limit and nid not in seen:
                out.append((nid, "notice: %s %d%% (%d/%d)" % (name, pct, used, limit)))
    if lim["stop"][1] and "stop-at" not in seen:
        out.append(("stop-at", "notice: stop-at passed (%s)" % lim["stop"][0]))
    return out


# ---- program, board, spend, next --------------------------------------------------------


def cmd_program(sub, a):
    prog = load_program(a["program"])
    rc = need_valid(prog)
    if rc:
        return rc
    h = {k: v[0] for k, v in prog["header"].items()}
    print("program: %s" % (prog["name"] or "-"))
    print("owner: %s" % h["Owner"])
    print("settle-mode: %s" % h["Settle mode"])
    print("max-live-lanes: %s" % h.get("Max live lanes", "config"))
    print("cycle-budget: %s" % h.get("Cycle budget", "sum-of-caps"))
    print("judgment-jobs: %s" % h.get("Judgment jobs", "none"))
    print("stop-at: %s" % h.get("Stop at", "none"))
    print("merge-lock: %s" % h.get("Merge lock", "on"))
    for r in prog["runs"]:
        if r["obj_problem"]:
            print("run %s: objective %s (fed by %s)%s" % (
                r["slug"], "pending" if r["pending"] else "invalid", r["fed_by"][0],
                "" if r["pending"] else ": " + r["obj_problem"]))
            continue
        print("run %s: objective %s | cap %d | lanes %d | after %s | resources %s" % (
            r["slug"], r["objective"], r["cap"], r["lanes"], ",".join(r["after"]) or "none",
            ",".join(r["resources"]) or "none"))
    for j in prog["judgment"]:
        print("judgment %s: %s | feeds %s" % (j["slug"], j["kind"], j["feeds"]))
    print("OK")
    return 0


def find_run(prog, slug):
    for r in prog["runs"]:
        if r["slug"] == slug:
            return r
    raise Fail(EXIT_USAGE, "--run %s is not a run in this program" % slug)


class ObjectiveRefusal(Exception):
    """Raised inside a rewrite_objective transform: refuse, write nothing."""


def find_run_state(lines):
    """-> (line index, current value) of the first `Run state:` line inside `## Scoreboard` (the
    heading line up to the next `## ` heading), or None. The one parser of that line."""
    at = next((i for i, ln in enumerate(lines) if ln.startswith("## Scoreboard")), None)
    if at is None:
        return None
    end = next((i for i in range(at + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    for i in range(at, end):
        m = re.match(r"^[ \t]*Run state:[ \t]*([^\r\n]*)", lines[i])
        if m:
            return i, m.group(1).strip()
    return None


def rewrite_objective(path, transform):
    """The one objective writer: under a flock on <objective>.lock, read the file, call
    transform(lines) -> (changed lines or None for no change, result), replace the file
    atomically when the text changed. -> (refusal text or None, result). transform refuses by
    raising ObjectiveRefusal, before anything is written."""
    try:
        with open(path + ".lock", "a") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            with open(path, encoding="utf-8", newline="") as f:
                text = f.read()
            lines = text.splitlines(keepends=True)
            try:
                out, result = transform(lines)
            except ObjectiveRefusal as e:
                return str(e), None
            new = "".join(lines if out is None else out)
            if new != text:
                atomic_write(path, new, prefix=".fleet-objective-")
            return None, result
    except OSError as e:
        raise Fail(EXIT_ERROR, "cannot rewrite objective %s: %s" % (path, e))


def set_run_state(path, date):
    """Write `Run state: fleet-relaunch <date>` over the first `Run state:` line inside the
    objective's `## Scoreboard`, nothing else changed. -> None, or the refusal text when there is
    no such scoreboard or line."""
    def transform(lines):
        at = find_run_state(lines)
        if not at:
            raise ObjectiveRefusal("fleet-board: %s has no '## Scoreboard' with a 'Run state:' line "
                                   "to rewrite" % path)
        m = re.match(r"^([ \t]*Run state:)[ \t]*[^\r\n]*(\r?\n?)$", lines[at[0]])
        lines[at[0]] = "%s fleet-relaunch %s%s" % (m.group(1), date, m.group(2))
        return None, None
    return rewrite_objective(path, transform)[0]


def cmd_board(sub, a):
    if sub == "show":
        prog = load_program(a["program"])
        rc = need_valid(prog)
        if rc:
            return rc
        runs = {r["slug"]: r for r in prog["runs"]}
        jobmap = {j["slug"]: j for j in effective_jobs(prog)}
        for b in effective_board(prog):
            print(board_line(b))
            hold = fed_hold(runs[b["slug"]], jobmap) if b["state"] == "queued" else None
            if hold and hold[0] == "wait":
                print("  wait: %s" % hold[1])
        for j in effective_jobs(prog):
            print(job_line(j))
        print(fleet_line(prog["fleet"], effective_board(prog)))
        return 0
    if sub in ("judgment", "judged", "verdict") or (sub in ("requeue", "idle") and "job" in a):
        if "run" in a:
            raise Fail(EXIT_USAGE, "--run and --job are mutually exclusive")
        return cmd_job(sub, a)
    need(a, "run")
    if sub in ("record", "draft", "settled"):
        need(a, "return")
    with ProgramLocked(a["program"]) as st:
        prog = st.prog
        rc = need_valid(prog)
        if rc:
            return rc
        run = find_run(prog, a["run"])
        board = effective_board(prog)
        b = [x for x in board if x["slug"] == run["slug"]][0]
        nonce = None
        if sub == "launch":
            if b["state"] != "queued":
                why = {"live": "never two supervisors on one unit list",
                       "done": "a done run is not launched again",
                       "relaunch": "a relaunch goes through board relaunch",
                       "settle": "requeue it first", "owner": "requeue it first"}[b["state"]]
                return refuse(EXIT_BOARD, "fleet-board: %s is %s, not queued; %s" % (
                    run["slug"], b["state"], why))
            held = fed_hold(run, {j["slug"]: j for j in effective_jobs(prog)})
            if held:
                return refuse(EXIT_BOARD, "fleet-board: %s" % decision_line(run["slug"], *held))
            nonce = begin_launch(run, b)
        elif sub == "relaunch":
            if b["state"] != "relaunch":
                return refuse(EXIT_BOARD, "fleet-board: %s is %s, not relaunch" % (
                    run["slug"], b["state"]))
            bmap = {x["slug"]: x for x in board}
            decided, _ = decide(prog, bmap, lane_cap(prog), limits(prog, board, prog["fleet"]))
            slug, word, text = [d for d in decided if d[0] == run["slug"]][0]
            if word != "relaunch":
                return refuse(EXIT_BOARD, "fleet-board: policy says %s for %s now, not relaunch" % (
                    decision_line(slug, word, text), run["slug"]))
            bad = set_run_state(run["objective"], stamp()[:10])
            if bad:
                return refuse(EXIT_BOARD, bad)
            nonce = begin_launch(run, b)
        elif sub == "idle":
            if b["state"] != "live":
                return refuse(EXIT_BOARD, "fleet-board: %s is %s, not live; nothing is idle" % (
                    run["slug"], b["state"]))
            text = read_text(run["objective"], "objective")
            used = cycles_used(text)
            if used < b["from"]:
                return refuse(EXIT_BOARD, "fleet-board: %s shows %d cycles used but resumed from "
                                          "%d; a negative delta is never clamped, so check the "
                                          "objective's scoreboard" % (run["slug"], used, b["from"]))
            b["cycles"] += used - b["from"]
            b["state"] = "relaunch"
            b["stop"] = "idle \u2014 no return"
            b["handoff"] = last_handoff(text)
            b["draft"], b["written"] = "none", []
            loop_guard(run, b)
        elif sub == "requeue":
            if b["state"] not in ("settle", "relaunch", "owner"):
                return refuse(EXIT_BOARD, "fleet-board: %s is %s; only settle, relaunch or "
                                          "owner can be requeued" % (run["slug"], b["state"]))
            b["state"] = "queued"
            b["draft"], b["written"] = "none", []
        elif sub == "draft":
            rc = record_draft(run, b, a["return"])
            if rc:
                return rc
            write_settle_counts(a["program"], run["slug"], None, (), ())
        elif sub == "settled":
            rc, last = record_settled(a["program"], run, b, a["return"])
            if rc:
                return rc
            st.write(board)
            print(board_line(b))
            print(last)
            return 0
        else:  # record
            rc = record_return(run, b, a["return"])
            if rc:
                return rc
        entry = None
        if sub in ("record", "idle"):
            entry = take_actuals(run["slug"], b)
        st.write(board)
        print(board_line(b))
        if entry is not None:
            if "unavailable" in entry:
                print("actuals: unavailable \u2014 %s" % entry["unavailable"])
            append_actuals(a["program"], entry)
        if nonce:
            print("nonce: %s" % nonce)
        return 0


def actuals_path(program):
    return program + ".actuals.jsonl"


def take_actuals(slug, b):
    """Read the launch's actuals from the transcripts, add agents and out to the board line, and
    return the detail-log entry. Never fails: unavailable actuals add nothing."""
    import fleet_actuals
    entry = {"slug": slug, "nonce": b["nonce"], "recorded_at": stamp()}
    got, why = fleet_actuals.launch_actuals(b["nonce"])
    if got is None:
        entry["unavailable"] = why
        return entry
    n, out = fleet_actuals.totals(got)
    b["agents"] += n
    b["out"] += out
    entry.update({"agents": n, "out": out, "by_seat_model": fleet_actuals.by_seat_model(got)})
    return entry


def append_actuals(program, entry):
    """One JSON line, appended under the program lock the caller holds. A log that cannot be
    written is reported, never fatal: the board line is already written."""
    try:
        with open(actuals_path(program), "a+") as fh:
            fh.seek(0, 2)
            if fh.tell():
                fh.seek(fh.tell() - 1)
                if fh.read(1) != "\n":
                    fh.write("\n")  # a torn final line must not swallow this entry
            fh.write(json.dumps(entry, sort_keys=True) + "\n")
    except OSError as e:
        print("actuals: log not written \u2014 %s" % e)


def read_actuals(program):
    """-> list of log entries (oldest first); [] when there is no log. A damaged line is exit 3."""
    try:
        with open(actuals_path(program), "r") as fh:
            lines = fh.read().splitlines()
    except FileNotFoundError:
        return []
    except OSError as e:
        raise Fail(EXIT_ERROR, "cannot read %s: %s" % (actuals_path(program), e))
    out = []
    last = max([i for i, ln in enumerate(lines, 1) if ln.strip()] or [0])
    for n, ln in enumerate(lines, 1):
        if not ln.strip():
            continue
        try:
            e = json.loads(ln)
            ok = isinstance(e, dict) and isinstance(e.get("slug"), str)
            if ok and "unavailable" not in e:
                ok = (isinstance(e["agents"], int) and isinstance(e["out"], int) and
                      all(isinstance(r["seat"], str) and isinstance(r["model"], str) and
                          all(isinstance(r[k], int) for k in ("agents", "turns", "out"))
                          for r in e["by_seat_model"]))
        except (ValueError, KeyError, TypeError):
            ok = False
        if not ok and n == last:
            print("actuals: skipped damaged final log line %d (a crash mid-append?)" % n)
            continue
        if not ok:
            raise Fail(EXIT_ERROR, "%s line %d is not an actuals entry; fix or delete it" % (
                actuals_path(program), n))
        out.append(e)
    return out


# Seats whose model a dispatch can override from config (the settler's `judgment-model`): the
# file's line is only a default, so their routing is not knowable from a script.
OVERRIDABLE_SEATS = ("stu:settler",)
MODEL_FAMILIES = ("opus", "sonnet", "haiku", "fable")


def model_tokens(model):
    return [t for t in re.split(r"[-._:/@ ]+", model.lower()) if t]


def on_route(want, model):
    """True when `model` (a transcript model id) is the routed one. `want` is a family or a full
    id; compared by whole tokens of the id, never as a substring."""
    fams = [t for t in model_tokens(want) if t in MODEL_FAMILIES]
    if fams:
        return fams[0] in model_tokens(model)
    return want == model.lower()


def routed_model(seat):
    """The model family a `stu:<name>` seat is routed to: the `model:` line in agents/<name>.md,
    or None when the seat has no file, inherits, or can be overridden at dispatch (the settler)."""
    if not seat.startswith("stu:") or seat in OVERRIDABLE_SEATS:
        return None
    path = os.path.join(os.path.dirname(HERE), "agents", seat[4:] + ".md")
    try:
        with open(path, "r") as fh:
            lines = fh.read().split("\n")
    except OSError:
        return None
    if not lines or lines[0].strip() != "---":
        return None
    for ln in lines[1:]:
        if ln.strip() == "---":
            break
        m = re.fullmatch(r"model:\s*(\S+)\s*", ln)
        if m:
            return None if m.group(1) == "inherit" else m.group(1).lower()
    return None


def print_actuals_block(entries):
    """The table and the off-route lines for the available entries in `entries`."""
    acc = {}
    for e in entries:
        for r in e.get("by_seat_model", []):
            v = acc.setdefault((r["seat"], r["model"]), [0, 0, 0])
            v[0] += r["agents"]
            v[1] += r["turns"]
            v[2] += r["out"]
    print("seat model agents turns out")
    for (seat, model), v in sorted(acc.items()):
        print("%s %s %d %d %d" % (seat, model, v[0], v[1], v[2]))
    seats = sorted({k[0] for k in acc})
    unknown = []
    for seat in seats:
        want = routed_model(seat)
        if want is None:
            unknown.append(seat)
            continue
        # a record with no model is counted in the table but says nothing about routing
        known = {k: v for k, v in acc.items() if k[0] == seat and k[1] != "unknown"}
        total = sum(v[1] for v in known.values())
        off = sum(v[1] for k, v in known.items() if not on_route(want, k[1]))
        print("off-route %s: %d/%d turns not on %s (%d%%)" % (
            seat, off, total, want, off * 100 // total if total else 0))
    if unknown:
        print("routing unknown: %s" % ", ".join(unknown))


def cmd_actuals(sub, a):
    prog = load_program(a["program"])
    rc = need_valid(prog)
    if rc:
        return rc
    entries = read_actuals(a["program"])
    if not entries:
        print("actuals: none recorded")
        return 0
    slugs = [r["slug"] for r in prog["runs"]]
    slugs += sorted({e["slug"] for e in entries} - set(slugs))
    def head(label, es):
        good = [e for e in es if "unavailable" not in e]
        bad = len(es) - len(good)
        print("%s: launches %d, agents %d, out %d%s" % (
            label, len(es), sum(e["agents"] for e in good), sum(e["out"] for e in good),
            ", unavailable %d" % bad if bad else ""))
        print_actuals_block(good)
    for slug in slugs:
        es = [e for e in entries if e["slug"] == slug]
        if es:
            head("run %s" % slug, es)
    head("fleet", entries)
    return 0


def job_paused(jobs):
    """True while any queued job carries the usage-limit stop (the Cap fallback pause)."""
    return any(j["state"] == "queued" and j["stop"] == USAGE_LIMIT_STOP for j in jobs)


def _job_refuse(j, why):
    return refuse(EXIT_BOARD, "fleet-board: job %s is %s, %s" % (j["slug"], j["state"], why))


def fold_judged(prog, spec, job, ret_path):
    """Validate the return for `spec` and fold it into `job`. -> rc after printing problems, or 0."""
    import judgment_return
    text = read_text(ret_path, "judgment return")
    if spec["kind"] == "design":
        block, problems = judgment_return.check_designer(text, spec["slug"])
    else:
        block, problems = judgment_return.check_groomer(text, spec["slug"], spec["kind"])
    if (not problems and block["status"] == "DONE" and spec["feeds"] != "none"):
        run = [r for r in prog["runs"] if r["slug"] == spec["feeds"]]
        listed = [p for p in re.split(r"\s*,\s*", block["fields"].get("OBJECTIVES", "")) if p]
        if run and not any(os.path.realpath(p) == os.path.realpath(run[0]["objective"])
                           for p in listed):
            problems.append("the job feeds run %s, so OBJECTIVES must list %s" % (
                spec["feeds"], run[0]["objective"]))
    if (not problems and spec["kind"] == "design" and block["status"] == "READY"):
        o = block["fields"].get("OUTPUT", "none")
        if not os.path.isabs(o) or not os.path.isdir(o):
            problems.append("OUTPUT %s is not an existing directory; board verdict could never "
                            "write VERDICT.md there" % o)
    if not problems and block["status"] in ("DONE", "SPLIT", "READY"):
        # The program line's output: is where the job writes. A designer's OUTPUT is that
        # directory itself; a groomer's OUTPUT is its report, which may sit inside it.
        want = os.path.realpath(spec["output"])
        got = os.path.realpath(block["fields"].get("OUTPUT", "none"))
        if spec["kind"] == "design":
            ok = got == want
        else:
            ok = got == want or got.startswith(want.rstrip(os.sep) + os.sep)
        if not ok:
            problems.append("OUTPUT %s is not the program line's output %s for job %s" % (
                block["fields"].get("OUTPUT", "none"), spec["output"], spec["slug"]))
    if problems:
        for p in problems:
            print("BLOCKED: %s" % p)
        print("BLOCKED")
        return EXIT_INVALID
    st = block["status"]
    out = block["fields"].get("OUTPUT", "none")
    if st == "DONE":
        job["state"], job["output"], job["stop"] = "done", out, "none"
    elif st == "SPLIT":
        job["state"], job["output"] = "owner", out
        job["stop"] = "split into %d scopes; add them as Judgment work lines" % len(block["scopes"])
    elif st == "READY":
        job["state"], job["output"], job["stop"] = "verdict", out, "none"
    elif judgment_return.is_usage_limit(block["summary"]):
        job["state"], job["stop"] = "queued", USAGE_LIMIT_STOP
    else:
        job["state"], job["stop"] = "owner", "BLOCKED — %s" % block["summary"]
    return 0


def cmd_job(sub, a):
    need(a, "job")
    if sub == "judged":
        need(a, "return")
    if sub == "verdict":
        need(a, "line")
    with ProgramLocked(a["program"]) as st:
        prog = st.prog
        rc = need_valid(prog)
        if rc:
            return rc
        specs = [j for j in prog["judgment"] if j["slug"] == a["job"]]
        if not specs:
            print("BLOCKED: %s is not a line under '## Judgment work'" % a["job"])
            return EXIT_INVALID
        spec = specs[0]
        board = effective_board(prog)
        jobs = effective_jobs(prog)
        job = [j for j in jobs if j["slug"] == spec["slug"]][0]
        if sub == "judgment":
            if job["state"] != "queued":
                return _job_refuse(job, "not queued")
            if job_paused(jobs):
                return refuse(EXIT_BOARD, "fleet-board: judgment jobs are paused on a usage limit; "
                                          "board requeue --job lifts it")
            lim = limits(prog, board, prog["fleet"])
            if lim["judgment"][2]:
                return refuse(EXIT_BOARD, "fleet-board: judgment jobs spent %s" % fmt_limit(lim["judgment"]))
            if lim["stop"][1]:
                return refuse(EXIT_BOARD, "fleet-board: stop at %s passed" % lim["stop"][0])
            job["state"], job["stop"] = "live", "none"
            job["dispatches"] += 1
            prog["fleet"]["judgment"] += 1
            st.write(board, jobs)
            print("judgment-jobs: %d/%s" % (prog["fleet"]["judgment"],
                                            "none" if lim["judgment"][1] is None else lim["judgment"][1]))
            return 0
        if sub == "judged":
            if job["state"] != "live":
                return _job_refuse(job, "not live; only a live job takes a return")
            rc = fold_judged(prog, spec, job, a["return"])
            if rc:
                return rc
        elif sub == "verdict":
            if job["state"] != "verdict":
                return _job_refuse(job, "not verdict; only a job awaiting the owner takes a verdict")
            out = job["output"]
            if not os.path.isabs(out) or not os.path.isdir(out):
                return _job_refuse(job, "its output %s is not an existing absolute directory" % out)
            path = os.path.join(out, "VERDICT.md")
            try:
                with open(path, "a", encoding="utf-8") as f:
                    f.write("%s — %s\n" % (stamp()[:10], a["line"]))
            except OSError as e:
                raise Fail(EXIT_ERROR, "cannot write %s: %s" % (path, e))
            job["state"], job["stop"] = ("done" if a.get("done") else "queued"), "none"
        elif sub == "requeue":
            if job["state"] == "owner":
                job["state"], job["stop"] = "queued", "none"
            elif job["state"] == "verdict":
                job["state"], job["stop"] = "queued", "none"  # escape hatch; output kept
            elif job["state"] == "queued" and job["stop"] == USAGE_LIMIT_STOP:
                job["stop"] = "none"
            else:
                return _job_refuse(job, "not owner, verdict or paused; nothing to requeue")
        elif sub == "idle":
            if job["state"] != "live":
                return _job_refuse(job, "not live; nothing is idle")
            job["state"], job["stop"] = "owner", "idle; stopped"
        else:
            raise Fail(EXIT_USAGE, "unknown board subcommand %s" % sub)
        st.write(board, jobs)
        print(job_line(job))
        return 0


def read_settler_return(path, status, run):
    """Validate a settler return file with settler_return.check. -> (block, None) or (None, rc)
    after printing `BLOCKED: <problem>` lines and `BLOCKED` (exit 1): the file must check clean,
    carry SETTLER: <status>, and name the run's objective."""
    import settler_return
    text = read_text(path, "settler return")
    problems = settler_return.check(text)
    block = settler_return.parse(text)[0]
    if not problems and block["status"] != status:
        problems.append("the return says SETTLER: %s, but this command takes %s" % (
            block["status"], status))
    if not problems and os.path.realpath(block["objective"]) != os.path.realpath(run["objective"]):
        problems.append("the return is for objective %s, not %s's %s" % (
            block["objective"], run["slug"], run["objective"]))
    if problems:
        for p in problems:
            print("BLOCKED: %s" % p)
        print("BLOCKED")
        return None, EXIT_INVALID
    return block, None


def record_draft(run, b, ret_path):
    """`board draft`: store the DRAFTED return's absolute path on a settle run with no draft."""
    if b["state"] != "settle" or b["draft"] != "none":
        return refuse(EXIT_BOARD, "fleet-board: %s is %s%s; a draft is recorded only on a settle "
                                  "run that has none" % (
            run["slug"], b["state"], " with a draft" if b["draft"] != "none" else ""))
    block, rc = read_settler_return(ret_path, "DRAFTED", run)
    if rc:
        return rc
    b["draft"] = os.path.abspath(ret_path)
    b["written"] = []
    return 0


def settle_counts_path(program):
    return program + ".settle.json"


def read_settle_counts(program, slug, draft):
    """-> (unparked ids, dropped ids) named by `unpark` / `drop` TODOs of earlier `board settled`
    calls under this draft, applied or not."""
    try:
        with open(settle_counts_path(program), encoding="utf-8") as f:
            e = json.load(f).get(slug) or {}
    except FileNotFoundError:
        return set(), set()
    except (OSError, ValueError, AttributeError) as e:
        raise Fail(EXIT_ERROR, "cannot read %s: %s; fix or delete it" % (settle_counts_path(program), e))
    if not isinstance(e, dict) or e.get("draft") != draft:
        return set(), set()
    try:
        return set(map(str, e.get("unparked", []))), set(map(str, e.get("dropped", [])))
    except TypeError:
        raise Fail(EXIT_ERROR, "%s has an unexpected shape; fix or delete it" % settle_counts_path(program))


def write_settle_counts(program, slug, draft, unparked, dropped):
    """Record the id sets for `slug`'s current draft (draft None clears the entry); called under
    the program lock. The file is a sidecar of the program, never part of it."""
    path = settle_counts_path(program)
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except FileNotFoundError:
        doc = {}
    except (OSError, ValueError) as e:
        raise Fail(EXIT_ERROR, "cannot read %s: %s; fix or delete it" % (path, e))
    if not isinstance(doc, dict):
        raise Fail(EXIT_ERROR, "%s has an unexpected shape; fix or delete it" % path)
    if draft is None:
        if slug not in doc:
            return
        del doc[slug]
    else:
        doc[slug] = {"draft": draft, "unparked": sorted(unparked), "dropped": sorted(dropped)}
    atomic_write(path, json.dumps(doc, indent=2, sort_keys=True) + "\n", prefix=".fleet-settle-")


_FIELD = r"^([ \t]*%s:[ \t]*)(.*?)([ \t]*)((?:\r?\n)?)$"


def _sb_blocks(lines):
    """-> list of (start, end) line ranges inside `## Scoreboard`: one per `Lane:` heading (the
    preamble before the first heading too, when there are headings), or the whole scoreboard
    when it has none. None when there is no `## Scoreboard`."""
    at = next((i for i, ln in enumerate(lines) if ln.startswith("## Scoreboard")), None)
    if at is None:
        return None
    end = next((i for i in range(at + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    heads = [i for i in range(at + 1, end) if re.match(r"\s*(?:#+\s*)?Lane:\s*\S", lines[i])]
    if not heads:
        return [(at, end)]
    cuts = [at] + heads + [end]
    return [(cuts[i], cuts[i + 1]) for i in range(len(cuts) - 1)]


def _field_at(lines, block, label):
    """-> (line index, items) of the first `<label>:` line in the block, or None."""
    for i in range(block[0], block[1]):
        m = re.match(_FIELD % label, lines[i])
        if m:
            v = m.group(2).strip()
            items = [] if not v or v.upper() == "NONE" else [x.strip() for x in v.split(",") if x.strip()]
            return i, items
    return None


def _set_items(lines, i, label, items):
    m = re.match(_FIELD % label, lines[i])
    lines[i] = m.group(1) + (", ".join(items) or "NONE") + m.group(3) + m.group(4)


def _has(items, uid):
    return any(x.split()[0] == uid for x in items)


def _without(items, uid):
    return [x for x in items if x.split()[0] != uid]


def edit_scoreboard(path, todos, written_n, prior, finish, date):
    """Apply `unpark` and `drop` TODOs to the objective's scoreboard lines and, when `finish`,
    rewrite the first `Run state:` there, all in memory first: a refusal writes nothing. Refused
    too while `Run state:` reads `running`. Only scoreboard lines change. `prior` is the
    (unparked ids, dropped ids) already named under this draft. -> (refusal or None, unparked
    ids, dropped ids): the ids named by this call's TODOs, whether applied now or already done."""
    def transform(lines):
        blocks = _sb_blocks(lines)
        if blocks is None:
            raise ObjectiveRefusal("fleet-board: %s has no '## Scoreboard' to settle into" % path)
        rs = find_run_state(lines)
        if rs and re.match(r"running\b", rs[1]):
            raise ObjectiveRefusal("fleet-board: %s reads 'Run state: running'; settles edit only "
                                   "while it reads stopped, waiting-on-human, settled or "
                                   "fleet-relaunch" % path)
        unparked, dropped = set(), set()
        for verb, uid in todos:
            found = {lab: [(b, _field_at(lines, b, lab)) for b in blocks] for lab in
                     ("Parked", "Outstanding", "Closed")}
            hit = lambda lab: [(b, f) for b, f in found[lab] if f and _has(f[1], uid)]
            if verb == "unpark":
                if hit("Parked"):
                    b, f = hit("Parked")[0]
                    out = _field_at(lines, b, "Outstanding")
                    if not out:
                        raise ObjectiveRefusal("fleet-board: no 'Outstanding:' line to move %s into" % uid)
                    _set_items(lines, f[0], "Parked", _without(f[1], uid))
                    _set_items(lines, out[0], "Outstanding", out[1] + [uid])
                elif not hit("Outstanding"):
                    raise ObjectiveRefusal("fleet-board: unpark %s, which is in no lane's Parked: and "
                                           "not already Outstanding:" % uid)
                unparked.add(uid)
            else:
                live = hit("Parked") + hit("Outstanding")
                dropped_already = any(_has(f[1], uid) and "dropped by the owner" in
                                      [x for x in f[1] if x.split()[0] == uid][0]
                                      for b, f in found["Closed"] if f)
                if live:
                    b = live[0][0]
                    clo = _field_at(lines, b, "Closed")
                    if not clo and not dropped_already:
                        raise ObjectiveRefusal("fleet-board: no 'Closed:' line to record %s in" % uid)
                    for lab in ("Parked", "Outstanding"):
                        f = _field_at(lines, b, lab)
                        if f and _has(f[1], uid):
                            _set_items(lines, f[0], lab, _without(f[1], uid))
                    if not dropped_already:
                        _set_items(lines, clo[0], "Closed",
                                   clo[1] + ["%s (dropped by the owner %s)" % (uid, date)])
                elif not dropped_already:
                    raise ObjectiveRefusal("fleet-board: drop %s, which is in no lane's Parked: or "
                                           "Outstanding: and is not already dropped" % uid)
                dropped.add(uid)
        if finish:
            at = find_run_state(lines)
            if at is None:
                raise ObjectiveRefusal("fleet-board: %s has no 'Run state:' line in its Scoreboard" % path)
            waiting = any(f and f[1] for b in blocks for lab in ("Waiting", "Awaiting approval")
                          for f in [_field_at(lines, b, lab)])
            m = re.match(_FIELD % "Run state", lines[at[0]])
            state = "waiting-on-human" if waiting else (
                "settled %s \u2014 %d answered, %d unparked, 0 added, %d dropped" % (
                    date, written_n, len(set(prior[0]) | unparked), len(set(prior[1]) | dropped)))
            lines[at[0]] = m.group(1) + state + m.group(3) + m.group(4)
        return None, (unparked, dropped)
    bad, res = rewrite_objective(path, transform)
    return (bad, set(), set()) if bad else (None,) + res


def units_left(path):
    """True when the objective's scoreboard still has a unit Outstanding, Parked, Waiting or
    Awaiting approval in any lane (the same fields `edit_scoreboard` reads)."""
    lines = read_text(path, "objective").splitlines()
    blocks = _sb_blocks(lines) or []
    return any(f and f[1] for blk in blocks
               for lab in ("Outstanding", "Parked", "Waiting", "Awaiting approval")
               for f in [_field_at(lines, blk, lab)])


def record_settled(program, run, b, ret_path):
    """`board settled`: fold a WRITTEN settler return into the board and the objective's
    scoreboard lines. -> (rc, last line to print or None); the caller writes the board."""
    import settler_return
    if b["state"] != "settle" or b["draft"] == "none":
        return refuse(EXIT_BOARD, "fleet-board: %s is %s%s; settled applies to a settle run that "
                                  "has a recorded draft" % (
            run["slug"], b["state"], " with no draft" if b["state"] == "settle" else "")), None
    block, rc = read_settler_return(ret_path, "WRITTEN", run)
    if rc:
        return rc, None
    drafted = settler_return.parse(read_text(b["draft"], "drafted settler return"))[0]
    if os.path.realpath(block["draft"]) != os.path.realpath(drafted["draft"] or ""):
        print("BLOCKED: the return's DRAFT %s is not the recorded draft's %s" % (
            block["draft"], drafted["draft"]))
        print("BLOCKED")
        return EXIT_INVALID, None
    todos = [settler_return.parse_todo(t) for t in block["todos"]]
    for verb, uid, _ in todos:
        if verb == "add":
            return refuse(EXIT_BOARD, "fleet-board: %s adds unit %s; settle it with /stu:settle %s" % (
                run["slug"], uid, run["objective"])), None
    ids = [int(x[1:]) for x in block["written"]]
    union = sorted(set(b["written"]) | set(ids))
    finish = not block["unanswered"]
    prior = read_settle_counts(program, run["slug"], b["draft"])
    date = stamp()[:10]
    bad, u, d = edit_scoreboard(run["objective"], [(v, i) for v, i, _ in todos], len(union),
                                prior, finish, date)
    if bad:
        return refuse(EXIT_BOARD, bad), None
    b["written"] = union
    if finish:
        write_settle_counts(program, run["slug"], None, (), ())
        b["draft"], b["written"] = "none", []
        if not units_left(run["objective"]):
            b["state"], b["stop"] = "done", "none"
            return 0, "done %s" % run["slug"]
        b["state"] = "queued"
        return 0, "requeued %s" % run["slug"]
    write_settle_counts(program, run["slug"], b["draft"], prior[0] | u, prior[1] | d)
    return 0, "pending %s: %s" % (run["slug"], ", ".join(block["unanswered"]))


def record_return(run, b, ret_path):
    import run_check
    text = read_text(ret_path, "supervisor return")
    bad = run_check.check_supervisor_return(text)
    if bad:
        for p in bad:
            print(p)
        print("BLOCKED")
        return EXIT_INVALID
    f = {}
    for ln in text.splitlines():
        m = run_check.SUP_KEY.match(ln)
        if m and m.group(1) not in f:
            f[m.group(1)] = m.group(2)
    if os.path.realpath(f["OBJECTIVE"]) != os.path.realpath(run["objective"]):
        return refuse(EXIT_BOARD, "fleet-board: the return is for objective %s, not %s's %s" % (
            f["OBJECTIVE"], run["slug"], run["objective"]))
    if b["state"] != "live":
        return refuse(EXIT_BOARD, "fleet-board: %s is %s, not live; nothing to record into" % (
            run["slug"], b["state"]))
    used = int(f["CYCLES"].split("/")[0])
    if used < b["from"]:
        return refuse(EXIT_BOARD, "fleet-board: %s returned %d cycles used but resumed from %d; "
                                  "a negative delta is never clamped, so check the objective's "
                                  "scoreboard" % (run["slug"], used, b["from"]))
    b["cycles"] += used - b["from"]
    b["state"] = NEXT_STATE[f["NEXT"]]
    b["handoff"] = f["LAST-HANDOFF"]
    b["stop"] = f["STOP-CONDITION"]
    b["draft"], b["written"] = "none", []
    loop_guard(run, b)
    return 0


def cmd_spend(sub, a):
    prog = load_program(a["program"])
    rc = need_valid(prog)
    if rc:
        return rc
    board = effective_board(prog)
    for b in board:
        print("run %s: cycles %d, launches %d, dry %d, agents %d, out %d" % (
            b["slug"], b["cycles"], b["launches"], b["dry"], b["agents"], b["out"]))
    lim = limits(prog, board, prog["fleet"])
    used, limit, _ = lim["cycle"]
    print("fleet: cycles %d, agents %d, out %d" % (
        used, sum(b["agents"] for b in board), sum(b["out"] for b in board)))
    if limit is None:
        print("budget: %d/none" % used)
    else:
        print("budget: %d/%d (%d%%)" % (used, limit, used * 100 // limit))
    print("judgment-jobs: %s" % fmt_limit(lim["judgment"]))
    print("stop-at: %s (%s)" % (lim["stop"][0] or "none", "passed" if lim["stop"][1] else "not passed"))
    return 0


def runtime_lane_limit():
    """The hook where a runtime that reports its own slot limit lowers the lane cap. Claude
    reports none, so this returns None; a runtime binding returns its limit as an int."""
    return None


def lane_cap(prog):
    raw = prog["header"].get("Max live lanes", (None,))[0]
    if raw is None:
        raw = os.environ.get("STU_FLEET_MAX_LANES")  # tests only
    if raw is None:
        sys.path.insert(0, HERE)
        import stu_env
        try:
            raw = stu_env.resolve(require_config=True).get("FLEET_MAX_LANES", "4")
        except stu_env.NoConfig:
            raw = "4"
        except Exception as e:
            raise Fail(EXIT_ERROR, "cannot resolve FLEET_MAX_LANES: %s; set 'Max live lanes:' "
                                   "in the program" % e)
    cap = int(raw)
    limit = runtime_lane_limit()
    return min(cap, limit) if limit else cap


def cmd_next(sub, a):
    """A notice is recorded in the fleet line before it is printed, so a crash in between loses
    that one notice; deliberate, so a notice never prints twice."""
    prog = load_program(a["program"])
    rc = need_valid(prog)
    if rc:
        return rc
    cap = lane_cap(prog)
    code = 0
    lines = []
    with Locked(state_path()) as st:  # release by observation, the one write
        lock = st.doc["lock"]
        if lock:
            try:
                gone, why = holder_gone(lock)
            except Fail as e:
                lines.append("lock: held by %s \u2014 %s; not released" % (ref(lock), e.msg))
                code = e.code
            else:
                if gone:
                    if why == "merged":
                        record_landing(st.doc, lock)
                    st.doc["lock"] = None
                    st.save()
                    lines.append("lock: released %s (%s)" % (ref(lock), why))
        hold = st.doc["hold"]
    board = effective_board(prog)
    lim = limits(prog, board, prog["fleet"])
    if new_notices(lim, prog["fleet"]["notices"]):
        with ProgramLocked(a["program"]) as pl:  # each notice prints once, ever: record it first
            prog = pl.prog
            board = effective_board(prog)
            lim = limits(prog, board, prog["fleet"])
            fresh = new_notices(lim, prog["fleet"]["notices"])
            if fresh:
                prog["fleet"]["notices"] += [nid for nid, _ in fresh]
                pl.write(board)
    else:
        fresh = []
    decided, shown_live = decide(prog, {b["slug"]: b for b in board}, cap, lim)
    lines += [decision_line(*d) for d in decided]
    lines += decide_jobs(prog, lim)
    lines += [text for _, text in fresh]
    lines.append("hold: set \u2014 %s" % hold["reason"] if hold else "hold: clear")
    lines.append("lanes: %d/%d" % (shown_live, cap))
    lines.append("budget: %s" % fmt_limit(lim["cycle"]))
    lines.append("judgment-jobs: %s" % fmt_limit(lim["judgment"]))
    print("\n".join(lines))
    return code


def drafted_runs(prog):
    """-> [(run, board line, parsed drafted return)] for every run with a draft, in Runs order."""
    import settler_return
    out = []
    for b in effective_board(prog):
        if b["draft"] != "none":
            run = find_run(prog, b["slug"])
            out.append((run, b, settler_return.parse(read_text(b["draft"], "drafted settler return"))[0]))
    return out


def cmd_brief(sub, a):
    prog = load_program(a["program"])
    rc = need_valid(prog)
    if rc:
        return rc
    drafts = drafted_runs(prog)
    if not drafts:
        print("brief: none")
        return 0
    for run, b, d in drafts:
        keep = []
        for ln in (d["brief"] or "").splitlines():
            m = re.match(r"^\s*(\d+)\.\s", ln)
            if m and int(m.group(1)) in b["written"]:
                continue
            keep.append(ln)
        while keep and (not keep[-1].strip() or keep[-1].startswith("Answer:")):
            keep.pop()  # the run's own Answer: line; one line for the whole brief follows
        print("\n".join(keep))
        print()
    if len(drafts) == 1:
        print("Answer: %s: fine | accept 2 | reverse 2, 5 | talk about 3" % drafts[0][0]["slug"])
    else:
        print("Answer per run, one per line or separated by ';': <slug>: <answer>")
    return 0


ANSWER_WORDS = ("fine", "accept", "reverse", "talk")


def cmd_answer(sub, a):
    need(a, "line")
    prog = load_program(a["program"])
    rc = need_valid(prog)
    if rc:
        return rc
    drafts = drafted_runs(prog)
    by_slug = {r["slug"]: (b, d) for r, b, d in drafts}
    known = [r["slug"] for r in prog["runs"]]
    problems, answers = [], {}
    for seg in re.split(r"[\n;]", a["line"]):
        seg = seg.strip()
        if not seg:
            continue
        m = re.match(r"^(%s)\s*:\s*(.*)$" % SLUG_RE, seg)
        if m and m.group(1).lower() not in ANSWER_WORDS:
            slug, text = m.group(1), m.group(2).strip()
        elif len(drafts) == 1:
            slug, text = drafts[0][0]["slug"], seg
        elif drafts:
            problems.append("%r names no run; several runs have a draft, so prefix it with "
                            "<slug>:" % seg)
            continue
        else:
            problems.append("%r answers nothing: no run has a draft" % seg)
            continue
        if slug not in known:
            problems.append("%s is not a run in this program" % slug)
            continue
        if slug not in by_slug:
            problems.append("%s has no draft to answer" % slug)
            continue
        if slug in answers:
            problems.append("%s is answered twice" % slug)
            continue
        answers[slug] = text
        b, d = by_slug[slug]
        n = int(d["rulings_n"])
        for kind, nums in re.findall(r"\b(accept|reverse|talk about)\b\s+(\d+(?:\s*,\s*\d+)*)", text):
            for num in re.findall(r"\d+", nums):
                k = int(num)
                if not 1 <= k <= n:
                    problems.append("%s: %s %d is outside the draft's 1..%d" % (slug, kind, k, n))
                elif k in b["written"]:
                    problems.append("%s: %s %d is already written" % (slug, kind, k))
    if problems:
        for p in problems:
            print("BLOCKED: %s" % p)
        print("BLOCKED")
        return EXIT_INVALID
    for run, b, d in drafts:
        if run["slug"] in answers:
            print("answer %s | draft: %s | line: %s" % (run["slug"], d["draft"], answers[run["slug"]]))
        else:
            print("unanswered %s" % run["slug"])
    return 0


# ---- command line -----------------------------------------------------------------------

SPEC = {
    ("hold", "set"): (("reason",), ()),
    ("hold", "clear"): ((), ()),
    ("hold", "status"): ((), ()),
    ("lock", "take"): (("slug", "pr", "sha", "label"), ()),
    ("lock", "release"): (("pr", "slug"), ("landed",)),
    ("lock", "status"): ((), ()),
}
# commands whose first argument after the subcommand is the program file
PROGRAM_SPEC = {
    ("program", "check"): ((), ()),
    ("board", "show"): ((), ()),
    ("board", "launch"): (("run",), ()),
    ("board", "record"): (("run", "return"), ()),
    ("board", "requeue"): (("run", "job"), ()),
    ("board", "idle"): (("run", "job"), ()),
    ("board", "relaunch"): (("run",), ()),
    ("board", "judgment"): (("job",), ()),
    ("board", "judged"): (("job", "return"), ()),
    ("board", "verdict"): (("job", "line"), ("done",)),
    ("board", "draft"): (("run", "return"), ()),
    ("board", "settled"): (("run", "return"), ()),
    ("brief", None): ((), ()),
    ("answer", None): (("line",), ()),
    ("spend", None): ((), ()),
    ("actuals", None): ((), ()),
    ("next", None): ((), ()),
}
USAGE = ("usage: stu-fleet hold set|clear|status | lock take|release|status [flags] | "
         "program check P | board show|launch|record|requeue|idle|relaunch|judgment|judged|verdict|draft|settled P [flags] | spend P | actuals P | next P | "
         "brief P | answer P --line TEXT")


def parse(argv):
    if argv and argv[0] in ("spend", "next", "actuals", "brief", "answer"):
        key, rest = (argv[0], None), argv[1:]
    elif len(argv) >= 2 and (argv[0], argv[1]) in PROGRAM_SPEC:
        key, rest = (argv[0], argv[1]), argv[2:]
    elif len(argv) >= 2 and (argv[0], argv[1]) in SPEC:
        key, rest = (argv[0], argv[1]), argv[2:]
    else:
        raise Fail(EXIT_USAGE, USAGE)
    values, bools = (PROGRAM_SPEC if key in PROGRAM_SPEC else SPEC)[key]
    a, i = {}, 0
    if key in PROGRAM_SPEC:
        if not rest or rest[0].startswith("--"):
            raise Fail(EXIT_USAGE, "%s needs the program file path" % " ".join(
                x for x in key if x))
        a["program"], rest = rest[0], rest[1:]
    while i < len(rest):
        tok = rest[i]
        name = tok[2:] if tok.startswith("--") else ""
        if name in bools:
            a[name] = True
            i += 1
        elif name in values:
            if i + 1 >= len(rest):
                raise Fail(EXIT_USAGE, "%s needs a value" % tok)
            a[name] = rest[i + 1]
            i += 2
        else:
            raise Fail(EXIT_USAGE, "unexpected argument %r" % tok)
    return key[0], key[1], a


DISPATCH = {"hold": cmd_hold, "lock": cmd_lock, "program": cmd_program, "board": cmd_board,
            "spend": cmd_spend, "actuals": cmd_actuals, "next": cmd_next, "brief": cmd_brief,
            "answer": cmd_answer}


def main(argv):
    try:
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
        group, sub, a = parse(argv)
        return DISPATCH[group](sub, a)
    except Fail as e:
        sys.stderr.write("stu-fleet: %s\n" % e.msg)
        return e.code
    except Exception as e:  # fail closed: a gate reads a nonzero exit as a refusal
        sys.stderr.write("stu-fleet: %s: %s\n" % (type(e).__name__, e))
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
