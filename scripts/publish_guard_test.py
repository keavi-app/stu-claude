#!/usr/bin/env python3
"""Regression suite for the publish guard: the git pre-push hook (stu_pre_push.py), the
tool-call hook (hooks/publish-guard.sh -> publish_guard.py) and stu-approve.

Real git repos with bare remotes under a temp dir, HOME pointed at a temp dir, nothing
touches the network. Pre-push cases drive a real `git push` with the hook installed;
tool-hook cases pipe a payload on stdin.

Run: python3 scripts/publish_guard_test.py
"""
import contextlib
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import stu_env  # noqa: E402

PRE_PUSH = os.path.join(ROOT, "bin", "stu-pre-push")
APPROVE = os.path.join(ROOT, "bin", "stu-approve")
LAUNCHER = os.path.join(ROOT, "hooks", "publish-guard.sh")
HOOKS_JSON = os.path.join(ROOT, "hooks", "hooks.json")
FAILURES = []
COUNT = [0]
CURRENT = [""]
RED = []  # test names with at least one failed check
PREFIX = "stu publish guard: "


def check(name, got, want):
    COUNT[0] += 1
    if got != want:
        FAILURES.append("%s / %s: got %r, want %r" % (CURRENT[0], name, got, want))


def rp(p):
    return os.path.realpath(p)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def read(path):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return None


# ---- fixtures ---------------------------------------------------------------------------

def env_for(home, **extra):
    e = {k: v for k, v in os.environ.items()
         if not k.startswith(("GIT_", "CODEX_"))}
    e.pop("STU_CONFIG", None)
    # The baseline is a human; agent cases opt in with explicit runtime markers.
    e.pop("CLAUDECODE", None)
    write(os.path.join(home, ".gitconfig"), "[init]\n\tdefaultBranch = main\n")
    e.update({"HOME": home, "GIT_CONFIG_GLOBAL": os.path.join(home, ".gitconfig"),
              "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "T",
              "GIT_AUTHOR_EMAIL": "t@e", "GIT_COMMITTER_NAME": "T",
              "GIT_COMMITTER_EMAIL": "t@e"})
    e.update(extra)
    return e


AGENT_ENV = {"CLAUDECODE": "1"}  # the marker a Claude Code process carries


def git(cwd, env, *args, **kw):
    p = subprocess.run(["git"] + list(args), cwd=cwd, env=env, capture_output=True,
                       text=True, input=kw.get("input"))
    if p.returncode != 0 and not kw.get("ok_fail"):
        raise RuntimeError("git %s failed in %s: %s" % (" ".join(args), cwd, p.stderr))
    return p


def commit(repo, env, fname="f.txt", text=None, msg="change"):
    write(os.path.join(repo, fname), text if text is not None else msg + "\n")
    git(repo, env, "add", fname)
    git(repo, env, "commit", "-q", "-m", msg)
    return git(repo, env, "rev-parse", "HEAD").stdout.strip()


def make_repo(parent, env, name, bare_dir=None):
    path = os.path.join(parent, name)
    os.makedirs(path)
    git(path, env, "init", "-q", "-b", "main")
    commit(path, env, "README.txt", msg="init")
    if bare_dir:
        bare = os.path.join(bare_dir, name + ".git")
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", bare], env=env,
                       check=True, capture_output=True)
        git(path, env, "remote", "add", "origin", bare)
        git(path, env, "push", "-q", "origin", "main")
    return rp(path)


def fam_text(app, lib, app_over=None, lib_over=None):
    def block(name, path, base, over):
        d = dict(base)
        d["path"] = path
        d.update(over or {})
        return "\n".join(["### " + name] + ["%s: %s" % (k, v) for k, v in d.items()
                                             if v is not None])

    app_base = {"slug": "acme/app", "remote": "origin", "base": "main",
                "visibility": "public", "mode": "work", "merge_mode": "direct",
                "ci": "aggregator", "human_checkpoints": "before-push"}
    lib_base = {"slug": "acme/lib", "remote": "origin", "base": "main",
                "visibility": "private", "mode": "work", "merge_mode": "report-only",
                "ci": "none"}
    return ("---\nowner: o\n---\n\n## repos\n%s\n%s\n\n## verification-commands\n```\n"
            "make test\n```\n\n## verification-commands @lib\n```\n./check\n```\n" % (block("app", app, app_base, app_over),
                                  block("lib", lib, lib_base, lib_over)))


class Fam:
    """app (public, before-push) and lib (private) with bare remotes and a family config."""

    def __init__(self, tmp, app_over=None, lib_over=None):
        self.tmp = tmp
        self.home = rp(os.makedirs(os.path.join(tmp, "home")) or os.path.join(tmp, "home"))
        self.env = env_for(self.home)
        parent = os.path.join(tmp, "x")
        os.makedirs(parent)
        remotes = os.path.join(tmp, "remotes")
        os.makedirs(remotes)
        self.app = make_repo(parent, self.env, "app", remotes)
        self.lib = make_repo(parent, self.env, "lib", remotes)
        self.app_remote = os.path.join(remotes, "app.git")
        self.lib_remote = os.path.join(remotes, "lib.git")
        self.cfg = os.path.join(self.home, ".stu", "fam", "stu.md")
        write(self.cfg, fam_text(self.app, self.lib, app_over, lib_over))
        self.run_home = os.path.join(self.home, ".stu", "fam")
        self.approvals = os.path.join(self.run_home, "approvals.tsv")
        self.worktrees = self.app + "-worktrees"

    def install(self, repo):
        p = subprocess.run([PRE_PUSH, "--install", "--path", repo], env=self.env,
                           capture_output=True, text=True)
        return p

    def approve(self, sha, ident="app#1"):
        return subprocess.run([APPROVE, ident, sha], cwd=self.app, env=self.env,
                              capture_output=True, text=True)

    def push(self, repo, *args, agent=False):
        """A real git push through the installed hook; AGENT=True marks it as Claude Code's."""
        env = dict(self.env, **AGENT_ENV) if agent else self.env
        return git(repo, env, "push", *args, ok_fail=True)

    def remote_ref(self, bare, ref="refs/heads/main"):
        p = git(bare, self.env, "rev-parse", "--verify", "--quiet", ref, ok_fail=True)
        return p.stdout.strip()


@contextlib.contextmanager
def fam(**kw):
    with tempfile.TemporaryDirectory() as tmp:
        yield Fam(rp(tmp), **kw)


def payload(tool, cwd, agent=False, **tool_input):
    d = {"session_id": "s", "cwd": cwd, "hook_event_name": "PreToolUse",
         "tool_name": tool, "tool_input": tool_input}
    if agent:
        d["agent_id"] = "a1"
    return d


def bash(cwd, command, **kw):
    return payload("Bash", cwd, command=command, **kw)


def hook(pl, env, path=None):
    """-> (rc, stdout, stderr) of the launcher run with PL on stdin."""
    e = dict(env)
    if path is not None:
        e["PATH"] = path
    p = subprocess.run(["/bin/sh", LAUNCHER], input=json.dumps(pl), env=e,
                       capture_output=True, text=True, cwd=pl.get("cwd") or None)
    return p.returncode, p.stdout, p.stderr


def verdict(pl, env, path=None):
    """-> ("deny", reason) or ("allow", "")."""
    rc, out, err = hook(pl, env, path)
    if rc != 0:
        return ("rc%d" % rc, err)
    if not out.strip():
        return ("allow", "")
    try:
        d = json.loads(out)["hookSpecificOutput"]
    except (ValueError, KeyError):
        return ("badjson", out)
    if d.get("hookEventName") != "PreToolUse":
        return ("badevent", out)
    return (d.get("permissionDecision"), d.get("permissionDecisionReason", ""))


def denied(pl, env, path=None):
    v, reason = verdict(pl, env, path)
    return v == "deny" and reason.startswith(PREFIX)


def allowed(pl, env, path=None):
    return verdict(pl, env, path) == ("allow", "")


def nopython_bin(tmp):
    d = os.path.join(tmp, "nopy")
    os.makedirs(d, exist_ok=True)
    for name in ("sh", "dirname", "readlink", "cat", "grep", "rm", "mktemp", "git", "env",
                 "tr", "sed", "head", "wc"):
        p = shutil.which(name)
        if p and not os.path.exists(os.path.join(d, name)):
            os.symlink(p, os.path.join(d, name))
    return d


def guard():
    """The in-process tool-hook module, reloaded fresh (it must exist and import cleanly)."""
    sys.modules.pop("publish_guard", None)
    return importlib.import_module("publish_guard")


@contextlib.contextmanager
def inproc(env, cwd=None):
    old_env, old_cwd = dict(os.environ), os.getcwd()
    os.environ.clear()
    os.environ.update(env)
    if cwd:
        os.chdir(cwd)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(old_env)
        os.chdir(old_cwd)


# ---- pre-push ---------------------------------------------------------------------------

