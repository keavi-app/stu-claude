#!/usr/bin/env python3
"""Regression suite for stu_fleet.py (merge hold and lock), through the bin/ wrapper.

The forge is a stand-in script (STU_FLEET_FORGE) except for one case that runs the real
stu-forge against the shared fake `gh`. Nothing touches the network or the real run home.
Run: python3 scripts/stu_fleet_test.py
"""
import json
import os
import re
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
        "- %s: %s | after: %s | resources: %s%s\n" % (r[:4] + (
            " | lanes: %s" % r[4] if len(r) > 4 else "",)) for r in runs) + tail)


NO_PROJECTS = os.path.join(TMP, "no-projects")


def pfleet(*args, **kw):
    kw.setdefault("extra", {})
    kw["extra"].setdefault("STU_FLEET_MAX_LANES", "4")
    kw["extra"].setdefault("STU_PROJECTS_ROOT", NO_PROJECTS)  # never the real transcripts
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
    program([("alpha", a, "none", "db"), ("beta", b, "alpha", "sim, db", 3)],
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


BOARD_HEAD = ("- {s} | state: {st} | cycles: {c} | launches: {l} | from: {f} | closed: {k} | "
              "dry: {d} | nonce: {n} | agents: {a} | out: {o} | draft: {dr} | written: {w} | "
              "handoff: {h} | stop: {p}")
FLEET0 = "- fleet | judgment: 0 | agents: 0 | out: 0 | notices: none"
NONCE = "stu-testnonce01"


def brd(s, st="queued", c=0, l=0, f=0, h="none", p="none", k=0, d=0, n="none", a=0, o=0,
        dr="none", w="none"):
    return BOARD_HEAD.format(s=s, st=st, c=c, l=l, f=f, h=h, p=p, k=k, d=d, n=n, a=a, o=o, dr=dr, w=w)


def v3(s, st="queued", c=0, l=0, f=0, h="none", p="none", k=0, d=0, n="none", a=0, o=0):
    return ("- %s | state: %s | cycles: %d | launches: %d | from: %d | closed: %d | dry: %d | "
            "nonce: %s | agents: %d | out: %d | handoff: %s | stop: %s") % (
        s, st, c, l, f, k, d, n, a, o, h, p)


def v2(s, st="queued", c=0, l=0, f=0, h="none", p="none", k=0, d=0, n="none"):
    return ("- %s | state: %s | cycles: %d | launches: %d | from: %d | closed: %d | dry: %d | "
            "nonce: %s | handoff: %s | stop: %s") % (s, st, c, l, f, k, d, n, h, p)


def v1(s, st="queued", c=0, l=0, f=0, h="none", p="none"):
    return "- %s | state: %s | cycles: %d | launches: %d | from: %d | handoff: %s | stop: %s" % (
        s, st, c, l, f, h, p)


def two_runs(extra_tail="", board=None):
    a = objective("a", cap="4")
    b = objective("b", cap="6")
    program([("alpha", a, "none", "db"), ("beta", b, "alpha", "none")],
            tail=extra_tail + ("\n## Fleet board\n" + "".join(x + "\n" for x in board) if board is not None else ""))
    return a, b


def test_board():
    a, b = two_runs()
    rc, out, err = pfleet("board", "show", PROG)
    check("show defaults queued", (rc, out), (0, [brd("alpha"), brd("beta"), FLEET0]))
    check("show does not write", os.path.exists(PROG + ".lock"), False)
    before = open(PROG).read()
    check("show leaves the file", open(PROG).read(), before)
    # launch
    rc, out, err = pfleet("board", "launch", PROG, "--run", "alpha", extra={"STU_FLEET_NONCE": NONCE})
    check("launch ok", (rc, out), (0, [brd("alpha", "live", l=1, n=NONCE), "nonce: " + NONCE]), )
    txt = open(PROG).read()
    check("sections before the board untouched", txt.startswith(before.rstrip("\n")), True)
    check("board section appended with every run", txt.endswith("## Fleet board\n%s\n%s\n%s\n" % (
        brd("alpha", "live", l=1, n=NONCE), brd("beta"), FLEET0)), True)
    rc, out, err = pfleet("board", "launch", PROG, "--run", "alpha")
    check("launch live refused 13", (rc, out[0].startswith("REFUSED fleet-board:")), (13, True))
    check("refused launch wrote nothing", open(PROG).read(), txt)
    check("unknown run is usage", pfleet("board", "launch", PROG, "--run", "ghost")[0], 2)
    # record
    ret = run_ret(os.path.join(PDIR, "ret.txt"), a)
    rc, out, err = pfleet("board", "record", PROG, "--run", "alpha", "--return", ret)
    check("record ok", (rc, out[:1], len(out), out[1].startswith("actuals: unavailable \u2014 ")),
          (0, [brd("alpha", "relaunch", c=3, l=1, h=HANDOFF, d=1, n=NONCE,
                   p="10 — cycle cap exhausted")], 2, True))
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
        check("launch of a %s run refused 13" % want,
              pfleet("board", "launch", PROG, "--run", "alpha")[0], 13)
    for st in ("queued", "live", "done"):
        program([("alpha", a, "none", "none")],
                tail="\n## Fleet board\n" + brd("alpha", st) + "\n")
        check("requeue from %s refused" % st, pfleet("board", "requeue", PROG, "--run", "alpha")[0], 13)


def test_launch_only_from_queued():
    a = objective("a")
    for st in ("settle", "relaunch", "owner", "done", "live"):
        program([("alpha", a, "none", "none")], tail="\n## Fleet board\n" + brd("alpha", st, p="10 — c") + "\n")
        before = open(PROG).read()
        rc, out, err = pfleet("board", "launch", PROG, "--run", "alpha")
        check("launch from %s refused 13" % st, (rc, "not queued" in out[0], open(PROG).read()), (13, True, before))


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
    pfleet("board", "launch", PROG, "--run", "alpha", extra={"STU_FLEET_NONCE": NONCE})
    txt = open(PROG).read()
    check("heading and later section preserved", ("## Fleet board        (coordinator writes)\n" in txt,
          txt.endswith("\n\n## Machine limits\nkeep  me \n")), (True, True))
    check("board line replaced", brd("alpha", "live", l=1, n=NONCE) in txt, True)
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
        "run alpha: cycles 5, launches 2, dry 0, agents 0, out 0", "run beta: cycles 3, launches 1, dry 0, agents 0, out 0",
        "fleet: cycles 8, agents 0, out 0", "budget: 8/10 (80%)", "judgment-jobs: 0/none", "stop-at: none (not passed)"]))
    program([("alpha", a, "none", "none")], header=HEADER + "Cycle budget: 40\n")
    check("explicit budget", pfleet("spend", PROG)[1][-3], "budget: 0/40 (0%)")
    program([("alpha", a, "none", "none")], header=HEADER + "Cycle budget: none\n")
    check("budget none", pfleet("spend", PROG)[1][-3], "budget: 0/none")


def test_next():
    reset()
    a = objective("a")
    b = objective("b")
    c = objective("c", mode="overnight", lanes=3)
    d = objective("d")
    program([("alpha", a, "none", "db"), ("beta", b, "alpha", "none"), ("gamma", c, "none", "db, sim", 3),
             ("delta", d, "none", "sim")])
    rc, out, err = pfleet("next", PROG)
    check("fresh fleet", (rc, out), (0, [
        "start alpha", "wait beta — after alpha", "wait gamma — resource db held by alpha",
        "start delta", "hold: clear", "lanes: 0/4", "budget: 0/16", "judgment-jobs: 0/none"]))
    # resources held by a live run; lane accounting
    program([("alpha", a, "none", "db"), ("gamma", c, "none", "sim", 3), ("delta", d, "none", "sim"),
             ("eps", d, "none", "none")], tail="\n## Fleet board\n" + brd("alpha", "live") + "\n")
    rc, out, err = pfleet("next", PROG)
    check("overnight run counts its lanes, later start sees earlier start",
          out, ["live alpha", "start gamma", "wait delta — resource sim held by gamma",
                "wait eps — lane cap 4/4", "hold: clear", "lanes: 1/4", "budget: 0/16",
                "judgment-jobs: 0/none"])
    rc, out, err = pfleet("next", PROG, extra={"STU_FLEET_MAX_LANES": "2"})
    check("cap from config hook", (out[1], out[-3]), ("owner gamma — needs 3 lanes, cap 2", "lanes: 1/2"))
    program([("alpha", a, "none", "db"), ("gamma", c, "none", "sim", 3)],
            header=HEADER + "Max live lanes: 9\n", tail="\n## Fleet board\n" + brd("alpha", "live") + "\n")
    check("program cap overrides config", pfleet("next", PROG, extra={"STU_FLEET_MAX_LANES": "2"})[1],
          ["live alpha", "start gamma", "hold: clear", "lanes: 1/9", "budget: 0/8",
           "judgment-jobs: 0/none"])
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
        "relaunch r5 — 10 — cap", "done r6", "start r7", "hold: clear", "lanes: 0/4",
        "budget: 0/28", "judgment-jobs: 0/none"])
    program([("alpha", a, "none", "none"), ("beta", b, "alpha", "none")],
            tail="\n## Fleet board\n" + brd("alpha", "done") + "\n")
    check("after done starts", pfleet("next", PROG)[1][:2], ["done alpha", "start beta"])
    # hold line
    check("hold set", pfleet("hold", "set", "--reason", "deploy first")[0], 0)
    check("hold shown", pfleet("next", PROG)[1][-4:-2], ["hold: set — deploy first", "lanes: 0/4"])
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
          (12, True, "judgment-jobs: 0/none", 10))
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
    program([("big", big, "none", "none", 3)])
    rc, out, err = pfleet("next", PROG, extra={"STU_FLEET_MAX_LANES": "2"})
    check("oversize run goes to the owner", out[0], "owner big \u2014 needs 3 lanes, cap 2")
    program([("big", big, "none", "none", 3)], header=HEADER + "Max live lanes: 2\n")
    rc, out, err = pfleet("program", "check", PROG)
    check("check blocks oversize run", (rc, any("3 lanes" in x for x in out)), (1, True))


