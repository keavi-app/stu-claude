#!/usr/bin/env python3
"""Tests for scripts/run_check.py (stu-run-check), through the bin/ wrapper.

Every case builds temp repos with local bare remotes, a temp HOME and a config named by
STU_CONFIG; nothing touches the network. Run: python3 scripts/run_check_test.py
"""
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BIN = os.path.join(ROOT, "bin", "stu-run-check")
APPROVE = os.path.join(ROOT, "bin", "stu-approve")
FAKE_GH = os.path.join(ROOT, "tests", "fake_gh.py")

FAILURES = []
COUNT = [0]


def check(name, got, want):
    COUNT[0] += 1
    if got != want:
        FAILURES.append("%s: got %r, want %r" % (name, got, want))


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def rp(p):
    return os.path.realpath(p)


# ---- git fixtures -----------------------------------------------------------------------

class World:
    """A family (or a flat one-repo config) of temp repos, each with a bare origin."""

    def __init__(self, tmp, rows=None, flat=False):
        self.tmp = rp(tmp)
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        write(os.path.join(self.home, ".gitconfig"), "[init]\n\tdefaultBranch = main\n")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env.pop("STU_CONFIG", None)
        self.env.update({"HOME": self.home,
                         "GIT_CONFIG_GLOBAL": os.path.join(self.home, ".gitconfig"),
                         "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "T",
                         "GIT_AUTHOR_EMAIL": "t@e", "GIT_COMMITTER_NAME": "T",
                         "GIT_COMMITTER_EMAIL": "t@e"})
        # The fake gh logs every call: the git-only checks must never reach for it.
        self.ghlog = os.path.join(self.tmp, "gh.called")
        self.fixtures = os.path.join(self.tmp, "gh.fixtures.json")
        self.ghstate = os.path.join(self.tmp, "gh.state")
        gh = os.path.join(self.tmp, "ghbin", "gh")
        os.makedirs(os.path.dirname(gh))
        os.symlink(FAKE_GH, gh)
        self.env["PATH"] = os.path.dirname(gh) + os.pathsep + self.env["PATH"]
        self.env.update({"FAKE_GH_LOG": self.ghlog, "FAKE_GH_FIXTURES": self.fixtures,
                         "FAKE_GH_STATE": self.ghstate, "STU_FORGE_REQUERY_DELAY": "0"})
        self.set_gh({})
        self.flat = flat
        rows = rows or {"app": {}, "lib": {"merge_mode": "report-only"}}
        if flat:
            rows = {"app": rows.get("app", {})}
        self.rows = rows
        self.path = {}
        self.remote = {}
        for name in rows:
            self.path[name] = self.make_repo(name)
        self.run_home = os.path.join(self.home, ".stu", "fam")
        if flat:
            self.cfg = os.path.join(self.path["app"], ".claude", "stu.md")
            fm = {"project": "app", "slug": "acme/app", "remote": "origin", "base": "main",
                  "visibility": "private", "mode": "work", "merge_mode": "direct",
                  "ci": "none"}
            fm.update(rows["app"])
            write(self.cfg, "---\nowner: o\n%s---\n" % "".join(
                "%s: %s\n" % (k, v) for k, v in fm.items() if v is not None))
            self.run_home = os.path.join(self.home, ".stu", "app")
        else:
            self.cfg = os.path.join(self.home, ".stu", "fam", "stu.md")
            write(self.cfg, self.fam_text())
        self.env["STU_CONFIG"] = self.cfg

    def set_gh(self, fixtures):
        write(self.fixtures, json.dumps(fixtures))
        if os.path.exists(self.ghstate):
            os.remove(self.ghstate)

    def make_repo(self, name):
        parent = os.path.join(self.tmp, "x")
        os.makedirs(parent, exist_ok=True)
        path = os.path.join(parent, name)
        os.makedirs(path)
        self.g(path, "init", "-q", "-b", "main")
        self.commit(path, "README.txt", "init")
        bare = os.path.join(self.tmp, "remotes", name + ".git")
        os.makedirs(os.path.dirname(bare), exist_ok=True)
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", bare], env=self.env,
                       check=True, capture_output=True)
        self.g(path, "remote", "add", "origin", bare)
        self.g(path, "push", "-q", "origin", "main")
        self.remote[name] = bare
        return rp(path)

    def fam_text(self):
        blocks = []
        for name, over in self.rows.items():
            d = {"slug": "acme/" + name, "remote": "origin", "base": "main",
                 "visibility": "private", "mode": "work", "merge_mode": "direct",
                 "ci": "none", "path": self.path[name]}
            d.update(over)
            blocks.append("\n".join(["### " + name] + ["%s: %s" % (k, v)
                                                       for k, v in d.items() if v is not None]))
        names = list(self.rows)
        text = "---\nowner: o\n---\n\n## repos\n%s\n\n## verification-commands\n```\nmake test\n```\n" % (
            "\n".join(blocks))
        for n in names[1:]:
            text += "\n## verification-commands @%s\n```\n./check\n```\n" % n
        return text

    def g(self, cwd, *args):
        p = subprocess.run(["git"] + list(args), cwd=cwd, env=self.env, capture_output=True,
                           text=True)
        if p.returncode != 0:
            raise RuntimeError("git %s: %s" % (" ".join(args), p.stderr))
        return p.stdout.strip()

    def commit(self, repo, fname, msg):
        write(os.path.join(repo, fname), msg + "\n")
        self.g(repo, "add", fname)
        self.g(repo, "commit", "-q", "-m", msg)
        return self.g(repo, "rev-parse", "HEAD")

    def landed(self, name, msg="work"):
        """A new commit on main, pushed to the bare origin. -> its sha."""
        sha = self.commit(self.path[name], msg + ".txt", msg)
        self.g(self.path[name], "push", "-q", "origin", "main")
        return sha

    def local_only(self, name, msg="local"):
        """A commit on a side branch that is never pushed. -> (branch, sha)."""
        repo = self.path[name]
        self.g(repo, "checkout", "-q", "-b", "feat-" + msg)
        sha = self.commit(repo, msg + ".txt", msg)
        self.g(repo, "checkout", "-q", "main")
        return "feat-" + msg, sha

    def tag(self, name, tag, sha):
        repo = self.path[name]
        self.g(repo, "tag", "-a", tag, sha, "-m", tag)
        self.g(repo, "push", "-q", "origin", "refs/tags/" + tag)

    def run(self, args, cwd=None):
        p = subprocess.run([BIN] + list(args), cwd=cwd or self.path["app"], env=self.env,
                           capture_output=True, text=True)
        return p.returncode, p.stdout.splitlines(), p.stderr

    def check_files(self, objective, ret, **kw):
        o = os.path.join(self.tmp, "objective.md")
        r = os.path.join(self.tmp, "return.txt")
        write(o, objective)
        write(r, ret)
        return self.run(["--objective", o, "--return", r], **kw)

    def gh_called(self):
        return os.path.exists(self.ghlog)