def test_unapproved_push_refused():
    with fam() as f:
        check("install", f.install(f.app).returncode, 0)
        sha = commit(f.app, f.env, msg="one")
        before = f.remote_ref(f.app_remote)
        p = f.push(f.app, "origin", "main", agent=True)
        check("refused", p.returncode != 0, True)
        check("names the sha", sha in p.stderr, True)
        check("names the stu-approve line", "stu-approve" in p.stderr, True)
        check("remote unchanged", f.remote_ref(f.app_remote), before)


def test_approved_push_allowed():
    with fam() as f:
        f.install(f.app)
        sha = commit(f.app, f.env, msg="one")
        a = f.approve(sha)
        check("approve ok", a.returncode, 0)
        p = f.push(f.app, "origin", "main")
        check("push ok", p.returncode, 0)
        check("remote moved", f.remote_ref(f.app_remote), sha)


def test_agent_unapproved_push_refused_with_message():
    with fam() as f:
        check("install", f.install(f.app).returncode, 0)
        sha = commit(f.app, f.env, msg="one")
        before = f.remote_ref(f.app_remote)
        p = f.push(f.app, "origin", "main", agent=True)
        check("agent push refused", p.returncode != 0, True)
        check("says not approved", "not approved (human_checkpoints: before-push)" in p.stderr,
              True)
        check("names the sha", sha in p.stderr, True)
        check("remote unchanged", f.remote_ref(f.app_remote), before)


def test_human_unapproved_push_allowed():
    with fam() as f:
        check("install", f.install(f.app).returncode, 0)
        sha = commit(f.app, f.env, msg="one")
        check("no marker in the baseline env", "CLAUDECODE" in f.env, False)
        p = f.push(f.app, "origin", "main")
        check("unmarked push of an unapproved tip allowed", p.returncode, 0)
        check("remote moved to the tip", f.remote_ref(f.app_remote), sha)
        check("one stderr line says the check was skipped",
              [l for l in p.stderr.splitlines() if "stu-pre-push" in l and "skipped" in l]
              != [], True)
        check("no refusal printed", "push refused" in p.stderr, False)


def test_human_approved_push_is_silent():
    with fam() as f:
        f.install(f.app)
        sha = commit(f.app, f.env, msg="one")
        f.approve(sha)
        p = f.push(f.app, "origin", "main")
        check("push ok", p.returncode, 0)
        check("remote moved", f.remote_ref(f.app_remote), sha)
        check("no skip notice when nothing would have been refused",
              "skipped" in p.stderr, False)


def test_agent_approved_push_allowed():
    with fam() as f:
        f.install(f.app)
        sha = commit(f.app, f.env, msg="one")
        f.approve(sha)
        p = f.push(f.app, "origin", "main", agent=True)
        check("push ok", p.returncode, 0)
        check("remote moved", f.remote_ref(f.app_remote), sha)


def test_empty_marker_is_a_human_push():
    with fam() as f:
        f.install(f.app)
        sha = commit(f.app, f.env, msg="one")
        p = git(f.app, dict(f.env, CLAUDECODE=""), "push", "origin", "main", ok_fail=True)
        check("empty CLAUDECODE is not the marker", p.returncode, 0)
        check("remote moved", f.remote_ref(f.app_remote), sha)


def test_approval_is_full_sha_of_tip():
    with fam() as f:
        f.install(f.app)
        first = commit(f.app, f.env, msg="one")
        tip = commit(f.app, f.env, msg="two")
        write(f.approvals, "app#1\t%s\t2026-01-01\n" % first)
        check("parent approval does not cover the tip",
              f.push(f.app, "origin", "main", agent=True).returncode != 0, True)
        write(f.approvals, "app#1\t%s\t2026-01-01\n" % tip[:12])
        check("abbreviated sha does not count",
              f.push(f.app, "origin", "main", agent=True).returncode != 0, True)
        write(f.approvals, "app#1\t%s\t2026-01-01\nlib#2\tdeadbeef\t2026-01-01\n" % tip)
        check("full sha of the tip is enough", f.push(f.app, "origin", "main", agent=True).returncode, 0)
        check("remote at tip", f.remote_ref(f.app_remote), tip)


def test_push_from_worktree_uses_shared_hook():
    with fam() as f:
        f.install(f.app)
        wt = os.path.join(f.worktrees, "wt")
        os.makedirs(f.worktrees)
        git(f.app, f.env, "worktree", "add", "-q", "-b", "wtbranch", wt)
        sha = commit(wt, f.env, msg="from the worktree")
        p = f.push(wt, "origin", "wtbranch", agent=True)
        check("refused from a linked worktree", p.returncode != 0, True)
        check("names the sha", sha in p.stderr, True)
        check("not pushed", f.remote_ref(f.app_remote, "refs/heads/wtbranch"), "")
        f.approve(sha)
        check("approved push ok", f.push(wt, "origin", "wtbranch", agent=True).returncode, 0)
        check("pushed", f.remote_ref(f.app_remote, "refs/heads/wtbranch"), sha)


def test_scripted_push_refused():
    with fam() as f:
        f.install(f.app)
        commit(f.app, f.env, msg="one")
        p = subprocess.run(["sh", "-c", "git push origin main"], cwd=f.app, env=dict(f.env, **AGENT_ENV),
                           capture_output=True, text=True)
        check("sh -c refused", p.returncode != 0, True)
        if shutil.which("make"):
            write(os.path.join(f.app, "Makefile"), "push:\n\tgit push origin main\n")
            p = subprocess.run(["make", "push"], cwd=f.app, env=dict(f.env, **AGENT_ENV), capture_output=True,
                               text=True)
            check("make target refused", p.returncode != 0, True)
        check("remote unchanged", f.remote_ref(f.app_remote) != git(
            f.app, f.env, "rev-parse", "HEAD").stdout.strip(), True)


def test_push_tags_unapproved_refused():
    with fam() as f:
        f.install(f.app)
        sha = commit(f.app, f.env, msg="release")
        git(f.app, f.env, "tag", "v1.4.1")
        git(f.app, f.env, "tag", "-a", "-m", "release 1.4.2", "v1.4.2")
        check("lightweight tag refused", f.push(f.app, "origin", "v1.4.1", agent=True).returncode != 0,
              True)
        p = f.push(f.app, "origin", "v1.4.2", agent=True)
        check("annotated tag refused", p.returncode != 0, True)
        check("names the peeled commit", sha in p.stderr, True)
        f.approve(sha)
        check("approved commit covers the lightweight tag",
              f.push(f.app, "origin", "v1.4.1", agent=True).returncode, 0)
        check("approved commit covers the annotated tag (peeled)",
              f.push(f.app, "origin", "v1.4.2", agent=True).returncode, 0)


def test_push_delete_branch_allowed():
    with fam() as f:
        f.install(f.app)
        git(f.app, f.env, "checkout", "-q", "-b", "feature")
        sha = commit(f.app, f.env, msg="feature work")
        f.approve(sha)
        check("feature pushed", f.push(f.app, "origin", "feature").returncode, 0)
        os.remove(f.approvals)
        p = f.push(f.app, "origin", "--delete", "feature")
        check("delete needs no approval", p.returncode, 0)
        check("branch gone", f.remote_ref(f.app_remote, "refs/heads/feature"), "")


def test_internal_error_refuses_push():
    with fam() as f:
        f.install(f.app)
        commit(f.app, f.env, msg="one")
        os.makedirs(f.approvals)  # unreadable as a file: an internal error, not "unapproved"
        before = f.remote_ref(f.app_remote)
        p = f.push(f.app, "origin", "main", agent=True)
        check("refused", p.returncode != 0, True)
        check("says internal error", "internal error" in p.stderr, True)
        check("remote unchanged", f.remote_ref(f.app_remote), before)
        os.rmdir(f.approvals)
        garbage = subprocess.run([os.path.join(f.app, ".git", "hooks", "pre-push"), "origin",
                                  "url"], input="not a ref line\n", cwd=f.app, env=dict(f.env, **AGENT_ENV),
                                 capture_output=True, text=True)
        check("malformed stdin refused", garbage.returncode, 1)


def test_config_error_refuses_push():
    with fam() as f:
        f.install(f.app)
        commit(f.app, f.env, msg="one")
        write(f.cfg, fam_text(f.app, f.lib, app_over={"visibility": "bogus"}))
        before = f.remote_ref(f.app_remote)
        p = f.push(f.app, "origin", "main")
        check("refused on a config error", p.returncode != 0, True)
        check("says config", "config" in p.stderr.lower(), True)
        check("remote unchanged", f.remote_ref(f.app_remote), before)


