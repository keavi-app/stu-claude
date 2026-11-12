#!/usr/bin/env python3
"""Tests for the settler return schema, through `stu-run-check --settler-return`.

Run: python3 scripts/settler_return_test.py
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin", "stu-run-check")
FAILURES = []
COUNT = [0]

R1 = ("R1: q-recurring-label | rec: keep the label | reverses-if: support sees confusion | "
      "precondition: none | row: 7 | verifier: HOLDS | flags: none")
R2 = ("R2: q-new-screen | rec: add the screen | reverses-if: the owner dislikes it | "
      "precondition: hold the deploy until the migration ran | row: 5 | verifier: STALE | "
      "flags: owner-only")
BRIEF = ("BRIEF:\nRun demo: 2 rulings drafted\n1. Keep the label? -> recommend yes. Reverses if "
         "support sees confusion.\n2. Add the screen? -> recommend yes. Reverses if disliked. [owner-only] "
         "[verifier: STALE]\n"
         "Answer: fine | accept 2 | reverse 2, 5 | talk about 3\n")
HEAD = "OBJECTIVE: /runs/demo-objective.md\nDRAFT: /runs/demo/settle/2026-11-12-draft.md\n"
DRAFTED = "SETTLER: DRAFTED — 2 rulings ready\n" + HEAD + "RULINGS: 2\n%s\n%s\n" % (R1, R2) + BRIEF
WRITTEN = ("SETTLER: WRITTEN — 1 written, 1 left\n" + HEAD + "RULINGS: 2\n%s\n%s\n" % (R1, R2) +
           "WRITTEN: R1\nUNANSWERED: R2\nHOLD: set — migration must run first\n"
           "SCOREBOARD-TODO: move q-recurring-label's unit from Parked to Outstanding\n")


def run(text):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "ret.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        r = subprocess.run([BIN, "--settler-return", p], capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def expect(name, text, code, needle=None):
    COUNT[0] += 1
    rc, out, err = run(text)
    if rc != code:
        FAILURES.append("%s: exit %d, want %d (%s%s)" % (name, rc, code, out, err))
    elif needle and needle not in out:
        FAILURES.append("%s: output lacks %r: %s" % (name, needle, out))
    if code in (0, 1):
        last = out.strip().splitlines()[-1] if out.strip() else ""
        if last != ("OK" if code == 0 else "BLOCKED"):
            FAILURES.append("%s: terminal line %r" % (name, last))


expect("drafted ok", DRAFTED, 0, "SETTLER OK DRAFTED")
expect("written ok", WRITTEN, 0, "SETTLER OK WRITTEN")
expect("blocked ok", "SETTLER: BLOCKED — no objective file\n", 0)
expect("blocked needs reason", "SETTLER: BLOCKED\n", 1, "one-line reason")
expect("zero rulings drafted", "SETTLER: DRAFTED — nothing waiting\n" + HEAD + "RULINGS: 0\n"
       "BRIEF:\nRun demo: 0 rulings drafted\nAnswer: fine\n", 0)
expect("bad status", DRAFTED.replace("DRAFTED —", "DONE —", 1), 1, "SETTLER line must start")
expect("relative path", DRAFTED.replace("/runs/demo-objective.md", "demo-objective.md"), 1,
       "absolute path")
expect("count mismatch", DRAFTED.replace("RULINGS: 2", "RULINGS: 3"), 1, "RULINGS says 3")
expect("row 5 without owner-only", DRAFTED.replace("flags: owner-only", "flags: none"), 1,
       "owner-only flag")
expect("unknown flag", DRAFTED.replace("flags: owner-only", "flags: owner-only, urgent"), 1,
       "unknown flag")
expect("bad verifier", DRAFTED.replace("verifier: HOLDS", "verifier: MAYBE"), 1, "verifier must be")
expect("missing field", DRAFTED.replace(" | row: 7", ""), 1, "want 7")
expect("renumbered R", DRAFTED.replace("R2:", "R3:"), 1, "numbered 1..n")
SC2 = DRAFTED.replace("flags: owner-only", "flags: owner-only, sc2-candidate").replace(
    "[owner-only]", "[owner-only] [sc2-candidate]")
expect("sc2 candidate flagged", SC2, 0)
expect("sc2 without owner-only", SC2.replace("flags: owner-only, sc2-candidate",
       "flags: sc2-candidate").replace("[owner-only] ", ""), 1, "implies owner-only")
expect("verifier PARTIAL", DRAFTED.replace("verifier: HOLDS", "verifier: PARTIAL"), 0)
expect("verifier UNVERIFIED", DRAFTED.replace("verifier: HOLDS", "verifier: UNVERIFIED"), 0)
expect("brief line lacks flag", DRAFTED.replace(" [owner-only]", ""), 1, "does not show the [owner-only]")
expect("brief lacks flagged item", DRAFTED.replace("2. Add the screen?", "Add the screen?"), 1,
       "no numbered line 2")
expect("brief missing Answer", DRAFTED.replace("Answer: fine | accept 2 | reverse 2, 5 | talk about 3\n", ""),
       1, "Answer:")
expect("drafted without brief", DRAFTED.split("BRIEF:")[0], 1, "needs a BRIEF")
expect("drafted carrying WRITTEN", DRAFTED.replace("RULINGS: 2\n", "RULINGS: 2\nWRITTEN: R1\n", 1),
       1, "must not carry WRITTEN")
expect("written missing HOLD", WRITTEN.replace("HOLD: set — migration must run first\n", ""), 1,
       "HOLD: line")
expect("written bad HOLD", WRITTEN.replace("set — migration", "maybe — migration"), 1, "HOLD must be")
expect("written does not cover ids", WRITTEN.replace("UNANSWERED: R2", "UNANSWERED: none"), 1,
       "cover exactly")
expect("written and unanswered overlap", WRITTEN.replace("UNANSWERED: R2", "UNANSWERED: R1, R2"),
       1, "both written and unanswered")
expect("duplicate SETTLER", "SETTLER: BLOCKED — x\nSETTLER: BLOCKED — y\n", 1, "duplicate SETTLER")
expect("garbage", "I drafted some rulings, see above.\n", 1, "SETTLER line must start")

COUNT[0] += 1
rc = subprocess.run([BIN, "--settler-return", "/nonexistent/ret.txt"], capture_output=True,
                    text=True)
if rc.returncode != 3 or rc.stdout:
    FAILURES.append("unreadable: exit %d stdout %r" % (rc.returncode, rc.stdout))

if FAILURES:
    print("FAIL settler_return_test: %d of %d" % (len(FAILURES), COUNT[0]))
    for f in FAILURES:
        print("  " + f)
    sys.exit(1)
print("ok: %d settler return checks" % COUNT[0])