def pr_doc(sha, slug="acme/lib", pr=5, state="OPEN", labels=(), merge=None):
    return {"json": {"state": state, "headRefName": "feat", "headRefOid": sha,
                     "baseRefName": "main", "mergeCommit": {"oid": merge} if merge else None,
                     "labels": [{"name": n} for n in labels], "autoMergeRequest": None,
                     "url": "https://github.com/%s/pull/%d" % (slug, pr)}}


def table(rows, header="| ID | Repo | After |"):
    cols = header.count("|") - 1
    out = [header, "|" + "---|" * cols]
    for r in rows:
        out.append("| " + " | ".join(r) + " |")
    return "\n".join(out)


def objective(rows=None, scoreboard=None, header="| ID | Repo | After |", extra="", issued=True):
    text = "# Objective: test\n\nWritten 2026-10-26. Mode: plain.\n%s\n" % extra
    if rows is not None and issued and not any(k == "Units issued" for k, _ in scoreboard or []):
        scoreboard = [("Units issued", ", ".join(r[0] for r in rows))] + list(scoreboard or [])
    if rows is not None:
        text += "\n## Units\n\n%s\n" % table(rows, header)
    if scoreboard is not None:
        text += "\n## Scoreboard\n\n%s\n" % "\n".join("%s: %s" % kv for kv in scoreboard)
    return text


def ret(**fields):
    lines = ["STATUS: CONTINUE", "CYCLE: 1"]
    for k, v in fields.items():
        lines.append("%s: %s" % (k, v))
    return "\n".join(lines) + "\n"


def status(out, ident):
    for l in out:
        if l.startswith(ident + " "):
            return l.split(" ", 2)[1:]
    return None


def term(out):
    return out[-1] if out else None


def blocked_with(out, ident, code):
    st = status(out, ident)
    return bool(st) and st[0] == "BLOCKED" and st[1].startswith(code)


FULL = "a" * 40


# ---- tests ------------------------------------------------------------------------------

def test_closing_by_ancestry():
    with tempfile.TemporaryDirectory() as tmp:
        w = World(tmp)
        sha = w.landed("app")
        rows = [("app#1", "app", "-")]
        rc, out, err = w.check_files(objective(rows),
                                     ret(CLOSED_IDS="app#1", MERGED_IDS="app#1@" + sha))
        check("direct_merged_closes", (rc, status(out, "app#1"), term(out)),
              (0, ["CLOSED", "merged-on-base"], "OK"))

        rc, out, err = w.check_files(objective(rows),
                                     ret(CLOSED_IDS="app#1", MERGED_IDS="app#1@" + sha[:12]))
        check("short_sha_blocked", (rc, blocked_with(out, "app#1", "non-full-sha"), term(out)),
              (1, True, "BLOCKED"))
        up = sha.upper()
        rc, out, err = w.check_files(objective(rows), ret(MERGED_IDS="app#1@" + up))
        check("uppercase sha blocked", blocked_with(out, "app#1", "non-full-sha"), True)

        branch, unpushed = w.local_only("app")
        rc, out, err = w.check_files(objective(rows),
                                     ret(CLOSED_IDS="app#1", MERGED_IDS="app#1@" + unpushed))
        check("direct_merged_not_on_base_blocked",
              (rc, blocked_with(out, "app#1", "merged-not-on-base"), term(out)),
              (1, True, "BLOCKED"))

        rc, out, err = w.check_files(objective(rows),
                                     ret(CLOSED_IDS="app#1", MERGED_IDS="app#1"))
        check("merged_ids_bare_id_blocked",
              (rc, blocked_with(out, "app#1", "merged-needs-sha")), (1, True))

        check("no gh needed for ancestry", w.gh_called(), False)


def test_wrong_field_for_mode():
    with tempfile.TemporaryDirectory() as tmp:
        w = World(tmp)
        sha = w.landed("lib")
        rows = [("app#1", "app", "-"), ("lib#2", "lib", "-")]
        rc, out, err = w.check_files(objective(rows),
                                     ret(CLOSED_IDS="lib#2", MERGED_IDS="lib#2@" + sha))
        check("wrong_field_for_mode_blocked",
              (rc, blocked_with(out, "lib#2", "wrong-field-for-mode"), term(out)),
              (1, True, "BLOCKED"))
        check("wrong_field_for_mode needs no gh", w.gh_called(), False)
        rc, out, err = w.check_files(objective(rows),
                                     ret(CLOSED_IDS="app#1", INTEGRATED_IDS="app#1@" + sha))
        check("integrated field needs completion integrated",
              blocked_with(out, "app#1", "wrong-field-for-mode"), True)


def test_after_pass_failed():
    with tempfile.TemporaryDirectory() as tmp:
        w = World(tmp)
        sha = w.landed("app")
        rows = [("app#1", "app", "-")]
        rc, out, err = w.check_files(
            objective(rows), ret(MERGED_IDS="app#1@" + sha, AFTER_PASS_FAILED="app#1 tag"))
        check("after_pass_failed_keeps_landed_open",
              (rc, status(out, "app#1"), term(out)), (0, ["OPEN", "after-pass-failed:tag"], "OK"))
        rc, out, err = w.check_files(
            objective(rows), ret(CLOSED_IDS="app#1", MERGED_IDS="app#1@" + sha,
                                 AFTER_PASS_FAILED="app#1 tag"))
        check("after_pass_failed_with_merged_is_open",
              (rc, status(out, "app#1")), (0, ["OPEN", "after-pass-failed:tag"]))
        # A failed required:false step is relayed as nothing at all: the unit closes.
        rc, out, err = w.check_files(
            objective(rows), ret(CLOSED_IDS="app#1", MERGED_IDS="app#1@" + sha,
                                 AFTER_PASS_FAILED="NONE",
                                 NOTE="notes step failed-optional"))
        check("after_pass_failed_optional_closes",
              (rc, status(out, "app#1")), (0, ["CLOSED", "merged-on-base"]))


def test_before_push():
    with tempfile.TemporaryDirectory() as tmp:
        rows = {"app": {}, "lib": {"merge_mode": "report-only",
                                   "human_checkpoints": "before-push"}}
        w = World(tmp, rows)
        branch, sha = w.local_only("lib")
        unit = [("lib#3", "lib", "-")]
        rc, out, err = w.check_files(
            objective(unit), ret(CLOSED_IDS="lib#3",
                                 APPROVAL_IDS="lib#3@%s@%s" % (branch, sha)))
        check("approval_ids_closes_before_push_unit",
              (rc, status(out, "lib#3"), term(out)),
              (0, ["CLOSED", "approval-branch-at-sha"], "OK"))

        rc, out, err = w.check_files(objective(unit), ret(CLOSED_IDS="lib#3"))
        check("before_push_bare_close_blocked",
              (rc, blocked_with(out, "lib#3", "closed-without-gate-field")), (1, True))

        # The branch moves after the gate: the recorded sha is no longer its tip.
        w.g(w.path["lib"], "checkout", "-q", branch)
        w.commit(w.path["lib"], "more.txt", "more")
        w.g(w.path["lib"], "checkout", "-q", "main")
        rc, out, err = w.check_files(
            objective(unit), ret(CLOSED_IDS="lib#3",
                                 APPROVAL_IDS="lib#3@%s@%s" % (branch, sha)))
        check("approval_ids_branch_moved_blocked",
              (rc, blocked_with(out, "lib#3", "approval-branch-moved")), (1, True))

        # Leg 1 cannot be returned twice.
        branch2, sha2 = w.local_only("lib", "second")
        sb = [("Awaiting approval", "lib#3@%s@%s" % (branch2, sha2))]
        rc, out, err = w.check_files(
            objective(unit, sb), ret(CLOSED_IDS="lib#3",
                                     APPROVAL_IDS="lib#3@%s@%s" % (branch2, sha2)))
        check("approval_ids_repeat_blocked",
              (rc, blocked_with(out, "lib#3", "approval-repeat")), (1, True))
        sb = [("Awaiting approval", "lib#3@%s@%s" % (branch, sha))]
        rc, out, err = w.check_files(
            objective(unit, sb), ret(CLOSED_IDS="lib#3",
                                     APPROVAL_IDS="lib#3@%s@%s" % (branch2, sha2)))
        check("a new sha is not a repeat", (rc, status(out, "lib#3")),
              (0, ["CLOSED", "approval-branch-at-sha"]))


