#!/usr/bin/env python3
"""Regression suite for stu_forge.py (forge facts). Fake `gh` (tests/fake_gh.py) for forge
reads; real temp git repos and bare remotes for the git verbs. Nothing touches the network.

Run: python3 scripts/stu_forge_test.py
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FAKE_GH = os.path.join(os.path.dirname(HERE), "tests", "fake_gh.py")
SCRIPT = os.path.join(HERE, "stu_forge.py")
FAILURES = []
COUNT = [0]
S = "acme/app"
TMP = tempfile.mkdtemp(prefix="stu-forge-test-")
SHA = "a" * 40
SHA2 = "b" * 40


def check(name, got, want):
    COUNT[0] += 1
    if got != want:
        FAILURES.append("%s: got %r, want %r" % (name, got, want))


def forge(args, fixtures=None, extra_env=None, cwd=None):
    """-> (rc, stdout lines, gh argv log lines, gh env log lines)."""
    d = os.path.join(TMP, "ghbin")
    os.makedirs(d, exist_ok=True)
    link = os.path.join(d, "gh")
    if not os.path.exists(link):
        os.symlink(FAKE_GH, link)
    paths = {k: os.path.join(TMP, k) for k in ("fixtures.json", "gh.log", "gh.env", "gh.state")}
    for k in ("gh.log", "gh.env", "gh.state"):
        if os.path.exists(paths[k]):
            os.remove(paths[k])
    with open(paths["fixtures.json"], "w") as f:
        json.dump(fixtures or {}, f)
    env = dict(os.environ)
    env.pop("GH_HOST", None)
    env.pop("GH_REPO", None)
    env.update({"PATH": d + os.pathsep + env["PATH"], "FAKE_GH_FIXTURES": paths["fixtures.json"],
                "FAKE_GH_LOG": paths["gh.log"], "FAKE_GH_ENV_LOG": paths["gh.env"],
                "FAKE_GH_STATE": paths["gh.state"], "STU_FORGE_REQUERY_DELAY": "0"})
    env.update(extra_env or {})
    p = subprocess.run([sys.executable, SCRIPT] + list(args), capture_output=True, text=True,
                       env=env, cwd=cwd)

    def rd(k):
        try:
            with open(paths[k]) as f:
                return f.read().splitlines()
        except OSError:
            return []
    return p.returncode, p.stdout.splitlines(), rd("gh.log"), rd("gh.env")


def ok(lines):
    return lines[:-1] if lines and lines[-1] == "OK" else None


def err(lines):
    return lines[-1] if lines and lines[-1].startswith("ERROR ") else None


def errcls(lines):
    e = err(lines)
    return e.split()[1] if e else None


def pages(*ps):
    return {"json": list(ps)}


def pr_doc(**kw):
    d = {"state": "OPEN", "headRefName": "feat", "headRefOid": SHA, "baseRefName": "main",
         "mergeCommit": None, "labels": [], "autoMergeRequest": None,
         "url": "https://github.com/acme/app/pull/5", "mergeable": "MERGEABLE",
         "mergeStateStatus": "BLOCKED"}
    d.update(kw)
    return {"json": d}


def cr(i, name, conclusion="success", status="completed", app="actions", url=None, title=""):
    return {"id": i, "name": name, "status": status, "conclusion": conclusion,
            "app": {"slug": app},
            "details_url": url or "https://github.com/acme/app/actions/runs/900%d/job/1" % i,
            "output": {"title": title}}


def st(ctx, state, login="bot", updated="2026-01-01T00:00:00Z", desc=""):
    return {"context": ctx, "state": state, "creator": {"login": login}, "updated_at": updated,
            "description": desc}


CR_KEY = "api repos/%s/commits/%s/check-runs" % (S, SHA)
ST_KEY = "api repos/%s/commits/%s/statuses" % (S, SHA)


def checks_fx(runs, stats=None, rc=0, stderr=""):
    return {CR_KEY: dict(pages({"check_runs": runs}), rc=rc, stderr=stderr),
            ST_KEY: pages(stats or [])}


def checks(fx):
    rc, lines, _, _ = forge(["checks", "--slug", S, "--sha", SHA], fx)
    return rc, lines


# ---- pr-state, checks ---------------------------------------------------------------------

def test_pr_state():
    rc, lines, _, _ = forge(["pr-state", "--slug", S, "--pr", "5"], {"pr view 5": pr_doc(
        labels=[{"name": "ready"}, {"name": "x"}], autoMergeRequest={"enabledBy": {}})})
    check("pr_state_open", (rc, lines), (0, [
        "STATE open", "HEAD_REF feat", "HEAD_SHA " + SHA, "BASE_REF main", "MERGE_COMMIT -",
        "SLUG acme/app", "LABELS ready,x", "AUTO_MERGE on", "OK"]))
    rc, lines, _, _ = forge(["pr-state", "--slug", S, "--pr", "5"], {"pr view 5": pr_doc(
        state="MERGED", mergeCommit={"oid": SHA2})})
    check("pr_state_merged", (lines[0], lines[4], lines[6], lines[7]),
          ("STATE merged", "MERGE_COMMIT " + SHA2, "LABELS -", "AUTO_MERGE off"))


def test_checks():
    runs = [cr(1, "build / unit"), cr(2, "lint", "failure"), cr(3, "e2e", None, "in_progress"),
            cr(4, "docs", "skipped"), cr(5, "opt", "neutral")]
    rc, lines = checks(checks_fx(runs, [st("ci/legacy", "error", "ci-bot", desc="legacy ci")]))
    check("checks_mixed_shapes", (rc, lines), (0, [
        "CHECK success app:actions 9001 build%20/%20unit -",
        "CHECK failure app:actions 9002 lint -",
        "CHECK pending app:actions 9003 e2e -",
        "CHECK skipped app:actions 9004 docs -",
        "CHECK neutral app:actions 9005 opt -",
        "CHECK failure status:ci-bot - ci/legacy legacy%20ci", "OK"]))
    rc, lines = checks(checks_fx([cr(1, 'gate/q"x, 100%\tz'), cr(2, "a,b")]))
    check("checks_encodes_only_percent_space_comma_tab", lines, [
        'CHECK success app:actions 9001 gate/q"x%2C%20100%25%09z -',
        "CHECK success app:actions 9002 a%2Cb -", "OK"])
    rc, lines = checks(checks_fx([cr(1, "t", "failure"), cr(7, "t", "success")]))
    check("checks_newest_wins runs", lines, ["CHECK success app:actions 9007 t -", "OK"])
    rc, lines = checks(checks_fx([], [st("c", "failure", updated="2026-01-01T00:00:00Z"),
                                      st("c", "success", updated="2026-02-01T00:00:00Z")]))
    check("checks_newest_wins statuses", lines, ["CHECK success status:bot - c -", "OK"])
    rc, lines = checks(checks_fx([cr(1, "t", "success"), cr(8, "t", "cancelled")]))
    check("checks_cancelled_newest_is_pending", lines, ["CHECK pending app:actions 9008 t -", "OK"])
    rc, lines = checks(checks_fx([cr(1, "t", app="one"), cr(2, "t", "failure", app="two")]))
    check("checks_duplicate_name_other_app", lines, [
        "CHECK success app:one 9001 t -", "CHECK failure app:two 9002 t -", "OK"])
    rc, lines = checks(checks_fx([cr(1, "build and test (3.9)")]))
    check("checks_name_with_spaces", lines[0], "CHECK success app:actions 9001 build%20and%20test%20(3.9) -")
    rc, lines = checks(checks_fx([cr(1, "a", url="https://x/actions/runs/42/job/7"),
                                  cr(2, "b", url="https://x/other")]))
    check("checks_run_id_from_details_url", lines[:2], [
        "CHECK success app:actions 42 a -", "CHECK success app:actions - b -"])
    rc, lines = checks(checks_fx([], rc=1, stderr="gh: Bad credentials (HTTP 401)"))
    check("checks_401", (rc, err(lines)[:11]), (3, "ERROR auth "))
    rc, lines = checks(checks_fx([], rc=1, stderr="gh: API rate limit exceeded (HTTP 403)"))
    check("checks_403_rate_limit", (rc, errcls(lines)), (3, "rate-limit"))
    rc, lines = checks(checks_fx([cr(1, "t")], rc=1, stderr="unexpected EOF"))
    check("checks_truncated_page", (rc, lines[0].split()[:2], any(l.startswith("CHECK") for l in lines)),
          (3, ["ERROR", "partial"], False))
    rc, lines = checks(checks_fx([]))
    check("checks_empty_rollup", (rc, errcls(lines)), (3, "empty"))


# ---- required-checks, mergeable, repo-settings -----------------------------------------------

RK = "api repos/%s/rules/branches/main" % S


def req(fx):
    rc, lines, _, _ = forge(["required-checks", "--slug", S, "--base", "main"], {RK: fx})
    return rc, lines


def test_required():
    rule = {"type": "required_status_checks", "parameters": {"required_status_checks": [
        {"context": "build / unit"}, {"context": "lint"}]}}
    check("required_checks_rulesets", req(pages([{"type": "pull_request"}, rule])),
          (0, ["REQUIRED build%20/%20unit", "REQUIRED lint", "OK"]))
    check("required_checks_none_readable", req(pages([])), (0, ["REQUIRED_NONE_READABLE none", "OK"]))
    check("required_checks_endpoint_error_is_error",
          (lambda r: (r[0], errcls(r[1])))(req({"rc": 1, "stderr": "gh: Server Error (HTTP 500)"})),
          (3, "forge"))
    check("required_checks_403_upgrade_is_none_readable",
          req({"rc": 1, "stderr": "gh: Upgrade to GitHub Pro or make this repository public (HTTP 403)"}),
          (0, ["REQUIRED_NONE_READABLE plan", "OK"]))
    check("required_checks_403 not available",
          req({"rc": 1, "stderr": "Rules are not available (HTTP 403)"})[1][0], "REQUIRED_NONE_READABLE plan")
    check("required_checks_404_is_none_readable", req({"rc": 1, "stderr": "gh: Not Found (HTTP 404)"}),
          (0, ["REQUIRED_NONE_READABLE unsupported", "OK"]))
    check("required_checks_403_auth_is_error",
          (lambda r: (r[0], errcls(r[1])))(req({"rc": 1, "stderr": "gh: Bad credentials (HTTP 403)"})),
          (3, "auth"))
    check("required_checks_rate_limit_is_error",
          errcls(req({"rc": 1, "stderr": "API rate limit exceeded (HTTP 403)"})[1]), "rate-limit")


def test_mergeable_and_settings():
    rc, lines, _, _ = forge(["mergeable", "--slug", S, "--pr", "5"], {"pr view 5": pr_doc()})
    check("mergeable_blocked_is_reported_not_error", (rc, lines), (0, ["MERGEABLE MERGEABLE BLOCKED", "OK"]))
    rc, lines, calls, _ = forge(["mergeable", "--slug", S, "--pr", "5"], {"pr view 5": [
        pr_doc(mergeable="UNKNOWN", mergeStateStatus="UNKNOWN"), pr_doc(mergeable="CONFLICTING",
                                                                       mergeStateStatus="DIRTY")]})
    check("mergeable_unknown_requeried_once", (lines, len(calls)), (["MERGEABLE CONFLICTING DIRTY", "OK"], 2))
    rc, lines, _, _ = forge(["repo-settings", "--slug", S, "--base", "main"], {
        "api repos/%s" % S: {"json": {"allow_squash_merge": True, "allow_merge_commit": False,
                                      "allow_rebase_merge": False, "allow_auto_merge": True}},
        RK: pages([{"type": "merge_queue"}])})
    check("repo_settings_reports_methods_and_auto_merge", (rc, lines), (0, [
        "SETTING squash on", "SETTING merge off", "SETTING rebase off", "SETTING auto_merge on",
        "SETTING merge_queue on", "OK"]))
    rc, lines, _, _ = forge(["repo-settings", "--slug", S, "--base", "main"], {
        "api repos/%s" % S: {"json": {"allow_squash_merge": True, "allow_merge_commit": True,
                                      "allow_rebase_merge": True, "allow_auto_merge": False}},
        RK: {"rc": 1, "stderr": "Not Found (HTTP 404)"}})
    check("repo_settings merge_queue unreadable omitted", any("merge_queue" in l for l in lines), False)
    # `gh repo view --json` has no auto-merge field (gh 2.92 rejects autoMergeAllowed), so the
    # settings come from the REST repo document, which carries all four.
    rc, lines, calls, _ = forge(["repo-settings", "--slug", S], {
        "api repos/%s" % S: {"json": {"allow_squash_merge": False, "allow_merge_commit": True,
                                      "allow_rebase_merge": False, "allow_auto_merge": False}}})
    check("repo_settings_reads_rest_repo_not_repo_view",
          (rc, lines, [c.split()[:2] for c in calls]),
          (0, ["SETTING squash off", "SETTING merge on", "SETTING rebase off",
               "SETTING auto_merge off", "OK"], [["api", "repos/%s" % S]]))
    rc, lines, _, _ = forge(["repo-settings", "--slug", S], {
        "api repos/%s" % S: {"json": {"allow_squash_merge": True, "allow_merge_commit": True,
                                      "allow_rebase_merge": True}}})
    check("repo_settings_missing_field_is_forge_error", (rc, errcls(lines)), (3, "forge"))


# ---- merge, arm, disarm, claim ---------------------------------------------------------------

def test_merge_arm():
    rc, lines, calls, _ = forge(["merge-at", "--slug", S, "--pr", "5", "--sha", SHA, "--method", "squash"],
                                {"pr merge": {"rc": 0}})
    check("merge_at_passes_match_head_commit", (rc, lines, "--match-head-commit " + SHA in calls[0]),
          (0, ["MERGED " + SHA, "OK"], True))
    rc, lines, _, _ = forge(["merge-at", "--slug", S, "--pr", "5", "--sha", SHA, "--method", "merge"],
                            {"pr merge": {"rc": 1, "stderr": "X Pull request merge failed: Head branch was modified. Review and try the merge again."}})
    check("merge_at_wrong_head_is_error", (rc, errcls(lines)), (3, "moved-head"))
    fx = {"pr merge": {"rc": 0}, "pr edit": {"rc": 0}}
    rc, lines, calls, _ = forge(["arm", "--slug", S, "--pr", "5", "--sha", SHA, "--method", "squash",
                                 "--label", "ready"], fx)
    check("arm_passes_match_head_commit", (rc, "--auto" in calls[1] and "--match-head-commit " + SHA in calls[1]),
          (0, True))
    check("arm_label_before_auto", (calls[0].startswith("pr edit"), calls[1].startswith("pr merge"), lines),
          (True, True, ["ARMED label", "ARMED auto", "OK"]))
    rc, lines, calls, _ = forge(["arm", "--slug", S, "--pr", "5", "--sha", SHA, "--method", "squash",
                                 "--label", "ready", "--no-auto"], fx)
    check("arm_no_auto_skips_auto_merge", (len(calls), lines), (1, ["ARMED label", "OK"]))
    rc, lines, _, _ = forge(["arm", "--slug", S, "--pr", "5", "--sha", SHA, "--method", "squash",
                             "--label", "ready"], {"pr edit": {"rc": 0}, "pr merge": {"rc": 1, "stderr": "boom"}})
    check("arm failure names the step", lines[-1].startswith("ERROR forge step=auto"), True)


WF = "api repos/%s/actions/workflows/ci.yml/runs?branch=feat" % S


def run_(i, status, concl=None, sha=SHA):
    return {"id": i, "status": status, "conclusion": concl, "head_sha": sha}


def test_disarm_claim():
    fx = {"pr view 5": pr_doc(), "pr edit": {"rc": 0}, "pr merge": {"rc": 0}, "run cancel": {"rc": 0},
          WF: pages({"workflow_runs": [run_(1, "completed", "success"), run_(2, "in_progress"),
                                       run_(3, "queued", None, SHA2)]})}
    rc, lines, calls, _ = forge(["disarm", "--slug", S, "--pr", "5", "--label", "ready",
                                 "--workflow", "ci.yml"], fx)
    check("disarm_removes_label_disables_auto_cancels_runs", (rc, [
        any("--remove-label ready" in c for c in calls), any("--disable-auto" in c for c in calls),
        any(c.startswith("run cancel 2") for c in calls)]), (0, [True, True, True]))
    check("disarm_cancels_old_sha_runs_on_branch", (any(c.startswith("run cancel 3") for c in calls),
          any(c.startswith("run cancel 1") for c in calls)), (True, False))
    rc, lines, calls, _ = forge(["claim-state", "--slug", S, "--pr", "5", "--label", "ready",
                                 "--workflow", "ci.yml"], dict(fx, **{"pr view 5": pr_doc(
                                     labels=[{"name": "ready"}], autoMergeRequest={"x": 1})}))
    check("claim_state_reports_all_three", (rc, lines), (0, ["LABEL present", "AUTO_MERGE on",
                                                              "RUNS_UNFINISHED 2", "OK"]))
    rc, lines, _, _ = forge(["disarm", "--slug", S, "--pr", "5", "--label", "ready"],
                            {"pr edit": {"rc": 1, "stderr": "nope"}, "pr merge": {"rc": 0}})
    check("disarm continues past a failed step", (lines[0], errcls(lines)), ("DISARMED auto", "forge"))


# ---- runs ------------------------------------------------------------------------------------

def test_runs():
    key = "api repos/%s/actions/workflows/ci.yml/runs?head_sha=%s" % (S, SHA)
    rc, lines, _, _ = forge(["workflow-runs", "--slug", S, "--workflow", "ci.yml", "--sha", SHA], {
        key: pages({"workflow_runs": [run_(5, "completed", "failure"), run_(9, "in_progress")]},
                   {"workflow_runs": [run_(7, "completed", "success")]})})
    check("workflow_runs_newest_first", (rc, lines), (0, ["RUN 9 in_progress -", "RUN 7 completed success",
                                                          "RUN 5 completed failure", "OK"]))
    rc, lines, calls, _ = forge(["workflow-runs", "--slug", S, "--workflow", "ci.yml", "--sha", SHA,
                                 "--event", "pull_request"], {
        key + "&event=pull_request": pages({"workflow_runs": [run_(1, "completed", "success")]},
                                           {"workflow_runs": [run_(2, "completed", "success")]})})
    check("workflow_runs_event_filter_and_pagination", (lines, "event=pull_request" in calls[0]),
          (["RUN 2 completed success", "RUN 1 completed success", "OK"], True))
    rc, lines, _, _ = forge(["run-head", "--slug", S, "--run", "9"], {"run view 9": {"json": {"headSha": SHA}}})
    check("run_head", lines, ["HEAD_SHA " + SHA, "OK"])
    jobs = {"jobs": [{"id": 1, "name": "unit", "status": "completed", "conclusion": "success"},
                     {"id": 2, "name": "integration / linux", "status": "completed", "conclusion": "failure"}]}
    rc, lines, _, _ = forge(["run-jobs", "--slug", S, "--run", "9"],
                            {"api repos/%s/actions/runs/9/jobs" % S: pages(jobs)})
    check("run_jobs_lists_red_job_under_green_rollup", lines, [
        "JOB 1 completed success unit", "JOB 2 completed failure integration%20/%20linux", "OK"])
    rc, lines, calls, _ = forge(["rerun-failed", "--slug", S, "--run", "9"], {"run rerun": {"rc": 0}})
    check("rerun_failed_logs_call", (lines, calls[0].startswith("run rerun 9"), "--failed" in calls[0]),
          (["RERUN 9", "OK"], True, True))


# ---- git helpers -----------------------------------------------------------------------------

def sh(cwd, *cmd):
    return subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def g(cwd, *a):
    return sh(cwd, "git", "-c", "user.name=T", "-c", "user.email=t@e", *a)


def commit(repo, name, msg=None):
    with open(os.path.join(repo, name), "w") as f:
        f.write(name)
    g(repo, "add", name)
    g(repo, "commit", "-q", "-m", msg or name)
    return g(repo, "rev-parse", "HEAD")


def mkrepo():
    """-> (clone, bare remote), branch main with one commit pushed."""
    d = tempfile.mkdtemp(dir=TMP)
    bare = os.path.join(d, "remote.git")
    sh(d, "git", "init", "-q", "--bare", "-b", "main", bare)
    clone = os.path.join(d, "clone")
    sh(d, "git", "init", "-q", "-b", "main", clone)
    g(clone, "remote", "add", "origin", bare)
    commit(clone, "base")
    g(clone, "push", "-q", "origin", "main")
    return clone, bare


def remote_head(bare, ref="main"):
    return g(bare, "rev-parse", "refs/heads/" + ref)


def F(clone, *args, fx=None):
    rc, lines, _, _ = forge(list(args), fx, cwd=clone)
    return rc, lines


def test_push():
    clone, bare = mkrepo()
    base = g(clone, "rev-parse", "HEAD")
    x = commit(clone, "feat")
    rc, lines = F(clone, "push-if-base-equals", "--path", clone, "--remote", "origin", "--base", "main",
                  "--sha", x, "--expect", base)
    check("push_if_base_equals_ok", (rc, lines, remote_head(bare)), (0, ["PUSHED " + x, "OK"], x))
    clone, bare = mkrepo()
    base = g(clone, "rev-parse", "HEAD")
    other = tempfile.mkdtemp(dir=TMP)
    sh(other, "git", "clone", "-q", bare, "c")
    oc = os.path.join(other, "c")
    moved = commit(oc, "moved")
    g(oc, "push", "-q", "origin", "main")
    x = commit(clone, "feat")
    rc, lines = F(clone, "push-if-base-equals", "--path", clone, "--remote", "origin", "--base", "main",
                  "--sha", x, "--expect", base)
    check("push_if_base_moved", (rc, errcls(lines), remote_head(bare)), (3, "base-moved", moved))
    # git reports the lease failure as "(stale info)" when the local tracking ref is absent
    sh(clone, "git", "update-ref", "-d", "refs/remotes/origin/main")
    rc, lines = F(clone, "push-if-base-equals", "--path", clone, "--remote", "origin", "--base", "main",
                  "--sha", x, "--expect", base)
    check("push_if_base_moved_is_stale_info", (errcls(lines), remote_head(bare)), ("base-moved", moved))
    clone, bare = mkrepo()
    base = g(clone, "rev-parse", "HEAD")
    x = commit(clone, "feat")
    rc, lines = F(clone, "push-if-base-equals", "--path", clone, "--remote", "origin", "--base", "main",
                  "--sha", base, "--expect", x)
    check("push_if_expect_not_ancestor", (rc, errcls(lines)), (3, "usage"))
    hook = os.path.join(bare, "hooks", "pre-receive")
    with open(hook, "w") as f:
        f.write("#!/bin/sh\necho 'remote: error: GH006: Protected branch update failed' >&2\nexit 1\n")
    os.chmod(hook, 0o755)
    rc, lines = F(clone, "push-if-base-equals", "--path", clone, "--remote", "origin", "--base", "main",
                  "--sha", x, "--expect", base)
    check("push_if_base_protected_is_forbidden", (rc, errcls(lines), remote_head(bare)), (3, "forbidden", base))


def test_landed():
    clone, bare = mkrepo()
    x = commit(clone, "feat")
    g(clone, "push", "-q", "origin", "main")
    merged = lambda head, oid: {"pr view 5": pr_doc(state="MERGED", headRefOid=head, mergeCommit={"oid": oid})}
    base = ["landed", "--path", clone, "--remote", "origin", "--base", "main", "--sha", x]
    check("landed_pr_ok", F(clone, *(base + ["--slug", S, "--pr", "5"]), fx=merged(x, x)),
          (0, ["LANDED " + x, "OK"]))
    rc, lines = F(clone, *(base + ["--slug", S, "--pr", "5"]), fx=merged(SHA2, x))
    check("landed_pr_moved_head", (rc, errcls(lines)), (3, "moved-head"))
    check("landed_merge_commit_not_on_base", F(clone, *(base + ["--slug", S, "--pr", "5"]), fx=merged(x, SHA2)),
          (0, ["NOT_LANDED", "OK"]))
    check("landed_pr_open", F(clone, *(base + ["--slug", S, "--pr", "5"]), fx={"pr view 5": pr_doc()}),
          (0, ["NOT_LANDED", "OK"]))
    check("landed_branch_ok", F(clone, *(base + ["--branch", "feat"])), (0, ["LANDED " + x, "OK"]))
    y = commit(clone, "local-only")
    check("not_landed", F(clone, "landed", "--path", clone, "--remote", "origin", "--base", "main",
                          "--sha", y, "--branch", "feat"), (0, ["NOT_LANDED", "OK"]))


def tag(clone, name, sha):
    g(clone, "tag", "-a", name, "-m", name, sha)
    g(clone, "push", "-q", "origin", "refs/tags/" + name)


def test_tags():
    clone, bare = mkrepo()
    first = g(clone, "rev-parse", "HEAD")
    x = commit(clone, "x")
    z = commit(clone, "z")
    tag(clone, "1.4.0", first)
    tag(clone, "1.5.0", z)
    tag(clone, "1.4.1", x)
    args = ["--path", clone, "--remote", "origin", "--sha", x]
    check("tag_for_lowest_matching", F(clone, "tag-for", *args, "--format", "{version}"), (0, ["TAG 1.4.1", "OK"]))
    check("tag_for_prefixed_format_none", F(clone, "tag-for", *args, "--format", "v{version}"),
          (0, ["TAG NONE", "OK"]))
    clone, bare = mkrepo()
    head = commit(clone, "h")
    args = ["--path", clone, "--remote", "origin", "--sha", head]
    check("next_version_no_previous_tag", (lambda r: (r[0], r[1][0].startswith("ERROR no-previous-tag"),
                                                      "initial_version" in r[1][0]))(
        F(clone, "next-version", *args, "--format", "{version}")), (3, True, True))
    check("next_version_uses_initial_version", F(clone, "next-version", *args, "--format", "v{version}",
                                                 "--initial", "0.1.0"), (0, ["VERSION v0.1.0", "OK"]))
    tag(clone, "1.4.9", head)
    tag(clone, "1.4.10", head)
    p = commit(clone, "p")
    check("next_version_patch_default", F(clone, "next-version", "--path", clone, "--remote", "origin",
                                          "--sha", p, "--format", "{version}"), (0, ["VERSION 1.4.11", "OK"]))
    m = commit(clone, "m", "feat\n\nbody\n\nRelease: minor\n")
    check("next_version_minor_trailer", F(clone, "next-version", "--path", clone, "--remote", "origin",
                                          "--sha", m, "--format", "{version}"), (0, ["VERSION 1.5.0", "OK"]))
    rc, lines = F(clone, "next-version", "--path", clone, "--remote", "origin", "--sha", m,
                  "--format", "{version}", "--initial", "9.9.9")
    check("next_version_reads_reviewed_head_not_squash", lines[0], "VERSION 1.5.0")
    sq = commit(clone, "squash", "Squash merge of feat")
    check("next_version_squash_commit_gets_patch", F(clone, "next-version", "--path", clone, "--remote", "origin",
                                                     "--sha", sq, "--format", "{version}")[1][0], "VERSION 1.4.11")
    check("next_version_bad_release", errcls(F(clone, "next-version", "--path", clone, "--remote", "origin",
                                               "--sha", commit(clone, "b", "x\n\nRelease: huge\n"),
                                               "--format", "{version}")[1]), "usage")
    clone, bare = mkrepo()
    x = commit(clone, "x")
    ta = ["--path", clone, "--remote", "origin", "--sha", x, "--name", "1.0.0", "--message", "release 1.0.0"]
    rc, lines = F(clone, "tag-create", *ta)
    peeled = sh(bare, "git", "rev-parse", "refs/tags/1.0.0^{commit}")
    check("tag_create_ok", (rc, lines, peeled), (0, ["TAG 1.0.0 " + x, "OK"], x))
    check("tag_create_same_commit_is_ok", F(clone, "tag-create", *ta), (0, ["TAG 1.0.0 " + x, "OK"]))
    y = commit(clone, "y")
    ta2 = ta[:5] + [y] + ta[6:]
    rc, lines = F(clone, "tag-create", *ta2)
    check("tag_create_exists_elsewhere", (rc, errcls(lines), sh(bare, "git", "rev-parse", "refs/tags/1.0.0^{commit}")),
          (3, "tag-exists", x))


def test_preflight():
    clone, bare = mkrepo()
    g(clone, "checkout", "-q", "-b", "feat")
    x = commit(clone, "f")
    pre = ["gate-preflight", "--path", clone, "--slug", S, "--base", "main"]
    fx = {"pr view 5": pr_doc(headRefOid=x)}
    check("gate_preflight_ok", F(clone, *pre, "--pr", "5", fx=fx), (0, ["PREFLIGHT ok", "OK"]))
    with open(os.path.join(clone, "untracked.o"), "w") as f:
        f.write("build output")
    check("gate_preflight_untracked_ok", F(clone, *pre, "--pr", "5", fx=fx)[0], 0)
    check("gate_preflight_epic_base_ok", F(clone, "gate-preflight", "--path", clone, "--slug", S, "--base",
                                           "epic/x", "--pr", "5", fx={"pr view 5": pr_doc(
                                               headRefOid=x, baseRefName="epic/x")})[0], 0)
    check("gate_preflight_branch_form", F(clone, *pre, "--branch", "feat")[1], ["PREFLIGHT ok", "OK"])
    check("gate_preflight_branch_mismatch", F(clone, *pre, "--branch", "other")[1][0].split()[:2],
          ["ERROR", "mismatch"])
    check("gate_preflight_head_mismatch", F(clone, *pre, "--pr", "5", fx={"pr view 5": pr_doc(headRefOid=SHA)})[1][0]
          .split()[:3], ["ERROR", "mismatch", "head-sha:"])
    check("gate_preflight_base_mismatch", F(clone, *pre, "--pr", "5", fx={"pr view 5": pr_doc(
        headRefOid=x, baseRefName="other")})[1][0].split()[:3], ["ERROR", "mismatch", "base-ref:"])
    check("gate_preflight_slug_mismatch", F(clone, *pre, "--pr", "5", fx={"pr view 5": pr_doc(
        headRefOid=x, url="https://github.com/other/app/pull/5")})[1][0].split()[:3],
        ["ERROR", "mismatch", "slug:"])
    check("gate_preflight_headref_mismatch", F(clone, *pre, "--pr", "5", fx={"pr view 5": pr_doc(
        headRefOid=x, headRefName="zzz")})[1][0].split()[:3], ["ERROR", "mismatch", "head-ref:"])
    with open(os.path.join(clone, "f"), "a") as f:
        f.write("edit")
    rc, lines = F(clone, *pre, "--pr", "5", fx=fx)
    check("gate_preflight_dirty", (rc, errcls(lines)), (3, "dirty"))


def test_misc():
    rc, lines, _, _ = forge(["visibility", "--slug", S], {"repo view": {"rc": 1, "stderr": "HTTP 500"}})
    check("visibility_error_is_error", (rc, errcls(lines)), (3, "forge"))
    check("visibility_internal_is_private", forge(["visibility", "--slug", S],
          {"repo view": {"json": {"visibility": "INTERNAL"}}})[1], ["VISIBILITY private", "OK"])
    check("visibility_public", forge(["visibility", "--slug", S],
          {"repo view": {"json": {"visibility": "PUBLIC"}}})[1], ["VISIBILITY public", "OK"])
    check("default_branch_ok", forge(["default-branch", "--slug", S],
          {"repo view": {"json": {"defaultBranchRef": {"name": "trunk"}}}})[1], ["DEFAULT trunk", "OK"])
    clone, _ = mkrepo()
    g(clone, "checkout", "-q", "-b", "feat")
    os.makedirs(os.path.join(clone, "d"))
    x = commit(clone, "d/a.txt")
    x = commit(clone, "b c.txt")
    check("changed_files_ok", F(clone, "changed-files", "--path", clone, "--base", "main", "--sha", x),
          (0, ["FILE b c.txt", "FILE d/a.txt", "OK"]))
    # a file renamed out of a path lists both sides
    clone, _ = mkrepo()
    os.makedirs(os.path.join(clone, "src", "core"))
    commit(clone, "src/core/engine.py", "engine")
    g(clone, "push", "-q", "origin", "main")
    g(clone, "checkout", "-q", "-b", "mv")
    os.makedirs(os.path.join(clone, "tools"))
    g(clone, "mv", "src/core/engine.py", "tools/engine.py")
    g(clone, "commit", "-q", "-m", "move engine")
    x = g(clone, "rev-parse", "HEAD")
    check("changed_files_lists_rename_source",
          F(clone, "changed-files", "--path", clone, "--base", "main", "--sha", x),
          (0, ["FILE src/core/engine.py", "FILE tools/engine.py", "OK"]))
    # --host: GH_HOST and GH_REPO reach gh when given; the environment is inherited otherwise
    fx = {"repo view": {"json": {"visibility": "PUBLIC"}}}
    _, _, _, envs = forge(["visibility", "--slug", S, "--host", "git.example.test"], fx)
    check("gh_host_passed_through", envs, ["GH_HOST=git.example.test GH_REPO=" + S])
    _, _, _, envs = forge(["visibility", "--slug", S], fx)
    check("gh_host_absent_inherits", envs, ["GH_HOST=- GH_REPO=-"])
    _, _, _, envs = forge(["visibility", "--slug", S], fx, extra_env={"GH_HOST": "h.test"})
    check("gh_host_absent_keeps_process_env", envs, ["GH_HOST=h.test GH_REPO=-"])


USAGE = {
    "pr-state": [], "checks": [], "required-checks": [], "mergeable": [], "repo-settings": [],
    "merge-at": [], "arm": [], "disarm": [], "claim-state": [], "workflow-runs": [], "run-head": [],
    "run-jobs": [], "rerun-failed": [], "push-if-base-equals": [], "landed": [], "tag-for": [],
    "next-version": [], "tag-create": [], "gate-preflight": [], "default-branch": [],
    "visibility": [], "changed-files": [],
}


def test_terminal_lines():
    for verb in USAGE:
        rc, lines, calls, _ = forge([verb])
        check("every_verb_has_terminal_line %s" % verb, (rc, lines[-1:], len(lines), calls),
              (3, ["ERROR usage " + lines[-1][len("ERROR usage "):]], 1, []))
        check("usage line %s" % verb, lines[-1].startswith("ERROR usage"), True)
    rc, lines, _, _ = forge(["nonsense"])
    check("unknown verb", (rc, errcls(lines)), (3, "usage"))
    rc, lines, _, _ = forge([])
    check("no verb", (rc, errcls(lines)), (3, "usage"))
    rc, lines, _, _ = forge(["checks", "--slug", S, "--sha", SHA, "--bogus", "1"])
    check("unknown flag", (rc, errcls(lines)), (3, "usage"))
    rc, lines, _, _ = forge(["checks", "--slug", S, "--sha", SHA], {})
    check("unmatched gh is a forge error", (rc, errcls(lines)), (3, "forge"))


for t in (test_pr_state, test_checks, test_required, test_mergeable_and_settings, test_merge_arm,
          test_disarm_claim, test_runs, test_push, test_landed, test_tags, test_preflight, test_misc,
          test_terminal_lines):
    t()

if FAILURES:
    print("FAIL: %d of %d checks" % (len(FAILURES), COUNT[0]))
    for f in FAILURES:
        print("  " + f)
    sys.exit(1)
print("ok: %d checks" % COUNT[0])
