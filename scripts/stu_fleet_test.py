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


for t in (test_no_file_means_no_hold, test_lock_take_basics, test_hold_refuses_take,
          test_hold_returns_holder_and_records_landing, test_release_landed_during_hold,
          test_stale_holder_released_on_the_forge, test_forge_unreachable_refuses,
          test_real_forge_through_fake_gh, test_fail_closed_on_bad_state, test_usage,
          test_concurrent_takes_serialise):
    t()

if FAILURES:
    print("FAIL %d of %d checks" % (len(FAILURES), COUNT[0]))
    for f in FAILURES:
        print("  " + f)
    sys.exit(1)
print("ok: %d checks" % COUNT[0])