def test_fleet_usage():
    check("unknown program subcommand", pfleet("program", "run", PROG)[0], 2)
    check("unknown flag", pfleet("spend", PROG, "--run", "x")[0], 2)
    check("spend needs a path", pfleet("spend")[0], 2)


OH = "# O\n\nWritten 2026-01-01. Mode: plain. Cycle cap: 4.\n\n"


def field(line, name):
    return [x.split(": ", 1)[1] for x in line.split(" | ") if x.startswith(name + ": ")][0]


def test_declared_lanes():
    a = objective("a")
    c = objective("c", mode="overnight", lanes=1)
    c3 = objective("c3", mode="overnight", lanes=3)

    def blocked(name, runs, want, **kw):
        program(runs, **kw)
        rc, out, err = pfleet("program", "check", PROG)
        check(name, (rc, any(want in x and "BLOCKED:" in x for x in out)), (1, True))

    blocked("overnight without lanes", [("alpha", c, "none", "none")], "must declare '| lanes: <n>'")
    blocked("plain with lanes 2", [("alpha", a, "none", "none", 2)], "plain objective runs one lane")
    blocked("lanes zero", [("alpha", a, "none", "none", 0)], "lanes: must be a positive integer")
    program([("alpha", a, "none", "none", 1)])
    check("plain with lanes 1 ok", pfleet("program", "check", PROG)[0], 0)
    program([("alpha", c, "none", "none", 3)])
    rc, out, err = pfleet("program", "check", PROG)
    check("declared beats counted", (rc, any("| lanes 3 |" in x for x in out)), (0, True))
    program([("alpha", c3, "none", "none", 2)])
    check("counted beats declared", any("| lanes 3 |" in x for x in pfleet("program", "check", PROG)[1]), True)
    blocked("declared over Max live lanes", [("alpha", c, "none", "none", 3)], "declares 3 lanes",
            header=HEADER + "Max live lanes: 2\n")
    blocked("counted over Max live lanes", [("alpha", c3, "none", "none", 2)], "declares 3 lanes",
            header=HEADER + "Max live lanes: 2\n")
    rc, out, err = pfleet("next", PROG, extra={"STU_FLEET_MAX_LANES": "2"})
    check("next refuses the invalid program", rc, 1)
    blocked("fleet is a reserved slug", [("fleet", a, "none", "none")], "reserved")


def test_closed_count():
    cc = stu_fleet.closed_count
    check("NONE is zero", cc("## Scoreboard\nClosed: NONE\n"), 0)
    check("plain list", cc("## Scoreboard\nClosed: S1, S2 (merged), #3\n"), 3)
    check("union across lanes", cc("## Scoreboard\n### Lane: A\nClosed: S1, S2\n### Lane: B\nClosed: S2, S3\n"), 3)
    check("overnight with a NONE lane", cc("## Scoreboard\nLane: A\nClosed: NONE\nLane: B\nClosed: S9\n"), 1)
    check("template text above the scoreboard ignored", cc("Closed: X, Y\n## Scoreboard\nClosed: NONE\n"), 0)
    check("no Closed line", cc("# x\n"), 0)


def test_board_v2_grammar():
    a = objective("a")
    b = objective("b")
    prog_runs = [("alpha", a, "none", "none"), ("beta", b, "none", "none")]
    # a v1 board reads as closed 0, dry 0, nonce none, and no fleet line reads judgment 0
    program(prog_runs, tail="\n## Fleet board\n" + v1("alpha", "relaunch", c=2, l=1, h="/h.md", p="10 — cap") + "\n" +
            v1("beta") + "\n")
    rc, out, err = pfleet("board", "show", PROG)
    check("v1 board migrates on read", (rc, out), (0, [
        brd("alpha", "relaunch", c=2, l=1, h="/h.md", p="10 — cap"), brd("beta"), FLEET0]))
    rc, out, err = pfleet("board", "requeue", PROG, "--run", "alpha")
    check("next write emits v4 for every line", open(PROG).read().endswith(
        "## Fleet board\n%s\n%s\n%s\n" % (brd("alpha", c=2, l=1, h="/h.md", p="10 — cap"), brd("beta"), FLEET0)), True)
    # mixed v1 and v2, a fleet line with notices
    program(prog_runs, tail="\n## Fleet board\n" + brd("alpha", "live", k=2, d=1, n="stu-x1234567") + "\n" +
            v1("beta", "done", c=3) + "\n- fleet | judgment: 2 | notices: cycle-80,stop-at\n")
    rc, out, err = pfleet("board", "show", PROG)
    check("mixed board", (rc, out), (0, [brd("alpha", "live", k=2, d=1, n="stu-x1234567"),
                                         brd("beta", "done", c=3),
                                         "- fleet | judgment: 2 | agents: 0 | out: 0 | notices: cycle-80,stop-at"]))
    for name, tail in (
            ("fleet line not last", brd("alpha") + "\n- fleet | judgment: 0 | notices: none\n" + brd("beta") + "\n"),
            ("duplicate fleet line", FLEET0 + "\n" + FLEET0 + "\n"),
            ("unknown notice id", "- fleet | judgment: 0 | notices: cycle-90\n"),
            ("malformed fleet line", "- fleet | notices: none\n"),
            ("v2 line with a bad nonce field", brd("alpha").replace("nonce: none", "nonse: none") + "\n")):
        program(prog_runs, tail="\n## Fleet board\n" + tail)
        check(name + " exits 3", pfleet("board", "show", PROG)[0], 3)


def asst_rec(rid, model, out):
    return {"type": "assistant", "requestId": rid, "message": {
        "id": "m-" + rid, "model": model, "usage": {"output_tokens": out}}}


def put_agent(root, session, aid, seat, parent=None, nonce=None, recs=()):
    sdir = os.path.join(root, "proj", session, "subagents")
    os.makedirs(sdir, exist_ok=True)
    meta = {"agentType": seat, "finished": True}
    if parent:
        meta["parentAgentId"] = parent
    with open(os.path.join(sdir, "agent-%s.meta.json" % aid), "w") as f:
        json.dump(meta, f)
    first = {"type": "user", "message": {"content": "go\n" + ("STU-SUPERVISED: %s\n" % nonce if nonce else "")}}
    with open(os.path.join(sdir, "agent-%s.jsonl" % aid), "w") as f:
        for r in [first] + list(recs):
            f.write(json.dumps(r) + "\n")