def test_python_missing_refuses_push():
    with fam() as f:
        f.install(f.app)
        bindir = nopython_bin(f.tmp)
        env = dict(f.env, PATH=bindir)
        check("no python3 on the test PATH", shutil.which("python3", path=bindir), None)
        p = subprocess.run([os.path.join(f.app, ".git", "hooks", "pre-push"), "origin", "u"],
                           input="refs/heads/main %s refs/heads/main %s\n" % ("a" * 40, "0" * 40),
                           cwd=f.app, env=env, capture_output=True, text=True)
        check("exit 1", p.returncode, 1)
        check("names python3", "python3" in p.stderr, True)
        w = subprocess.run(["/bin/sh", PRE_PUSH, "--check"], cwd=f.app, env=env,
                           capture_output=True, text=True)
        check("wrapper alone exits 1, not 127", w.returncode, 1)


def test_non_strict_row_exits_immediately():
    with fam() as f:
        f.install(f.lib)
        commit(f.lib, f.env, msg="private work")
        os.makedirs(f.approvals)  # would be an internal error if it were ever read
        hook_path = os.path.join(f.lib, ".git", "hooks", "pre-push")
        p = subprocess.run([hook_path, "origin", "u"], input="garbage\n", cwd=f.lib,
                           env=f.env, capture_output=True, text=True)
        check("exit 0 without reading stdin or approvals", (p.returncode, p.stderr), (0, ""))
        check("real push from the private row", f.push(f.lib, "origin", "main").returncode, 0)


def test_install_chains_existing_hook():
    with fam() as f:
        hooks = os.path.join(f.lib, ".git", "hooks")
        marker = os.path.join(f.tmp, "local-ran")
        write(os.path.join(hooks, "pre-push"),
              "#!/bin/sh\necho ran >> '%s'\ncat > /dev/null\nexit 0\n" % marker)
        os.chmod(os.path.join(hooks, "pre-push"), 0o755)
        check("install ok", f.install(f.lib).returncode, 0)
        check("old hook kept", os.path.isfile(os.path.join(hooks, "pre-push.local")), True)
        commit(f.lib, f.env, msg="x")
        check("push ok", f.push(f.lib, "origin", "main").returncode, 0)
        check("old hook ran first", read(marker), "ran\n")
        write(os.path.join(hooks, "pre-push.local"), "#!/bin/sh\ncat > /dev/null\nexit 1\n")
        os.chmod(os.path.join(hooks, "pre-push.local"), 0o755)
        commit(f.lib, f.env, msg="y")
        check("old hook nonzero refuses", f.push(f.lib, "origin", "main").returncode != 0,
              True)


def test_install_is_idempotent():
    with fam() as f:
        hooks = os.path.join(f.lib, ".git", "hooks")
        write(os.path.join(hooks, "pre-push"), "#!/bin/sh\nexit 0\n")
        os.chmod(os.path.join(hooks, "pre-push"), 0o755)
        f.install(f.lib)
        first = read(os.path.join(hooks, "pre-push"))
        local = read(os.path.join(hooks, "pre-push.local"))
        check("second install ok", f.install(f.lib).returncode, 0)
        check("hook unchanged", read(os.path.join(hooks, "pre-push")), first)
        check("local not replaced by our own hook", read(os.path.join(hooks, "pre-push.local")),
              local)
        check("local is the original", local, "#!/bin/sh\nexit 0\n")
        # a fresh repo: two installs, no .local ever appears
        f.install(f.app)
        f.install(f.app)
        check("no local invented", os.path.exists(
            os.path.join(f.app, ".git", "hooks", "pre-push.local")), False)


def test_install_honours_core_hookspath():
    with fam() as f:
        hp = os.path.join(f.tmp, "hp")
        os.makedirs(hp)
        git(f.app, f.env, "config", "core.hooksPath", hp)
        check("install ok", f.install(f.app).returncode, 0)
        check("hook in hooksPath", os.path.isfile(os.path.join(hp, "pre-push")), True)
        check("not in .git/hooks", os.path.exists(
            os.path.join(f.app, ".git", "hooks", "pre-push")), False)
        commit(f.app, f.env, msg="one")
        check("push through hooksPath hook refused",
              f.push(f.app, "origin", "main", agent=True).returncode != 0, True)


def test_check_reports_missing_and_installed():
    with fam() as f:
        def chk(path=None):
            args = [PRE_PUSH, "--check"] + (["--path", path] if path else [])
            p = subprocess.run(args, cwd=f.app, env=f.env, capture_output=True, text=True)
            return p.returncode, p.stdout.strip()

        check("missing", chk(), (1, "MISSING"))
        check("missing --path", chk(f.lib), (1, "MISSING"))
        f.install(f.app)
        check("installed", chk(), (0, "INSTALLED"))
        check("installed --path", chk(f.app), (0, "INSTALLED"))
        check("other repo still missing", chk(f.lib), (1, "MISSING"))
        os.remove(os.path.join(f.app, ".git", "hooks", "pre-push"))
        check("missing again", chk(), (1, "MISSING"))


def test_check_reports_missing_when_hook_target_gone():
    with fam() as f:
        f.install(f.app)
        hook = os.path.join(f.app, ".git", "hooks", "pre-push")
        text = open(hook).read()
        live = os.path.join(ROOT, "bin", "stu-pre-push")
        gone = os.path.join(f.tmp, "old-plugin", "bin", "stu-pre-push")
        with open(hook, "w") as fh:
            fh.write(text.replace(live, gone))
        p = subprocess.run([PRE_PUSH, "--check"], cwd=f.app, env=f.env, capture_output=True,
                           text=True)
        check("stale hook is not installed", (p.returncode, p.stdout.strip()), (1, "MISSING"))
        check("names the dead path", gone in p.stderr, True)
        q = subprocess.run([hook, "origin", "x"], cwd=f.app, env=f.env, input="",
                           capture_output=True, text=True)
        check("the stale hook refuses with a repair line",
              (q.returncode, "--install" in q.stderr), (1, True))


# ---- tool hook: approval file -----------------------------------------------------------

def test_write_to_approvals_refused_any_seat():
    with fam() as f:
        for agent in (False, True):
            pl = payload("Write", f.app, agent=agent, file_path=f.approvals, content="x")
            check("write refused (agent=%s)" % agent, denied(pl, f.env), True)
        check("edit of an upper-case name refused", denied(
            payload("Edit", f.lib, file_path=os.path.join(f.run_home, "APPROVALS.TSV"),
                    old_string="a", new_string="b"), f.env), True)
        check("relative path resolved against cwd", denied(
            payload("Write", f.run_home, file_path="approvals.tsv", content="x"), f.env), True)
        check("new file in an unconfigured dir refused", denied(
            payload("Write", f.tmp, file_path=os.path.join(f.tmp, "new", "approvals.tsv"),
                    content="x"), f.env), True)


def test_multiedit_approvals_refused():
    with fam() as f:
        pl = payload("MultiEdit", f.app, file_path=f.approvals,
                     edits=[{"old_string": "a", "new_string": "b"}])
        check("multiedit refused", denied(pl, f.env), True)
        nb = payload("NotebookEdit", f.app, notebook_path=f.approvals, new_source="x")
        check("notebook edit refused", denied(nb, f.env), True)


def test_write_symlink_to_approvals_tsv_refused():
    with fam() as f:
        write(f.approvals, "")
        link = os.path.join(f.tmp, "copy-approvals.tsv.txt")
        os.symlink(f.approvals, link)
        check("symlink to the file refused", denied(
            payload("Write", f.app, file_path=link, content="x"), f.env), True)
        dirlink = os.path.join(f.tmp, "approvals.tsv.d")
        os.symlink(f.run_home, dirlink)
        check("write through a directory symlink refused", denied(
            payload("Write", f.app, file_path=os.path.join(dirlink, "approvals.tsv"),
                    content="x"), f.env), True)


def test_bash_stu_approve_refused():
    with fam() as f:
        for cwd in (f.app, f.lib, f.tmp):
            check("stu-approve by path refused (%s)" % os.path.basename(cwd), denied(
                bash(cwd, '"%s" app#1 abc123' % APPROVE), f.env), True)
        check("bare word refused", denied(bash(f.tmp, "stu-approve app#1 abc"), f.env), True)
        check("through env refused", denied(
            bash(f.tmp, "env X=1 '%s/bin/stu-approve' app#1 abc" % ROOT), f.env), True)


def test_bash_stu_approve_py_refused():
    with fam() as f:
        check("python3 stu_approve.py refused", denied(
            bash(f.tmp, "python3 %s/scripts/stu_approve.py app#1 abc" % ROOT), f.env), True)
        check("upper-case name refused", denied(
            bash(f.tmp, "python3 scripts/STU_APPROVE.PY app#1 abc"), f.env), True)


def test_bash_echo_into_approvals_refused():
    with fam() as f:
        check("echo >> refused", denied(
            bash(f.tmp, 'echo "app#1\tabc\t2026" >> %s' % f.approvals), f.env), True)
        check("tee refused", denied(bash(f.app, "printf x | tee ~/.stu/fam/Approvals.TSV"),
                                    f.env), True)
        check("cat refused too (text rule, no parsing)", denied(
            bash(f.app, "cat approvals.tsv"), f.env), True)


