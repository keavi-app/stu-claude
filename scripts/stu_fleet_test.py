#!/usr/bin/env python3
"""Regression suite for stu_fleet.py (merge hold and lock), through the bin/ wrapper.

The forge is a stand-in script (STU_FLEET_FORGE) except for one case that runs the real
stu-forge against the shared fake `gh`. Nothing touches the network or the real run home.
Run: python3 scripts/stu_fleet_test.py
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BIN = os.path.join(ROOT, "bin", "stu-fleet")
FAKE_GH = os.path.join(ROOT, "tests", "fake_gh.py")
FAILURES = []
COUNT = [0]
SLUG = "acme/app"
SHA = "a" * 40
SHA2 = "b" * 40
T0 = 1700000000


def check(name, got, want):
    COUNT[0] += 1
    if got != want:
        FAILURES.append("%s: got %r, want %r" % (name, got, want))


TMP = tempfile.mkdtemp(prefix="stu-fleet-test-")
STATE = os.path.join(TMP, "run", "merge-hold.json")
PRS = os.path.join(TMP, "prs")
os.makedirs(PRS)
STUB = os.path.join(TMP, "forge-stub")
with open(STUB, "w") as f:
    f.write("""#!/bin/sh
# usage: pr-state --slug S --pr N ; reads $PRS/N: "STATE <s>" "LABELS <l>" lines, or "FAIL"
n=$5
file="%s/$n"
[ -f "$file" ] || { echo "ERROR not-found no such PR"; exit 3; }
if [ "$(cat "$file")" = FAIL ]; then echo "ERROR forge boom"; exit 3; fi
cat "$file"; echo OK
""" % PRS)
os.chmod(STUB, 0o755)


def pr(n, state="open", labels="merge-ok", auto="off"):
    with open(os.path.join(PRS, str(n)), "w") as f:
        f.write("STATE %s\nLABELS %s\nAUTO_MERGE %s\n" % (state, labels or "-", auto))


def pr_unreachable(n):
    with open(os.path.join(PRS, str(n)), "w") as f:
        f.write("FAIL")


def reset():
    for p in (STATE, STATE + ".lock"):
        if os.path.exists(p):
            os.remove(p)


def fleet(*args, now=T0, extra=None):
    env = dict(os.environ)
    env.update({"STU_FLEET_FILE": STATE, "STU_FLEET_FORGE": STUB, "STU_FLEET_NOW": str(now)})
    env.update(extra or {})
    p = subprocess.run([BIN] + list(args), capture_output=True, text=True, env=env)
    return p.returncode, p.stdout.splitlines(), p.stderr


def take(n, slug=SLUG, sha=SHA, label="merge-ok", now=T0):
    return fleet("lock", "take", "--slug", slug, "--pr", str(n), "--sha", sha,
                 "--label", label, now=now)


def state():
    with open(STATE) as f:
        return json.load(f)


def test_no_file_means_no_hold():
    reset()
    check("hold status, no file", fleet("hold", "status")[:2], (0, ["HOLD none"]))
    check("lock status, no file", fleet("lock", "status")[:2], (0, ["LOCK none"]))
    check("no file created by a read", os.path.exists(STATE), False)


def test_lock_take_basics():
    reset()
    pr(1)
    pr(2)
    check("take", take(1)[:2], (0, ["LOCK held %s#1 %s" % (SLUG, SHA)]))
    check("status shows holder", fleet("lock", "status")[1][0].startswith("LOCK %s#1" % SLUG), True)
    check("re-entrant, new sha", take(1, sha=SHA2, now=T0 + 60)[:2],
          (0, ["LOCK held %s#1 %s" % (SLUG, SHA2)]))
    st = state()["lock"]
    check("re-entry updates sha, keeps taken_at", (st["sha"], st["taken_at"]),
          (SHA2, "2023-11-14T22:13:20Z"))
    check("another PR refused", take(2)[:2],
          (11, ["REFUSED fleet-lock: held by %s#1" % SLUG]))
    check("same number, other repo refused", take(1, slug="acme/lib")[0], 11)
    check("release other PR is a no-op", fleet("lock", "release", "--pr", "2")[0], 0)
    check("lock survives the no-op", state()["lock"]["pr"], 1)
    check("release", fleet("lock", "release", "--pr", "1")[1], ["LOCK released %s#1" % SLUG])
    check("release twice", fleet("lock", "release", "--pr", "1")[0], 0)
    check("take after release", take(2)[0], 0)


def test_hold_refuses_take():
    reset()
    pr(1)
    check("hold set, nothing held", fleet("hold", "set", "--reason", "deploy freeze")[:2],
          (0, ["HOLD set deploy freeze", "DISARM none"]))
    check("take refused", take(1)[:2], (10, ["REFUSED fleet-hold: deploy freeze"]))
    check("no lock recorded", state()["lock"], None)
    check("hold status exit", fleet("hold", "status")[0], 10)
    check("clear", fleet("hold", "clear")[1], ["HOLD cleared; nothing re-armed"])
    check("hold status after clear", fleet("hold", "status")[:2], (0, ["HOLD none"]))
    check("take after clear", take(1)[0], 0)
    check("hold set needs a reason", fleet("hold", "set")[0], 2)


def test_hold_returns_holder_and_records_landing():
    reset()
    pr(7)
    pr(8)
    take(7)
    rc, out, _ = fleet("hold", "set", "--reason", "peer asked")
    check("hold set returns the holder", (rc, out[1]), (0, "DISARM %s#7 %s" % (SLUG, SHA)))
    check("holder recorded in the file", state()["hold"]["disarm"],
          {"slug": SLUG, "pr": 7, "sha": SHA})
    check("hold does not release the lock", state()["lock"]["pr"], 7)
    check("hold set again keeps the first reason",
          fleet("hold", "set", "--reason", "other")[1][0], "HOLD already set peer asked")
    pr(7, state="merged")
    # a later gate on another PR observes the holder landed during the hold
    check("take refused for the hold", take(8)[0], 10)
    got = state()
    check("lock released on observation", got["lock"], None)
    check("landed-during-hold recorded", [(e["slug"], e["pr"]) for e in got["landed_during_hold"]],
          [(SLUG, 7)])
    rc, out, _ = fleet("hold", "status")
    check("status lists it", (rc, any(l.startswith("LANDED-DURING-HOLD %s#7" % SLUG) for l in out)),
          (10, True))
    rc, out, _ = fleet("hold", "clear")
    check("clear surfaces it", any(l.startswith("LANDED-DURING-HOLD") for l in out), True)
    check("clear empties the log", state()["landed_during_hold"], [])


def test_release_landed_during_hold():
    reset()
    take(5)
    fleet("hold", "set", "--reason", "h")
    rc, out, _ = fleet("lock", "release", "--pr", "5", "--slug", SLUG, "--landed")
    check("release --landed during hold", out[0], "LANDED-DURING-HOLD %s#5" % SLUG)
    check("recorded", len(state()["landed_during_hold"]), 1)
    reset()
    take(5)
    fleet("lock", "release", "--pr", "5", "--landed")
    check("release --landed with no hold records nothing", state()["landed_during_hold"], [])
    reset()
    take(5)
    check("release with the wrong slug is a no-op",
          (fleet("lock", "release", "--pr", "5", "--slug", "acme/lib")[0], state()["lock"]["pr"]),
          (0, 5))


def test_stale_holder_released_on_the_forge():
    for why, kw in (("merged", {"state": "merged"}), ("closed", {"state": "closed"})):
        reset()
        pr(1, **kw)
        pr(2)
        take(1)
        rc, out, _ = take(2)
        check("%s holder released, new take wins" % why, (rc, out[-1].startswith("LOCK held")), (0, True))
        check("%s: note printed" % why, out[0], "LOCK released %s#1 (%s)" % (SLUG, why))
        check("%s: not a hold landing" % why, state()["landed_during_hold"], [])
    reset()
    pr(1, labels="")
    pr(2)
    take(1)
    check("fresh lock without its label is not abandoned", take(2, now=T0 + 60)[0], 11)
    check("lock older than the grace without its label is released",
          take(2, now=T0 + 1000)[0], 0)
    reset()
    pr(1, labels="", auto="on")
    pr(2)
    take(1)
    check("label gone but auto-merge still on keeps the lock", take(2, now=T0 + 99999)[0], 11)
    reset()
    pr(1, labels="")
    pr(2)
    take(1, label="")
    check("no label recorded: label check is skipped", take(2, now=T0 + 99999)[0], 11)
    reset()
    pr(1)
    pr(2)
    take(1)
    check("open and labelled holder keeps the lock", take(2, now=T0 + 99999)[0], 11)


def test_forge_unreachable_refuses():
    reset()
    pr_unreachable(1)
    pr(2)
    take(1)
    rc, out, _ = take(2)
    check("unreachable: refused, distinct code", rc, 12)
    check("unreachable: reason prefix", out[0].startswith("REFUSED fleet-lock: held by %s#1, forge" % SLUG), True)
    check("lock untouched", state()["lock"]["pr"], 1)
    os.remove(os.path.join(PRS, "1"))
    check("unknown PR is also unreachable", take(2)[0], 12)
    rc, out, _ = fleet("lock", "take", "--slug", SLUG, "--pr", "2", "--sha", SHA,
                       extra={"STU_FLEET_FORGE": os.path.join(TMP, "missing-binary")})
    check("missing forge command refuses", rc, 12)
    # with the hold set the refusal is the hold's, and nothing is assumed about the holder
    pr_unreachable(1)
    fleet("hold", "set", "--reason", "freeze")
    check("hold wins over unreachable", take(2)[:2], (10, ["REFUSED fleet-hold: freeze"]))
    check("holder kept", state()["lock"]["pr"], 1)


def test_real_forge_through_fake_gh():
    reset()
    ghdir = os.path.join(TMP, "ghbin")
    os.makedirs(ghdir, exist_ok=True)
    if not os.path.exists(os.path.join(ghdir, "gh")):
        os.symlink(FAKE_GH, os.path.join(ghdir, "gh"))
    fx = os.path.join(TMP, "fx.json")

    def doc(state, labels):
        return {"rc": 0, "json": {
            "state": state, "headRefName": "b", "headRefOid": SHA, "baseRefName": "main",
            "mergeCommit": None, "labels": [{"name": l} for l in labels],
            "autoMergeRequest": None, "url": "https://github.com/%s/pull/1" % SLUG}}
    with open(fx, "w") as f:
        json.dump({"pr view 1": doc("MERGED", ["merge-ok"])}, f)
    extra = {"PATH": ghdir + os.pathsep + os.environ["PATH"], "FAKE_GH_FIXTURES": fx,
             "FAKE_GH_STATE": os.path.join(TMP, "gh.state")}
    env = dict(os.environ)
    env.pop("STU_FLEET_FORGE", None)
    env.update(extra)
    env.update({"STU_FLEET_FILE": STATE, "STU_FLEET_NOW": str(T0)})
    take(1)
    p = subprocess.run([BIN, "lock", "take", "--slug", SLUG, "--pr", "2", "--sha", SHA],
                       capture_output=True, text=True, env=env)
    check("real stu-forge: merged holder released", (p.returncode, p.stdout.splitlines()[:1]),
          (0, ["LOCK released %s#1 (merged)" % SLUG]))


def test_fail_closed_on_bad_state():
    reset()
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    for text in ("{not json", "[]", '{"hold": 3}'):
        with open(STATE, "w") as f:
            f.write(text)
        check("bad state %r: take" % text, take(1)[0], 3)
        check("bad state %r: hold status" % text, fleet("hold", "status")[0], 3)
    reset()


def test_usage():
    check("no args", fleet()[0], 2)
    check("unknown subcommand", fleet("hold", "toggle")[0], 2)
    check("take without sha", fleet("lock", "take", "--slug", SLUG, "--pr", "1")[0], 2)
    check("bad pr", fleet("lock", "take", "--slug", SLUG, "--pr", "x", "--sha", SHA)[0], 2)
    check("bad slug", fleet("lock", "take", "--slug", "nope", "--pr", "1", "--sha", SHA)[0], 2)
    check("unknown flag", fleet("lock", "status", "--pr", "1")[0], 2)


def test_concurrent_takes_serialise():
    reset()
    for n in range(1, 9):
        pr(n)
    env = dict(os.environ)
    env.update({"STU_FLEET_FILE": STATE, "STU_FLEET_FORGE": STUB, "STU_FLEET_NOW": str(T0)})
    procs = [subprocess.Popen([BIN, "lock", "take", "--slug", SLUG, "--pr", str(n),
                               "--sha", SHA, "--label", "merge-ok"],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
             for n in range(1, 9)]
    codes = sorted(p.wait() for p in procs)
    for p in procs:
        p.stdout.close()
        p.stderr.close()
    check("exactly one of eight takes wins", codes, [0] + [11] * 7)
    check("file is valid and names one holder", state()["lock"]["pr"] in range(1, 9), True)

# ---- program, board, spend, next -------------------------------------------------------

sys.path.insert(0, HERE)
import stu_fleet  # noqa: E402

PDIR = os.path.join(TMP, "prog")
os.makedirs(PDIR, exist_ok=True)
PROG = os.path.join(PDIR, "program.md")
HANDOFF = "/abs/handoffs/h1.md"


def write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def objective(name, cap="4", mode="plain", scoreboard="", lanes=0):
    head = "# Objective: %s\n\nWritten 2026-01-01. Mode: %s. Cycle cap: %s.\n" % (
        name, mode, cap) if cap else "# Objective: %s\n\nWritten 2026-01-01. Mode: %s.\n" % (name, mode)
    body = head + "\n## Scoreboard\n\n" + scoreboard
    for i in range(lanes):
        body += "\nLane: lane%d\nLane state: running\n" % i
    return write(os.path.join(PDIR, "%s-objective.md" % name), body)


HEADER = "# Fleet program: demo\nOwner: pat\nSettle mode: draft\n"


def program(runs, header=HEADER, tail=""):
    return write(PROG, header + "\n## Runs\n" + "".join(
        "- %s: %s | after: %s | resources: %s\n" % r for r in runs) + tail)


def pfleet(*args, **kw):
    kw.setdefault("extra", {})
    kw["extra"].setdefault("STU_FLEET_MAX_LANES", "4")
    return fleet(*args, **kw)


def run_ret(path, obj, run="STOPPED", cond="10 — cycle cap exhausted", cycles="3/4",
            nxt="relaunch", state="stopped — BLOCKED: cap"):
    return write(path, "STU-RUN: %s\nOBJECTIVE: %s\nRUN-STATE: %s\nSTOP-CONDITION: %s\n"
                       "CYCLES: %s\nLAST-HANDOFF: %s\nPARKED: 0\nNEXT: %s\n" % (
                           run, obj, state, cond, cycles, HANDOFF, nxt))


def test_resume_count():
    rc = stu_fleet.resume_count
    sb = lambda st, used="3/4", extra="": "Run state: %s\nCycles used: %s\n%s" % (st, used, extra)
    check("settled nothing to settle continues", rc(sb("settled 2026-01-02 — nothing to settle")), 3)
    check("settled other starts 0", rc(sb("settled 2026-01-02 — ruled 2 questions")), 0)
    check("stopped plain starts 0", rc(sb("stopped — BLOCKED: x")), 0)
    check("stopped with self-stop lane continues",
          rc(sb("stopped — BLOCKED: x", extra="Lane state: stopped — self-stop: context\n")), 3)
    check("self-stop text but state not stopped", rc(sb("running", extra="Lane state: self-stop: x\n")), 0)
    check("fleet-relaunch starts 0", rc(sb("fleet-relaunch 2026-01-03")), 0)
    check("running starts 0", rc(sb("running")), 0)
    check("waiting-on-human starts 0", rc(sb("waiting-on-human")), 0)
    check("no scoreboard starts 0", rc("# Objective: x\n"), 0)
    check("no cycles used starts 0", rc("Run state: settled 2026-01-02 — nothing to settle\n"), 0)
    check("template text above the scoreboard is ignored",
          rc("Run state: settled 2026-01-02 — nothing to settle\nCycles used: 9/9\n"
             "## Scoreboard\nRun state: running\nCycles used: 1/4\n"), 0)


def test_program_check():
    a = objective("a")
    b = objective("b", mode="overnight", lanes=3)
    program([("alpha", a, "none", "db"), ("beta", b, "alpha", "sim, db")],
            header=HEADER + "Max live lanes: 6\nCycle budget: 20\nJudgment jobs: none\n"
                   "Stop at: 2026-11-12T18:00:00+00:00\nMerge lock: off\n",
            tail="\n## Judgment work\n- g1: groom | scope: the ledger | output: /out/g1.md | "
                 "feeds: alpha\n\n## Excluded (owned by peer sessions)\nnotes\n\n## Machine limits\nx\n")
    rc, out, err = pfleet("program", "check", PROG)
    check("valid program exits 0", rc, 0)
    check("summary ends OK", out[-1], "OK")
    check("summary run line", "run beta: objective %s | cap 4 | lanes 3 | after alpha | "
          "resources sim,db" % b in out, True)
    check("summary header fields", ("max-live-lanes: 6" in out, "merge-lock: off" in out,
                                    "cycle-budget: 20" in out), (True, True, True))
    program([("alpha", a, "none", "none")])
    rc, out, err = pfleet("program", "check", PROG)
    check("defaults normalised", (rc, "merge-lock: on" in out, "cycle-budget: sum-of-caps" in out,
                                  "max-live-lanes: config" in out), (0, True, True, True))

    def blocked(name, text_or_runs, want, **kw):
        if isinstance(text_or_runs, str):
            write(PROG, text_or_runs)
        else:
            program(text_or_runs, **kw)
        rc, out, err = pfleet("program", "check", PROG)
        check("%s: exit 1" % name, (rc, out[-1]), (1, "BLOCKED"))
        check("%s: names it" % name, any(want in ln and "BLOCKED:" in ln for ln in out[:-1]), True)

    ok = [("alpha", a, "none", "none")]
    blocked("owner missing", "# x\nSettle mode: draft\n\n## Runs\n- r: %s | after: none | resources: none\n" % a,
            "Owner")
    blocked("settle mode missing", "# x\nOwner: p\n\n## Runs\n- r: %s | after: none | resources: none\n" % a,
            "Settle mode")
    blocked("settle mode bad", ok, "Settle mode", header="Owner: p\nSettle mode: maybe\n")
    for k, v, w in (("Max live lanes", "0", "Max live lanes"), ("Max live lanes", "x", "Max live lanes"),
                    ("Cycle budget", "0", "Cycle budget"), ("Cycle budget", "-3", "Cycle budget"),
                    ("Judgment jobs", "many", "Judgment jobs"), ("Stop at", "tomorrow", "Stop at"),
                    ("Stop at", "2026-11-12T18:00:00", "Stop at"), ("Stop at", "2026-13-40T18:00:00Z", "Stop at"),
                    ("Merge lock", "maybe", "Merge lock"), ("Colour", "red", "unknown header")):
        blocked("%s %s" % (k, v), ok, w, header=HEADER + "%s: %s\n" % (k, v))
    check("none and Z accepted", pfleet("program", "check", program(ok, header=HEADER +
          "Cycle budget: none\nJudgment jobs: none\nStop at: 2026-11-12T18:00Z\n"))[0], 0)
    blocked("no runs", HEADER + "\n## Runs\n", "no runs")
    blocked("run shape", HEADER + "\n## Runs\n- alpha %s\n" % a, "run line must be")
    blocked("relative objective", [("alpha", "rel/o.md", "none", "none")], "not absolute")
    blocked("missing objective", [("alpha", os.path.join(PDIR, "nope.md"), "none", "none")], "does not exist")
    blocked("no cycle cap", [("alpha", objective("nocap", cap=""), "none", "none")], "Cycle cap")
    blocked("dup slug", [("alpha", a, "none", "none"), ("alpha", a, "none", "none")], "appears twice")
    blocked("unknown after", [("alpha", a, "ghost", "none")], "not a run")
    blocked("self after", [("alpha", a, "alpha", "none")], "itself")
    blocked("cycle", [("alpha", a, "gamma", "none"), ("beta", a, "alpha", "none"),
                      ("gamma", a, "beta", "none")], "cycle among runs")
    blocked("unknown section", HEADER + "\n## Runz\n", "unknown section")
    blocked("judgment kind", ok, "judgment line", tail="\n## Judgment work\n- g: fix | scope: s | output: /o | feeds: none\n")
    blocked("judgment feeds unknown", ok, "feeds",
            tail="\n## Judgment work\n- g: groom | scope: s | output: /o | feeds: ghost\n")
    rc, out, err = pfleet("program", "check", os.path.join(PDIR, "absent.md"))
    check("unreadable exits 3", rc, 3)
    check("usage exits 2", (pfleet("program", "check")[0], pfleet("program")[0],
                            pfleet("board", "launch", PROG)[0]), (2, 2, 2))


BOARD_HEAD = "- {s} | state: {st} | cycles: {c} | launches: {l} | from: {f} | handoff: {h} | stop: {p}"


def brd(s, st="queued", c=0, l=0, f=0, h="none", p="none"):
    return BOARD_HEAD.format(s=s, st=st, c=c, l=l, f=f, h=h, p=p)


def two_runs(extra_tail="", board=None):
    a = objective("a", cap="4")
    b = objective("b", cap="6")
    program([("alpha", a, "none", "db"), ("beta", b, "alpha", "none")],
            tail=extra_tail + ("\n## Fleet board\n" + "".join(x + "\n" for x in board) if board is not None else ""))
    return a, b


def test_board():
    a, b = two_runs()
    rc, out, err = pfleet("board", "show", PROG)
    check("show defaults queued", (rc, out), (0, [brd("alpha"), brd("beta")]))
    check("show does not write", os.path.exists(PROG + ".lock"), False)
    before = open(PROG).read()
    check("show leaves the file", open(PROG).read(), before)
    # launch
    rc, out, err = pfleet("board", "launch", PROG, "--run", "alpha")
    check("launch ok", (rc, out), (0, [brd("alpha", "live", l=1)]))
    txt = open(PROG).read()
    check("sections before the board untouched", txt.startswith(before.rstrip("\n")), True)
    check("board section appended with every run", txt.endswith("## Fleet board\n%s\n%s\n" % (
        brd("alpha", "live", l=1), brd("beta"))), True)
    rc, out, err = pfleet("board", "launch", PROG, "--run", "alpha")
    check("launch live refused 13", (rc, out[0].startswith("REFUSED fleet-board:")), (13, True))
    check("refused launch wrote nothing", open(PROG).read(), txt)
    check("unknown run is usage", pfleet("board", "launch", PROG, "--run", "ghost")[0], 2)
    # record
    ret = run_ret(os.path.join(PDIR, "ret.txt"), a)
    rc, out, err = pfleet("board", "record", PROG, "--run", "alpha", "--return", ret)
    check("record ok", (rc, out), (0, [brd("alpha", "relaunch", c=3, l=1, h=HANDOFF,
                                           p="10 — cycle cap exhausted")]))
    check("record on non-live refused", pfleet("board", "record", PROG, "--run", "alpha",
                                               "--return", ret)[0], 13)
    # requeue
    rc, out, err = pfleet("board", "requeue", PROG, "--run", "alpha")
    check("requeue ok keeps counts", (rc, out[0].split(" | ")[1:4]),
          (0, ["state: queued", "cycles: 3", "launches: 1"]))
    check("requeue queued refused", pfleet("board", "requeue", PROG, "--run", "alpha")[0], 13)
    # relaunch resumes from the objective's count rule: a fleet-relaunch state starts at 0
    with open(a, "a") as f:
        f.write("Run state: fleet-relaunch 2026-01-05\nCycles used: 3/4\n")
    rc, out, err = pfleet("board", "launch", PROG, "--run", "alpha")
    check("relaunch from fleet-relaunch resumes at 0", out[0].split(" | ")[4], "from: 0")
    ret2 = run_ret(os.path.join(PDIR, "ret2.txt"), a, cycles="2/4")
    rc, out, err = pfleet("board", "record", PROG, "--run", "alpha", "--return", ret2)
    check("cycles accumulate across launches", out[0].split(" | ")[2:4], ["cycles: 5", "launches: 2"])


def test_board_continue_and_negative():
    a = objective("a", scoreboard="Run state: settled 2026-01-02 — nothing to settle\nCycles used: 3/4\n")
    b = objective("b", scoreboard="Run state: stopped — BLOCKED: x\nCycles used: 2/4\n"
                                  "Lane state: stopped — self-stop: context\n")
    program([("alpha", a, "none", "none"), ("beta", b, "none", "none")])
    rc, out, err = pfleet("board", "launch", PROG, "--run", "alpha")
    check("launch continues a settled run", out[0].split(" | ")[4], "from: 3")
    rc, out, err = pfleet("board", "launch", PROG, "--run", "beta")
    check("launch continues a self-stop run", out[0].split(" | ")[4], "from: 2")
    ret = run_ret(os.path.join(PDIR, "neg.txt"), a, cycles="1/4")
    before = open(PROG).read()
    rc, out, err = pfleet("board", "record", PROG, "--run", "alpha", "--return", ret)
    check("negative delta refused", (rc, "negative delta" in out[0]), (13, True))
    check("negative delta wrote nothing", open(PROG).read(), before)
    other = objective("other")
    wrong = run_ret(os.path.join(PDIR, "wrong.txt"), other, cycles="4/4")
    rc, out, err = pfleet("board", "record", PROG, "--run", "alpha", "--return", wrong)
    check("return for another objective refused", rc, 13)
    junk = write(os.path.join(PDIR, "junk.txt"), "STU-RUN: STOPPED\nNEXT: owner\n")
    rc, out, err = pfleet("board", "record", PROG, "--run", "alpha", "--return", junk)
    check("invalid return is BLOCKED, exit 1", (rc, out[-1], any("BLOCKED missing" in x for x in out)),
          (1, "BLOCKED", True))
    inconsistent = run_ret(os.path.join(PDIR, "inc.txt"), a, nxt="none")
    check("NEXT inconsistent with condition is BLOCKED",
          pfleet("board", "record", PROG, "--run", "alpha", "--return", inconsistent)[0], 1)
    check("unreadable return exits 3", pfleet("board", "record", PROG, "--run", "alpha",
                                              "--return", os.path.join(PDIR, "absent.txt"))[0], 3)
    # NEXT mapping and pipe sanitising
    for nxt, cond, run, state, want in (("none", "none", "DONE", "settled 2026-01-01 — x", "done"),
                                        ("settle", "2 — a | b", "STOPPED", "stopped — BLOCKED: q", "settle"),
                                        ("owner", "4 — stuck", "STOPPED", "stopped — BLOCKED: q", "owner")):
        program([("alpha", a, "none", "none")])
        pfleet("board", "launch", PROG, "--run", "alpha")
        r = run_ret(os.path.join(PDIR, "m.txt"), a, run=run, cond=cond, nxt=nxt, state=state, cycles="3/4")
        rc, out, err = pfleet("board", "record", PROG, "--run", "alpha", "--return", r)
        check("NEXT %s -> %s" % (nxt, want), (rc, out[0].split(" | ")[1]), (0, "state: %s" % want))
        if "|" in cond:
            check("pipe in stop replaced", out[0].endswith("stop: 2 — a / b"), True)
        check("done run is not relaunched" if want == "done" else "launch of %s refused? no" % want,
              pfleet("board", "launch", PROG, "--run", "alpha")[0], 13 if want == "done" else 0)
    for st in ("queued", "live", "done"):
        program([("alpha", a, "none", "none")],
                tail="\n## Fleet board\n" + brd("alpha", st) + "\n")
        check("requeue from %s refused" % st, pfleet("board", "requeue", PROG, "--run", "alpha")[0], 13)


def test_board_errors_and_preservation():
    a = objective("a")
    program([("alpha", a, "none", "none")], tail="\n## Fleet board\n" + brd("ghost") + "\n")
    rc, out, err = pfleet("board", "show", PROG)
    check("board slug not in Runs exits 3", (rc, "ghost" in err), (3, True))
    check("check also exits 3", pfleet("program", "check", PROG)[0], 3)
    program([("alpha", a, "none", "none")], tail="\n## Fleet board\n- alpha | state: busy | cycles: 1\n")
    check("malformed board line exits 3", pfleet("board", "show", PROG)[0], 3)
    program([("alpha", a, "none", "none")], tail="\n## Fleet board\n" + brd("alpha") + "\n" + brd("alpha") + "\n")
    check("duplicate board line exits 3", pfleet("board", "show", PROG)[0], 3)
    # a board between other sections: nothing outside it changes, the file keeps its mode
    write(PROG, HEADER + "\n## Runs\n- alpha: %s | after: none | resources: none\n\n"
          "## Fleet board        (coordinator writes)\n%s\n\n## Machine limits\nkeep  me \n" % (a, brd("alpha")))
    os.chmod(PROG, 0o640)
    pfleet("board", "launch", PROG, "--run", "alpha")
    txt = open(PROG).read()
    check("heading and later section preserved", ("## Fleet board        (coordinator writes)\n" in txt,
          txt.endswith("\n\n## Machine limits\nkeep  me \n")), (True, True))
    check("board line replaced", brd("alpha", "live", l=1) in txt, True)
    check("mode preserved", oct(os.stat(PROG).st_mode & 0o777), "0o640")
    leftovers = [f for f in os.listdir(PDIR) if f.startswith(".fleet-program-")]
    check("no temp files left", leftovers, [])
    # program problems block every command that reads one
    write(PROG, "Owner: p\n")
    check("board launch on invalid program is exit 1", pfleet("board", "launch", PROG, "--run", "x")[0], 1)
    check("spend on invalid program is exit 1", pfleet("spend", PROG)[0], 1)
    check("next on invalid program is exit 1", pfleet("next", PROG)[0], 1)


def test_spend():
    a = objective("a", cap="4")
    b = objective("b", cap="6")
    program([("alpha", a, "none", "none"), ("beta", b, "none", "none")],
            tail="\n## Fleet board\n" + brd("alpha", "done", c=5, l=2) + "\n" + brd("beta", "live", c=3, l=1) + "\n")
    rc, out, err = pfleet("spend", PROG)
    check("spend default budget is the sum of caps", (rc, out), (0, [
        "run alpha: cycles 5, launches 2", "run beta: cycles 3, launches 1", "fleet: cycles 8",
        "budget: 8/10 (80%)", "judgment-jobs: not counted yet"]))
    program([("alpha", a, "none", "none")], header=HEADER + "Cycle budget: 40\n")
    check("explicit budget", pfleet("spend", PROG)[1][-2], "budget: 0/40 (0%)")
    program([("alpha", a, "none", "none")], header=HEADER + "Cycle budget: none\n")
    check("budget none", pfleet("spend", PROG)[1][-2], "budget: 0/none")


def test_next():
    reset()
    a = objective("a")
    b = objective("b")
    c = objective("c", mode="overnight", lanes=3)
    d = objective("d")
    program([("alpha", a, "none", "db"), ("beta", b, "alpha", "none"), ("gamma", c, "none", "db, sim"),
             ("delta", d, "none", "sim")])
    rc, out, err = pfleet("next", PROG)
    check("fresh fleet", (rc, out), (0, [
        "start alpha", "wait beta — after alpha", "wait gamma — resource db held by alpha",
        "start delta", "hold: clear", "lanes: 0/4"]))
    # resources held by a live run; lane accounting
    program([("alpha", a, "none", "db"), ("gamma", c, "none", "sim"), ("delta", d, "none", "sim"),
             ("eps", d, "none", "none")], tail="\n## Fleet board\n" + brd("alpha", "live") + "\n")
    rc, out, err = pfleet("next", PROG)
    check("overnight run counts its lanes, later start sees earlier start",
          out, ["live alpha", "start gamma", "wait delta — resource sim held by gamma",
                "wait eps — lane cap 4/4", "hold: clear", "lanes: 1/4"])
    rc, out, err = pfleet("next", PROG, extra={"STU_FLEET_MAX_LANES": "2"})
    check("cap from config hook", (out[1], out[-1]), ("owner gamma — needs 3 lanes, cap 2", "lanes: 1/2"))
    program([("alpha", a, "none", "db"), ("gamma", c, "none", "sim")],
            header=HEADER + "Max live lanes: 9\n", tail="\n## Fleet board\n" + brd("alpha", "live") + "\n")
    check("program cap overrides config", pfleet("next", PROG, extra={"STU_FLEET_MAX_LANES": "2"})[1],
          ["live alpha", "start gamma", "hold: clear", "lanes: 1/9"])
    # board states
    program([("r1", a, "none", "none"), ("r2", a, "none", "none"), ("r3", a, "none", "none"),
             ("r4", a, "none", "none"), ("r5", a, "none", "none"), ("r6", a, "none", "none"),
             ("r7", a, "none", "none")],
            tail="\n## Fleet board\n" + "".join(x + "\n" for x in (
                brd("r1", "settle", p="1 — q"), brd("r2", "settle", p="2 — sc2"),
                brd("r3", "settle", p="3 — row"), brd("r4", "owner", p="4 — stuck"),
                brd("r5", "relaunch", p="10 — cap"), brd("r6", "done"),
                brd("r7", "queued"))))
    rc, out, err = pfleet("next", PROG)
    check("state lines", out, [
        "settle r1", "settle r2 owner-only", "settle r3 owner-only", "owner r4 — 4 — stuck",
        "relaunch r5 — 10 — cap", "done r6", "start r7", "hold: clear", "lanes: 0/4"])
    program([("alpha", a, "none", "none"), ("beta", b, "alpha", "none")],
            tail="\n## Fleet board\n" + brd("alpha", "done") + "\n")
    check("after done starts", pfleet("next", PROG)[1][:2], ["done alpha", "start beta"])
    # hold line
    check("hold set", pfleet("hold", "set", "--reason", "deploy first")[0], 0)
    check("hold shown", pfleet("next", PROG)[1][-2:], ["hold: set — deploy first", "lanes: 0/4"])
    reset()
    # lock release by observation
    pr(7, state="merged")
    take(7)
    rc, out, err = pfleet("next", PROG)
    check("merged holder released", (rc, out[0]), (0, "lock: released %s#7 (merged)" % SLUG))
    check("lock cleared in the state file", state()["lock"], None)
    pr(8, state="open", labels="merge-ok")
    take(8)
    rc, out, err = pfleet("next", PROG)
    check("open labelled holder stays", (rc, out[0].startswith("lock:"), state()["lock"]["pr"]), (0, False, 8))
    reset()
    pr(9, state="closed")
    take(9)
    check("closed holder released", pfleet("next", PROG)[1][0].endswith("(closed)"), True)
    reset()
    pr(10)
    take(10)
    pr_unreachable(10)
    rc, out, err = pfleet("next", PROG)
    check("unreachable forge: full output, exit 12, lock kept",
          (rc, out[0].startswith("lock: held by %s#10" % SLUG), out[-1], state()["lock"]["pr"]),
          (12, True, "lanes: 0/4", 10))
    reset()
    check("no state file is not an error", pfleet("next", PROG)[0], 0)


def test_review_fixes():
    a = objective("a")
    obj = write(os.path.join(PDIR, "hd-objective.md"),
                "# O\n\nWritten x. Mode: overnight. Cycle cap: 4.\n\n## Scoreboard\n\n"
                "### Lane: A\nLane state: running\n## Lane: B\nLane state: running\n")
    check("markdown lane headings counted", stu_fleet.objective_facts(obj)[1], 2)
    # a handoff path with a space round-trips through record, show and next
    program([("alpha", a, "none", "none")])
    pfleet("board", "launch", PROG, "--run", "alpha")
    ret = run_ret(os.path.join(PDIR, "sp.txt"), a, cycles="1/4")
    text = open(ret).read().replace(HANDOFF, "/x/my handoff.md")
    write(ret, text)
    check("record with spaced handoff", pfleet("board", "record", PROG, "--run", "alpha", "--return", ret)[0], 0)
    rc, out, err = pfleet("board", "show", PROG)
    check("show reads it back", (rc, "handoff: /x/my handoff.md | stop:" in out[0]), (0, True))
    check("next reads it back", pfleet("next", PROG)[0], 0)
    # a run needing more lanes than the cap
    big = objective("big", mode="overnight", lanes=3)
    program([("big", big, "none", "none")])
    rc, out, err = pfleet("next", PROG, extra={"STU_FLEET_MAX_LANES": "2"})
    check("oversize run goes to the owner", out[0], "owner big \u2014 needs 3 lanes, cap 2")
    program([("big", big, "none", "none")], header=HEADER + "Max live lanes: 2\n")
    rc, out, err = pfleet("program", "check", PROG)
    check("check blocks oversize run", (rc, any("3 lanes" in x for x in out)), (1, True))


def test_fleet_usage():
    check("unknown program subcommand", pfleet("program", "run", PROG)[0], 2)
    check("unknown flag", pfleet("spend", PROG, "--run", "x")[0], 2)
    check("spend needs a path", pfleet("spend")[0], 2)


for t in (test_no_file_means_no_hold, test_lock_take_basics, test_hold_refuses_take,
          test_hold_returns_holder_and_records_landing, test_release_landed_during_hold,
          test_stale_holder_released_on_the_forge, test_forge_unreachable_refuses,
          test_real_forge_through_fake_gh, test_fail_closed_on_bad_state, test_usage,
          test_concurrent_takes_serialise, test_resume_count, test_program_check, test_board,
          test_board_continue_and_negative, test_board_errors_and_preservation, test_spend,
          test_next, test_review_fixes, test_fleet_usage):
    t()

if FAILURES:
    print("FAIL %d of %d checks" % (len(FAILURES), COUNT[0]))
    for f in FAILURES:
        print("  " + f)
    sys.exit(1)
print("ok: %d checks" % COUNT[0])