def test_actuals():
    root = os.path.join(TMP, "projects")
    env = {"STU_PROJECTS_ROOT": root}
    o = lifecycle()
    log = PROG + ".actuals.jsonl"
    if os.path.exists(log):
        os.remove(log)  # earlier tests share this program path and left records
    ret = run_ret(os.path.join(PDIR, "act.txt"), o, nxt="owner", cond="4 \u2014 x")
    check("actuals on an empty log", pfleet("actuals", PROG), (0, ["actuals: none recorded"], ""))
    check("actuals needs a path", pfleet("actuals")[0], 2)
    # launch one: the supervisor lives in another session than its subagents' consumer would
    put_agent(root, "s1", "sup", "stu:supervisor", nonce="stu-act-one", recs=[asst_rec("a", "claude-opus-x", 10)])
    put_agent(root, "s1", "imp", "stu:implementer", parent="sup", recs=[
        asst_rec("b", "claude-sonnet-x", 5), asst_rec("b", "claude-sonnet-x", 50), asst_rec("c", "claude-opus-x", 20)])
    put_agent(root, "s1", "rev", "stu:reviewer", parent="imp", recs=[asst_rec("d", "claude-sonnet-x", 8)])
    pfleet("board", "launch", PROG, "--run", "alpha", extra={"STU_FLEET_NONCE": "stu-act-one"})
    rc, out, err = pfleet("board", "record", PROG, "--run", "alpha", "--return", ret, extra=env)
    check("record adds agents and out, prints no actuals line", (rc, len(out), field(out[0], "agents"),
          field(out[0], "out")), (0, 1, "3", "88"))
    entries = [json.loads(x) for x in open(log)]
    check("one log line with the shape", (len(entries), sorted(entries[0]), entries[0]["agents"], entries[0]["out"]),
          (1, ["agents", "by_seat_model", "nonce", "out", "recorded_at", "slug"], 3, 88))
    check("log rows", entries[0]["by_seat_model"], [
        {"seat": "stu:implementer", "model": "claude-opus-x", "agents": 1, "turns": 1, "out": 20},
        {"seat": "stu:implementer", "model": "claude-sonnet-x", "agents": 1, "turns": 1, "out": 50},
        {"seat": "stu:reviewer", "model": "claude-sonnet-x", "agents": 1, "turns": 1, "out": 8},
        {"seat": "stu:supervisor", "model": "claude-opus-x", "agents": 1, "turns": 1, "out": 10}])
    check("fleet line carries the totals", pfleet("board", "show", PROG)[1][-1],
          "- fleet | judgment: 0 | agents: 3 | out: 88 | notices: none")
    # launch two: transcript missing -> still succeeds, adds nothing, logs unavailable
    pfleet("board", "requeue", PROG, "--run", "alpha")
    pfleet("board", "launch", PROG, "--run", "alpha", extra={"STU_FLEET_NONCE": "stu-act-gone"})
    rc, out, err = pfleet("board", "record", PROG, "--run", "alpha", "--return", ret, extra=env)
    check("missing transcript never blocks the record", (rc, field(out[0], "agents"), field(out[0], "out"),
          out[1].startswith("actuals: unavailable \u2014 no agent file under ")), (0, "3", "88", True))
    # launch three: ambiguous nonce, via idle
    put_agent(root, "s2", "d1", "stu:supervisor", nonce="stu-act-two")
    put_agent(root, "s3", "d2", "stu:supervisor", nonce="stu-act-two")
    pfleet("board", "requeue", PROG, "--run", "alpha")
    pfleet("board", "launch", PROG, "--run", "alpha", extra={"STU_FLEET_NONCE": "stu-act-two"})
    rc, out, err = pfleet("board", "idle", PROG, "--run", "alpha", extra=env)
    check("idle with an ambiguous nonce still succeeds", (rc, field(out[0], "state"), "ambiguous" in out[1]),
          (0, "owner", True))  # the loop guard fired: three dry launches
    # launch four: idle adds actuals too
    put_agent(root, "s4", "sup4", "stu:supervisor", nonce="stu-act-four", recs=[asst_rec("z", "claude-opus-x", 7)])
    pfleet("board", "requeue", PROG, "--run", "alpha")
    pfleet("board", "launch", PROG, "--run", "alpha", extra={"STU_FLEET_NONCE": "stu-act-four"})
    rc, out, err = pfleet("board", "idle", PROG, "--run", "alpha", extra=env)
    check("idle is cumulative", (rc, field(out[0], "agents"), field(out[0], "out")), (0, "4", "95"))
    entries = [json.loads(x) for x in open(log)]
    check("log is append-only, one line per launch", [("unavailable" in e, e["nonce"]) for e in entries], [
        (False, "stu-act-one"), (True, "stu-act-gone"), (True, "stu-act-two"), (False, "stu-act-four")])
    check("log entry is unavailable with a reason", sorted(entries[1]), ["nonce", "recorded_at", "slug", "unavailable"])
    # the report
    before = open(log).read(), open(PROG).read()
    rc, out, err = pfleet("actuals", PROG)
    check("actuals output", (rc, out), (0, [
        "run alpha: launches 4, agents 4, out 95, unavailable 2",
        "seat model agents turns out",
        "stu:implementer claude-opus-x 1 1 20",
        "stu:implementer claude-sonnet-x 1 1 50",
        "stu:reviewer claude-sonnet-x 1 1 8",
        "stu:supervisor claude-opus-x 2 2 17",
        "off-route stu:implementer: 1/2 turns not on sonnet (50%)",
        "off-route stu:reviewer: 0/1 turns not on sonnet (0%)",
        "routing unknown: stu:supervisor",
        "fleet: launches 4, agents 4, out 95, unavailable 2",
        "seat model agents turns out",
        "stu:implementer claude-opus-x 1 1 20",
        "stu:implementer claude-sonnet-x 1 1 50",
        "stu:reviewer claude-sonnet-x 1 1 8",
        "stu:supervisor claude-opus-x 2 2 17",
        "off-route stu:implementer: 1/2 turns not on sonnet (50%)",
        "off-route stu:reviewer: 0/1 turns not on sonnet (0%)",
        "routing unknown: stu:supervisor"]))
    check("actuals is read-only", (open(log).read(), open(PROG).read()), before)
    check("spend carries agents and out", pfleet("spend", PROG)[1][0], "run alpha: cycles 6, launches 4, dry 4, agents 4, out 95")
    with open(log, "a") as f:
        f.write("not json\n" + json.dumps(entries[0]) + "\n")
    check("a damaged middle line is exit 3", pfleet("actuals", PROG)[0], 3)


def test_actuals_review_fixes():
    # family token match, never a substring; a full-id model: line is accepted
    on = stu_fleet.on_route
    check("family in id position", (on("sonnet", "claude-sonnet-5-5"), on("sonnet", "claude-3-5-sonnet-20241022")),
          (True, True))
    check("substring inside another token is off route", (on("sonnet", "claude-opus-sonnetx"),
          on("opus", "claude-opus-5"), on("opus", "claude-sonnet-5")), (False, True, False))
    check("full id compares by its family", (on("claude-sonnet-4-5", "claude-sonnet-5-5"),
          on("claude-sonnet-4-5", "claude-opus-5")), (True, False))
    check("settler routing is not knowable", (stu_fleet.routed_model("stu:settler"),
          stu_fleet.routed_model("stu:implementer")), (None, "sonnet"))
    # a no-model record is in the table but not in the off-route share; settler is routing unknown
    root = os.path.join(TMP, "projects-review")
    o = lifecycle()
    log = PROG + ".actuals.jsonl"
    entry = {"slug": "alpha", "nonce": "stu-r1", "recorded_at": "2023-11-14T22:13:20Z", "agents": 3, "out": 9,
             "by_seat_model": [
                 {"seat": "stu:implementer", "model": "unknown", "agents": 1, "turns": 4, "out": 1},
                 {"seat": "stu:implementer", "model": "claude-sonnet-5", "agents": 1, "turns": 3, "out": 3},
                 {"seat": "stu:settler", "model": "claude-opus-5", "agents": 1, "turns": 2, "out": 5}]}
    with open(log, "w") as f:
        f.write(json.dumps(entry) + "\n")
    rc, out, err = pfleet("actuals", PROG)
    check("unknown model excluded from the share", "off-route stu:implementer: 0/3 turns not on sonnet (0%)" in out, True)
    check("settler is routing unknown", "routing unknown: stu:settler" in out, True)
    # a torn final line is skipped with a warning; the next append does not glue onto it
    with open(log, "a") as f:
        f.write('{"slug": "alpha", "nonce"')
    rc, out, err = pfleet("actuals", PROG)
    check("torn final line skipped with a warning", (rc, out[0].startswith("actuals: skipped damaged final log line 2")), (0, True))
    with open(log, "a") as f:
        f.write("\n" + json.dumps(entry) + "\n")
    check("a damaged line that is not last is exit 3", pfleet("actuals", PROG)[0], 3)
    with open(log, "w") as f:
        f.write(json.dumps(entry) + "\n" + '{"slug": "al')
    pfleet("board", "launch", PROG, "--run", "alpha", extra={"STU_FLEET_NONCE": "stu-r2"})
    pfleet("board", "record", PROG, "--run", "alpha", "--return", run_ret(os.path.join(PDIR, "r.txt"), o, nxt="owner",
           cond="4 \u2014 x"))
    check("append starts a fresh line after a torn one", open(log).read().count("\n"), 3)
    # wrong fleet-line totals are rewritten from the run lines
    a = objective("a")
    program([("alpha", a, "none", "none")], tail="\n## Fleet board\n" + brd("alpha", "settle", a=3, o=40) +
            "\n- fleet | judgment: 0 | agents: 99 | out: 99 | notices: none\n")
    pfleet("board", "requeue", PROG, "--run", "alpha")
    check("fleet totals rewritten", open(PROG).read().rstrip().endswith(
        "- fleet | judgment: 0 | agents: 3 | out: 40 | notices: none"), True)