def test_approved():
    with tempfile.TemporaryDirectory() as tmp:
        rows = {"app": {}, "lib": {"merge_mode": "report-only",
                                   "human_checkpoints": "before-push"}}
        w = World(tmp, rows)
        b1, s1 = w.local_only("lib", "one")
        b2, s2 = w.local_only("lib", "two")
        b3, s3 = w.local_only("lib", "three")
        p = subprocess.run([APPROVE, "lib#3", s1], cwd=w.path["lib"], env=w.env,
                           capture_output=True, text=True)
        check("fixture: approval written", p.returncode, 0)
        p = subprocess.run([APPROVE, "lib#9", s3], cwd=w.path["lib"], env=w.env,
                           capture_output=True, text=True)
        check("fixture: other id approved", p.returncode, 0)
        sb = [("Awaiting approval", "lib#3@%s@%s, lib#4@%s@%s, lib#5@%s@%s" % (
            b1, s1, b2, s2, b3, s3))]
        o = os.path.join(tmp, "o.md")
        write(o, objective([("lib#3", "lib", "-"), ("lib#4", "lib", "-"),
                            ("lib#5", "lib", "-")], sb))
        rc, out, err = w.run(["--approved", "--objective", o])
        # lib#3 has its own record; lib#4 has none; lib#5's sha is approved under lib#9 only.
        check("approved_lists_records", (rc, out), (0, ["lib#3 APPROVED " + s1, "OK"]))
        write(o, objective([("lib#3", "lib", "-")], [("Awaiting approval", "NONE")]))
        rc, out, err = w.run(["--approved", "--objective", o])
        check("approved with nothing awaiting", (rc, out), (0, ["OK"]))


def test_tagged():
    with tempfile.TemporaryDirectory() as tmp:
        w = World(tmp)
        sha = w.landed("app", "one")
        sha2 = w.landed("app", "two")
        w.tag("app", "v1.4.1", sha)
        rows = [("app#1", "app", "-")]
        rc, out, err = w.check_files(
            objective(rows), ret(CLOSED_IDS="app#1", MERGED_IDS="app#1@" + sha,
                                 TAGGED_IDS="app#1=v1.4.1@" + sha))
        check("tagged_ids_peel_ok", (rc, status(out, "app#1")),
              (0, ["CLOSED", "merged-on-base,tagged"]))
        rc, out, err = w.check_files(
            objective(rows), ret(CLOSED_IDS="app#1", MERGED_IDS="app#1@" + sha2,
                                 TAGGED_IDS="app#1=v1.4.1@" + sha2))
        check("tagged_ids_wrong_sha_blocked",
              (rc, blocked_with(out, "app#1", "tag-peel-mismatch")), (1, True))
        rc, out, err = w.check_files(
            objective(rows), ret(CLOSED_IDS="app#1", MERGED_IDS="app#1@" + sha,
                                 TAGGED_IDS="app#1=v9.9.9@" + sha))
        check("an absent tag is a mismatch",
              blocked_with(out, "app#1", "tag-peel-mismatch"), True)
        rc, out, err = w.check_files(
            objective(rows), ret(CLOSED_IDS="app#1", MERGED_IDS="app#1@" + sha2,
                                 TAGGED_IDS="app#1=v1.4.1@" + sha))
        check("tagged_sha_not_merged_sha_blocked",
              (rc, blocked_with(out, "app#1", "tag-sha-not-merged-sha")), (1, True))
        rc, out, err = w.check_files(
            objective(rows), ret(TAGGED_IDS="app#1=v1.4.1@" + sha))
        check("a tag with no merged sha anywhere",
              blocked_with(out, "app#1", "tag-without-merged-sha"), True)
        # The merged sha may come from an earlier cycle's scoreboard.
        rc, out, err = w.check_files(
            objective(rows, [("Merged", "app#1@" + sha)]),
            ret(TAGGED_IDS="app#1=v1.4.1@" + sha))
        check("tag against the scoreboard Merged line", (rc, status(out, "app#1")),
              (0, ["CLOSED", "tagged"]))


def test_park_and_closes():
    with tempfile.TemporaryDirectory() as tmp:
        w = World(tmp, {"app": {}, "lib": {"mode": "park"}})
        rc, out, err = w.check_files(objective([("lib#1", "lib", "-")]),
                                     ret(CLOSED_IDS="lib#1"))
        check("park_row_unit_blocked",
              (rc, blocked_with(out, "lib#1", "park-row"), term(out)), (1, True, "BLOCKED"))
    with tempfile.TemporaryDirectory() as tmp:
        w = World(tmp)
        rc, out, err = w.check_files(objective([("app#1", "app", "-")]),
                                     ret(CLOSED_IDS="app#1"))
        check("no_pr_close_ok_direct", (rc, status(out, "app#1"), term(out)),
              (0, ["CLOSED", "no-pr"], "OK"))
        rc, out, err = w.check_files(objective([("app#1", "app", "-")]),
                                     ret(REMAINING_IDS="app#1", PARKED_IDS="NONE"))
        check("remaining ids print no line", (rc, out), (0, ["OK"]))
    with tempfile.TemporaryDirectory() as tmp:
        w = World(tmp, {"app": {}, "lib": {"merge_mode": "label-handoff"}})
        rc, out, err = w.check_files(objective([("lib#1", "lib", "-")]),
                                     ret(CLOSED_IDS="lib#1"))
        check("no_pr_close_ok_label_handoff", (rc, status(out, "lib#1")),
              (0, ["CLOSED", "no-pr"]))