def test_write_approvals_py_in_unconfigured_repo_allowed():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = rp(tmp)
        home = os.path.join(tmp, "home")
        os.makedirs(home)
        env = env_for(home)
        repo = make_repo(tmp, env, "plain")
        check("approvals.py allowed", allowed(
            payload("Write", repo, file_path=os.path.join(repo, "approvals.py"),
                    content="x = 1\n"), env), True)
        check("approvals_test.tsv-less names allowed", allowed(
            payload("Edit", repo, file_path=os.path.join(repo, "src", "approvals.go"),
                    old_string="a", new_string="b"), env), True)


def test_bash_grep_approvals_in_source_allowed():
    with fam() as f:
        check("grep approvals allowed", allowed(
            bash(f.app, "grep -rn approvals src/ | head"), f.env), True)
        check("in an unconfigured dir", allowed(bash(f.tmp, "grep -rn approvals ."), f.env),
              True)


def test_bash_commit_message_mentioning_approvals_allowed():
    with fam() as f:
        check("commit message allowed", allowed(
            bash(f.app, 'git commit -m "Document the approvals flow for reviewers"'),
            f.env), True)
        check("heredoc message allowed", allowed(bash(
            f.lib, "git commit -F - <<'EOF'\nExplain approvals and the gate\nEOF"), f.env),
            True)


def test_other_tools_approvals_dir_allowed():
    with fam() as f:
        check("write under approvals/ allowed", allowed(
            payload("Write", f.app, file_path=os.path.join(f.app, "approvals", "rules.json"),
                    content="{}"), f.env), True)
        check("ls approvals/ allowed", allowed(bash(f.app, "ls approvals/"), f.env), True)


# ---- tool hook: bypass on a strict row --------------------------------------------------

def test_no_verify_on_strict_row_refused():
    with fam() as f:
        check("push --no-verify from the strict row", denied(
            bash(f.app, "git push --no-verify origin main"), f.env), True)
        check("upper case flag", denied(bash(f.app, "git push origin main --NO-VERIFY"),
                                        f.env), True)
        check("text names the row path from elsewhere", denied(
            bash(f.tmp, "git -C %s push --no-verify origin main" % f.app), f.env), True)
        check("text names the slug", denied(
            bash(f.tmp, "git push --no-verify git@example.com:acme/app.git main"), f.env),
            True)
        check("commit --no-verify is not a push", allowed(
            bash(f.app, "git commit --no-verify -m wip"), f.env), True)


def test_no_verify_from_worktree_outside_worktrees_dir_refused():
    with fam() as f:
        wt = os.path.join(f.tmp, "elsewhere-wt")
        git(f.app, f.env, "worktree", "add", "-q", "-b", "elsewhere", wt)
        check("push --no-verify from a worktree outside worktrees_dir", denied(
            bash(wt, "git push --no-verify origin elsewhere"), f.env), True)
        check("a plain push from there is not a bypass", allowed(
            bash(wt, "git status"), f.env), True)


def test_core_hookspath_override_on_strict_row_refused():
    with fam() as f:
        check("-c core.hooksPath", denied(
            bash(f.app, "git -c core.hooksPath=/dev/null push origin main"), f.env), True)
        check("git config core.hooksPath", denied(
            bash(f.app, "git config core.hooksPath /tmp/x"), f.env), True)
        check("any case", denied(bash(f.app, "git -c CORE.HOOKSPATH=/dev/null push"), f.env),
              True)


def test_no_verify_on_private_row_allowed():
    with fam() as f:
        check("private row", allowed(bash(f.lib, "git push --no-verify origin main"), f.env),
              True)
        check("private row hooksPath", allowed(
            bash(f.lib, "git -c core.hooksPath=/dev/null push"), f.env), True)
        check("unconfigured dir", allowed(bash(f.tmp, "git push --no-verify origin main"),
                                          f.env), True)


def test_variable_target_in_family_cwd_denied():
    with fam() as f:
        wt = os.path.join(f.worktrees, "wt")
        os.makedirs(f.worktrees)
        git(f.app, f.env, "worktree", "add", "-q", "-b", "wtb", wt)
        cmd = 'git push --no-verify "$TARGET" main'
        check("cwd in the strict row", denied(bash(f.app, cmd), f.env), True)
        check("cwd in a linked worktree", denied(bash(wt, cmd), f.env), True)
        check("cwd in the worktrees dir", denied(bash(f.worktrees, cmd), f.env), True)
        check("cwd in the private row", allowed(bash(f.lib, cmd), f.env), True)


def test_flat_strict_row_matched_via_cwd():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = rp(tmp)
        home = os.path.join(tmp, "home")
        os.makedirs(home)
        env = env_for(home)
        flat = make_repo(tmp, env, "solo")
        other = make_repo(tmp, env, "other")
        write(os.path.join(flat, ".claude", "stu.md"),
              "---\nowner: o\nvisibility: public\nhuman_checkpoints: before-push\n---\n")
        # a flat home config elsewhere has an empty path: it must never match every command
        write(os.path.join(home, ".stu", "flatfam", "stu.md"),
              "---\nowner: o\nvisibility: public\nhuman_checkpoints: before-push\n---\n")
        cmd = "git push --no-verify origin main"
        check("flat strict repo, cwd inside", denied(bash(flat, cmd), env), True)
        check("empty path never matches another repo", allowed(bash(other, cmd), env), True)


# ---- tool hook: scope and cost ----------------------------------------------------------

def test_pr_body_command_substitution_in_private_row_allowed():
    with fam() as f:
        cmd = ("gh pr create --title t --body \"$(cat <<'EOF'\nsummary of the change\nEOF\n)\"")
        check("heredoc substitution in the private row", allowed(bash(f.lib, cmd), f.env),
              True)
        check("unconfigured dir", allowed(bash(f.tmp, cmd), f.env), True)


def test_push_branch_substitution_in_flat_private_row_allowed():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = rp(tmp)
        home = os.path.join(tmp, "home")
        os.makedirs(home)
        env = env_for(home)
        flat = make_repo(tmp, env, "solo")
        write(os.path.join(flat, ".claude", "stu.md"), "---\nowner: o\nvisibility: private\n---\n")
        check("substitution in a flat private row", allowed(
            bash(flat, 'git push origin "$(git branch --show-current)"'), env), True)
        check("--no-verify on a flat private row", allowed(
            bash(flat, "git push --no-verify origin main"), env), True)


def test_launcher_unrelated_payload_no_python():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = rp(tmp)
        home = os.path.join(tmp, "home")
        os.makedirs(home)
        env = env_for(home)
        bindir = nopython_bin(tmp)
        check("no python3 on the test PATH", shutil.which("python3", path=bindir), None)
        for pl in (bash(tmp, "ls -la && git status"),
                   payload("Write", tmp, file_path=os.path.join(tmp, "notes.md"),
                           content="plain notes about nothing\n"),
                   payload("Edit", tmp, file_path=os.path.join(tmp, "a.py"),
                           old_string="x", new_string="y")):
            rc, out, err = hook(pl, env, bindir)
            check("silent exit 0 for %s" % pl["tool_name"], (rc, out, err), (0, "", ""))


def test_launcher_python_missing_denies_relevant_payload():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = rp(tmp)
        home = os.path.join(tmp, "home")
        os.makedirs(home)
        env = env_for(home)
        bindir = nopython_bin(tmp)
        for pl in (bash(tmp, "git push --no-verify origin main"),
                   bash(tmp, "cat approvals.tsv"),
                   payload("Write", tmp, file_path=os.path.join(tmp, "approvals.tsv"),
                           content="x"),
                   bash(tmp, "gh pr create --title t")):
            rc, out, err = hook(pl, env, bindir)
            check("exit 0", rc, 0)
            d = json.loads(out)["hookSpecificOutput"] if out.strip() else {}
            check("denies", d.get("permissionDecision"), "deny")
            check("names the failure", "python3" in d.get("permissionDecisionReason", ""), True)
            check("prefix", d.get("permissionDecisionReason", "").startswith(PREFIX), True)


def test_systemexit_in_resolve_is_caught():
    with fam() as f:
        with inproc(f.env, f.app):
            g = guard()
            real_resolve, real_families = stu_env.resolve, stu_env.families

            def boom(*a, **k):
                raise SystemExit(3)

            stu_env.resolve = boom
            stu_env.families = boom
            try:
                got = []
                for pl in (bash(f.app, "git push --no-verify origin main"),
                           payload("Write", f.app, file_path=f.approvals, content="x"),
                           bash(f.tmp, "cat approvals.tsv")):
                    try:
                        got.append(g.evaluate(pl))
                    except BaseException as e:  # noqa: BLE001
                        got.append("raised %r" % e)
            finally:
                stu_env.resolve, stu_env.families = real_resolve, real_families
        check("nothing escapes", [x for x in got if isinstance(x, str) and
                                  x.startswith("raised")], [])
        check("the approval-file rule needs no resolver", bool(got[1]), True)
        check("a plain-text approvals.tsv hit still denies", bool(got[2]), True)


