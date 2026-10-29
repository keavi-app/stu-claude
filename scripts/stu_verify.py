#!/usr/bin/env python3
"""stu-verify: run a repo's verification commands at one commit, in the background.

  stu-verify --repo NAME --sha X --start        create the worktree, spawn the runner, return
  stu-verify --repo NAME --sha X --retry        as --start, but a cached FAIL is discarded and
      re-run once (see below)
  stu-verify --repo NAME --sha X --wait SECS    poll (SECS <= 540), print exactly one line:
      VERIFY: PASS|FAIL|PENDING sha=<full> cmds=<n> failed=<index|none> rc=<rc|-> log=<path>

Commands come from `stu-env commands verification-setup|verification-commands --repo NAME`
(setup lines first); `cmds` counts both, `failed` is the 1-based index of the first failure.
Each command runs under CI_TIMEOUT (rc 124 on timeout). Zero verification commands is FAIL.
A finished result for the same sha is reused, never re-run, with one exception: --retry discards
a cached FAIL and runs the commands again, once per sha. The new result is marked "retried", so a
second --retry on a retried FAIL (or on a PASS) changes nothing. The worktree lives at
RUN_HOME/verify/<sha> and is removed (no --force) once a result exists.
"""
import json
import os
import shlex
import signal
import subprocess
import sys
import time

MAX_WAIT = 540
DEFAULT_TIMEOUT = 1800
HERE = os.path.dirname(os.path.abspath(__file__))


class Usage(Exception):
    pass


def _env_cmd():
    cmd = os.environ.get("STU_ENV_CMD")
    return shlex.split(cmd) if cmd else [os.path.join(HERE, "..", "bin", "stu-env")]


def _stu_env(args):
    p = subprocess.run(_env_cmd() + args, capture_output=True, text=True)
    if p.returncode != 0:
        raise Usage("stu-env %s failed (exit %d): %s" % (" ".join(args), p.returncode,
                                                         p.stderr.strip().splitlines()[0]
                                                         if p.stderr.strip() else ""))
    return p.stdout


def _load(repo):
    env = {}
    for line in _stu_env(["--repo", repo]).splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            parts = shlex.split(v)
            env[k] = parts[0] if parts else ""
    for k in ("MAIN_CHECKOUT", "RUN_HOME"):
        if not env.get(k):
            raise Usage("stu-env did not report %s for row %s" % (k, repo))
    env["RUN_HOME"] = os.path.expanduser(env["RUN_HOME"])
    try:
        env["_TIMEOUT"] = float(env.get("CI_TIMEOUT") or DEFAULT_TIMEOUT)
    except ValueError:
        env["_TIMEOUT"] = DEFAULT_TIMEOUT
    return env


def _commands(repo):
    out = []
    for sec in ("verification-setup", "verification-commands"):
        out.append([l for l in _stu_env(["commands", sec, "--repo", repo]).splitlines() if l])
    return out


def _git(checkout, *args):
    return subprocess.run(["git", "-C", checkout] + list(args), capture_output=True, text=True)


def _paths(env, sha):
    base = os.path.join(env["RUN_HOME"], "verify")
    return {"dir": base, "wt": os.path.join(base, sha), "log": os.path.join(base, sha + ".log"),
            "result": os.path.join(base, sha + ".result"),
            "retry": os.path.join(base, sha + ".retry"), "pid": os.path.join(base, sha + ".pid")}


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read_pid(path):
    try:
        with open(path) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def _write_result(p, res):
    tmp = p["result"] + ".tmp"
    with open(tmp, "w") as f:
        json.dump(res, f)
    os.replace(tmp, p["result"])


def _run_one(cmd, cwd, log, timeout):
    with open(log, "ab") as lf:
        lf.write(("\n$ %s\n" % cmd).encode())
        lf.flush()
        proc = subprocess.Popen(["sh", "-c", cmd], cwd=cwd, stdout=lf, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True)
        try:
            return proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
            proc.wait()
            lf.write(("\n[stu-verify] timed out after %ss\n" % timeout).encode())
            return 124


def runner(repo, sha):
    env = _load(repo)
    p = _paths(env, sha)
    setup, cmds = _commands(repo)
    allc = setup + cmds
    res = {"sha": sha, "cmds": len(allc) if cmds else 0, "failed": None, "rc": None,
           "status": "PASS"}
    if not cmds:
        res["status"] = "FAIL"
        with open(p["log"], "ab") as lf:
            lf.write(b"[stu-verify] no verification commands configured\n")
    else:
        for i, c in enumerate(allc, 1):
            rc = _run_one(c, p["wt"], p["log"], env["_TIMEOUT"])
            if rc != 0:
                res.update(status="FAIL", failed=i, rc=rc)
                break
        else:
            res["rc"] = 0
    if os.path.exists(p["retry"]):
        res["retried"] = True
    # The result is published last: its existence means the run, its log and its cleanup are
    # finished. It is written even if the cleanup raises, so a SHA is never left without one.
    try:
        r = _git(env["MAIN_CHECKOUT"], "worktree", "remove", p["wt"])
        if r.returncode != 0:
            with open(p["log"], "ab") as lf:
                lf.write(("[stu-verify] worktree not removed: %s\n" % r.stderr.strip()).encode())
    finally:
        _write_result(p, res)
    return 0


