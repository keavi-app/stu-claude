#!/usr/bin/env python3
"""Cross-run unit claim file for /stu:run.

Several supervisors can run at once on one machine. Each unit (an issue number or
slug) is worked by one run; this file is how a second run learns the first holds it.

File: <RUN_HOME>/runs/claims.tsv, RUN_HOME from stu-env (override: RUN_CLAIMS_FILE). Two row kinds:
  claim (4 fields), at most one per unit:
    <unit id> TAB <run slug> TAB <session id> TAB <claimed at, UTC ISO 8601>
  hold (5 fields, the fifth is the literal "hold"), one per unit and run:
    <unit id> TAB <run slug> TAB <session id> TAB <held at, UTC ISO 8601> TAB hold
Unit ids are opaque strings. A hold marks a unit a run is waiting on; it never goes stale.

A claim is LIVE while it is unreleased and younger than the stale threshold
(RUN_CLAIM_STALE_HOURS, default 12). A stale claim does not block another run.
Re-claiming a unit you hold refreshes its timestamp, so a long run keeps its claims
live by claiming again. Every read-modify-write holds fcntl.flock on <file>.lock
(the flock binary is not installed on macOS; Python's fcntl is).

Exit codes: 0 ok; 1 conflict (claim and hold: another run has a live claim or any hold
on the unit); 2 error (usage, bad field or duration, unresolvable RUN_HOME). Malformed
lines in the file are skipped.

Subcommands:
  claim UNIT RUN [SESSION]   exit 1 and print the holder's run slug if another run
                             holds UNIT live or holds it with a hold; otherwise
                             record it (idempotent; keeps the run's own hold)
  hold UNIT RUN [SESSION]    like claim, but records a non-expiring hold; the run's
                             own live claim does not conflict and is kept
  release RUN [UNIT]         drop RUN's claims (one unit, or all); holds are kept
  release --held RUN UNIT    drop RUN's hold on UNIT
  list [--runs]              all lines; --runs prints each run with a live claim,
                             then "<run> waiting" for each run with only holds
  stale --older-than 6h      claims older than the duration (s, m, h, d); never holds
"""
import fcntl
import os
import sys
import time
from datetime import datetime, timedelta, timezone

DEFAULT_STALE_HOURS = 12.0
FMT = "%Y-%m-%dT%H:%M:%SZ"


def claims_path():
    override = os.environ.get("RUN_CLAIMS_FILE")
    if override:
        return override
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import stu_env
        try:
            try:
                env = stu_env.resolve(require_config=True)
            except stu_env.NoConfig:  # no config at all: today's flat per-project default
                env = stu_env.resolve(require_config=False)
        except stu_env.ConfigError as e:  # the fix is the config, not an override
            die("cannot resolve RUN_HOME: %s" % e)
        except stu_env.NotInRepo as e:
            die("cannot resolve RUN_HOME (%s); set RUN_CLAIMS_FILE" % e)
        run_home = env["RUN_HOME"]
    except SystemExit:
        raise
    except BaseException as e:
        die("cannot resolve RUN_HOME: %s: %s" % (type(e).__name__, e))
    return os.path.join(run_home, "runs", "claims.tsv")


def stale_threshold():
    text = os.environ.get("RUN_CLAIM_STALE_HOURS", DEFAULT_STALE_HOURS)
    try:
        return timedelta(hours=float(text))
    except (ValueError, OverflowError):
        die("bad RUN_CLAIM_STALE_HOURS %r: want a number of hours" % text)


def now():
    override = os.environ.get("RUN_CLAIMS_NOW")  # tests only
    if override:
        return datetime.strptime(override, FMT).replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def die(msg):
    print(msg, file=sys.stderr)
    raise SystemExit(2)


def parse_duration(text):
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    if not text or text[-1] not in units:
        die("bad duration %r: want a number and one of s m h d" % text)
    try:
        return timedelta(seconds=float(text[:-1]) * units[text[-1]])
    except (ValueError, OverflowError):
        die("bad duration %r: want a number and one of s m h d" % text)


