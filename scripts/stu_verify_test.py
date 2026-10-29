#!/usr/bin/env python3
"""Regression suite for stu_verify.py. A fake STU_ENV_CMD, real temp git repos, no network.

Run: python3 scripts/stu_verify_test.py
"""
import os
import re
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "stu_verify.py")
FAILURES = []
COUNT = [0]
TMP = tempfile.mkdtemp(prefix="stu-verify-test-")

FAKE_ENV = """#!/bin/sh
# fake stu-env: $STUV_DIR/<id> holds the command lines; $STUV_DIR/env holds KEY=VALUE lines
if [ "$1" = "commands" ]; then
  [ -f "$STUV_DIR/$2" ] && cat "$STUV_DIR/$2"
  exit 0
fi
cat "$STUV_DIR/env"
"""


def check(name, got, want):
    COUNT[0] += 1
    if got != want:
        FAILURES.append("%s: got %r, want %r" % (name, got, want))


def git(repo, *args):
    p = subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True,
                       check=True, env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e",
                                            GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e"))
    return p.stdout.strip()


def make_case(name, setup=(), commands=(), timeout="60"):
    """-> dict(repo, run_home, dir, sha, env). Two commits: sha is the first."""
    base = os.path.join(TMP, name)
    repo = os.path.join(base, "repo")
    os.makedirs(repo)
    git(repo, "init", "-q", "-b", "main")
    with open(os.path.join(repo, "marker"), "w") as f:
        f.write("first\n")
    git(repo, "add", "marker")
    git(repo, "commit", "-q", "-m", "first")
    sha = git(repo, "rev-parse", "HEAD")
    with open(os.path.join(repo, "marker"), "w") as f:
        f.write("second\n")
    git(repo, "commit", "-q", "-am", "second")
    d = os.path.join(base, "cfg")
    os.makedirs(d)
    run_home = os.path.join(base, "home")
    with open(os.path.join(d, "env"), "w") as f:
        f.write("MAIN_CHECKOUT='%s'\nRUN_HOME='%s'\nCI_TIMEOUT='%s'\n" % (repo, run_home, timeout))
    for cid, lines in (("verification-setup", setup), ("verification-commands", commands)):
        if lines:
            with open(os.path.join(d, cid), "w") as f:
                f.write("\n".join(lines) + "\n")
    fake = os.path.join(base, "fake-stu-env")
    with open(fake, "w") as f:
        f.write(FAKE_ENV)
    os.chmod(fake, 0o755)
    env = dict(os.environ, STU_ENV_CMD=fake, STUV_DIR=d)
    return {"repo": repo, "home": run_home, "sha": sha, "env": env}


def run(c, *args):
    p = subprocess.run([sys.executable, SCRIPT, "--repo", "app", "--sha", c["sha"]] + list(args),
                       capture_output=True, text=True, env=c["env"], timeout=60)
    return p.returncode, p.stdout.strip(), p.stderr


LINE = re.compile(r"^VERIFY: (PASS|FAIL|PENDING) sha=([0-9a-f]{40}) cmds=(\d+) "
                  r"failed=(\d+|none) rc=(-?\d+|-) log=(\S+)$")


def parse(out):
    m = LINE.match(out)
    return m.groups() if m else None


def finish(c, secs="30"):
    run(c, "--start")
    return run(c, "--wait", secs)


def test_verify_pass_records_counts():
    c = make_case("pass", commands=["true", "echo hi"])
    rc, out, _ = finish(c)
    g = parse(out)
    check("pass.rc", rc, 0)
    check("pass.line", bool(g), True)
    if g:
        check("pass.fields", g[:5], ("PASS", c["sha"], "2", "none", "0"))
        check("pass.log", os.path.isfile(g[5]) and "hi" in open(g[5]).read(), True)
    check("pass.one-line", len(out.splitlines()), 1)
    check("pass.worktree-removed", os.path.exists(os.path.join(c["home"], "verify", c["sha"])), False)


def test_verify_nonzero_is_fail_with_index():
    c = make_case("nonzero", commands=["true", "exit 3", "true"])
    _, out, _ = finish(c)
    g = parse(out)
    check("nonzero.line", bool(g), True)
    if g:
        check("nonzero.fields", g[:5], ("FAIL", c["sha"], "3", "2", "3"))


def test_verify_zero_commands_is_fail():
    c = make_case("zero")
    _, out, _ = finish(c)
    g = parse(out)
    check("zero.line", bool(g), True)
    if g:
        check("zero.fields", (g[0], g[2]), ("FAIL", "0"))