def test_integrated():
    with tempfile.TemporaryDirectory() as tmp:
        w = World(tmp)
        repo = w.path["app"]
        w.g(repo, "checkout", "-q", "-b", "epic")
        sha = w.commit(repo, "unit.txt", "unit")
        w.g(repo, "push", "-q", "origin", "epic")
        w.g(repo, "checkout", "-q", "main")
        rows = [("app#1", "app", "-")]
        obj = objective(rows, extra="Base branch: origin/epic\ncompletion: integrated")
        rc, out, err = w.check_files(obj, ret(CLOSED_IDS="app#1",
                                              INTEGRATED_IDS="app#1@" + sha))
        check("integrated_close_ok", (rc, status(out, "app#1"), term(out)),
              (0, ["CLOSED", "integrated"], "OK"))
        obj = objective(rows, extra="Base branch: origin/epic\ncompletion: integrated")
        rc, out, err = w.check_files(obj, ret(CLOSED_IDS="app#1",
                                              INTEGRATED_IDS="app#1@" + FULL))
        check("integrated sha not in the epic branch",
              blocked_with(out, "app#1", "integrated-not-on-base"), True)
        # The epic branch is the scope base: a MERGED sha there is on base for that unit.
        rc, out, err = w.check_files(obj, ret(CLOSED_IDS="app#1",
                                              MERGED_IDS="app#1@" + sha))
        check("epic branch counts as the scope base", status(out, "app#1"),
              ["CLOSED", "merged-on-base"])


def test_legacy_and_flat():
    with tempfile.TemporaryDirectory() as tmp:
        w = World(tmp, flat=True)
        sha = w.landed("app")
        old = "| ID | What it is | Contended resource |"
        obj = objective([("42", "the thing", "src/")], header=old)
        rc, out, err = w.check_files(obj, ret(CLOSED_IDS="42", MERGED_IDS="42@" + sha))
        check("legacy_objective_columns", (rc, status(out, "42"), term(out)),
              (0, ["CLOSED", "merged-on-base"], "OK"))
        w.tag("app", "v1.4.2", sha)
        obj = objective([("42", "the thing", "src/")],
                        [("Merged/readied", "42@" + sha)], header=old)
        rc, out, err = w.check_files(obj, ret(TAGGED_IDS="42=v1.4.2@" + sha))
        check("legacy_merged_readied_line_read", (rc, status(out, "42")),
              (0, ["CLOSED", "tagged"]))
        # No table at all: the scoreboard's Units issued is the unit list.
        obj = objective(None, [("Units issued", "7, 8")])
        rc, out, err = w.check_files(obj, ret(CLOSED_IDS="7, 9"))
        check("epic_argument_without_table",
              (rc, status(out, "7"), blocked_with(out, "9", "not-issued")),
              (1, ["CLOSED", "no-pr"], True))
        # A unit added this return is not in the table yet.
        obj = objective([("42", "the thing", "src/")], header=old)
        rc, out, err = w.check_files(
            obj, ret(UNITS_ADDED="43 — found while testing", CLOSED_IDS="43"))
        check("units_added_same_return_ok", (rc, status(out, "43")),
              (0, ["CLOSED", "no-pr"]))
        rc, out, err = w.check_files(
            obj, ret(UNITS_CHANGED="42 -> 42a, 42b — split", CLOSED_IDS="42a"))
        check("units_changed children are issued", (rc, status(out, "42a")),
              (0, ["CLOSED", "no-pr"]))


def test_units_changed_child_inherits_after():
    with tempfile.TemporaryDirectory() as tmp:
        w = World(tmp, {"app": {"tag_by": "human", "tag_format": "v{version}"}, "lib": {}})
        sha = w.landed("app", "pred")
        rows = [("app#1", "app", "-"), ("lib#2", "lib", "app#1 (landed, tagged)")]
        sb = [("Merged", "app#1@" + sha), ("Closed", "app#1")]
        split = ret(UNITS_CHANGED="lib#2 -> lib#3, lib#4 \u2014 split", CLOSED_IDS="lib#3")
        rc, out, err = w.check_files(objective(rows, sb), split)
        check("units_changed_child_inherits_after_blocked",
              (rc, blocked_with(out, "lib#3", "predecessor-not-tagged")), (1, True))
        w.tag("app", "v1.4.1", sha)
        rc, out, err = w.check_files(objective(rows, sb), split)
        check("units_changed_child_inherits_after_passes_once_tagged",
              (rc, status(out, "lib#3")), (0, ["CLOSED", "no-pr"]))


def test_exit_3():
    with tempfile.TemporaryDirectory() as tmp:
        w = World(tmp)
        rc, out, err = w.check_files(objective([("5", "app", "-")]), ret(CLOSED_IDS="5"))
        check("bare_id_in_family_is_exit_3", (rc, out, err.startswith("stu-run-check: id-form")),
              (3, [], True))
        rc, out, err = w.check_files(objective([("app#1", "app", "-")]),
                                     ret(REMAINING_IDS="5"))
        check("bare_remaining_id_in_family_is_exit_3",
              (rc, out, err.startswith("stu-run-check: id-form")), (3, [], True))
        rc, out, err = w.check_files(objective([("lib#2", "app", "-")]),
                                     ret(CLOSED_IDS="lib#2"))
        check("repo prefix differs from the repo column", (rc, out), (3, []))
        rc, out, err = w.check_files(objective([("app#1", "app", "-")]),
                                     ret(CLOSED_IDS="9"))
        check("a bare returned id in a family", (rc, out), (3, []))
        rc, out, err = w.check_files(objective([("nope#1", "nope", "-")]),
                                     ret(CLOSED_IDS="nope#1"))
        check("unknown repo", (rc, out), (3, []))

        o = os.path.join(tmp, "o.md")
        r = os.path.join(tmp, "r.txt")
        write(o, objective([("app#1", "app", "-")]))
        write(r, ret(CLOSED_IDS="app#1"))
        rc, out, err = w.run(["--objective", o, "--return", os.path.join(tmp, "missing")])
        check("exit_3_prints_no_terminal_line",
              (rc, out, re.match(r"stu-run-check: [a-z-]+: .+", err.strip()) is not None,
               len(err.strip().splitlines())), (3, [], True, 1))
        rc, out, err = w.run(["--objective", os.path.join(tmp, "missing"), "--return", r])
        check("missing objective", (rc, out), (3, []))
        rc, out, err = w.run(["--objective", o])
        check("missing --return", (rc, out), (3, []))
        rc, out, err = w.run(["--objective", o, "--return", r, "--bogus"])
        check("bad flag is exit 3", (rc, out), (3, []))
        write(o, "## Units\n\n| ID | Repo |\n|---|---|\n| only-one-cell |\n")
        rc, out, err = w.run(["--objective", o, "--return", r])
        check("unparseable table", (rc, out, "table" in err), (3, [], True))
        write(o, objective([("app#1", "app", "after-ish nonsense")]))
        rc, out, err = w.run(["--objective", o, "--return", r])
        check("unparseable after cell", (rc, out), (3, []))
        rc, out, err = w.run(["--approved", "--objective", os.path.join(tmp, "missing")])
        check("--approved with no objective file", (rc, out), (3, []))
        # A flat config run from outside its repo cannot be judged.
    with tempfile.TemporaryDirectory() as tmp:
        w = World(tmp, flat=True)
        o = os.path.join(tmp, "o.md")
        r = os.path.join(tmp, "r.txt")
        write(o, objective([("1", "the thing", "x")], header="| ID | What | Res |"))
        write(r, ret(CLOSED_IDS="1"))
        rc, out, err = w.run(["--objective", o, "--return", r], cwd=tmp)
        check("flat config outside the repo", (rc, out), (3, []))


