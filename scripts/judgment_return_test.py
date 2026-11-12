#!/usr/bin/env python3
"""Tests for the groomer and designer return schemas, through `stu-run-check --groomer-return`
and `--designer-return`.

Run: python3 scripts/judgment_return_test.py
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.join(os.path.dirname(HERE), "bin", "stu-run-check")
FAILURES = []
COUNT = [0]

DONE = ("GROOMER: DONE — 3 issues filed\nJOB: g1\nKIND: groom\nOUTPUT: /runs/g1/report.md\n"
        "ISSUES: 11, 12, 13\nOBJECTIVES: /runs/demo-objective.md\nLEDGER: none\nNOT-REACHED: 0\n")
SPLIT = ("GROOMER: SPLIT — too wide\nJOB: g1\nKIND: audit\nOUTPUT: /runs/g1/report.md\n"
         "ISSUES: none\nOBJECTIVES: none\nLEDGER: /inbox/a.md\nNOT-REACHED: 4\nSPLIT: 2\n"
         "S1: the api handlers\nS2: the jobs\n")
READY = ("DESIGNER: READY — round 1 drawn\nJOB: d1\nROUND: 1\nOUTPUT: /runs/d1/round-1\n"
         "ARTIFACTS: /runs/d1/round-1/a.png, /runs/d1/round-1/b.png\n"
         "DECISION: which header do you want\nD1: tall | big title (recommended)\n"
         "D2: short | small title\nNOT-REACHED: 0\n")


def run(mode, text, extra=()):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "ret.txt")
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        r = subprocess.run([BIN, mode, p] + list(extra), capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def expect(name, mode, text, code, needle=None, extra=()):
    COUNT[0] += 1
    rc, out, err = run(mode, text, extra)
    if rc != code:
        FAILURES.append("%s: exit %d, want %d (%s%s)" % (name, rc, code, out, err))
    elif needle and needle not in out:
        FAILURES.append("%s: output lacks %r: %s" % (name, needle, out))
    if code in (0, 1):
        last = out.strip().splitlines()[-1] if out.strip() else ""
        if last != ("OK" if code == 0 else "BLOCKED"):
            FAILURES.append("%s: terminal line %r" % (name, last))


G, D = "--groomer-return", "--designer-return"
expect("groomer done", G, DONE, 0, "GROOMER OK DONE")
expect("groomer split", G, SPLIT, 0, "GROOMER OK SPLIT")
expect("groomer blocked needs only a reason", G, "GROOMER: BLOCKED — no repo access\n", 0)
expect("groomer blocked usage limit", G, "GROOMER: BLOCKED — usage limit\n", 0)
import judgment_return as _jr
for _t, _w in (("usage limit", True), ("  Usage Limit reached ", True), ("hit no usage limit", False),
               ("blocked by usage limit", False)):
    assert _jr.is_usage_limit(_t) is _w, _t
expect("groomer blocked without reason", G, "GROOMER: BLOCKED\n", 1, "one-line reason")
expect("groomer missing field", G, DONE.replace("ISSUES: 11, 12, 13\n", ""), 1, "ISSUES")
expect("groomer bad status", G, DONE.replace("DONE", "READY", 1), 1, "GROOMER line must start")
expect("groomer relative path", G, DONE.replace("/runs/g1/report.md", "report.md"), 1, "absolute")
expect("groomer bad issue", G, DONE.replace("11, 12, 13", "eleven"), 1, "ISSUES")
expect("split with no S lines", G, SPLIT.replace("S1: the api handlers\nS2: the jobs\n", ""), 1,
       "SPLIT says 2")
expect("split count mismatch", G, SPLIT.replace("SPLIT: 2", "SPLIT: 3"), 1, "SPLIT says 3")
expect("done carrying S lines", G, DONE + "S1: x\n", 1, "must not carry")
expect("job matches", G, DONE, 0, extra=["--job", "g1"])
expect("job mismatch", G, DONE, 1, "JOB is g1", extra=["--job", "other"])
expect("blocked job mismatch", G, "GROOMER: BLOCKED — x\nJOB: g1\n", 1, "JOB is g1",
       extra=["--job", "other"])
expect("kind matches", G, DONE, 0, extra=["--kind", "groom"])
expect("kind mismatch", G, DONE, 1, "KIND is groom", extra=["--kind", "audit"])
expect("designer ready", D, READY, 0, "DESIGNER OK READY")
expect("designer blocked", D, "DESIGNER: BLOCKED — usage limit\n", 0)
expect("designer one option", D, READY.replace("D2: short | small title\n", ""), 1, "at least two D options")
expect("designer relative artifact", D, READY.replace("/runs/d1/round-1/a.png", "a.png"), 1,
       "absolute")
expect("designer missing decision", D, READY.replace("DECISION: which header do you want\n", ""),
       1, "DECISION")
expect("designer job mismatch", D, READY, 1, "JOB is d1", extra=["--job", "g1"])
expect("designer job matches", D, READY, 0, extra=["--job", "d1"])
expect("designer wrong header", D, DONE, 1, "DESIGNER line must start")

COUNT[0] += 1
rc = subprocess.run([BIN, G, "/nonexistent/ret.txt"], capture_output=True, text=True)
if rc.returncode != 3 or rc.stdout:
    FAILURES.append("unreadable: exit %d stdout %r" % (rc.returncode, rc.stdout))

if FAILURES:
    print("FAIL judgment_return_test: %d of %d" % (len(FAILURES), COUNT[0]))
    for f in FAILURES:
        print("  " + f)
    sys.exit(1)
print("ok: %d judgment return checks" % COUNT[0])