def test_crash_in_unconfigured_repo_allows():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = rp(tmp)
        home = os.path.join(tmp, "home")
        os.makedirs(home)
        env = env_for(home)
        repo = make_repo(tmp, env, "plain")
        with inproc(env, repo):
            g = guard()

            def boom(*a, **k):
                raise RuntimeError("forced")

            real = g.check_bypass
            g.check_bypass = boom
            try:
                got = g.evaluate(bash(repo, "git push --no-verify origin main"))
            finally:
                g.check_bypass = real
        check("allowed", got, None)


def test_crash_on_claimed_path_denies():
    with fam() as f:
        with inproc(f.env, f.app):
            g = guard()

            def boom(*a, **k):
                raise RuntimeError("forced")

            real = g.check_bypass
            g.check_bypass = boom
            try:
                strict_got = g.evaluate(bash(f.app, "git push --no-verify origin main"))
                private_got = g.evaluate(bash(f.lib, "git push --no-verify origin main"))
            finally:
                g.check_bypass = real
        check("strict row denies on a crash", bool(strict_got), True)
        check("private row allows on a crash", private_got, None)


def test_unreadable_config_no_verify_denied():
    with fam() as f:
        good = open(f.cfg).read()
        write(f.cfg, good.replace("### lib\n", "### app\n", 1))
        v, reason = verdict(bash(f.app, "git push --no-verify origin main"), f.env)
        check("no-verify push denied", v, "deny")
        check("names the config failure", "config" in reason.lower(), True)
        check("hooksPath denied", denied(
            bash(f.app, "git -c core.hooksPath=/dev/null push origin main"), f.env), True)
        check("a forge write denied", denied(
            bash(f.app, "gh pr create --title t --body x"), f.env), True)


def test_unreadable_config_unrelated_bash_allowed():
    with fam() as f:
        good = open(f.cfg).read()
        write(f.cfg, good.replace("### lib\n", "### app\n", 1))
        check("a plain command", allowed(bash(f.app, "ls -la && git status"), f.env), True)
        check("a commit --no-verify is not a push", allowed(
            bash(f.app, "git commit --no-verify -m wip"), f.env), True)
        bindir = nopython_bin(f.tmp)
        rc, out, err = hook(bash(f.app, "ls -la"), f.env, bindir)
        check("no python started for an unrelated payload", (rc, out, err), (0, "", ""))
        check("unconfigured dir, bypass text, still allowed", allowed(
            bash(f.tmp, "git push --no-verify origin main"), f.env), True)


def test_unreadable_config_named_from_outside_denied():
    with fam() as f:
        good = open(f.cfg).read()
        write(f.cfg, good.replace("### lib\n", "### app\n", 1))
        v, reason = verdict(bash(f.tmp, "git -C %s push --no-verify origin main" % f.app), f.env)
        check("named from an unconfigured cwd, denied", v, "deny")
        check("names the config failure", "config" in reason.lower(), True)
        check("hooksPath naming the row, denied", denied(bash(
            f.tmp, "git -C %s -c core.hooksPath=/dev/null push origin main" % f.app), f.env), True)
        check("not naming any row, allowed", allowed(
            bash(f.tmp, "git push --no-verify origin main"), f.env), True)


def test_root_like_path_in_broken_config_never_matches():
    with fam() as f:
        good = open(f.cfg).read()
        extra = "\n### root\npath: /\n\n### home\npath: %s\n\n### blank\npath:  \n" % f.home
        write(f.cfg, good.replace("### lib\n", "### app\n", 1) + extra)
        check("a root-like path denies nothing", allowed(
            bash(f.tmp, "git push --no-verify origin main"), f.env), True)
        check("a plain gh write outside any row", allowed(
            bash(f.tmp, "gh pr create --title t --body x"), f.env), True)


def test_stu_config_without_row_allows():
    with fam() as f:
        other = make_repo(os.path.join(f.tmp, "x"), f.env, "other", os.path.join(f.tmp, "remotes"))
        env = dict(f.env, STU_CONFIG=f.cfg)
        check("no-verify push allowed", allowed(
            bash(other, "git push --no-verify origin main"), env), True)
        check("gh pr create allowed", allowed(
            bash(other, "gh pr create --title t --body x"), env), True)


def test_tilde_row_path_matches_when_resolve_fails():
    with fam() as f:
        with inproc(f.env, f.tmp):
            g = guard()
            real_res, real_fam = g.stu_env.resolve, g.stu_env.families

            def nope(*a, **k):
                raise g.stu_env.ConfigError("forced")

            raw = {"path": "~/" + os.path.relpath(f.app, f.home), "slug": "acme/app",
                   "visibility": "public", "human_checkpoints": "before-push"}
            g.stu_env.resolve = nope
            g.stu_env.families = lambda: [(f.cfg, [raw])]
            try:
                got = g.strict_targets(f.tmp)
            finally:
                g.stu_env.resolve, g.stu_env.families = real_res, real_fam
        check("the raw ~ path is expanded", [rp(t[0]) for t in got], [f.app])


def test_hook_entry_has_onfailure_block():
    with open(HOOKS_JSON) as fh:
        hooks = json.load(fh)["hooks"]
    entry = hooks.get("PreToolUse", [{}])[0]
    check("matcher", entry.get("matcher"),
          "^(Bash|Write|Edit|MultiEdit|NotebookEdit)$|^mcp__.*")
    h = (entry.get("hooks") or [{}])[0]
    check("type", h.get("type"), "command")
    check("command", h.get("command"), 'sh "${CLAUDE_PLUGIN_ROOT}/hooks/publish-guard.sh"')
    check("timeout", h.get("timeout"), 30)
    check("onFailure", h.get("onFailure"), "block")
    check("PostToolUse kept", "PostToolUse" in hooks, True)


# ---- stu-approve ------------------------------------------------------------------------

def test_stu_approve_cli_appends_row():
    with fam() as f:
        sha = commit(f.app, f.env, msg="one")
        p = subprocess.run([APPROVE, "app#12", sha], cwd=f.tmp, env=f.env,
                           capture_output=True, text=True)
        check("exit 0", p.returncode, 0)
        lines = (read(f.approvals) or "").splitlines()
        check("one line", len(lines), 1)
        cols = lines[0].split("\t") if lines else []
        check("three columns", len(cols), 3)
        check("id and sha", cols[:2], ["app#12", sha])
        check("date is UTC ISO", bool(cols) and len(cols[-1]) >= 10 and cols[-1][4] == "-", True)
        check("prints the row", p.stdout.strip(), lines[0] if lines else None)
        p = subprocess.run([APPROVE, "app:slug", sha], cwd=f.app, env=f.env,
                           capture_output=True, text=True)
        check("slug form ok", p.returncode, 0)
        check("two lines", len((read(f.approvals) or "").splitlines()), 2)
        p = subprocess.run([APPROVE, "12", sha], cwd=f.app, env=f.env,
                           capture_output=True, text=True)
        check("bare id in a two-row family: usage", p.returncode, 2)
        check("names the qualified form", "<repo>#" in p.stderr or "app#" in p.stderr, True)


def test_stu_approve_stores_full_sha():
    with fam() as f:
        sha = commit(f.app, f.env, msg="one")
        p = subprocess.run([APPROVE, "app#3", sha[:9]], cwd=f.tmp, env=f.env,
                           capture_output=True, text=True)
        check("exit 0", p.returncode, 0)
        cols = (read(f.approvals) or "").strip().split("\t")
        check("full sha stored", cols[1] if len(cols) > 1 else None, sha)
        tag = subprocess.run(["git", "tag", "-a", "-m", "m", "v1.4.3"], cwd=f.app,
                             env=f.env, capture_output=True, text=True)
        p = subprocess.run([APPROVE, "app#4", "v1.4.3"], cwd=f.tmp, env=f.env,
                           capture_output=True, text=True)
        check("a tag peels to its commit", (tag.returncode, p.returncode), (0, 0))
        check("peeled sha stored", (read(f.approvals) or "").splitlines()[-1].split("\t")[1],
              sha)


def test_stu_approve_unknown_sha_rejected():
    with fam() as f:
        p = subprocess.run([APPROVE, "app#3", "f" * 40], cwd=f.tmp, env=f.env,
                           capture_output=True, text=True)
        check("exit 1", p.returncode, 1)
        check("nothing appended", read(f.approvals), None)
        p = subprocess.run([APPROVE, "app#3", "--help"], cwd=f.tmp, env=f.env,
                           capture_output=True, text=True)
        check("option-like sha rejected", p.returncode != 0, True)
        p = subprocess.run([APPROVE, "app 3", "HEAD"], cwd=f.tmp, env=f.env,
                           capture_output=True, text=True)
        check("whitespace id rejected", p.returncode, 2)