def test_v2_board_migrates():
    a = objective("a")
    program([("alpha", a, "none", "none")], tail="\n## Fleet board\n" + v2("alpha", "live", c=2, l=1, n="stu-x1234567") +
            "\n- fleet | judgment: 1 | notices: none\n")
    check("v2 line reads as agents 0, out 0", pfleet("board", "show", PROG)[1], [
        brd("alpha", "live", c=2, l=1, n="stu-x1234567"), "- fleet | judgment: 1 | agents: 0 | out: 0 | notices: none"])
    rc = pfleet("board", "idle", PROG, "--run", "alpha")[0]
    check("the next write adds the fields", ("agents: 0 | out: 0 | draft: none" in open(PROG).read(),
          open(PROG).read().rstrip().endswith("| agents: 0 | out: 0 | notices: none")), (True, True))


def lifecycle(name="loop", scoreboard="Run state: running\nCycles used: 0/4\nClosed: NONE\n", header=HEADER):
    o = objective(name, scoreboard=scoreboard)
    program([("alpha", o, "none", "none")], header=header)
    return o


def test_loop_guard():
    o = lifecycle()
    ret = run_ret(os.path.join(PDIR, "lg.txt"), o)
    pfleet("board", "launch", PROG, "--run", "alpha")
    rc, out, err = pfleet("board", "record", PROG, "--run", "alpha", "--return", ret)
    check("first dry launch relaunches", (field(out[0], "state"), field(out[0], "dry")), ("relaunch", "1"))
    pfleet("board", "requeue", PROG, "--run", "alpha")
    pfleet("board", "launch", PROG, "--run", "alpha")
    rc, out, err = pfleet("board", "record", PROG, "--run", "alpha", "--return", ret)
    check("second dry launch trips the guard", (field(out[0], "state"), field(out[0], "dry"),
          field(out[0], "stop")),
          ("owner", "2", "loop guard — 2 launches closed no unit; last stop: 10 — cycle cap exhausted"))
    # a closed unit resets the count
    pfleet("board", "requeue", PROG, "--run", "alpha")
    rc, out, err = pfleet("board", "launch", PROG, "--run", "alpha")
    check("launch snapshots closed", field(out[0], "closed"), "0")
    with open(o, "a") as f:
        f.write("Closed: S1, S2\n")
    rc, out, err = pfleet("board", "record", PROG, "--run", "alpha", "--return", ret)
    check("new closed unit resets dry", (field(out[0], "state"), field(out[0], "dry")), ("relaunch", "0"))
    pfleet("board", "requeue", PROG, "--run", "alpha")
    rc, out, err = pfleet("board", "launch", PROG, "--run", "alpha")
    check("closed snapshot is now 2", field(out[0], "closed"), "2")
    # done, settle and owner outcomes keep their state while dry still updates
    for nxt, cond, run, state, want in (("none", "none", "DONE", "settled 2026-01-01 — x", "done"),
                                        ("settle", "1 — q", "STOPPED", "stopped — BLOCKED: q", "settle"),
                                        ("owner", "4 — stuck", "STOPPED", "stopped — BLOCKED: q", "owner")):
        o2 = lifecycle("lg2")
        program([("alpha", o2, "none", "none")], tail="\n## Fleet board\n" +
                brd("alpha", "live", d=5, n="stu-n123456") + "\n")
        r = run_ret(os.path.join(PDIR, "lg2.txt"), o2, run=run, cond=cond, nxt=nxt, state=state, cycles="1/4")
        rc, out, err = pfleet("board", "record", PROG, "--run", "alpha", "--return", r)
        check("guard leaves %s alone" % want, (field(out[0], "state"), field(out[0], "dry"),
              field(out[0], "stop").startswith("loop guard")), (want, "6", False))


def test_nonces():
    o = lifecycle()
    seen = set()
    for i in range(4):
        rc, out, err = pfleet("board", "launch", PROG, "--run", "alpha")
        n = out[-1].split(": ")[1]
        check("launch prints nonce last and stores it", (out[-1].startswith("nonce: stu-"), field(out[-2], "nonce")),
              (True, n))
        check("nonce matches agent_tree's rule", bool(re.match(r"^[A-Za-z0-9._-]{6,80}$", n)), True)
        seen.add(n)
        pfleet("board", "record", PROG, "--run", "alpha", "--return", run_ret(os.path.join(PDIR, "n.txt"), o, nxt="owner",
               cond="4 — x"))
        pfleet("board", "requeue", PROG, "--run", "alpha")
    check("never reused", len(seen), 4)
    check("board show carries the nonce", field(pfleet("board", "show", PROG)[1][0], "nonce") in seen, True)


def test_idle():
    o = lifecycle(scoreboard="Run state: running\nCycles used: 3/4\nClosed: NONE\nLast handoff: /x/last.md\n"
                             "Last handoff: /x/later.md\n")
    rc, out, err = pfleet("board", "idle", PROG, "--run", "alpha")
    check("idle on queued refused 13", (rc, out[0].startswith("REFUSED fleet-board:")), (13, True))
    check("idle needs --run", pfleet("board", "idle", PROG)[0], 2)
    pfleet("board", "launch", PROG, "--run", "alpha")
    rc, out, err = pfleet("board", "idle", PROG, "--run", "alpha")
    check("idle sets relaunch", (rc, field(out[0], "state"), field(out[0], "stop"), field(out[0], "handoff"),
          field(out[0], "cycles"), field(out[0], "dry")), (0, "relaunch", "idle — no return", "/x/last.md", "3", "1"))
    check("idle on relaunch refused", pfleet("board", "idle", PROG, "--run", "alpha")[0], 13)
    pfleet("board", "requeue", PROG, "--run", "alpha")
    pfleet("board", "launch", PROG, "--run", "alpha")
    rc, out, err = pfleet("board", "idle", PROG, "--run", "alpha")
    check("idle applies the loop guard", (field(out[0], "state"), field(out[0], "stop")),
          ("owner", "loop guard — 2 launches closed no unit; last stop: idle — no return"))
    # no handoff -> none; negative delta refused and nothing written
    o2 = lifecycle("idle2", scoreboard="Run state: settled 2026-01-02 — nothing to settle\nCycles used: 3/4\n")
    pfleet("board", "launch", PROG, "--run", "alpha")
    with open(o2, "w") as f:
        f.write(OH + "## Scoreboard\nRun state: running\nCycles used: 1/4\n")
    before = open(PROG).read()
    rc, out, err = pfleet("board", "idle", PROG, "--run", "alpha")
    check("negative idle delta refused", (rc, "negative delta" in out[0], open(PROG).read()), (13, True, before))
    with open(o2, "w") as f:
        f.write(OH + "## Scoreboard\nRun state: running\nCycles used: 5/4\n")
    rc, out, err = pfleet("board", "idle", PROG, "--run", "alpha")
    check("no Last handoff reads none; delta from the resume point", (rc, out),
          0) if rc else check("no Last handoff reads none; delta from the resume point",
          (field(out[0], "handoff"), field(out[0], "cycles")), ("none", "2"))


SB = "Run state: stopped — BLOCKED: cap\nCycles used: 4/4\nClosed: NONE\nLast handoff: /x/h.md\n"


def relaunch_setup(header=HEADER, scoreboard=SB, tail_text="\nNotes: Run state: unrelated\n"):
    o = objective("rl", scoreboard=scoreboard)
    with open(o, "a") as f:
        f.write(tail_text)
    program([("alpha", o, "none", "none")], header=header)
    pfleet("board", "launch", PROG, "--run", "alpha")
    pfleet("board", "record", PROG, "--run", "alpha", "--return", run_ret(os.path.join(PDIR, "rl.txt"), o, cycles="4/4"))
    return o


