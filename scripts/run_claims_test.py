#!/usr/bin/env python3
"""Regression suite for run_claims.py. Every decision has a check that would go red
if it changed: conflict exits non-zero with the holder named, re-claim is
idempotent, a stale holder does not block, release frees, concurrent writers do not
lose or interleave lines. Never touches the real claims file: RUN_CLAIMS_FILE points at a temp dir.

Run: python3 scripts/run_claims_test.py
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "run_claims.py")
FAILURES = []
COUNT = [0]


def check(name, got, want):
    COUNT[0] += 1
    if got != want:
        FAILURES.append("%s: got %r, want %r" % (name, got, want))


def env_for(d, **extra):
    e = dict(os.environ)
    e["RUN_CLAIMS_FILE"] = os.path.join(d, "claims.tsv")
    for k in ("RUN_CLAIMS_NOW", "RUN_CLAIMS_TEST_DELAY", "RUN_CLAIM_STALE_HOURS"):
        e.pop(k, None)
    e.update(extra)
    return e


def run(d, *args, **extra):
    p = subprocess.run(
        [sys.executable, SCRIPT] + list(args),
        env=env_for(d, **extra), capture_output=True, text=True,
    )
    return p.returncode, p.stdout


def rows(d):
    rc, out = run(d, "list")
    return [l.split("\t") for l in out.splitlines()]


T0 = "2026-10-01T10:00:00Z"
T_SOON = "2026-10-01T12:00:00Z"
T_LATE = "2026-10-02T00:00:01Z"  # 14h after T0, past the 12h default


def test_claim_and_conflict():
    with tempfile.TemporaryDirectory() as d:
        rc, out = run(d, "claim", "101", "run-a", "sess-a", RUN_CLAIMS_NOW=T0)
        check("first claim exits 0", rc, 0)
        rc, out = run(d, "claim", "101", "run-b", "sess-b", RUN_CLAIMS_NOW=T_SOON)
        check("claim held by another run exits non-zero", rc, 1)
        check("conflict prints the holder slug", out.strip(), "run-a")
        check("conflict does not overwrite", rows(d), [["101", "run-a", "sess-a", T0]])


def test_idempotent_reclaim():
    with tempfile.TemporaryDirectory() as d:
        run(d, "claim", "101", "run-a", "sess-a", RUN_CLAIMS_NOW=T0)
        rc, _ = run(d, "claim", "101", "run-a", "sess-a", RUN_CLAIMS_NOW=T_SOON)
        check("re-claim by same run exits 0", rc, 0)
        check("re-claim leaves one line, refreshed", rows(d),
              [["101", "run-a", "sess-a", T_SOON]])


def test_release():
    with tempfile.TemporaryDirectory() as d:
        run(d, "claim", "1", "a", "s", RUN_CLAIMS_NOW=T0)
        run(d, "claim", "2", "a", "s", RUN_CLAIMS_NOW=T0)
        run(d, "claim", "3", "b", "s", RUN_CLAIMS_NOW=T0)
        run(d, "release", "a", "1")
        check("release one unit", [r[0] for r in rows(d)], ["2", "3"])
        run(d, "release", "a")
        check("release all of a run leaves other runs", [r[0] for r in rows(d)], ["3"])
        rc, out = run(d, "claim", "1", "b", "s", RUN_CLAIMS_NOW=T0)
        check("released unit can be claimed by another run", rc, 0)


def test_stale():
    with tempfile.TemporaryDirectory() as d:
        run(d, "claim", "101", "run-a", "s", RUN_CLAIMS_NOW=T0)
        rc, out = run(d, "claim", "101", "run-b", "s", RUN_CLAIMS_NOW=T_LATE)
        check("stale holder does not block", rc, 0)
        check("stale claim taken over", rows(d), [["101", "run-b", "s", T_LATE]])
    with tempfile.TemporaryDirectory() as d:
        run(d, "claim", "1", "a", "s", RUN_CLAIMS_NOW=T0)
        run(d, "claim", "2", "b", "s", RUN_CLAIMS_NOW=T_SOON)
        rc, out = run(d, "stale", "--older-than", "3h", RUN_CLAIMS_NOW="2026-10-01T14:00:00Z")
        check("stale --older-than lists only the older claim",
              [l.split("\t")[0] for l in out.splitlines()], ["1"])
        rc, out = run(d, "stale", "--older-than", "1d", RUN_CLAIMS_NOW="2026-10-01T14:00:00Z")
        check("stale --older-than 1d lists none", out, "")
        rc, _ = run(d, "stale", "--older-than", "bogus")
        check("bad duration is the error code", rc, 2)


def test_live_runs():
    with tempfile.TemporaryDirectory() as d:
        run(d, "claim", "1", "a", "s", RUN_CLAIMS_NOW=T0)
        run(d, "claim", "2", "a", "s", RUN_CLAIMS_NOW=T0)
        run(d, "claim", "3", "b", "s", RUN_CLAIMS_NOW=T_SOON)
        run(d, "claim", "4", "c", "s", RUN_CLAIMS_NOW="2026-09-30T00:00:00Z")
        rc, out = run(d, "list", "--runs", RUN_CLAIMS_NOW=T_SOON)
        check("live runs are distinct and exclude stale-only runs",
              out.split(), ["a", "b"])


def test_bad_fields():
    with tempfile.TemporaryDirectory() as d:
        rc, _ = run(d, "claim", "a\tb", "r", "s")
        check("tab in unit id is refused with the error code, not the conflict code", rc, 2)
        check("nothing written", rows(d), [])


def test_error_codes_and_corrupt_lines():
    with tempfile.TemporaryDirectory() as d:
        check("claim with no args exits 2", run(d, "claim")[0], 2)
        check("unknown subcommand exits 2", run(d, "frob")[0], 2)
        check("release with no args exits 2", run(d, "release")[0], 2)
        check("list with a bad flag exits 2", run(d, "list", "--bogus")[0], 2)
        check("stale without --older-than exits 2", run(d, "stale")[0], 2)
        check("bad stale-hours env exits 2 on claim", run(d, "claim", "9", "z", RUN_CLAIM_STALE_HOURS="abc")[0], 2)
        check("overflowing stale-hours env exits 2", run(d, "claim", "9", "z", RUN_CLAIM_STALE_HOURS="1e999")[0], 2)
        check("huge duration exits 2", run(d, "stale", "--older-than", "1e999d")[0], 2)
        check("nan duration exits 2", run(d, "stale", "--older-than", "nand")[0], 2)
        run(d, "claim", "1", "a", "s", RUN_CLAIMS_NOW=T0)
        with open(os.path.join(d, "claims.tsv"), "a") as f:
            f.write("junk\n\t\t\t\nx\ty\tz\tnot-a-time\n")
        rc, out = run(d, "list", "--runs", RUN_CLAIMS_NOW=T_SOON)
        check("list --runs skips corrupt lines", (rc, out.split()), (0, ["a"]))
        rc, out = run(d, "list")
        check("list skips corrupt lines", (rc, len(out.splitlines())), (0, 1))
        rc, _ = run(d, "claim", "2", "b", "s", RUN_CLAIMS_NOW=T_SOON)
        check("claim tolerates corrupt lines", rc, 0)


def test_boundaries():
    with tempfile.TemporaryDirectory() as d:
        run(d, "claim", "1", "a", "s", RUN_CLAIMS_NOW=T0)
        rc, _ = run(d, "claim", "1", "b", "s", RUN_CLAIMS_NOW="2026-10-01T21:59:59Z")
        check("claim 1s under the threshold still blocks", rc, 1)
        rc, _ = run(d, "claim", "1", "c", "s", RUN_CLAIMS_NOW="2026-10-01T22:00:00Z")
        check("claim exactly at the threshold is stale (live means younger)", rc, 0)
    with tempfile.TemporaryDirectory() as d:
        run(d, "claim", "1", "a", "s", RUN_CLAIMS_NOW=T0)
        rc, out = run(d, "stale", "--older-than", "3h", RUN_CLAIMS_NOW="2026-10-01T13:00:00Z")
        check("stale at exactly the age is not listed (strictly older)", out, "")
        rc, out = run(d, "stale", "--older-than", "3h", RUN_CLAIMS_NOW="2026-10-01T13:00:01Z")
        check("stale 1s past the age is listed", len(out.splitlines()), 1)
    with tempfile.TemporaryDirectory() as d:
        run(d, "claim", "1", "a", RUN_CLAIMS_NOW=T0)
        check("session defaults to -", rows(d), [["1", "a", "-", T0]])
        run(d, "release", "b", "1")
        check("release RUN UNIT does not drop another run's claim", len(rows(d)), 1)


def spawn(d, argvs, **extra):
    procs = [
        subprocess.Popen([sys.executable, SCRIPT] + a, env=env_for(d, **extra),
                         stdout=subprocess.PIPE, text=True)
        for a in argvs
    ]
    return [(p.wait(), p.stdout.read()) for p in procs]


def test_concurrent_distinct_units():
    n = 16
    with tempfile.TemporaryDirectory() as d:
        res = spawn(d, [["claim", "u%d" % i, "run%d" % i, "s"] for i in range(n)],
                    RUN_CLAIMS_TEST_DELAY="0.3")
        check("all concurrent distinct claims exit 0", [r[0] for r in res], [0] * n)
        got = sorted(r[0] for r in rows(d))
        check("no claim lost to a racing writer", got, sorted("u%d" % i for i in range(n)))
        check("every line has four fields", all(len(r) == 4 for r in rows(d)), True)


def test_concurrent_same_unit():
    n = 12
    with tempfile.TemporaryDirectory() as d:
        res = spawn(d, [["claim", "101", "run%d" % i, "s"] for i in range(n)],
                    RUN_CLAIMS_TEST_DELAY="0.3")
        check("exactly one concurrent claimant wins", sorted(r[0] for r in res),
              [0] + [1] * (n - 1))
        r = rows(d)
        check("exactly one line for the unit", len(r), 1)
        winner = r[0][1]
        check("every loser is told the winner",
              {o.strip() for c, o in res if c == 1}, {winner})


def test_default_path_is_run_home():
    """Without RUN_CLAIMS_FILE the file is <RUN_HOME>/runs/claims.tsv from stu-env."""
    with tempfile.TemporaryDirectory() as d:
        repo = os.path.join(d, "repo")
        cfg = os.path.join(d, "stu.md")
        home = os.path.join(d, "home")
        subprocess.run(["git", "init", "-q", repo], check=True)
        with open(cfg, "w") as fh:
            fh.write("---\nrun_home: %s\ngithub_repo: o/r\n---\n" % home)
        e = dict(os.environ, STU_CONFIG=cfg)
        e.pop("RUN_CLAIMS_FILE", None)
        p = subprocess.run([sys.executable, SCRIPT, "claim", "7", "r1", "s"], cwd=repo,
                           env=e, capture_output=True, text=True)
        check("default-path claim exits 0", p.returncode, 0)
        check("claims land under RUN_HOME/runs",
              os.path.exists(os.path.join(home, "runs", "claims.tsv")), True)


def test_hold_survives_release():
    with tempfile.TemporaryDirectory() as d:
        run(d, "claim", "1", "a", "s", RUN_CLAIMS_NOW=T0)
        rc, _ = run(d, "hold", "2", "a", "s", RUN_CLAIMS_NOW=T0)
        check("hold exits 0", rc, 0)
        run(d, "release", "a")
        check("release RUN keeps holds", rows(d), [["2", "a", "s", T0, "hold"]])
        run(d, "release", "a", "2")
        check("release RUN UNIT keeps a hold", len(rows(d)), 1)


def test_hold_never_stale():
    with tempfile.TemporaryDirectory() as d:
        run(d, "hold", "2", "a", "s", RUN_CLAIMS_NOW=T0)
        rc, out = run(d, "claim", "2", "b", "s", RUN_CLAIMS_NOW="2026-10-31T00:00:00Z")
        check("a 30-day-old hold still blocks another run's claim", (rc, out.strip()), (1, "a"))
        rc, out = run(d, "hold", "2", "b", "s", RUN_CLAIMS_NOW="2026-10-31T00:00:00Z")
        check("hold vs hold conflicts", (rc, out.strip()), (1, "a"))
        check("conflicts write nothing", len(rows(d)), 1)


def test_hold_conflicts_with_live_claim():
    with tempfile.TemporaryDirectory() as d:
        run(d, "claim", "2", "a", "s", RUN_CLAIMS_NOW=T0)
        rc, out = run(d, "hold", "2", "b", "s", RUN_CLAIMS_NOW=T_SOON)
        check("hold vs another run's live claim conflicts", (rc, out.strip()), (1, "a"))
        rc, _ = run(d, "hold", "2", "b", "s", RUN_CLAIMS_NOW=T_LATE)
        check("hold over a stale claim is allowed", rc, 0)


def test_hold_on_own_claim():
    with tempfile.TemporaryDirectory() as d:
        run(d, "claim", "2", "a", "s", RUN_CLAIMS_NOW=T0)
        rc, _ = run(d, "hold", "2", "a", "s", RUN_CLAIMS_NOW=T_SOON)
        check("hold on own live claim exits 0", rc, 0)
        check("claim row kept beside the hold", rows(d),
              [["2", "a", "s", T0], ["2", "a", "s", T_SOON, "hold"]])
        run(d, "hold", "2", "a", "s", RUN_CLAIMS_NOW=T_LATE)
        check("re-hold refreshes, no duplicate", len(rows(d)), 2)


def test_stale_never_lists_holds():
    with tempfile.TemporaryDirectory() as d:
        run(d, "hold", "2", "a", "s", RUN_CLAIMS_NOW=T0)
        run(d, "claim", "3", "a", "s", RUN_CLAIMS_NOW=T0)
        rc, out = run(d, "stale", "--older-than", "1h", RUN_CLAIMS_NOW="2026-10-05T00:00:00Z")
        check("stale lists the claim, never the hold",
              [l.split("\t")[0] for l in out.splitlines()], ["3"])


def test_release_held_drops_one():
    with tempfile.TemporaryDirectory() as d:
        run(d, "hold", "1", "a", "s", RUN_CLAIMS_NOW=T0)
        run(d, "hold", "2", "a", "s", RUN_CLAIMS_NOW=T0)
        run(d, "claim", "3", "a", "s", RUN_CLAIMS_NOW=T0)
        rc, _ = run(d, "release", "--held", "a", "1")
        check("release --held exits 0", rc, 0)
        check("only that hold dropped", [r[0] for r in rows(d)], ["2", "3"])
        check("release --held without unit is usage", run(d, "release", "--held", "a")[0], 2)
        check("release --held bare is usage", run(d, "release", "--held")[0], 2)


def test_list_runs_waiting():
    with tempfile.TemporaryDirectory() as d:
        run(d, "claim", "1", "a", "s", RUN_CLAIMS_NOW=T_SOON)
        run(d, "hold", "2", "a", "s", RUN_CLAIMS_NOW=T_SOON)
        run(d, "hold", "3", "b", "s", RUN_CLAIMS_NOW=T_SOON)
        run(d, "hold", "4", "b", "s", RUN_CLAIMS_NOW=T_SOON)
        run(d, "claim", "5", "c", "s", RUN_CLAIMS_NOW=T0)
        run(d, "hold", "6", "c", "s", RUN_CLAIMS_NOW=T0)
        rc, out = run(d, "list", "--runs", RUN_CLAIMS_NOW=T_LATE)
        check("stale claim plus a hold is waiting; each run once",
              out.splitlines(), ["a waiting", "b waiting", "c waiting"])
        rc, out = run(d, "list", "--runs", RUN_CLAIMS_NOW=T_SOON)
        check("live runs first, then waiting", out.splitlines(),
              ["a", "c", "b waiting"])


def test_four_column_rows_still_read():
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "claims.tsv"), "w") as f:
            f.write("1\ta\ts\t%s\n" % T0)
        check("a four-column row is a claim", rows(d), [["1", "a", "s", T0]])
        rc, out = run(d, "claim", "1", "b", "s", RUN_CLAIMS_NOW=T_SOON)
        check("it still blocks", (rc, out.strip()), (1, "a"))
        with open(os.path.join(d, "claims.tsv"), "a") as f:
            f.write("2\ta\ts\t%s\tnothold\n" % T0)
        check("a five-field row not ending in hold is skipped", len(rows(d)), 1)


def test_qualified_ids_distinct():
    with tempfile.TemporaryDirectory() as d:
        check("app#12 claim", run(d, "claim", "app#12", "r1", "s")[0], 0)
        check("lib#12 is a different unit", run(d, "claim", "lib#12", "r2", "s")[0], 0)
        check("app#12 still conflicts", run(d, "claim", "app#12", "r2", "s")[0], 1)


def test_own_claim_keeps_hold():
    with tempfile.TemporaryDirectory() as d:
        run(d, "hold", "2", "a", "s", RUN_CLAIMS_NOW=T0)
        rc, _ = run(d, "claim", "2", "a", "s", RUN_CLAIMS_NOW=T_SOON)
        check("claim by the hold's own run exits 0", rc, 0)
        check("hold row kept beside the new claim", rows(d),
              [["2", "a", "s", T0, "hold"], ["2", "a", "s", T_SOON]])
        rc, out = run(d, "claim", "2", "b", "s", RUN_CLAIMS_NOW="2026-10-31T00:00:00Z")
        check("hold still blocks others after the claim goes stale", (rc, out.strip()), (1, "a"))


def test_family_resolution_failure_is_error():
    with tempfile.TemporaryDirectory() as d:
        home = os.path.join(d, "home")
        run_home = os.path.join(d, "run_home")
        repos = []
        for n in ("app", "lib", "other"):
            p = os.path.join(d, n)
            subprocess.run(["git", "init", "-q", p], check=True)
            repos.append(p)
        cfg = os.path.join(d, "stu.md")
        def block(n, p):
            return ("### %s\npath: %s\nslug: acme/%s\nremote: origin\nbase: main\n"
                    "visibility: public\nmode: work\nmerge_mode: direct\nci: none\n" % (n, p, n))
        with open(cfg, "w") as fh:
            fh.write("---\nowner: acme\nrun_home: %s\n---\n\n## repos\n%s\n%s\n"
                     % (run_home, block("app", repos[0]), block("lib", repos[1])))
        e = dict(os.environ, STU_CONFIG=cfg, HOME=home)
        e.pop("RUN_CLAIMS_FILE", None)
        p = subprocess.run([sys.executable, SCRIPT, "claim", "app#1", "r1", "s"], cwd=repos[2],
                           env=e, capture_output=True, text=True)
        check("a repo matching no family row is exit 2", p.returncode, 2)
        check("nothing written under run_home", os.path.exists(run_home), False)
        check("the message does not tell a family user to set RUN_CLAIMS_FILE",
              "RUN_CLAIMS_FILE" in p.stderr, False)
        check("the message says why", "cannot resolve RUN_HOME" in p.stderr, True)


for t in (test_default_path_is_run_home, test_claim_and_conflict, test_idempotent_reclaim, test_release, test_stale,
          test_live_runs, test_bad_fields, test_error_codes_and_corrupt_lines,
          test_boundaries, test_concurrent_distinct_units,
          test_concurrent_same_unit, test_hold_survives_release, test_hold_never_stale,
          test_hold_conflicts_with_live_claim, test_hold_on_own_claim,
          test_stale_never_lists_holds, test_release_held_drops_one,
          test_list_runs_waiting, test_four_column_rows_still_read,
          test_qualified_ids_distinct, test_own_claim_keeps_hold,
          test_family_resolution_failure_is_error):
    t()

if FAILURES:
    print("FAIL: %d of %d checks" % (len(FAILURES), COUNT[0]))
    for f in FAILURES:
        print("  " + f)
    sys.exit(1)
print("ok: %d checks" % COUNT[0])