def pr_at(w, pr, **kw):
    """Serve `pr view <pr>` with the given doc fields (sha first)."""
    return {"pr view %d" % pr: pr_doc(pr=pr, **kw)}


def test_passed_and_ready():
    with tempfile.TemporaryDirectory() as tmp:
        w = World(tmp)
        sha = "b" * 40
        unit = [("lib#2", "lib", "-")]
        entry = "lib#2@acme/lib#5@" + sha
        w.set_gh(pr_at(w, 5, sha=sha))
        rc, out, err = w.check_files(objective(unit), ret(CLOSED_IDS="lib#2", PASSED_IDS=entry))
        check("report_only_passed_closes", (rc, status(out, "lib#2"), term(out)),
              (0, ["CLOSED", "passed:acme/lib#5@" + sha[:12]], "OK"))
        w.set_gh(pr_at(w, 5, sha="c" * 40))
        rc, out, err = w.check_files(objective(unit), ret(CLOSED_IDS="lib#2", PASSED_IDS=entry))
        check("report_only_passed_wrong_sha_blocked",
              (rc, blocked_with(out, "lib#2", "passed-wrong-sha"), term(out)),
              (1, True, "BLOCKED"))
        w.set_gh(pr_at(w, 5, sha=sha, state="CLOSED"))
        rc, out, err = w.check_files(objective(unit), ret(PASSED_IDS=entry))
        check("a closed unmerged PR is not a pass",
              blocked_with(out, "lib#2", "passed-pr-closed"), True)
        w.set_gh(pr_at(w, 5, sha=sha, slug="acme/app"))
        rc, out, err = w.check_files(objective(unit), ret(PASSED_IDS=entry))
        check("pr-state slug differs from the entry",
              blocked_with(out, "lib#2", "passed-other-slug"), True)
        w.set_gh(pr_at(w, 5, sha=sha))
        rc, out, err = w.check_files(
            objective(unit), ret(CLOSED_IDS="lib#2", PASSED_IDS="lib#2@acme/app#5@" + sha))
        check("passed_ids_other_slug_blocked",
              (rc, blocked_with(out, "lib#2", "passed-other-slug")), (1, True))
        rc, out, err = w.check_files(objective(unit), ret(PASSED_IDS="lib#2"))
        check("a bare PASSED_IDS id", blocked_with(out, "lib#2", "passed-needs-pr-and-sha"), True)
        rc, out, err = w.check_files(objective(unit),
                                     ret(PASSED_IDS="lib#2@acme/lib#5@" + sha[:9]))
        check("a short PASSED_IDS sha", blocked_with(out, "lib#2", "non-full-sha"), True)
        w.set_gh({})
        rc, out, err = w.check_files(objective(unit), ret(PASSED_IDS=entry))
        check("a forge failure is exit 3", (rc, out), (3, []))
    # label-handoff under completion: ready
    with tempfile.TemporaryDirectory() as tmp:
        w = World(tmp, {"app": {}, "lib": {"merge_mode": "label-handoff",
                                           "ci_merge_label": "go"}})
        sha = "d" * 40
        unit = [("lib#2", "lib", "-")]
        entry = "lib#2@acme/lib#5@" + sha
        obj = objective(unit, extra="completion: ready")
        w.set_gh(pr_at(w, 5, sha=sha, labels=("go",)))
        rc, out, err = w.check_files(obj, ret(CLOSED_IDS="lib#2", READY_IDS=entry))
        check("ready_ids_closes", (rc, status(out, "lib#2"), term(out)),
              (0, ["CLOSED", "ready-labelled:acme/lib#5,auto-merge-off"], "OK"))
        w.set_gh(pr_at(w, 5, sha=sha, labels=("other",)))
        rc, out, err = w.check_files(obj, ret(CLOSED_IDS="lib#2", READY_IDS=entry))
        check("ready_ids_label_absent_blocked",
              (rc, blocked_with(out, "lib#2", "ready-label-absent")), (1, True))
        rc, out, err = w.check_files(obj, ret(CLOSED_IDS="lib#2", READY_IDS="lib#2"))
        check("ready_ids_bare_id_blocked",
              (rc, blocked_with(out, "lib#2", "ready-needs-pr-and-sha")), (1, True))
        rc, out, err = w.check_files(obj, ret(READY_IDS="lib#2@acme/lib#5"))
        check("ready entry without sha", blocked_with(out, "lib#2", "ready-needs-pr-and-sha"),
              True)
        w.set_gh(pr_at(w, 5, sha="e" * 40, labels=("go",)))
        rc, out, err = w.check_files(obj, ret(READY_IDS=entry))
        check("ready head is not the gated sha", blocked_with(out, "lib#2", "ready-wrong-sha"),
              True)
        w.set_gh(pr_at(w, 5, sha=sha, labels=("go",)))
        rc, out, err = w.check_files(objective(unit), ret(READY_IDS=entry))
        check("READY_IDS is the wrong field under completion merged",
              blocked_with(out, "lib#2", "wrong-field-for-mode"), True)
    with tempfile.TemporaryDirectory() as tmp:
        w = World(tmp, {"app": {}, "lib": {"merge_mode": "label-handoff", "ci_merge_label": None}})
        sha = "d" * 40
        w.set_gh(pr_at(w, 5, sha=sha, labels=("go",)))
        rc, out, err = w.check_files(objective([("lib#2", "lib", "-")], extra="completion: ready"),
                                     ret(READY_IDS="lib#2@acme/lib#5@" + sha))
        check("an empty merge label is exit 3", (rc, out, "ci_merge_label" in err), (3, [], True))
        rc, out, err = w.check_files(objective([("lib#2", "lib", "-")]), ret(CLOSED_IDS="lib#2"))
        check("no_pr_close_ok_label_handoff (no label needed)", (rc, status(out, "lib#2")),
              (0, ["CLOSED", "no-pr"]))


def test_before_push_leg2():
    with tempfile.TemporaryDirectory() as tmp:
        rows = {"app": {}, "lib": {"merge_mode": "report-only",
                                   "human_checkpoints": "before-push"}}
        w = World(tmp, rows)
        branch, sha = w.local_only("lib")
        unit = [("lib#3", "lib", "-")]
        entry = "lib#3@acme/lib#6@" + sha
        w.set_gh(pr_at(w, 6, sha=sha))
        rc, out, err = w.check_files(objective(unit), ret(CLOSED_IDS="lib#3", PASSED_IDS=entry))
        check("before_push_leg2_unapproved_blocked",
              (rc, blocked_with(out, "lib#3", "leg2-unapproved"), term(out)),
              (1, True, "BLOCKED"))
        p = subprocess.run([APPROVE, "lib#3", sha], cwd=w.path["lib"], env=w.env,
                           capture_output=True, text=True)
        check("fixture: approval written", p.returncode, 0)
        rc, out, err = w.check_files(objective(unit), ret(CLOSED_IDS="lib#3", PASSED_IDS=entry))
        check("before_push_leg2_approved_closes", (rc, status(out, "lib#3"), term(out)),
              (0, ["CLOSED", "passed:acme/lib#6@" + sha[:12]], "OK"))
        # An approval for another id at the same sha does not count.
        rc, out, err = w.check_files(
            objective([("lib#4", "lib", "-")]),
            ret(CLOSED_IDS="lib#4", PASSED_IDS="lib#4@acme/lib#6@" + sha))
        check("leg 2 needs the unit's own record", blocked_with(out, "lib#4", "leg2-unapproved"),
              True)