def test_relaunch():
    o = relaunch_setup(header=HEADER + "Cycle budget: 20\n")
    check("next says relaunch", pfleet("next", PROG)[1][0], "relaunch alpha \u2014 10 \u2014 cycle cap exhausted")
    before = open(o, "rb").read()
    rc, out, err = pfleet("board", "relaunch", PROG, "--run", "alpha", extra={"STU_FLEET_NONCE": NONCE})
    after = open(o, "rb").read()
    want = before.replace(b"Run state: stopped \xe2\x80\x94 BLOCKED: cap", b"Run state: fleet-relaunch 2023-11-14", 1)
    check("relaunch exits 0 and prints the nonce last", (rc, out[-1]), (0, "nonce: " + NONCE))
    check("only the Run state line changed", after, want)
    check("board is live from 0, launches 2", (field(out[0], "state"), field(out[0], "from"), field(out[0], "launches"),
          field(out[0], "cycles")), ("live", "0", "2", "4"))
    check("objective lock file is the only extra", sorted(f for f in os.listdir(PDIR) if f.startswith("rl-objective")),
          ["rl-objective.md", "rl-objective.md.lock"])
    rc, out, err = pfleet("board", "relaunch", PROG, "--run", "alpha")
    check("relaunch on live refused 13", (rc, out[0].startswith("REFUSED fleet-board:")), (13, True))
    # a limit hit between next and relaunch refuses, objective untouched
    o = relaunch_setup(header=HEADER + "Cycle budget: 20\n")
    check("next says relaunch again", pfleet("next", PROG)[1][0].startswith("relaunch alpha"), True)
    program([("alpha", o, "none", "none")], header=HEADER + "Cycle budget: 4\n",
            tail="\n## Fleet board\n" + brd("alpha", "relaunch", c=4, l=1, h="/x/h.md", p="10 — cycle cap exhausted", d=1) + "\n")
    frozen = open(o, "rb").read()
    board_before = open(PROG).read()
    rc, out, err = pfleet("board", "relaunch", PROG, "--run", "alpha")
    check("stale next cannot override the budget", (rc, "cycle budget spent 4/4" in out[0]), (13, True))
    check("refusal wrote nothing", (open(o, "rb").read(), open(PROG).read()), (frozen, board_before))
    program([("alpha", o, "none", "none")], header=HEADER + "Cycle budget: 20\nStop at: 2023-11-14T00:00:00+00:00\n",
            tail="\n## Fleet board\n" + brd("alpha", "relaunch", c=4, l=1, p="10 — cap") + "\n")
    rc, out, err = pfleet("board", "relaunch", PROG, "--run", "alpha")
    check("stop at refuses relaunch", (rc, "stop at 2023-11-14T00:00:00+00:00 passed" in out[0]), (13, True))
    check("objective still untouched", open(o, "rb").read(), frozen)
    # other refusals
    program([("alpha", o, "none", "none")], tail="\n## Fleet board\n" + brd("alpha", "owner", p="4 — x") + "\n")
    check("relaunch from owner refused", pfleet("board", "relaunch", PROG, "--run", "alpha")[0], 13)
    for name, text in (("no Scoreboard heading", OH + "Run state: stopped\n"),
                       ("no Run state line", OH + "## Scoreboard\nCycles used: 1/4\n"),
                       ("Run state only above the Scoreboard", OH + "Run state: x\n\n## Scoreboard\nCycles used: 1/4\n")):
        write(o, text)
        program([("alpha", o, "none", "none")], tail="\n## Fleet board\n" + brd("alpha", "relaunch", p="10 — c") + "\n")
        rc, out, err = pfleet("board", "relaunch", PROG, "--run", "alpha")
        check(name + " refused 13, objective untouched", (rc, open(o).read()), (13, text))


def test_limits_and_next():
    a = objective("la")
    b = objective("lb")
    two = [("alpha", a, "none", "none"), ("beta", b, "alpha", "none")]
    # cycle budget spent: a queued start and a relaunch become owner lines; a live run is untouched
    program([("alpha", a, "none", "none"), ("beta", b, "none", "none"), ("gamma", a, "none", "none")],
            header=HEADER + "Cycle budget: 8\n",
            tail="\n## Fleet board\n" + brd("alpha", "live", c=8, l=1) + "\n" +
                 brd("gamma", "relaunch", p="10 — cap") + "\n")
    rc, out, err = pfleet("next", PROG)
    check("spent budget: owner for start and relaunch, live untouched", out[:3], [
        "live alpha", "owner beta \u2014 cycle budget spent 8/8", "owner gamma \u2014 cycle budget spent 8/8"])
    check("notices printed after the run lines, before hold", out[3:6], [
        "notice: cycle-budget 80% (8/8)", "notice: cycle-budget 100% (8/8)", "hold: clear"])
    check("budget lines last", out[-2:], ["budget: 8/8", "judgment-jobs: 0/none"])
    rc, out2, err = pfleet("next", PROG)
    check("each notice prints once across calls", [x for x in out2 if x.startswith("notice")], [])
    check("fleet line records them", open(PROG).read().rstrip().endswith(
        "- fleet | judgment: 0 | agents: 0 | out: 0 | notices: cycle-80,cycle-100"), True)
    # 80% only
    program(two, header=HEADER + "Cycle budget: 10\n", tail="\n## Fleet board\n" + brd("alpha", "done", c=8) + "\n")
    out = pfleet("next", PROG)[1]
    check("80% notice, then the start is still allowed", (out[1], out[2]), (
        "start beta", "notice: cycle-budget 80% (8/10)"))
    check("80% second call silent", [x for x in pfleet("next", PROG)[1] if x.startswith("notice")], [])
    # stop at: owner line, one notice, relaunch becomes owner, cycle budget first
    program([("alpha", a, "none", "none"), ("beta", b, "none", "none")],
            header=HEADER + "Stop at: 2023-11-14T00:00:00+00:00\n",
            tail="\n## Fleet board\n" + brd("beta", "relaunch", p="10 — cap") + "\n")
    out = pfleet("next", PROG)[1]
    check("stop at passed", out[:3], ["owner alpha \u2014 stop at 2023-11-14T00:00:00+00:00 passed",
                                      "owner beta \u2014 stop at 2023-11-14T00:00:00+00:00 passed",
                                      "notice: stop-at passed (2023-11-14T00:00:00+00:00)"])
    check("stop-at notice once", [x for x in pfleet("next", PROG)[1] if x.startswith("notice")], [])
    program([("alpha", a, "none", "none")], header=HEADER + "Cycle budget: 3\nStop at: 2023-11-14T00:00:00+00:00\n",
            tail="\n## Fleet board\n" + brd("alpha", "relaunch", c=3, p="10 — cap") + "\n")
    check("cycle budget reported before stop at", pfleet("next", PROG)[1][0],
          "owner alpha \u2014 cycle budget spent 3/3")
    program([("alpha", a, "none", "none")], header=HEADER + "Stop at: 2099-01-01T00:00:00+00:00\n")
    out = pfleet("next", PROG)[1]
    check("stop at in the future is quiet", (out[0], [x for x in out if x.startswith("notice")]), ("start alpha", []))
    # relaunch obeys after:, resources and lanes exactly as start does
    program([("alpha", a, "none", "db"), ("beta", b, "alpha", "db"), ("gamma", a, "none", "db")],
            tail="\n## Fleet board\n" + brd("alpha", "live") + "\n" + brd("beta", "relaunch", p="1 — x") + "\n" +
                 brd("gamma", "relaunch", p="10 — cap") + "\n")
    out = pfleet("next", PROG)[1]
    check("relaunch waits on after: and resources", out[:3], [
        "live alpha", "wait beta \u2014 after alpha", "wait gamma \u2014 resource db held by alpha"])
    program([("alpha", a, "none", "none"), ("beta", b, "none", "none")],
            tail="\n## Fleet board\n" + brd("alpha", "relaunch", p="10 — cap") + "\n" + brd("beta", "relaunch", p="10 — cap") + "\n")
    out = pfleet("next", PROG, extra={"STU_FLEET_MAX_LANES": "1"})[1]
    check("relaunch waits at the lane cap", out[:2], ["relaunch alpha \u2014 10 \u2014 cap", "wait beta \u2014 lane cap 1/1"])
    # judgment jobs
    j = "\n## Judgment work\n- g1: groom | scope: s | output: /o | feeds: none\n"
    program([("alpha", a, "none", "none")], header=HEADER + "Judgment jobs: 5\n", tail=j)
    check("judgment unknown job is BLOCKED exit 1", pfleet("board", "judgment", PROG, "--job", "nope")[0], 1)
    check("judgment needs --job", pfleet("board", "judgment", PROG)[0], 2)
    for i in range(1, 6):
        rc, out, err = pfleet("board", "judgment", PROG, "--job", "g1")
        check("judgment %d counted" % i, (rc, out), (0, ["judgment-jobs: %d/5" % i]))
    out = pfleet("next", PROG)[1]
    check("judgment notices at 80 and 100", [x for x in out if x.startswith("notice")],
          ["notice: judgment-jobs 80% (5/5)", "notice: judgment-jobs 100% (5/5)"])
    check("judgment line in next", out[-1], "judgment-jobs: 5/5")
    rc, out, err = pfleet("board", "judgment", PROG, "--job", "g1")
    check("spent judgment refused 13", (rc, out[0]), (13, "REFUSED fleet-board: judgment jobs spent 5/5"))
    check("spend shows judgment", pfleet("spend", PROG)[1][-2], "judgment-jobs: 5/5")
    program([("alpha", a, "none", "none")], header=HEADER + "Judgment jobs: 5\n", tail=j)
    pfleet("board", "judgment", PROG, "--job", "g1")
    check("judgment 20% has no notice", [x for x in pfleet("next", PROG)[1] if x.startswith("notice")], [])
    program([("alpha", a, "none", "none")], header=HEADER + "Stop at: 2023-11-14T00:00:00+00:00\n", tail=j)
    rc, out, err = pfleet("board", "judgment", PROG, "--job", "g1")
    check("stop at refuses judgment", (rc, "stop at" in out[0]), (13, True))
    program([("alpha", a, "none", "none")], tail=j)
    check("no judgment limit counts freely", pfleet("board", "judgment", PROG, "--job", "g1")[1], ["judgment-jobs: 1/none"])
    # spend
    program([("alpha", a, "none", "none")], header=HEADER + "Stop at: 2099-01-01T00:00:00+00:00\n")
    check("spend stop-at not passed", pfleet("spend", PROG)[1][-1], "stop-at: 2099-01-01T00:00:00+00:00 (not passed)")
    program([("alpha", a, "none", "none")], header=HEADER + "Stop at: 2023-11-14T00:00:00+00:00\n")
    check("spend stop-at passed", pfleet("spend", PROG)[1][-1], "stop-at: 2023-11-14T00:00:00+00:00 (passed)")
    check("spend never writes", os.path.exists(PROG + ".lock") and "notices" not in open(PROG).read(), True)