# ---- the private-repo leak scan (4b) ----------------------------------------------------

def lib_files(f, files, msg="lib files"):
    """Commit FILES ({path: text}) to the private lib repo; returns its new HEAD."""
    for p, t in files.items():
        write(os.path.join(f.lib, p), t)
        git(f.lib, f.env, "add", p)
    git(f.lib, f.env, "commit", "-q", "-m", msg)
    return git(f.lib, f.env, "rev-parse", "HEAD").stdout.strip()


def pushed(f, repo, *args, agent=False):
    """Approve the tip of REPO's HEAD, then push: the only reason left to refuse is the scan."""
    sha = git(repo, f.env, "rev-parse", "HEAD").stdout.strip()
    f.approve(sha)
    return sha, f.push(repo, *args, agent=agent)


def test_leak_in_commit_message_refused():
    with fam() as f:
        lib_files(f, {"src/module_a.py": "x = 1\n"})
        f.install(f.app)
        commit(f.app, f.env, msg="speed up module_a.py loading")
        sha, p = pushed(f, f.app, "origin", "main")
        check("refused", p.returncode != 0, True)
        check("names the item", "module_a.py" in p.stderr, True)
        check("says where", "commit message" in p.stderr, True)
        check("remote unchanged", f.remote_ref(f.app_remote) != sha, True)


def test_leak_refused_for_unmarked_and_agent_pushes_alike():
    with fam() as f:
        lib_files(f, {"src/module_a.py": "x = 1\n"})
        f.install(f.app)
        sha = commit(f.app, f.env, msg="speed up module_a.py loading")
        before = f.remote_ref(f.app_remote)
        p = f.push(f.app, "origin", "main")  # unmarked and unapproved: only the scan can refuse
        check("unmarked leak refused", p.returncode != 0, True)
        check("unmarked: names the item", "module_a.py" in p.stderr, True)
        check("unmarked: not an approval refusal", "not approved" in p.stderr, False)
        check("unmarked: remote unchanged", f.remote_ref(f.app_remote), before)
        p = f.push(f.app, "origin", "main", agent=True)
        check("agent leak refused", p.returncode != 0, True)
        check("agent: names the item", "module_a.py" in p.stderr, True)
        sha, p = pushed(f, f.app, "origin", "main", agent=True)
        check("agent leak refused even when approved", p.returncode != 0, True)
        check("agent: names the item when approved", "module_a.py" in p.stderr, True)
        check("remote still unchanged", f.remote_ref(f.app_remote), before)


def test_leak_after_plus_plus_content_line_refused():
    with fam() as f:
        lib_files(f, {"src/module_a.py": "x = 1\n"})
        f.install(f.app)
        commit(f.app, f.env, "notes.md",
               text="intro\n++ heading\nsee src/module_a.py for details\n",
               msg="add notes")
        sha, p = pushed(f, f.app, "origin", "main")
        check("refused", p.returncode != 0, True)
        check("names the item", "module_a.py" in p.stderr, True)
        check("says where", "notes.md" in p.stderr, True)


def test_leak_in_added_line_refused():
    with fam() as f:
        lib_files(f, {"src/module_a.py": "x = 1\n"})
        f.install(f.app)
        commit(f.app, f.env, "notes.txt", text="see src/module_a.py for details\n",
               msg="add notes")
        sha, p = pushed(f, f.app, "origin", "main")
        check("refused", p.returncode != 0, True)
        check("names the item", "module_a.py" in p.stderr, True)
        check("says where", "notes.txt" in p.stderr, True)
        check("does not print the whole line", "for details" not in p.stderr, True)


def test_leak_in_branch_name_refused():
    with fam() as f:
        lib_files(f, {"src/module_a.py": "x = 1\n"})
        f.install(f.app)
        git(f.app, f.env, "checkout", "-q", "-b", "fix-module_a.py-crash")
        commit(f.app, f.env, msg="clean change")
        sha, p = pushed(f, f.app, "origin", "fix-module_a.py-crash")
        check("refused", p.returncode != 0, True)
        check("names the item", "module_a.py" in p.stderr, True)
        check("says ref name", "ref name" in p.stderr, True)


def test_public_tag_message_leak_refused():
    with fam() as f:
        lib_files(f, {"src/module_a.py": "x = 1\n"})
        f.install(f.app)
        commit(f.app, f.env, msg="release prep")
        git(f.app, f.env, "tag", "-a", "-m", "fixes module_a.py", "v1.4.5")
        sha, p = pushed(f, f.app, "origin", "v1.4.5")
        check("refused", p.returncode != 0, True)
        check("names the item", "module_a.py" in p.stderr, True)
        check("says tag message", "tag message" in p.stderr, True)
        git(f.app, f.env, "tag", "-a", "-m", "clean notes", "v1.4.6")
        check("clean annotated tag allowed", f.push(f.app, "origin", "v1.4.6").returncode, 0)


def test_issue_ref_pattern_refused():
    with fam() as f:
        f.install(f.app)
        commit(f.app, f.env, msg="work around acme/lib#12")
        sha, p = pushed(f, f.app, "origin", "main")
        check("org/name#n refused", p.returncode != 0, True)
        check("names the match", "acme/lib#12" in p.stderr, True)
        git(f.app, f.env, "reset", "-q", "--hard", "HEAD~1")
        commit(f.app, f.env, msg="work around lib#7")
        sha, p = pushed(f, f.app, "origin", "main")
        check("name#n refused", p.returncode != 0, True)
        git(f.app, f.env, "reset", "-q", "--hard", "HEAD~1")
        commit(f.app, f.env, msg="fix issue #7 and app#3")
        sha, p = pushed(f, f.app, "origin", "main")
        check("own issue refs allowed", p.returncode, 0)


def test_pin_file_slug_allowed():
    with fam(app_over={"pin_files": "deps.txt"}) as f:
        lib_files(f, {"src/module_a.py": "x = 1\n"})
        f.install(f.app)
        sha = "a" * 40
        commit(f.app, f.env, "deps.txt",
               text="lib https://github.com/acme/lib.git %s\nlib git@github.com:acme/lib.git\n"
                    % sha, msg="pin the library")
        sha, p = pushed(f, f.app, "origin", "main")
        check("pin line with slug, clone url and sha allowed", p.returncode, 0)


def test_pin_file_with_private_path_refused():
    with fam(app_over={"pin_files": "deps.txt"}) as f:
        lib_files(f, {"src/module_a.py": "x = 1\n"})
        f.install(f.app)
        commit(f.app, f.env, "deps.txt",
               text="lib https://github.com/acme/lib.git %s # uses module_a.py\n" % ("b" * 40),
               msg="pin the library")
        sha, p = pushed(f, f.app, "origin", "main")
        check("refused", p.returncode != 0, True)
        check("names the item", "module_a.py" in p.stderr, True)
        check("slug alone is not named", "acme/lib.git" not in p.stderr, True)


def test_pin_file_with_issue_reference_refused():
    with fam(app_over={"pin_files": "deps.txt"}) as f:
        lib_files(f, {"src/module_a.py": "x = 1\n"})
        f.install(f.app)
        commit(f.app, f.env, "deps.txt",
               text="lib https://github.com/acme/lib.git %s # see acme/lib#9 here\n" % ("c" * 40),
               msg="pin the library")
        sha, p = pushed(f, f.app, "origin", "main")
        check("issue reference in a pin file refused", p.returncode != 0, True)
        check("names the reference", "acme/lib#9" in p.stderr, True)
        check("slug alone is not named", "acme/lib.git" not in p.stderr, True)


def test_shared_basename_not_flagged():
    with fam() as f:
        lib_files(f, {"internal/util_shared.py": "x = 1\n"})
        commit(f.app, f.env, "pkg/util_shared.py", text="y = 2\n", msg="add a helper")
        f.install(f.app)
        commit(f.app, f.env, msg="touch util_shared.py again")
        sha, p = pushed(f, f.app, "origin", "main")
        check("basename also tracked in the public repo is not flagged", p.returncode, 0)


def test_common_word_basename_not_flagged():
    with fam() as f:
        lib_files(f, {"docs/README.md": "x\n", "svc/main.go": "y\n", "svc/config.yaml": "z\n",
                      "svc/LICENSE": "l\n", "svc/CHANGELOG.md": "c\n", "svc/index.html": "i\n"})
        f.install(f.app)
        commit(f.app, f.env, msg="update README.md, main.go, config.yaml, LICENSE, "
                                  "CHANGELOG.md and index.html")
        sha, p = pushed(f, f.app, "origin", "main")
        check("common names allowed", p.returncode, 0)