def test_before_push_wrong_fields():
    # A before-push row closes only on APPROVAL_IDS (leg 1) or PASSED_IDS (leg 2); MERGED_IDS
    # and READY_IDS are the wrong field whatever the merge mode.
    with tempfile.TemporaryDirectory() as tmp:
        w = World(tmp, {"app": {}, "lib": {"merge_mode": "direct",
                                           "human_checkpoints": "before-push"}})
        sha = w.landed("lib")
        unit = [("lib#3", "lib", "-")]
        rc, out, err = w.check_files(objective(unit), ret(CLOSED_IDS="lib#3",
                                                           MERGED_IDS="lib#3@" + sha))
        check("before_push_merged_ids_blocked",
              (rc, blocked_with(out, "lib#3", "wrong-field-for-mode"), term(out)),
              (1, True, "BLOCKED"))
    with tempfile.TemporaryDirectory() as tmp:
        w = World(tmp, {"app": {}, "lib": {"merge_mode": "label-handoff", "ci_merge_label": "go",
                                           "human_checkpoints": "before-push"}})
        sha = "d" * 40
        w.set_gh(pr_at(w, 5, sha=sha, labels=("go",)))
        rc, out, err = w.check_files(
            objective([("lib#2", "lib", "-")], extra="completion: ready"),
            ret(CLOSED_IDS="lib#2", READY_IDS="lib#2@acme/lib#5@" + sha))
        check("before_push_ready_ids_blocked",
              (rc, blocked_with(out, "lib#2", "wrong-field-for-mode"), term(out)),
              (1, True, "BLOCKED"))


def pr_at_slug(pr, head, slug, state, merge=None):
    return {"pr view %d" % pr: pr_doc(head, slug=slug, pr=pr, state=state, merge=merge)}


def test_waiting_and_after():
    pred_head = "b" * 40
    rows = [("lib#4", "lib", "-"), ("app#1", "app", "lib#4 (landed)")]
    sb = [("Passed", "lib#4@acme/lib#9@" + pred_head), ("Closed", "lib#4")]
    with tempfile.TemporaryDirectory() as tmp:
        w = World(tmp)
        w.set_gh(pr_at_slug(9, pred_head, "acme/lib", "OPEN"))
        obj = objective(rows, sb)
        rc, out, err = w.check_files(obj, ret(WAITING_IDS="app#1 needs: merge acme/lib#9"))
        check("waiting_valid", (rc, status(out, "app#1"), term(out)),
              (0, ["WAITING", "needs: merge acme/lib#9"], "OK"))
        rc, out, err = w.check_files(
            objective([("lib#4", "lib", "-"), ("app#1", "app", "-")], sb),
            ret(WAITING_IDS="app#1 needs: merge acme/lib#9"))
        check("waiting_without_after_blocked",
              (rc, blocked_with(out, "app#1", "waiting-without-after")), (1, True))
        rc, out, err = w.check_files(objective(rows, [("Passed", "lib#4@acme/lib#9@" + pred_head)]),
                                     ret(WAITING_IDS="app#1 needs: merge acme/lib#9"))
        check("a predecessor that is not closed", blocked_with(
            out, "app#1", "waiting-predecessor-not-closed"), True)
        rc, out, err = w.check_files(objective(rows, [("Passed", "lib#4@acme/lib#9@" + pred_head)]),
                                     ret(CLOSED_IDS="lib#4",
                                         WAITING_IDS="app#1 needs: merge acme/lib#9"))
        check("a predecessor closed in this return", status(out, "app#1")[0], "WAITING")
        rc, out, err = w.check_files(obj, ret(WAITING_IDS="app#1 reason: merge acme/lib#9"))
        check("a malformed waiting entry", blocked_with(out, "app#1", "malformed-entry"), True)
        # The predecessor has not landed: the dependent may not close.
        rc, out, err = w.check_files(obj, ret(CLOSED_IDS="app#1"))
        check("dependent_closed_before_predecessor_landed_blocked",
              (rc, blocked_with(out, "app#1", "predecessor-not-landed")), (1, True))
        # Now it lands: the dependent closes and may no longer wait.
        m = w.landed("lib", "merge9")
        w.set_gh(pr_at_slug(9, pred_head, "acme/lib", "MERGED", m))
        rc, out, err = w.check_files(obj, ret(WAITING_IDS="app#1 needs: merge acme/lib#9"))
        check("waiting_predecessor_landed_blocked",
              (rc, blocked_with(out, "app#1", "waiting-predecessor-landed")), (1, True))
        rc, out, err = w.check_files(obj, ret(CLOSED_IDS="app#1"))
        check("dependent closes once the predecessor landed", (rc, status(out, "app#1")),
              (0, ["CLOSED", "no-pr"]))
        # The PR merged with a head other than the gated sha.
        w.set_gh(pr_at_slug(9, "f" * 40, "acme/lib", "MERGED", m))
        rc, out, err = w.check_files(obj, ret(CLOSED_IDS="app#1"))
        check("predecessor_passed_moved_head_blocked",
              (rc, blocked_with(out, "app#1", "predecessor-moved-head")), (1, True))
        rc, out, err = w.check_files(obj, ret(MOVED_IDS="app#1@" + "9" * 40))
        check("a moved unit is held to the same predecessor test",
              blocked_with(out, "app#1", "predecessor-moved-head"), True)
        # Nothing recorded for the predecessor at all.
        rc, out, err = w.check_files(objective(rows, [("Closed", "lib#4")]),
                                     ret(CLOSED_IDS="app#1"))
        check("a predecessor with no evidence", blocked_with(
            out, "app#1", "predecessor-unverified"), True)

    # Merged: cycles, squash merges and bare entries (direct predecessor in app).
    with tempfile.TemporaryDirectory() as tmp:
        w = World(tmp)
        sha = w.landed("app", "pred")
        rows = [("app#1", "app", "-"), ("lib#2", "lib", "app#1 (landed)")]
        rc, out, err = w.check_files(
            objective(rows, [("Merged", "app#1@" + sha)]), ret(CLOSED_IDS="lib#2"))
        check("predecessor_from_earlier_cycle_scoreboard", (rc, status(out, "lib#2"), term(out)),
              (0, ["CLOSED", "no-pr"], "OK"))
        branch, unpushed = w.local_only("app", "side")
        rc, out, err = w.check_files(
            objective(rows, [("Merged", "app#1@" + unpushed)]), ret(CLOSED_IDS="lib#2"))
        check("a scoreboard Merged sha that is not on base", blocked_with(
            out, "lib#2", "predecessor-not-landed"), True)
        rc, out, err = w.check_files(
            objective(rows), ret(CLOSED_IDS="app#1, lib#2", MERGED_IDS="app#1"))
        check("predecessor_in_after_without_sha_blocked",
              (rc, blocked_with(out, "lib#2", "predecessor-unverified"),
               blocked_with(out, "app#1", "merged-needs-sha")), (1, True, True))
        # A squash merge: the landing commit is on base though the branch head is not.
        repo = w.path["app"]
        w.g(repo, "checkout", "-q", "-b", "feat-sq")
        w.commit(repo, "sq1.txt", "sq1")
        w.commit(repo, "sq2.txt", "sq2")
        w.g(repo, "checkout", "-q", "main")
        w.g(repo, "merge", "--squash", "feat-sq")
        w.g(repo, "commit", "-q", "-m", "squashed")
        squash = w.g(repo, "rev-parse", "HEAD")
        w.g(repo, "push", "-q", "origin", "main")
        rc, out, err = w.check_files(
            objective(rows), ret(CLOSED_IDS="app#1, lib#2", MERGED_IDS="app#1@" + squash))
        check("predecessor_direct_squash_landed",
              (rc, status(out, "app#1"), status(out, "lib#2")),
              (0, ["CLOSED", "merged-on-base"], ["CLOSED", "no-pr"]))
        check("squash ancestry needs no gh", w.gh_called(), False)

    # (landed, tagged): the tag by a human, and by stu.
    for by in ("human", "stu"):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp, {"app": {"tag_by": by, "tag_format": "v{version}"}, "lib": {}})
            sha = w.landed("app", "pred")
            rows = [("app#1", "app", "-"), ("lib#2", "lib", "app#1 (landed, tagged)")]
            sb = [("Merged", "app#1@" + sha), ("Closed", "app#1")]
            rc, out, err = w.check_files(objective(rows, sb), ret(CLOSED_IDS="lib#2"))
            check("dependent_closed_tag_missing_blocked (%s)" % by,
                  (rc, blocked_with(out, "lib#2", "predecessor-not-tagged")), (1, True))
            waiting = ret(WAITING_IDS="lib#2 needs: tag app at " + sha)
            rc, out, err = w.check_files(objective(rows, sb), waiting)
            if by == "human":
                check("human_tag_waiting_valid", (rc, status(out, "lib#2"), term(out)),
                      (0, ["WAITING", "needs: tag app at " + sha], "OK"))
            w.tag("app", "v1.4.1", sha)
            if by == "stu":
                sb.append(("Tagged", "app#1=v1.4.1@" + sha))
            rc, out, err = w.check_files(objective(rows, sb), ret(CLOSED_IDS="lib#2"))
            check("dependent closes once tagged (%s)" % by, (rc, status(out, "lib#2")),
                  (0, ["CLOSED", "no-pr"]))
            rc, out, err = w.check_files(objective(rows, sb), waiting)
            check("a tagged predecessor is not waited on (%s)" % by,
                  blocked_with(out, "lib#2", "waiting-predecessor-landed"), True)
    with tempfile.TemporaryDirectory() as tmp:
        w = World(tmp)
        sha = w.landed("app", "pred")
        rows = [("app#1", "app", "-"), ("lib#2", "lib", "app#1 (landed, tagged)")]
        rc, out, err = w.check_files(objective(rows, [("Merged", "app#1@" + sha)]),
                                     ret(CLOSED_IDS="lib#2"))
        check("tagged needed but the row has no tag_by", (rc, out), (3, []))