def _resolve_sha(env, sha):
    r = _git(env["MAIN_CHECKOUT"], "rev-parse", "--verify", sha + "^{commit}")
    if r.returncode != 0:
        raise Usage("cannot resolve %s in %s" % (sha, env["MAIN_CHECKOUT"]))
    return r.stdout.strip()


def _discard_failed(env, p):
    """Drop a cached non-retried FAIL and its per-sha state. True if discarded."""
    try:
        with open(p["result"]) as f:
            res = json.load(f)
    except (OSError, ValueError):
        return False
    if res.get("status") != "FAIL" or res.get("retried"):
        return False
    # Marker first and durable: a kill after this point still leaves the retry recorded, so the
    # next run is marked retried whether or not the result below was removed.
    with open(p["retry"], "w") as f:
        f.write("1\n")
        f.flush()
        os.fsync(f.fileno())
    if os.path.exists(p["wt"]):
        _git(env["MAIN_CHECKOUT"], "worktree", "remove", "--force", p["wt"])
    for k in ("result", "pid", "log"):
        try:
            os.remove(p[k])
        except OSError:
            pass
    return True


def start(repo, sha_arg, retry=False):
    env = _load(repo)
    sha = _resolve_sha(env, sha_arg)
    p = _paths(env, sha)
    os.makedirs(p["dir"], exist_ok=True)
    if os.path.exists(p["result"]) and not (retry and _discard_failed(env, p)):
        return 0
    pid = _read_pid(p["pid"])
    if pid and _alive(pid):
        return 0
    if os.path.exists(p["wt"]):
        _git(env["MAIN_CHECKOUT"], "worktree", "remove", p["wt"])
    r = _git(env["MAIN_CHECKOUT"], "worktree", "add", "--detach", p["wt"], sha)
    if r.returncode != 0:
        raise Usage("git worktree add failed: %s" % r.stderr.strip())
    open(p["log"], "wb").close()
    proc = subprocess.Popen([sys.executable, os.path.abspath(__file__), "--runner", "--repo", repo,
                             "--sha", sha], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=True,
                            env=dict(os.environ))
    with open(p["pid"], "w") as f:
        f.write(str(proc.pid))
    return 0


def _line(status, sha, res, log):
    failed = res.get("failed") if res else None
    rc = res.get("rc") if res else None
    return "VERIFY: %s sha=%s cmds=%d failed=%s rc=%s log=%s" % (
        status, sha, (res or {}).get("cmds", 0), "none" if failed is None else failed,
        "-" if rc is None else rc, log)


def wait(repo, sha_arg, secs):
    env = _load(repo)
    sha = _resolve_sha(env, sha_arg)
    p = _paths(env, sha)
    deadline = time.time() + secs
    while True:
        if os.path.exists(p["result"]):
            with open(p["result"]) as f:
                res = json.load(f)
            print(_line(res["status"], sha, res, p["log"]))
            return 0
        pid = _read_pid(p["pid"])
        if pid is None:
            raise Usage("no verification started for %s; run --start first" % sha)
        if not _alive(pid) and not os.path.exists(p["result"]):
            print(_line("FAIL", sha, {"cmds": 0}, p["log"]))
            return 0
        if time.time() >= deadline:
            print(_line("PENDING", sha, None, p["log"]))
            return 0
        time.sleep(0.5)


def main(argv):
    try:
        a, repo, sha, secs, mode = argv[1:], None, None, None, None
        i = 0
        while i < len(a):
            x = a[i]
            if x in ("--repo", "--sha", "--wait") and i + 1 < len(a):
                if x == "--repo":
                    repo = a[i + 1]
                elif x == "--sha":
                    sha = a[i + 1]
                else:
                    mode = "wait"
                    try:
                        secs = int(a[i + 1])
                    except ValueError:
                        raise Usage("--wait needs whole seconds")
                i += 2
            elif x in ("--start", "--retry", "--runner"):
                mode = x[2:]
                i += 1
            else:
                raise Usage("unexpected argument %s" % x)
        if not repo or not sha or not mode:
            raise Usage("usage: stu-verify --repo NAME --sha X (--start | --retry | --wait SECS)")
        if mode == "wait" and not 0 <= secs <= MAX_WAIT:
            raise Usage("--wait SECS must be 0..%d (a foreground call is capped at 10 minutes)"
                        % MAX_WAIT)
        if mode == "runner":
            return runner(repo, sha)
        if mode in ("start", "retry"):
            return start(repo, sha, retry=mode == "retry")
        return wait(repo, sha, secs)
    except Usage as e:
        sys.stderr.write("stu-verify: %s\n" % e)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