def test_common_extensionless_basename_not_flagged():
    with fam() as f:
        lib_files(f, {"bin/runner": "x\n", ".hidden": "h\n", "tools/Makefile": "m\n"})
        f.install(f.app)
        commit(f.app, f.env, msg="the runner is fast; see .hidden and the Makefile")
        sha, p = pushed(f, f.app, "origin", "main")
        check("extensionless, dotfile and Makefile basenames allowed", p.returncode, 0)


def test_case_variant_of_public_file_not_flagged():
    with fam() as f:
        lib_files(f, {"Docs/Guide_Page.md": "x\n"})
        commit(f.app, f.env, "docs/guide_page.md", text="y\n", msg="add the guide")
        f.install(f.app)
        commit(f.app, f.env, msg="edit docs/guide_page.md and Guide_Page.md")
        sha, p = pushed(f, f.app, "origin", "main")
        check("case variant of a public file allowed", p.returncode, 0)


def test_shared_org_not_flagged():
    with fam() as f:
        f.install(f.app)
        commit(f.app, f.env, msg="thanks to the acme team")
        sha, p = pushed(f, f.app, "origin", "main")
        check("org shared with the public row allowed", p.returncode, 0)
    with fam(lib_over={"slug": "hidden-org/lib"}) as f:
        f.install(f.app)
        commit(f.app, f.env, msg="coordinate with hidden-org on this")
        sha, p = pushed(f, f.app, "origin", "main")
        check("private-only org refused", p.returncode != 0, True)
        check("names the org", "hidden-org" in p.stderr, True)


def test_vendored_private_path_not_in_list():
    with fam() as f:
        lib_files(f, {"vendor/acme_dep/dep_widget.go": "a\n",
                      "node_modules/pk/pk_widget.js": "b\n",
                      "third_party/tp_widget.c": "c\n", "vendor/lib_a_widget.c": "d\n",
                      "ext/gen_widget.py": "e\n", "src/real_thing.py": "r\n",
                      ".gitattributes": "ext/* linguist-vendored\n"})
        f.install(f.app)
        commit(f.app, f.env, msg="mention dep_widget.go pk_widget.js tp_widget.c "
                                  "lib_a_widget.c gen_widget.py")
        sha, p = pushed(f, f.app, "origin", "main")
        check("vendored names allowed", p.returncode, 0)
        mod = guard_policy()
        with inproc(f.env, f.app):
            names = mod.private_list(mod.family_of(
                stu_env.resolve(cwd=f.app, forge_lookup=False)["CONFIG_PATH"]),
                stu_env.resolve(cwd=f.app, forge_lookup=False))
        check("list built", len(names) > 0, True)
        check("no vendored path in the list",
              [n for n in names if "widget" in n.lower()], [])
        check("a real private path is in the list", "src/real_thing.py" in names, True)


def guard_policy():
    sys.modules.pop("push_policy", None)
    return importlib.import_module("push_policy")


def test_bare_name_and_tag_allowed():
    with fam() as f:
        f.install(f.app)
        commit(f.app, f.env, msg="bump lib to 1.4.1")
        git(f.app, f.env, "tag", "-a", "-m", "release 1.4.1 of the library", "v1.4.1")
        sha, p = pushed(f, f.app, "origin", "main", "v1.4.1")
        check("bare name and version allowed", p.returncode, 0)


def test_cache_key_includes_public_head():
    with fam() as f:
        lib_files(f, {"src/cache_probe.py": "x\n"})
        f.install(f.app)
        commit(f.app, f.env, msg="first")
        pushed(f, f.app, "origin", "main")
        vis = os.path.join(f.run_home, "visibility")
        first = sorted(os.listdir(vis)) if os.path.isdir(vis) else []
        check("one cache file after the first scan", len(first), 1)
        lib_head = git(f.lib, f.env, "rev-parse", "HEAD").stdout.strip()
        app_head = git(f.app, f.env, "rev-parse", "HEAD").stdout.strip()
        check("named row-privateHEAD-publicHEAD", first,
              ["lib-%s-%s.txt" % (lib_head, app_head)] if first else None)
        commit(f.app, f.env, msg="second")
        pushed(f, f.app, "origin", "main")
        second = sorted(os.listdir(vis))
        check("a new public HEAD makes a new cache file", len(second), 2)
        # the key matters: a public file that now shares the name drops it from the list
        commit(f.app, f.env, "src/cache_probe.py", text="y\n", msg="add the same name")
        sha, p = pushed(f, f.app, "origin", "main")
        check("same name now public: not flagged", p.returncode, 0)


def test_scan_10k_file_private_repo_2k_line_diff_under_5s():
    import time
    with fam() as f:
        files = {}
        for i in range(10000):
            files["pkg%03d/mod_%05d.py" % (i % 200, i)] = "x\n"
        for p, t in files.items():
            write(os.path.join(f.lib, p), t)
        git(f.lib, f.env, "add", "-A")
        git(f.lib, f.env, "commit", "-q", "-m", "many files")
        f.install(f.app)
        body = "".join("line %d of ordinary public text with words like mod and pkg\n" % i
                       for i in range(2000))
        commit(f.app, f.env, "big.txt", text=body, msg="a big public change")
        sha = git(f.app, f.env, "rev-parse", "HEAD").stdout.strip()
        f.approve(sha)
        t0 = time.time()
        p = f.push(f.app, "origin", "main")
        cold = time.time() - t0
        check("clean big push allowed", p.returncode, 0)
        check("cold scan under 5s (%.1fs)" % cold, cold < 5.0, True)
        body2 = body + "now mentions mod_09999.py by name\n"
        commit(f.app, f.env, "big.txt", text=body2, msg="leak at the end")
        sha = git(f.app, f.env, "rev-parse", "HEAD").stdout.strip()
        f.approve(sha)
        t0 = time.time()
        p = f.push(f.app, "origin", "main")
        warm = time.time() - t0
        check("leak found in a big diff", "mod_09999.py" in p.stderr, True)
        check("warm scan under 5s (%.1fs)" % warm, warm < 5.0, True)


def test_new_branch_range_from_base():
    with fam() as f:
        f.install(f.app)
        commit(f.app, f.env, msg="old note about module_a.py")
        lib_files(f, {"src/module_a.py": "x\n"})
        f.approve(git(f.app, f.env, "rev-parse", "HEAD").stdout.strip())
        env = dict(f.env)
        p = subprocess.run(["git", "push", "--no-verify", "origin", "main"], cwd=f.app,
                           env=env, capture_output=True, text=True)
        check("history already on the remote pushed past the hook", p.returncode, 0)
        git(f.app, f.env, "checkout", "-q", "-b", "feature")
        commit(f.app, f.env, msg="clean feature work")
        sha, p = pushed(f, f.app, "origin", "feature")
        check("only the new commits are scanned", p.returncode, 0)
        commit(f.app, f.env, msg="then module_a.py slips in")
        sha, p = pushed(f, f.app, "origin", "feature")
        check("a leak in the new range refused", p.returncode != 0, True)


def _no_base_setup(f):
    """A new branch with a leak-free base commit on the remote, then a feature branch off it,
    pushed by the remote's URL: <url>/main is no ref, so pushed_range takes the fallback."""
    f.install(f.app)
    git(f.app, f.env, "checkout", "-q", "-b", "feature")


def test_new_branch_no_base_clean_not_refused():
    # the fallback scans; it does not refuse because the base is unknown
    with fam() as f:
        lib_files(f, {"src/module_a.py": "x\n"})
        _no_base_setup(f)
        commit(f.app, f.env, msg="clean feature work")
        sha, p = pushed(f, f.app, f.app_remote, "feature")
        check("clean push with no resolvable base allowed", p.returncode, 0)
        check("branch landed", f.remote_ref(f.app_remote, "refs/heads/feature"), sha)


def test_new_branch_no_base_leak_refused():
    with fam() as f:
        lib_files(f, {"src/module_a.py": "x\n"})
        _no_base_setup(f)
        commit(f.app, f.env, msg="then module_a.py slips in")
        sha, p = pushed(f, f.app, f.app_remote, "feature")
        check("leak refused with no resolvable base", p.returncode != 0, True)
        check("names the item", "module_a.py" in p.stderr, True)
        check("nothing landed", f.remote_ref(f.app_remote, "refs/heads/feature"), "")


def test_new_branch_deleted_tracking_ref_leak_refused():
    # the remote is named, but its tracking ref for the base is gone
    with fam() as f:
        lib_files(f, {"src/module_a.py": "x\n"})
        _no_base_setup(f)
        git(f.app, f.env, "update-ref", "-d", "refs/remotes/origin/main")
        commit(f.app, f.env, msg="clean feature work")
        sha, p = pushed(f, f.app, "origin", "feature")
        check("clean push allowed", p.returncode, 0)
        commit(f.app, f.env, msg="then module_a.py slips in")
        git(f.app, f.env, "update-ref", "-d", "refs/remotes/origin/feature")
        git(f.app, f.env, "checkout", "-q", "-b", "feature2")
        sha, p = pushed(f, f.app, "origin", "feature2")
        check("leak refused with the tracking ref gone", p.returncode != 0, True)
        check("names the item", "module_a.py" in p.stderr, True)