def test_close_paths():
    sha = "a1" * 20
    cases = [
        ("direct-push", {}, "", "MERGED", "PASSED"),
        ("label-handoff", {"ci_merge_label": "go"}, "completion: ready", "READY", "MERGED"),
        ("report-only", {}, "", "PASSED", "MERGED"),
    ]
    for mode, over, extra, good, bad in cases:
        with tempfile.TemporaryDirectory() as tmp:
            row = {"merge_mode": mode}
            row.update(over)
            w = World(tmp, {"lib": {}, "app": row})
            head = w.landed("app", "close-" + mode)
            w.set_gh(pr_at_slug(5, head, "acme/app", "OPEN", None))
            if mode == "label-handoff":
                w.set_gh({"pr view 5": pr_doc(head, slug="acme/app", labels=("go",))})
            obj = objective([("app#1", "app", "-")], extra=extra)

            def entry(field):
                if field == "MERGED":
                    return "MERGED_IDS", "app#1@" + head
                return field + "_IDS", "app#1@acme/app#5@" + head
            k, v = entry(good)
            rc, out, err = w.check_files(obj, ret(CLOSED_IDS="app#1", **{k: v}))
            check("close_paths_direct_push_label_handoff_pr_only %s closes" % mode,
                  (rc, status(out, "app#1")[0]), (0, "CLOSED"))
            k, v = entry(bad)
            rc, out, err = w.check_files(obj, ret(CLOSED_IDS="app#1", **{k: v}))
            check("close_paths_direct_push_label_handoff_pr_only %s rejects %s" % (mode, bad),
                  (rc, blocked_with(out, "app#1", "wrong-field-for-mode")), (1, True))


def test_park_anywhere():
    with tempfile.TemporaryDirectory() as tmp:
        w = World(tmp, {"app": {}, "lib": {"mode": "park"}})
        unit = [("app#1", "app", "-"), ("lib#1", "lib", "-")]
        for field, val in (("REMAINING_IDS", "lib#1"), ("PARKED_IDS", "lib#1"),
                           ("UNITS_ADDED", "lib#7 — found"),
                           ("UNITS_CHANGED", "app#1 -> lib#8 — split")):
            rc, out, err = w.check_files(objective(unit), ret(**{field: val}))
            ident = val.split()[0] if field == "UNITS_ADDED" else \
                ("lib#8" if field == "UNITS_CHANGED" else "lib#1")
            check("park_row_unit_blocked (only in %s)" % field,
                  (rc, blocked_with(out, ident, "park-row"), term(out)), (1, True, "BLOCKED"))
        rc, out, err = w.check_files(objective(unit), ret(REMAINING_IDS="app#1"))
        check("a non-park remaining id stays silent", (rc, out), (0, ["OK"]))
        # The unit table never widens the issued set.
        rc, out, err = w.check_files(objective(unit, issued=False), ret(CLOSED_IDS="app#1"))
        check("the table does not issue units", (rc, blocked_with(out, "app#1", "not-issued")),
              (1, True))