R1 = ("R1: q-recurring-label | rec: keep the label | reverses-if: support sees confusion | "
      "precondition: none | row: 7 | verifier: HOLDS | flags: none")
R2 = ("R2: q-new-screen | rec: add the screen | reverses-if: the owner dislikes it | "
      "precondition: hold the deploy until the migration ran | row: 5 | verifier: STALE | "
      "flags: owner-only")
R3 = ("R3: q-export | rec: ship the export | reverses-if: it is slow | precondition: none | "
      "row: 7 | verifier: HOLDS | flags: none")
BRIEF3 = ("BRIEF:\nRun demo: 3 rulings drafted\n1. Keep the label? -> recommend yes. Reverses if "
          "support sees confusion.\n2. Add the screen? -> recommend yes. Reverses if disliked. "
          "[owner-only]\n3. Ship the export? -> recommend yes.\n"
          "Answer: fine | accept 2 | reverse 2, 5 | talk about 3\n")


def drafted_text(obj, draft="/runs/demo/settle/draft.md", n=3):
    rs = [R1, R2, R3][:n]
    brief = BRIEF3 if n == 3 else BRIEF3.replace("3. Ship the export? -> recommend yes.\n", "")
    return ("SETTLER: DRAFTED \u2014 %d rulings ready\nOBJECTIVE: %s\nDRAFT: %s\nRULINGS: %d\n%s\n%s" % (
        n, obj, draft, n, "\n".join(rs), brief))


def written_text(obj, written, unanswered, todos=(), draft="/runs/demo/settle/draft.md", hold="none", n=3):
    rs = [R1, R2, R3][:n]
    return ("SETTLER: WRITTEN \u2014 some written\nOBJECTIVE: %s\nDRAFT: %s\nRULINGS: %d\n%s\n"
            "WRITTEN: %s\nUNANSWERED: %s\nHOLD: %s\n%s" % (
        obj, draft, n, "\n".join(rs), written, unanswered, hold,
        "".join("SCOREBOARD-TODO: %s\n" % x for x in todos)))


def settle_board(slug="alpha", dr="none", w="none", st="settle", p="1 \u2014 q"):
    return "\n## Fleet board\n" + brd(slug, st, c=2, l=1, p=p, dr=dr, w=w) + "\n"


def test_board_v4_and_draft():
    a = objective("a")
    prog_runs = [("alpha", a, "none", "none")]
    program(prog_runs, tail="\n## Fleet board\n" + v3("alpha", "settle", c=2, l=1, p="1 \u2014 q") + "\n")
    check("v3 line reads draft none, written none", pfleet("board", "show", PROG)[1],
          [brd("alpha", "settle", c=2, l=1, p="1 \u2014 q"), FLEET0])
    check("next says settle without a draft", pfleet("next", PROG)[1][0], "settle alpha")
    ret = write(os.path.join(PDIR, "d.txt"), drafted_text(a))
    rc, out, err = pfleet("board", "draft", PROG, "--run", "alpha", "--return", ret)
    check("draft stores the absolute path", (rc, out), (0, [brd("alpha", "settle", c=2, l=1, p="1 \u2014 q", dr=ret)]))
    check("the write emitted v4", ("draft: %s | written: none | handoff" % ret) in open(PROG).read(), True)
    check("next says brief with a draft", pfleet("next", PROG)[1][0], "brief alpha")
    rc, out, err = pfleet("board", "draft", PROG, "--run", "alpha", "--return", ret)
    check("a second draft is refused 13", (rc, out[0].startswith("REFUSED fleet-board:")), (13, True))
    # refusals and BLOCKED
    program(prog_runs, tail=settle_board())
    other = objective("other")
    for name, text, code in (
            ("other objective", drafted_text(other), 1),
            ("a WRITTEN return", written_text(a, "R1, R2, R3", "none"), 1),
            ("malformed", drafted_text(a).replace("RULINGS: 3", "RULINGS: 4"), 1),
            ("blocked status", "SETTLER: BLOCKED \u2014 nothing\n", 1)):
        before = open(PROG).read()
        rc, out, err = pfleet("board", "draft", PROG, "--run", "alpha", "--return", write(os.path.join(PDIR, "x.txt"), text))
        check("draft refuses %s with BLOCKED" % name, (rc, out[-1], out[0].startswith("BLOCKED: "),
              open(PROG).read()), (code, "BLOCKED", True, before))
    check("draft needs --return", pfleet("board", "draft", PROG, "--run", "alpha")[0], 2)
    check("draft unreadable return is 3", pfleet("board", "draft", PROG, "--run", "alpha",
          "--return", os.path.join(PDIR, "nope.txt"))[0], 3)
    for st in ("queued", "live", "relaunch", "owner", "done"):
        program(prog_runs, tail=settle_board(st=st, p="none"))
        rc, out, err = pfleet("board", "draft", PROG, "--run", "alpha", "--return", ret)
        check("draft refused 13 on %s" % st, (rc, out[0].startswith("REFUSED fleet-board:")), (13, True))
    # a settle run with owner-only still prints settle owner-only without a draft
    program(prog_runs, tail=settle_board(p="2 \u2014 q"))
    check("owner-only unchanged", pfleet("next", PROG)[1][0], "settle alpha owner-only")
    # every reset
    for how in ("requeue", "idle", "record", "launch", "relaunch"):
        o = lifecycle("rs", scoreboard="Run state: stopped \u2014 BLOCKED: x\nCycles used: 4/4\nClosed: NONE\n")
        st = {"requeue": "settle", "idle": "live", "record": "live", "launch": "queued", "relaunch": "relaunch"}[how]
        p = {"relaunch": "10 \u2014 cap"}.get(how, "none")
        program([("alpha", o, "none", "none")], tail=settle_board(st=st, p=p, dr="/x/d.txt", w="1,2"))
        args = ["board", how, PROG, "--run", "alpha"]
        if how == "record":
            args += ["--return", run_ret(os.path.join(PDIR, "rs.txt"), o, cycles="4/4")]
        rc, out, err = pfleet(*args)
        check("%s resets draft and written" % how, (rc, field(out[0], "draft"), field(out[0], "written")),
              (0, "none", "none"))

SB_PLAIN = ("Run state: stopped \u2014 BLOCKED: 1 \u2014 q\nCycles used: 4/4\nUnits issued: S1, S2, S3, S4\n"
            "Closed: S1\nAwaiting approval: NONE\nWaiting: NONE\nParked: S2, S3\nOutstanding: S4\n"
            "Last handoff: /x/h.md\n")
SB_TAIL = "\n## Notes\nParked: S9\nRun state: untouched\n"
SB_LANES = ("Run state: stopped \u2014 BLOCKED: 1 \u2014 q\nCycles used: 4/4\nUnits added: 0/3\n\n"
            "Lane: one\nLane state: stopped \u2014 BLOCKED: q\nUnits issued: A1, A2\nClosed: NONE\n"
            "Awaiting approval: NONE\nWaiting: NONE\nParked: A1\nOutstanding: A2\n\n"
            "Lane: two\nLane state: running\nUnits issued: B1, B2\nClosed: B1\n"
            "Awaiting approval: NONE\nWaiting: NONE\nParked: B2\nOutstanding: NONE\n")


def settle_fixture(sb=SB_PLAIN, name="st", lanes=None, drafted=True):
    o = objective(name, scoreboard=sb, mode="overnight" if lanes else "plain")
    with open(o, "a") as f:
        f.write(SB_TAIL)
    program([("alpha", o, "none", "none") + ((lanes,) if lanes else ())], tail=settle_board())
    d = write(os.path.join(PDIR, name + "-draft.txt"), drafted_text(o))
    if drafted:
        pfleet("board", "draft", PROG, "--run", "alpha", "--return", d)
    return o, d


def wret(o, name, written, unanswered, todos=()):
    return write(os.path.join(PDIR, name + ".txt"), written_text(o, written, unanswered, todos))


def settled(o, name, written, unanswered, todos=()):
    return pfleet("board", "settled", PROG, "--run", "alpha", "--return", wret(o, name, written, unanswered, todos))