def test_verify_long_command_backgrounded():
    c = make_case("long", commands=["sleep 4"])
    t0 = time.time()
    rc, _, _ = run(c, "--start")
    check("long.start-rc", rc, 0)
    check("long.start-returns-at-once", time.time() - t0 < 3, True)
    _, out, _ = run(c, "--wait", "1")
    g = parse(out)
    check("long.pending", g[0] if g else None, "PENDING")
    _, out, _ = run(c, "--wait", "30")
    g = parse(out)
    check("long.then-pass", g[0] if g else None, "PASS")


def test_verify_setup_runs_before_commands():
    c = make_case("order", setup=["echo setup > order.txt"],
                  commands=["test \"$(cat order.txt)\" = setup", "echo more >> order.txt"])
    _, out, _ = finish(c)
    g = parse(out)
    check("order.fields", g[:5] if g else None, ("PASS", c["sha"], "3", "none", "0"))


def test_verify_timeout_is_fail():
    c = make_case("timeout", commands=["sleep 30"], timeout="1")
    t0 = time.time()
    _, out, _ = finish(c, "20")
    g = parse(out)
    check("timeout.fields", g[:5] if g else None, ("FAIL", c["sha"], "1", "1", "124"))
    check("timeout.fast", time.time() - t0 < 15, True)


def test_verify_result_reused_for_same_sha():
    c = make_case("reuse", commands=["echo ran >> %s" % os.path.join(TMP, "reuse.count")])
    _, first, _ = finish(c)
    _, second, _ = finish(c)
    check("reuse.same-line", first == second and bool(parse(first)), True)
    path = os.path.join(TMP, "reuse.count")
    check("reuse.ran-once", open(path).read().splitlines() if os.path.exists(path) else [], ["ran"])


def _count(name):
    path = os.path.join(TMP, name + ".count")
    return open(path).read().splitlines() if os.path.exists(path) else []


def _set_commands(c, lines):
    with open(os.path.join(c["env"]["STUV_DIR"], "verification-commands"), "w") as f:
        f.write("\n".join(lines) + "\n")


def _status(out):
    g = parse(out)
    return g[0] if g else None


def test_verify_fail_reused_by_plain_start():
    path = os.path.join(TMP, "failreuse.count")
    c = make_case("failreuse", commands=["echo ran >> %s" % path, "exit 1"])
    _, first, _ = finish(c)
    _, second, _ = finish(c)
    check("failreuse.first", _status(first), "FAIL")
    check("failreuse.second", _status(second), "FAIL")
    check("failreuse.ran-once", _count("failreuse"), ["ran"])


def test_verify_retry_reruns_cached_fail():
    path = os.path.join(TMP, "retryfail.count")
    c = make_case("retryfail", commands=["echo ran >> %s" % path, "exit 1"])
    _, first, _ = finish(c)
    check("retryfail.first", _status(first), "FAIL")
    _set_commands(c, ["echo ran >> %s" % path])
    rc, _, _ = run(c, "--retry")
    check("retryfail.retry-rc", rc, 0)
    _, out, _ = run(c, "--wait", "30")
    g = parse(out)
    check("retryfail.new-status", g[:5] if g else None, ("PASS", c["sha"], "1", "none", "0"))
    check("retryfail.ran-twice", _count("retryfail"), ["ran", "ran"])


def test_verify_retry_keeps_cached_pass():
    path = os.path.join(TMP, "retrypass.count")
    c = make_case("retrypass", commands=["echo ran >> %s" % path])
    _, first, _ = finish(c)
    check("retrypass.first", _status(first), "PASS")
    _set_commands(c, ["exit 1"])
    run(c, "--retry")
    _, out, _ = run(c, "--wait", "30")
    check("retrypass.still-pass", out, first)
    check("retrypass.ran-once", _count("retrypass"), ["ran"])


def test_verify_retry_only_once_per_sha():
    path = os.path.join(TMP, "retryonce.count")
    c = make_case("retryonce", commands=["echo ran >> %s" % path, "exit 1"])
    finish(c)
    run(c, "--retry")
    _, second, _ = run(c, "--wait", "30")
    check("retryonce.second", _status(second), "FAIL")
    run(c, "--retry")
    _, third, _ = run(c, "--wait", "30")
    check("retryonce.third", _status(third), "FAIL")
    check("retryonce.ran-twice", _count("retryonce"), ["ran", "ran"])


def test_verify_retry_without_result_acts_as_start():
    path = os.path.join(TMP, "retryfresh.count")
    c = make_case("retryfresh", commands=["echo ran >> %s" % path])
    run(c, "--retry")
    _, out, _ = run(c, "--wait", "30")
    check("retryfresh.status", _status(out), "PASS")
    check("retryfresh.ran-once", _count("retryfresh"), ["ran"])