def test_closed_but_remaining():
    with tempfile.TemporaryDirectory() as tmp:
        w = World(tmp)
        sha = "b" * 40
        units = [("lib#2", "lib", "-"), ("lib#3", "lib", "-")]
        entry = "lib#2@acme/lib#5@" + sha
        w.set_gh(pr_at(w, 5, sha=sha))
        rc, out, err = w.check_files(objective(units),
                                     ret(CLOSED_IDS="NONE", REMAINING_IDS="lib#2",
                                         PASSED_IDS=entry))
        check("passed_and_remaining_blocked",
              (rc, blocked_with(out, "lib#2", "closed-but-remaining"), term(out)),
              (1, True, "BLOCKED"))
        rc, out, err = w.check_files(objective(units),
                                     ret(CLOSED_IDS="lib#2", PARKED_IDS="lib#2",
                                         PASSED_IDS=entry))
        check("passed_and_parked_blocked",
              (rc, blocked_with(out, "lib#2", "closed-but-remaining")), (1, True))
        rc, out, err = w.check_files(objective(units),
                                     ret(CLOSED_IDS="lib#2", REMAINING_IDS="NONE",
                                         PASSED_IDS=entry))
        check("passed_and_closed_accepted", (rc, status(out, "lib#2"), term(out)),
              (0, ["CLOSED", "passed:acme/lib#5@" + sha[:12]], "OK"))
        rc, out, err = w.check_files(objective(units),
                                     ret(CLOSED_IDS="lib#2", REMAINING_IDS="lib#3",
                                         PASSED_IDS=entry))
        check("an unrelated remaining id beside a passed, closed one",
              (rc, status(out, "lib#2"), status(out, "lib#3"), term(out)),
              (0, ["CLOSED", "passed:acme/lib#5@" + sha[:12]], None, "OK"))
    with tempfile.TemporaryDirectory() as tmp:
        w = World(tmp)
        sha = w.landed("app")
        rows = [("app#1", "app", "-")]
        rc, out, err = w.check_files(objective(rows),
                                     ret(REMAINING_IDS="app#1", MERGED_IDS="app#1@" + sha))
        check("merged_and_remaining_blocked (direct row)",
              (rc, blocked_with(out, "app#1", "closed-but-remaining")), (1, True))
        # A failed after-pass step keeps a landed unit outstanding: remaining is right there.
        rc, out, err = w.check_files(objective(rows),
                                     ret(REMAINING_IDS="app#1", MERGED_IDS="app#1@" + sha,
                                         AFTER_PASS_FAILED="app#1 tag"))
        check("after_pass_failed_may_stay_remaining",
              (rc, status(out, "app#1")), (0, ["OPEN", "after-pass-failed:tag"]))
        # ...but never a CLOSED_IDS entry: a unit with a failed after-pass step is not closed.
        rc, out, err = w.check_files(objective(rows),
                                     ret(CLOSED_IDS="app#1", REMAINING_IDS="app#1",
                                         MERGED_IDS="app#1@" + sha,
                                         AFTER_PASS_FAILED="app#1 tag"))
        check("after_pass_failed_does_not_excuse_closed_and_remaining",
              (rc, blocked_with(out, "app#1", "closed-but-remaining")), (1, True))
    # before-push leg 1: APPROVAL_IDS closes the unit.
    with tempfile.TemporaryDirectory() as tmp:
        w = World(tmp, {"app": {}, "lib": {"merge_mode": "report-only",
                                           "human_checkpoints": "before-push"}})
        branch, sha = w.local_only("lib")
        unit = [("lib#3", "lib", "-")]
        rc, out, err = w.check_files(
            objective(unit), ret(REMAINING_IDS="lib#3",
                                 APPROVAL_IDS="lib#3@%s@%s" % (branch, sha)))
        check("approval_and_remaining_blocked",
              (rc, blocked_with(out, "lib#3", "closed-but-remaining")), (1, True))
    # completion: integrated: INTEGRATED_IDS closes; INTEGRATING_IDS counts as outstanding.
    with tempfile.TemporaryDirectory() as tmp:
        w = World(tmp)
        repo = w.path["app"]
        w.g(repo, "checkout", "-q", "-b", "epic")
        sha = w.commit(repo, "unit.txt", "unit")
        w.g(repo, "push", "-q", "origin", "epic")
        w.g(repo, "checkout", "-q", "main")
        rows = [("app#1", "app", "-")]
        obj = objective(rows, extra="Base branch: origin/epic\ncompletion: integrated")
        for name, extra in (("integrated_and_remaining_blocked",
                             {"REMAINING_IDS": "app#1"}),
                            ("integrated_and_integrating_blocked",
                             {"INTEGRATING_IDS": "app#1"}),
                            ("closed_integrated_and_integrating_blocked",
                             {"CLOSED_IDS": "app#1", "INTEGRATING_IDS": "app#1"})):
            rc, out, err = w.check_files(obj, ret(INTEGRATED_IDS="app#1@" + sha, **extra))
            check(name, (rc, blocked_with(out, "app#1", "closed-but-remaining")), (1, True))
        rc, out, err = w.check_files(obj, ret(CLOSED_IDS="app#1", INTEGRATED_IDS="app#1@" + sha,
                                              REMAINING_IDS="NONE", INTEGRATING_IDS="NONE"))
        check("integrated_and_closed_accepted", (rc, status(out, "app#1")),
              (0, ["CLOSED", "integrated"]))
        rc, out, err = w.check_files(obj, ret(CLOSED_IDS="NONE", INTEGRATING_IDS="app#1",
                                              REMAINING_IDS="app#1"))
        check("integrating_and_remaining_alone_is_silent", (rc, out), (0, ["OK"]))
    # label-handoff: READY_IDS closes under completion: ready, not under merged.
    with tempfile.TemporaryDirectory() as tmp:
        w = World(tmp, {"app": {}, "lib": {"merge_mode": "label-handoff",
                                           "ci_merge_label": "go"}})
        sha = "d" * 40
        unit = [("lib#2", "lib", "-")]
        entry = "lib#2@acme/lib#5@" + sha
        w.set_gh(pr_at(w, 5, sha=sha, labels=("go",)))
        rc, out, err = w.check_files(objective(unit, extra="completion: ready"),
                                     ret(REMAINING_IDS="lib#2", READY_IDS=entry))
        check("ready_and_remaining_blocked_under_ready",
              (rc, blocked_with(out, "lib#2", "closed-but-remaining")), (1, True))
        # Under merged READY_IDS is not the closing field: the checker already blocks it as
        # wrong-field-for-mode, and REMAINING_IDS adds nothing (the output is the same with
        # and without it).
        rc, out, err = w.check_files(objective(unit), ret(REMAINING_IDS="lib#2", READY_IDS=entry))
        rc0, out0, err0 = w.check_files(objective(unit), ret(READY_IDS=entry))
        check("ready_and_remaining_under_merged_is_only_wrong_field",
              (rc, blocked_with(out, "lib#2", "wrong-field-for-mode"),
               any("closed-but-remaining" in l for l in out), out == out0),
              (1, True, False, True))


for t in (test_closing_by_ancestry, test_wrong_field_for_mode, test_after_pass_failed,
          test_before_push, test_approved, test_tagged, test_park_and_closes,
          test_integrated, test_legacy_and_flat, test_units_changed_child_inherits_after, test_exit_3,
          test_passed_and_ready, test_before_push_leg2, test_before_push_wrong_fields,
          test_waiting_and_after,
          test_close_paths, test_park_anywhere, test_closed_but_remaining):
    t()

if FAILURES:
    print("FAIL: %d of %d checks" % (len(FAILURES), COUNT[0]))
    for f in FAILURES:
        print("  " + f)
    sys.exit(1)
print("ok: %d checks" % COUNT[0])