# ---- the tool-call hook, check 3: text published through the forge ----------------------

def lib_leak(f):
    lib_files(f, {"src/module_a.py": "x\n"})


def test_gh_pr_create_heredoc_leak_on_public_refused():
    with fam() as f:
        lib_leak(f)
        cmd = ("gh pr create --title t --body \"$(cat <<'EOF'\nfixes the crash in "
               "module_a.py\nEOF\n)\"")
        v, reason = verdict(bash(f.app, cmd), f.env)
        check("denied", v == "deny" and reason.startswith(PREFIX), True)
        check("names the item", "module_a.py" in reason, True)


def test_gh_pr_create_clean_on_public_allowed():
    with fam() as f:
        lib_leak(f)
        cmd = ("gh pr create --title t --body \"$(cat <<'EOF'\nAdds a retry to the loader.\n"
               "EOF\n)\"")
        check("allowed", allowed(bash(f.app, cmd), f.env), True)
        check("comment allowed", allowed(bash(f.app, "gh pr comment 4 --body thanks"), f.env),
              True)


def test_gh_body_file_leak_refused():
    with fam() as f:
        lib_leak(f)
        body = os.path.join(f.tmp, "body.md")
        write(body, "Details: module_a.py is the cause.\n")
        for flag in ("--body-file %s", "--body-file=%s", "-F %s", "--notes-file %s"):
            sub = "release create v1.4.9" if flag.startswith("--notes") else "pr create"
            cmd = "gh %s %s" % (sub, flag % body)
            check("denied: " + flag, denied(bash(f.app, cmd), f.env), True)
        write(body, "A clean description.\n")
        check("clean file allowed", allowed(bash(f.app, "gh pr create --body-file " + body),
                                            f.env), True)
        write(os.path.join(f.app, "rel.md"), "mentions module_a.py\n")
        check("relative file leak denied", denied(bash(
            f.app, "gh pr edit 3 --body-file rel.md"), f.env), True)


def test_gh_dash_R_public_slug_from_private_cwd_scanned():
    with fam() as f:
        lib_leak(f)
        cmd = "gh issue create -R acme/app --title t --body 'see module_a.py'"
        check("scanned from the private row", denied(bash(f.lib, cmd), f.env), True)
        cmd = "gh issue create --repo acme/app --title t --body 'a clean body'"
        check("clean text allowed", allowed(bash(f.lib, cmd), f.env), True)
        cmd = "gh issue create -R acme/lib --title t --body 'see module_a.py'"
        check("private target is not scanned", allowed(bash(f.lib, cmd), f.env), True)


def test_gh_issue_view_on_public_allowed():
    with fam() as f:
        lib_leak(f)
        check("view allowed", allowed(bash(f.app, "gh issue view 3 --json body"), f.env),
              True)
        check("pr list mentioning a private name allowed", allowed(bash(
            f.app, "gh pr list --search module_a.py"), f.env), True)


def test_mcp_write_to_public_slug_denied():
    with fam() as f:
        pl = payload("mcp__github__create_issue", f.lib, owner="acme", repo="app",
                     slug="acme/app", title="t")
        v, reason = verdict(pl, f.env)
        check("denied", v == "deny" and reason.startswith(PREFIX), True)
        check("says to use git or gh", "git or gh" in reason, True)
        pl = payload("mcp__github__create_issue", f.lib, slug="acme/lib", title="t")
        check("private slug allowed", allowed(pl, f.env), True)
        pl = payload("mcp__github__create_issue", f.lib, slug="other/thing", title="t")
        check("unrelated slug allowed", allowed(pl, f.env), True)


def test_mcp_read_allowed():
    with fam() as f:
        pl = payload("mcp__github__get_file_contents", f.lib, slug="acme/app", path="a")
        check("read allowed", allowed(pl, f.env), True)
        pl = payload("mcp__github__list_issues", f.lib, slug="acme/app")
        check("list allowed", allowed(pl, f.env), True)



TESTS = (
    test_unapproved_push_refused,
    test_agent_unapproved_push_refused_with_message,
    test_human_unapproved_push_allowed,
    test_human_approved_push_is_silent,
    test_agent_approved_push_allowed,
    test_empty_marker_is_a_human_push,
    test_approved_push_allowed,
    test_approval_is_full_sha_of_tip,
    test_push_from_worktree_uses_shared_hook,
    test_scripted_push_refused,
    test_push_tags_unapproved_refused,
    test_push_delete_branch_allowed,
    test_internal_error_refuses_push,
    test_config_error_refuses_push,
    test_python_missing_refuses_push,
    test_non_strict_row_exits_immediately,
    test_install_chains_existing_hook,
    test_install_is_idempotent,
    test_install_honours_core_hookspath,
    test_check_reports_missing_and_installed,
    test_check_reports_missing_when_hook_target_gone,
    test_write_to_approvals_refused_any_seat,
    test_multiedit_approvals_refused,
    test_write_symlink_to_approvals_tsv_refused,
    test_bash_stu_approve_refused,
    test_bash_stu_approve_py_refused,
    test_bash_echo_into_approvals_refused,
    test_write_approvals_py_in_unconfigured_repo_allowed,
    test_bash_grep_approvals_in_source_allowed,
    test_bash_commit_message_mentioning_approvals_allowed,
    test_other_tools_approvals_dir_allowed,
    test_no_verify_on_strict_row_refused,
    test_no_verify_from_worktree_outside_worktrees_dir_refused,
    test_core_hookspath_override_on_strict_row_refused,
    test_no_verify_on_private_row_allowed,
    test_variable_target_in_family_cwd_denied,
    test_flat_strict_row_matched_via_cwd,
    test_pr_body_command_substitution_in_private_row_allowed,
    test_push_branch_substitution_in_flat_private_row_allowed,
    test_launcher_unrelated_payload_no_python,
    test_launcher_python_missing_denies_relevant_payload,
    test_systemexit_in_resolve_is_caught,
    test_crash_in_unconfigured_repo_allows,
    test_crash_on_claimed_path_denies,
    test_hook_entry_has_onfailure_block,
    test_unreadable_config_no_verify_denied,
    test_unreadable_config_unrelated_bash_allowed,
    test_unreadable_config_named_from_outside_denied,
    test_root_like_path_in_broken_config_never_matches,
    test_stu_config_without_row_allows,
    test_tilde_row_path_matches_when_resolve_fails,
    test_stu_approve_cli_appends_row,
    test_stu_approve_stores_full_sha,
    test_stu_approve_unknown_sha_rejected,
    test_leak_in_commit_message_refused,
    test_leak_refused_for_unmarked_and_agent_pushes_alike,
    test_leak_in_added_line_refused,
    test_leak_after_plus_plus_content_line_refused,
    test_leak_in_branch_name_refused,
    test_public_tag_message_leak_refused,
    test_issue_ref_pattern_refused,
    test_pin_file_slug_allowed,
    test_pin_file_with_private_path_refused,
    test_pin_file_with_issue_reference_refused,
    test_shared_basename_not_flagged,
    test_common_word_basename_not_flagged,
    test_common_extensionless_basename_not_flagged,
    test_case_variant_of_public_file_not_flagged,
    test_shared_org_not_flagged,
    test_vendored_private_path_not_in_list,
    test_bare_name_and_tag_allowed,
    test_cache_key_includes_public_head,
    test_scan_10k_file_private_repo_2k_line_diff_under_5s,
    test_new_branch_range_from_base,
    test_new_branch_no_base_clean_not_refused,
    test_new_branch_no_base_leak_refused,
    test_new_branch_deleted_tracking_ref_leak_refused,
    test_gh_pr_create_heredoc_leak_on_public_refused,
    test_gh_pr_create_clean_on_public_allowed,
    test_gh_body_file_leak_refused,
    test_gh_dash_R_public_slug_from_private_cwd_scanned,
    test_gh_issue_view_on_public_allowed,
    test_mcp_write_to_public_slug_denied,
    test_mcp_read_allowed,
)


def main():
    for t in TESTS:
        CURRENT[0] = t.__name__
        before = len(FAILURES)
        try:
            t()
        except Exception as e:  # noqa: BLE001  a crashed case is a red case, not a crash
            COUNT[0] += 1
            FAILURES.append("%s: raised %s: %s" % (t.__name__, type(e).__name__, e))
        if len(FAILURES) > before:
            RED.append(t.__name__)
    if FAILURES:
        print("FAIL: %d of %d checks, %d of %d cases red" % (
            len(FAILURES), COUNT[0], len(RED), len(TESTS)))
        for name in RED:
            print("  red: " + name)
        for m in FAILURES:
            print("  - " + m[:300])
        return 1
    print("ok: %d checks in %d cases" % (COUNT[0], len(TESTS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
