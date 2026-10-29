#!/usr/bin/env python3
"""stu-approve <id> <sha>: record the owner's approval of one commit.

The human-only channel for a before-push checkpoint: the owner types
`! "<plugin root>/bin/stu-approve" <id> <sha>`. An agent never runs this (the tool-call
hook denies it) and never writes the file it appends to.

<id> is qualified, `<repo>#<n>` or `<repo>:<slug>`, and names its row by the part before
the `#` or `:`. A bare id is accepted only when the family has one row. <sha> may be
abbreviated or a tag: the full commit sha is verified in the row's checkout and stored.

Appends `<id> TAB <full sha> TAB <UTC date>` to RUN_HOME/approvals.tsv under an flock and
prints that line. Exit 0 ok; 1 unknown sha or unresolvable row; 2 usage.
"""
import fcntl
import os
import re
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import push_policy  # noqa: E402
import stu_env  # noqa: E402


def die(msg, code):
    sys.stderr.write("stu-approve: %s\n" % msg)
    return code


def resolve_row(ident):
    """-> the resolve() dict of the unit's row. Raises ValueError (usage) or the stu_env
    errors."""
    m = re.match(r"([^#:]+)[#:]", ident)
    if m:
        return stu_env.resolve(repo=m.group(1), forge_lookup=False)
    try:
        row = stu_env.resolve(forge_lookup=False)
    except stu_env.NoConfig:
        row = stu_env.resolve(require_config=False, forge_lookup=False)
    if int(row.get("FAMILY_ROWS") or 1) > 1:
        raise ValueError("this family has several repos; name the row, e.g. "
                         "'<repo>#%s' or '<repo>:%s'" % (ident, ident))
    return row


def main(argv):
    if len(argv) != 3 or re.search(r"\s", argv[1]) or not argv[1] or argv[2].startswith("-"):
        return die("usage: stu-approve <repo>#<n>|<repo>:<slug> <sha> (no spaces in the id)", 2)
    ident, ref = argv[1], argv[2]
    push_policy.scrub_environ()
    try:
        row = resolve_row(ident)
    except ValueError as e:
        return die(str(e), 2)
    except (stu_env.NoConfig, stu_env.ConfigError, stu_env.NotInRepo,
            stu_env.UsageError) as e:
        return die("cannot resolve the unit's repo row: %s" % e, 1)
    rc, sha = push_policy.git(row["MAIN_CHECKOUT"], "rev-parse", "--verify", "--quiet",
                              ref + "^{commit}")
    if rc != 0 or not push_policy.FULL_SHA.fullmatch(sha):
        return die("%r is not a commit in %s" % (ref, row["MAIN_CHECKOUT"]), 1)
    line = "%s\t%s\t%s" % (ident, sha, datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    path = push_policy.approvals_path(row["RUN_HOME"])
    os.makedirs(row["RUN_HOME"], exist_ok=True)
    fd = os.open(path + ".lock", os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