class Locked:
    """Exclusive lock on <claims file>.lock for the life of the block."""

    def __enter__(self):
        path = claims_path()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.fd = os.open(path + ".lock", os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(self.fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        fcntl.flock(self.fd, fcntl.LOCK_UN)
        os.close(self.fd)


def read_rows():
    try:
        with open(claims_path()) as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        return []
    rows = []
    for l in lines:
        r = l.split("\t")
        if (len(r) == 4 and all(r)) or (len(r) == 5 and all(r) and r[4] == "hold"):
            try:
                datetime.strptime(r[3], FMT)
            except ValueError:
                continue
            rows.append(r)
    return rows


def write_rows(rows):
    path = claims_path()
    tmp = "%s.tmp.%d" % (path, os.getpid())
    with open(tmp, "w") as f:
        for r in rows:
            f.write("\t".join(r) + "\n")
    os.replace(tmp, path)


def age(row):
    return now() - datetime.strptime(row[3], FMT).replace(tzinfo=timezone.utc)


def is_hold(row):
    return len(row) == 5


def blocks(row, unit, run):
    """Does this row stop `run` from claiming or holding `unit`?"""
    return row[0] == unit and row[1] != run and (is_hold(row) or is_live(row))


def is_live(row):
    return age(row) < stale_threshold()


def check_field(name, value):
    if not value or any(c in value for c in "\t\n\r"):
        die("%s must be non-empty with no tab or newline" % name)


def cmd_claim(args):
    if len(args) not in (2, 3):
        die("usage: claim UNIT RUN [SESSION]")
    unit, run = args[0], args[1]
    session = args[2] if len(args) == 3 else "-"
    for n, v in (("unit", unit), ("run", run), ("session", session)):
        check_field(n, v)
    with Locked():
        rows = read_rows()
        for r in rows:
            if blocks(r, unit, run):
                print(r[1])
                return 1
        kept = [r for r in rows if r[0] != unit or is_hold(r)]
        if os.environ.get("RUN_CLAIMS_TEST_DELAY"):  # tests only: widen the race
            time.sleep(float(os.environ["RUN_CLAIMS_TEST_DELAY"]))
        kept.append([unit, run, session, now().strftime(FMT)])
        write_rows(kept)
    return 0


def cmd_hold(args):
    if len(args) not in (2, 3):
        die("usage: hold UNIT RUN [SESSION]")
    unit, run = args[0], args[1]
    session = args[2] if len(args) == 3 else "-"
    for n, v in (("unit", unit), ("run", run), ("session", session)):
        check_field(n, v)
    with Locked():
        rows = read_rows()
        for r in rows:
            if blocks(r, unit, run):
                print(r[1])
                return 1
        kept = [r for r in rows if not (is_hold(r) and r[0] == unit and r[1] == run)]
        kept.append([unit, run, session, now().strftime(FMT), "hold"])
        write_rows(kept)
    return 0


def cmd_release(args):
    if args and args[0] == "--held":
        if len(args) != 3:
            die("usage: release --held RUN UNIT")
        run, unit = args[1], args[2]
        with Locked():
            write_rows([r for r in read_rows()
                        if not (is_hold(r) and r[1] == run and r[0] == unit)])
        return 0
    if len(args) not in (1, 2):
        die("usage: release RUN [UNIT]  |  release --held RUN UNIT")
    run = args[0]
    unit = args[1] if len(args) == 2 else None
    with Locked():
        rows = read_rows()
        write_rows(
            [r for r in rows
             if is_hold(r) or not (r[1] == run and (unit is None or r[0] == unit))]
        )
    return 0


def cmd_list(args):
    rows = read_rows()
    if args == ["--runs"]:
        seen = []
        for r in rows:
            if not is_hold(r) and is_live(r) and r[1] not in seen:
                seen.append(r[1])
        waiting = []
        for r in rows:
            if is_hold(r) and r[1] not in seen and r[1] not in waiting:
                waiting.append(r[1])
        for s in seen:
            print(s)
        for s in waiting:
            print("%s waiting" % s)
        return 0
    if args:
        die("usage: list [--runs]")
    for r in rows:
        print("\t".join(r))
    return 0


def cmd_stale(args):
    if len(args) != 2 or args[0] != "--older-than":
        die("usage: stale --older-than DURATION")
    limit = parse_duration(args[1])
    for r in read_rows():
        if not is_hold(r) and age(r) > limit:
            print("\t".join(r))
    return 0


COMMANDS = {"claim": cmd_claim, "hold": cmd_hold, "release": cmd_release, "list": cmd_list, "stale": cmd_stale}


def main(argv):
    if not argv or argv[0] not in COMMANDS:
        die(__doc__)
    stale_threshold()  # a bad RUN_CLAIM_STALE_HOURS is an error for every command
    return COMMANDS[argv[0]](argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