def test_verify_retry_marker_without_result_counts_as_the_retry():
    # State left by a kill after the marker was written but before the result was removed.
    path = os.path.join(TMP, "retrycrash.count")
    c = make_case("retrycrash", commands=["echo ran >> %s" % path, "exit 1"])
    finish(c)
    base = os.path.join(c["home"], "verify")
    open(os.path.join(base, c["sha"] + ".retry"), "w").write("1\n")
    os.remove(os.path.join(base, c["sha"] + ".result"))
    run(c, "--retry")
    _, second, _ = run(c, "--wait", "30")
    check("retrycrash.second", _status(second), "FAIL")
    run(c, "--retry")
    _, third, _ = run(c, "--wait", "30")
    check("retrycrash.third", _status(third), "FAIL")
    check("retrycrash.ran-twice", _count("retrycrash"), ["ran", "ran"])


def test_verify_retry_with_marker_and_result_still_reruns():
    # Kill after the marker but before the discard: the FAIL is still cached, retry must act.
    path = os.path.join(TMP, "retryhalf.count")
    c = make_case("retryhalf", commands=["echo ran >> %s" % path, "exit 1"])
    finish(c)
    base = os.path.join(c["home"], "verify")
    open(os.path.join(base, c["sha"] + ".retry"), "w").write("1\n")
    run(c, "--retry")
    _, second, _ = run(c, "--wait", "30")
    check("retryhalf.second", _status(second), "FAIL")
    check("retryhalf.ran-twice", _count("retryhalf"), ["ran", "ran"])
    run(c, "--retry")
    run(c, "--wait", "30")
    check("retryhalf.still-twice", _count("retryhalf"), ["ran", "ran"])


def test_verify_runs_at_sha_not_worktree_head():
    c = make_case("atsha", commands=["true"])
    with open(os.path.join(c["env"]["STUV_DIR"], "verification-commands"), "w") as f:
        f.write('test "$(cat marker)" = first\ntest "$(git rev-parse HEAD)" = %s\n' % c["sha"])
    _, out, _ = finish(c)
    g = parse(out)
    check("atsha.fields", g[:5] if g else None, ("PASS", c["sha"], "2", "none", "0"))


def test_verify_untracked_file_keeps_worktree_without_force():
    c = make_case("untracked", commands=["echo left > leftover.txt"])
    _, out, _ = finish(c)
    g = parse(out)
    check("untracked.fields", g[:5] if g else None, ("PASS", c["sha"], "1", "none", "0"))
    wt = os.path.join(c["home"], "verify", c["sha"])
    check("untracked.worktree-kept", os.path.isfile(os.path.join(wt, "leftover.txt")), True)
    log = open(g[5]).read() if g else ""
    check("untracked.log-note", "worktree not removed" in log, True)


def test_verify_result_is_published_after_the_log_is_final():
    # A git shim on the runner's PATH stalls the worktree removal, so a result published before
    # the removal note is written would be observable here every time, not once in a while.
    c = make_case("lognote", commands=["echo left > leftover.txt"])
    shim_dir = os.path.join(TMP, "lognote", "shim")
    os.makedirs(shim_dir)
    real_git = subprocess.run(["which", "git"], capture_output=True, text=True,
                              check=True).stdout.strip()
    with open(os.path.join(shim_dir, "git"), "w") as f:
        f.write('#!/bin/sh\ncase " $* " in *" worktree remove "*) sleep 2;; esac\n'
                'exec "%s" "$@"\n' % real_git)
    os.chmod(os.path.join(shim_dir, "git"), 0o755)
    c["env"] = dict(c["env"], PATH=shim_dir + os.pathsep + c["env"]["PATH"])
    _, out, _ = finish(c)
    g = parse(out)
    check("lognote.fields", g[:5] if g else None, ("PASS", c["sha"], "1", "none", "0"))
    log = open(g[5]).read() if g else ""
    check("lognote.log-final-at-result", "worktree not removed" in log, True)


def test_usage_errors():
    c = make_case("usage", commands=["true"])
    rc, _, err = run(c, "--wait", "600")
    check("usage.wait-cap-rc", rc, 2)
    check("usage.wait-cap-msg", "540" in err, True)


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    if FAILURES:
        for f in FAILURES:
            print("FAIL " + f)
        print("%d of %d checks failed" % (len(FAILURES), COUNT[0]))
        return 1
    print("stu_verify_test: %d checks ok" % COUNT[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