def test_board_settled():
    o, d = settle_fixture()
    orig, prog0 = open(o, "rb").read(), open(PROG).read()
    # refusals and BLOCKED, each leaving everything untouched
    cases = (("an add", ("add S9 \u2014 a new export",), 13,
              "REFUSED fleet-board: alpha adds unit S9; settle it with /stu:settle %s" % o),
             ("add after a good todo", ("unpark S2", "add S9 \u2014 x"), 13, "adds unit S9"),
             ("unpark of an unknown id", ("unpark S7",), 13, "unpark S7"),
             ("unpark of a closed id", ("unpark S1",), 13, "unpark S1"),
             ("drop of an unknown id", ("drop S7",), 13, "drop S7"),
             ("drop of a merged id", ("drop S1",), 13, "drop S1"),
             ("a second bad todo after a good one", ("unpark S2", "drop S7"), 13, "drop S7"))
    for name, todos, code, needle in cases:
        rc, out, err = settled(o, "s1", "R1, R2, R3", "none", todos)
        check("%s refused" % name, (rc, needle in out[0], out[0].startswith("REFUSED fleet-board:"),
              open(o, "rb").read() == orig, open(PROG).read() == prog0), (code, True, True, True, True))
    check("the add refusal text exactly", settled(o, "s1", "R1, R2, R3", "none", ("add S9 \u2014 x",))[1],
          ["REFUSED fleet-board: alpha adds unit S9; settle it with /stu:settle %s" % o])
    other = objective("elsewhere")
    for name, text in (("a DRAFTED return", drafted_text(o)),
                       ("another objective", written_text(other, "R1, R2, R3", "none")),
                       ("another DRAFT", written_text(o, "R1, R2, R3", "none", draft="/runs/other.md")),
                       ("a malformed todo", written_text(o, "R1, R2, R3", "none", ("move S2",)))):
        rc, out, err = pfleet("board", "settled", PROG, "--run", "alpha", "--return", write(os.path.join(PDIR, "bad.txt"), text))
        check("%s is BLOCKED exit 1" % name, (rc, out[0].startswith("BLOCKED: "), out[-1],
              open(o, "rb").read() == orig, open(PROG).read() == prog0), (1, True, "BLOCKED", True, True))
    # no Scoreboard
    nosb = o + ".nosb"
    write(nosb, OH + "no scoreboard here\n")
    program([("alpha", nosb, "none", "none")], tail=settle_board(dr=d))
    p0 = open(PROG).read()
    rc, out, err = settled(nosb, "s2", "R1, R2, R3", "none")
    check("no Scoreboard refused 13", (rc, "Scoreboard" in out[0], open(PROG).read()), (13, True, p0))
    # not settle, or no draft
    for st, dr in (("settle", "none"), ("queued", d), ("live", "none"), ("owner", "none"), ("done", "none")):
        program([("alpha", o, "none", "none")], tail=settle_board(st=st, dr=dr, p="none"))
        rc, out, err = settled(o, "s3", "R1, R2, R3", "none")
        check("settled refused 13 on %s/%s" % (st, dr), (rc, out[0].startswith("REFUSED fleet-board:"),
              open(o, "rb").read() == orig), (13, True, True))
    check("settled needs --return", pfleet("board", "settled", PROG, "--run", "alpha")[0], 2)

    # partial answer: unpark S2, drop S3; stays settle with its draft
    o, d = settle_fixture()
    rc, out, err = settled(o, "p1", "R1", "R2, R3", ("unpark S2", "drop S3"))
    check("partial exits 0 with pending last", (rc, out[-1]), (0, "pending alpha: R2, R3"))
    check("partial board line", out[0], brd("alpha", "settle", c=2, l=1, p="1 \u2014 q", dr=d, w="1"))
    want = orig.decode().replace("Parked: S2, S3\n", "Parked: NONE\n", 1).replace(
        "Outstanding: S4\n", "Outstanding: S4, S2\n", 1).replace(
        "Closed: S1\n", "Closed: S1, S3 (dropped by the owner 2023-11-14)\n", 1)
    check("exactly three scoreboard lines changed, Run state untouched", open(o).read(), want)
    check("next says brief again", pfleet("next", PROG)[1][0], "brief alpha")
    mid = open(o, "rb").read()
    rc, out, err = settled(o, "p2", "R1, R2, R3", "none", ("unpark S2", "drop S3"))
    check("final settled requeues", (rc, out[-1], out[0]), (0, "requeued alpha", brd("alpha", "queued", c=2, l=1, p="1 \u2014 q")))
    fin = open(o, "rb").read()
    check("no-op repeats leave the lines; Run state carries the summed counts",
          fin, mid.replace(b"Run state: stopped \xe2\x80\x94 BLOCKED: 1 \xe2\x80\x94 q",
                           "Run state: settled 2023-11-14 \u2014 3 answered, 1 unparked, 0 added, 1 dropped".encode(), 1))
    check("the Notes section untouched", b"## Notes\nParked: S9\nRun state: untouched\n" in fin, True)
    check("sidecar cleared", "alpha" in (json.load(open(PROG + ".settle.json")) if os.path.exists(PROG + ".settle.json") else {}), False)

    # Waiting keeps waiting-on-human
    o, d = settle_fixture(sb=SB_PLAIN.replace("Waiting: NONE", "Waiting: S4 needs: merge acme/app#9"), name="wt")
    rc, out, err = settled(o, "w1", "R1, R2, R3", "none", ("unpark S2",))
    check("waiting lane gives waiting-on-human", (rc, out[-1], "Run state: waiting-on-human\n" in open(o).read()),
          (0, "requeued alpha", True))
    o, d = settle_fixture(sb=SB_PLAIN.replace("Awaiting approval: NONE", "Awaiting approval: S4@br@abc"), name="aw")
    rc, out, err = settled(o, "w2", "R1, R2, R3", "none")
    check("awaiting approval gives waiting-on-human", "Run state: waiting-on-human\n" in open(o).read(), True)
    # everything answered with no todos: nothing to move
    o, d = settle_fixture(name="nt")
    rc, out, err = settled(o, "n1", "R1, R2, R3", "none")
    check("no todos settles with 0 unparked", (rc, "Run state: settled 2023-11-14 \u2014 3 answered, 0 unparked, 0 added, 0 dropped\n" in open(o).read()),
          (0, True))
    # a drop of an outstanding unit
    o, d = settle_fixture(name="do")
    rc, out, err = settled(o, "d1", "R1, R2, R3", "none", ("drop S4",))
    txt = open(o).read()
    check("drop of an outstanding unit", (rc, "Outstanding: NONE\n" in txt,
          "Closed: S1, S4 (dropped by the owner 2023-11-14)\n" in txt, "Units issued: S1, S2, S3, S4\n" in txt),
          (0, True, True, True))
    # overnight: two lanes, a global Run state
    o, d = settle_fixture(sb=SB_LANES, name="ln", lanes="2")
    rc, out, err = settled(o, "l1", "R1, R2, R3", "none", ("unpark A1", "drop B2", "unpark B2"))
    check("an id dropped then unparked in one return", (rc, out[0].startswith("REFUSED")), (13, True))
    rc, out, err = settled(o, "l1", "R1, R2, R3", "none", ("unpark A1", "drop B2"))
    txt = open(o).read()
    check("lane lines edited per lane", (rc, "Parked: NONE\nOutstanding: A2, A1\n" in txt,
          "Closed: B1, B2 (dropped by the owner 2023-11-14)\nAwaiting approval: NONE\nWaiting: NONE\nParked: NONE\nOutstanding: NONE\n" in txt,
          "Run state: settled 2023-11-14 \u2014 3 answered, 1 unparked, 0 added, 1 dropped\n" in txt), (0, True, True, True))
    # a v3 board settles into v4
    o, d = settle_fixture(name="v3")
    program([("alpha", o, "none", "none")], tail="\n## Fleet board\n" + v3("alpha", "settle", c=2, l=1, p="1 \u2014 q") + "\n")
    rc, out, err = pfleet("board", "draft", PROG, "--run", "alpha", "--return", d)
    check("a v3 board takes a draft", (rc, field(out[0], "draft")), (0, d))


def test_settled_crash_and_guards():
    side = PROG + ".settle.json"
    # crash after the objective write, before the board/sidecar write: the retry counts the same
    for finishing in (True, False):
        o, d = settle_fixture(name="cr%d" % finishing)
        prog0 = open(PROG).read()
        un = "none" if finishing else "R2, R3"
        rc, out, err = settled(o, "c1", "R1, R2, R3" if finishing else "R1", un, ("unpark S2", "drop S3"))
        if os.path.exists(side):
            os.remove(side)
        write(PROG, prog0)
        rc, out, err = settled(o, "c1", "R1, R2, R3" if finishing else "R1", un, ("unpark S2", "drop S3"))
        if not finishing:
            rc, out, err = settled(o, "c2", "R1, R2, R3", "none", ("unpark S2", "drop S3"))
        check("retry after a crash (finishing=%s) keeps the counts" % finishing,
              (rc, "Run state: settled 2023-11-14 — 3 answered, 1 unparked, 0 added, 1 dropped\n" in open(o).read()),
              (0, True))
    # a retried identical partial call is idempotent on the sidecar
    o, d = settle_fixture(name="cs")
    settled(o, "s1", "R1", "R2, R3", ("unpark S2", "drop S3"))
    first = open(side).read()
    settled(o, "s1", "R1", "R2, R3", ("unpark S2", "drop S3"))
    check("sidecar holds id sets, stable on retry", (open(side).read(), json.load(open(side))["alpha"]["unparked"]),
          (first, ["S2"]))
    # Run state: running refuses before writing
    o, d = settle_fixture(sb=SB_PLAIN.replace("stopped — BLOCKED: 1 — q", "running"), name="rn")
    orig, prog0 = open(o, "rb").read(), open(PROG).read()
    rc, out, err = settled(o, "r1", "R1, R2, R3", "none", ("unpark S2",))
    check("running refused 13, nothing written", (rc, out[0].startswith("REFUSED fleet-board:"), "running" in out[0],
          open(o, "rb").read() == orig, open(PROG).read() == prog0), (13, True, True, True, True))
    # drop of an id already dropped in Closed: with a stale Parked: entry
    sb = SB_PLAIN.replace("Closed: S1\n", "Closed: S1, S3 (dropped by the owner 2023-11-01)\n")
    o, d = settle_fixture(sb=sb, name="dd")
    rc, out, err = settled(o, "dd1", "R1, R2, R3", "none", ("drop S3",))
    txt = open(o).read()
    check("drop of an already-dropped id only cleans the stale list", (rc, "Parked: S2\n" in txt,
          txt.count("S3 (dropped"), "Closed: S1, S3 (dropped by the owner 2023-11-01)\n" in txt,
          "0 unparked, 0 added, 1 dropped" in txt), (0, True, 1, True, True))


def two_drafts():
    """alpha (3 rulings, R1 written) and beta (2 rulings) both with a recorded draft."""
    oa = objective("ba")
    ob = objective("bb")
    program([("alpha", oa, "none", "none"), ("beta", ob, "none", "none"), ("gamma", objective("bc"), "none", "none")],
            tail="\n## Fleet board\n" + "".join(x + "\n" for x in (
                brd("alpha", "settle", p="1 \u2014 q"), brd("beta", "settle", p="1 \u2014 q"), brd("gamma"))))
    da = write(os.path.join(PDIR, "ba-d.txt"), drafted_text(oa, draft="/runs/a/draft.md"))
    db = write(os.path.join(PDIR, "bb-d.txt"), drafted_text(ob, draft="/runs/b/draft.md", n=2))
    pfleet("board", "draft", PROG, "--run", "alpha", "--return", da)
    pfleet("board", "draft", PROG, "--run", "beta", "--return", db)
    return oa, ob, da, db


def test_brief_and_answer():
    program([("alpha", objective("bq0"), "none", "none")], tail=settle_board())
    check("brief with no drafts", pfleet("brief", PROG)[:2], (0, ["brief: none"]))
    check("answer with no drafts is BLOCKED", pfleet("answer", PROG, "--line", "fine")[:2],
          (1, ["BLOCKED: 'fine' answers nothing: no run has a draft", "BLOCKED"]))
    o, d = settle_fixture(name="bq")
    before = open(PROG).read()
    rc, out, err = pfleet("brief", PROG)
    check("brief for one run: the block, a blank line, one Answer line", (rc, out), (0, [
        "Run demo: 3 rulings drafted",
        "1. Keep the label? -> recommend yes. Reverses if support sees confusion.",
        "2. Add the screen? -> recommend yes. Reverses if disliked. [owner-only]",
        "3. Ship the export? -> recommend yes.", "",
        "Answer: alpha: fine | accept 2 | reverse 2, 5 | talk about 3"]))
    check("brief never writes", open(PROG).read(), before)
    # written items vanish, numbering stays
    rc, out, err = settled(o, "bw", "R1, R3", "R2")
    rc, out, err = pfleet("brief", PROG)
    check("brief hides written items and keeps numbering", out[1:3], [
        "2. Add the screen? -> recommend yes. Reverses if disliked. [owner-only]", ""])
    check("two lines of the block gone", ("1. Keep" in "\n".join(out), "3. Ship" in "\n".join(out)), (False, False))
    # answers, single run
    rc, out, err = pfleet("answer", PROG, "--line", "accept 2")
    check("single run, no prefix", (rc, out), (0, ["answer alpha | draft: /runs/demo/settle/draft.md | line: accept 2"]))
    check("single run with prefix and extra words", pfleet("answer", PROG, "--line", "alpha: reverse 2 because the label is wrong")[1],
          ["answer alpha | draft: /runs/demo/settle/draft.md | line: reverse 2 because the label is wrong"])
    check("fine passes", pfleet("answer", PROG, "--line", "fine")[1][0].endswith("line: fine"), True)
    for name, line, needle in (("number 0", "accept 0", "outside the draft's 1..3"),
                               ("number past RULINGS", "reverse 2, 4", "reverse 4 is outside"),
                               ("talk about past", "talk about 9", "talk about 9 is outside"),
                               ("already written", "accept 1", "accept 1 is already written"),
                               ("unknown slug", "ghost: fine", "ghost is not a run"),
                               ("twice", "alpha: fine; alpha: accept 2", "alpha is answered twice")):
        rc, out, err = pfleet("answer", PROG, "--line", line)
        check("answer BLOCKED: %s" % name, (rc, out[-1], any(needle in x for x in out), len(out) >= 2), (1, "BLOCKED", True, True))
    rc, out, err = pfleet("answer", PROG, "--line", "accept 1")
    check("BLOCKED prints nothing but BLOCKED lines", all(x.startswith("BLOCKED") for x in out), True)
    # several runs
    oa, ob, da, db = two_drafts()
    rc, out, err = pfleet("brief", PROG)
    check("brief for several runs: blocks in Runs order, one Answer line", (rc, out[0], out[-1], len([x for x in out if x.startswith("Run demo:")])),
          (0, "Run demo: 3 rulings drafted", "Answer per run, one per line or separated by ';': <slug>: <answer>", 2))
    rc, out, err = pfleet("answer", PROG, "--line", "beta: reverse 1\nalpha: fine; ")
    check("several runs answered in Runs order", (rc, out), (0, [
        "answer alpha | draft: /runs/a/draft.md | line: fine", "answer beta | draft: /runs/b/draft.md | line: reverse 1"]))
    rc, out, err = pfleet("answer", PROG, "--line", "alpha: accept 2")
    check("an unanswered run is reported", (rc, out), (0, ["answer alpha | draft: /runs/a/draft.md | line: accept 2", "unanswered beta"]))
    check("beta has 2 rulings", pfleet("answer", PROG, "--line", "alpha: fine; beta: accept 3")[1][:1],
          ["BLOCKED: beta: accept 3 is outside the draft's 1..2"])
    rc, out, err = pfleet("answer", PROG, "--line", "fine")
    check("several runs, no prefix is BLOCKED", (rc, out[0].startswith("BLOCKED: 'fine' names no run")), (1, True))
    rc, out, err = pfleet("answer", PROG, "--line", "gamma: fine")
    check("a run with no draft is BLOCKED", (rc, out[0]), (1, "BLOCKED: gamma has no draft to answer"))
    rc, out, err = pfleet("answer", PROG, "--line", "alpha: fine\nbeta: fine\nbeta: fine")
    check("duplicate across newlines", (rc, out[0]), (1, "BLOCKED: beta is answered twice"))
    check("answer needs --line", pfleet("answer", PROG)[0], 2)
    check("answer and brief never write", ("brief" in open(PROG).read()), False)


for t in (test_no_file_means_no_hold, test_lock_take_basics, test_hold_refuses_take,
          test_hold_returns_holder_and_records_landing, test_release_landed_during_hold,
          test_stale_holder_released_on_the_forge, test_forge_unreachable_refuses,
          test_real_forge_through_fake_gh, test_fail_closed_on_bad_state, test_usage,
          test_concurrent_takes_serialise, test_resume_count, test_program_check, test_board,
          test_board_continue_and_negative, test_board_errors_and_preservation, test_launch_only_from_queued, test_spend,
          test_next, test_review_fixes, test_fleet_usage, test_declared_lanes, test_closed_count,
          test_board_v2_grammar, test_loop_guard, test_nonces, test_idle, test_relaunch,
          test_limits_and_next, test_board_v4_and_draft, test_board_settled, test_settled_crash_and_guards, test_brief_and_answer, test_actuals, test_actuals_review_fixes, test_v2_board_migrates):
    t()

if FAILURES:
    print("FAIL %d of %d checks" % (len(FAILURES), COUNT[0]))
    for f in FAILURES:
        print("  " + f)
    sys.exit(1)
print("ok: %d checks" % COUNT[0])
