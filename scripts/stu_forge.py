#!/usr/bin/env python3
"""stu-forge: forge facts for the run kit, with a fail-closed output contract.

Contract another forge's backend must meet: every verb prints zero or more result lines,
then exactly one terminal line, `OK` (exit 0) or `ERROR <class> <detail>` (exit 3); a
caller treats anything else, including a missing terminal line, as failure. Result lines
are never printed before an error is known to be absent for a read that could be partial
(a truncated list read prints no result lines at all), counts reported by the forge are
never trusted (lists are read to the end and counted here), and a fact the forge cannot
supply is an ERROR, never a guess. Classes: auth, rate-limit, not-found, partial, empty,
base-moved, forbidden, moved-head, tag-exists, no-previous-tag, dirty, mismatch, usage,
forge.

Run: python3 scripts/stu_forge.py VERB [--flag value ...]
"""
import json
import os
import re
import subprocess
import sys
import time
from urllib.parse import quote

EXIT_ERROR = 3


class Fail(Exception):
    def __init__(self, cls, detail=""):
        Exception.__init__(self, cls)
        self.cls = cls
        self.detail = detail


class State:
    host = None
    slug = None


def _clean(text):
    return " ".join(str(text).split())[:300]


def _done(ok, cls=None, detail=""):
    if ok:
        print("OK")
        return 0
    line = "ERROR %s" % cls
    if detail:
        line += " " + _clean(detail)
    print(line)
    return EXIT_ERROR


def _classify(rc, out, err, lists=False):
    low = err.lower()
    if "403" in low and "rate limit" in low:
        return "rate-limit"
    if "401" in low or "bad credentials" in low or "authentication" in low:
        return "auth"
    if "404" in low:
        return "not-found"
    if lists and out.strip():
        return "partial"
    return "forge"


def _run(cmd, env=None, cwd=None):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=cwd)
    except OSError as e:
        return 127, "", str(e)
    return p.returncode, p.stdout, p.stderr


def _gh(args):
    """-> (rc, stdout, stderr). With --host, gh runs with GH_HOST and GH_REPO set;
    otherwise the process environment is inherited unchanged."""
    env = None
    if State.host:
        env = dict(os.environ)
        env["GH_HOST"] = State.host
        if State.slug:
            env["GH_REPO"] = State.slug
    return _run(["gh"] + list(args), env=env)


def _gh_ok(args, lists=False):
    rc, out, err = _gh(args)
    if rc != 0:
        raise Fail(_classify(rc, out, err, lists), err or out)
    return out


def _json_stream(text):
    dec = json.JSONDecoder()
    i, n, items = 0, len(text), []
    while True:
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            return items
        obj, i = dec.raw_decode(text, i)
        items.append(obj)


def _gh_list(path, jq):
    """A paginated list read: one JSON value per element; any failure discards everything."""
    out = _gh_ok(["api", "--paginate", path, "--jq", jq], lists=True)
    try:
        return _json_stream(out)
    except ValueError as e:
        raise Fail("partial", "unparseable list output: %s" % e)


def _git(path, args):
    return _run(["git", "-C", path] + list(args))


def _git_ok(path, args):
    rc, out, err = _git(path, args)
    if rc != 0:
        raise Fail("forge", "git %s: %s" % (args[0], err or out))
    return out


def _pct(s):
    """Names print with only % space comma tab and newline encoded; / and quotes stay literal."""
    if not s:
        return "-"
    out = s.replace("%", "%25").replace(" ", "%20").replace(",", "%2C")
    return out.replace("\t", "%09").replace("\n", "%0A")


def _need(a, *names):
    for n in names:
        if a.get(n) in (None, ""):
            raise Fail("usage", "missing --%s" % n)


def _pr_number(a):
    _need(a, "pr")
    if not re.fullmatch(r"[0-9]+", a["pr"]):
        raise Fail("usage", "--pr must be a number")
    return a["pr"]


def _pr_view(a, fields):
    _need(a, "slug")
    out = _gh_ok(["pr", "view", _pr_number(a), "-R", a["slug"], "--json", fields])
    try:
        doc = json.loads(out)
    except ValueError as e:
        raise Fail("forge", "unparseable pr view: %s" % e)
    if not isinstance(doc, dict):
        raise Fail("forge", "unexpected pr view shape")
    return doc


# ---- forge reads ------------------------------------------------------------------------

def v_pr_state(a):
    doc = _pr_view(a, "state,headRefName,headRefOid,baseRefName,mergeCommit,labels,"
                      "autoMergeRequest,url")
    state = str(doc.get("state") or "").lower()
    if state not in ("open", "merged", "closed"):
        raise Fail("forge", "unknown PR state %r" % doc.get("state"))
    m = re.match(r"https?://[^/]+/([^/]+/[^/]+)/pull/", str(doc.get("url") or ""))
    labels = [x.get("name") for x in (doc.get("labels") or []) if x.get("name")]
    merge = (doc.get("mergeCommit") or {}).get("oid") or "-"
    return ["STATE " + state,
            "HEAD_REF %s" % doc.get("headRefName"),
            "HEAD_SHA %s" % doc.get("headRefOid"),
            "BASE_REF %s" % doc.get("baseRefName"),
            "MERGE_COMMIT " + merge,
            "SLUG %s" % (m.group(1) if m else "-"),
            "LABELS " + (",".join(labels) or "-"),
            "AUTO_MERGE " + ("on" if doc.get("autoMergeRequest") else "off")]


RUN_ID = re.compile(r"/actions/runs/([0-9]+)")


def _run_state(status, conclusion):
    if status != "completed":
        return "pending"
    c = conclusion or ""
    if c == "success":
        return "success"
    if c in ("failure", "timed_out", "action_required", "startup_failure", "stale"):
        return "failure"
    if c == "skipped":
        return "skipped"
    if c == "neutral":
        return "neutral"
    return "pending"  # cancelled, or a conclusion this reader does not know


def v_checks(a):
    _need(a, "slug", "sha")
    s, sha = a["slug"], a["sha"]
    runs = _gh_list("repos/%s/commits/%s/check-runs" % (s, sha), ".check_runs[]")
    stats = _gh_list("repos/%s/commits/%s/statuses" % (s, sha), ".[]")
    newest = {}
    order = []
    for r in runs:
        key = (r.get("name") or "", "app:%s" % ((r.get("app") or {}).get("slug") or "-"))
        if key not in newest:
            order.append(key)
        if key not in newest or (r.get("id") or 0) > (newest[key][1].get("id") or 0):
            newest[key] = ("run", r)
    for st in stats:
        key = (st.get("context") or "",
               "status:%s" % ((st.get("creator") or {}).get("login") or "-"))
        if key not in newest:
            order.append(key)
        if key not in newest or (st.get("updated_at") or "") > (newest[key][1].get("updated_at") or ""):
            newest[key] = ("status", st)
    if not order:
        raise Fail("empty", "no checks reported for %s" % sha)
    lines = []
    for key in order:
        kind, o = newest[key]
        if kind == "run":
            state = _run_state(o.get("status"), o.get("conclusion"))
            m = RUN_ID.search(o.get("details_url") or "")
            rid = m.group(1) if m else "-"
            desc = (o.get("output") or {}).get("title") or ""
        else:
            raw = o.get("state") or ""
            state = {"success": "success", "failure": "failure", "error": "failure"}.get(raw, "pending")
            rid, desc = "-", o.get("description") or ""
        lines.append("CHECK %s %s %s %s %s" % (state, key[1], rid, _pct(key[0]), _pct(desc)))
    return lines


def _rules(slug, base):
    return _gh_list("repos/%s/rules/branches/%s" % (slug, base), ".[]")


def _rules_allow_unavailable(slug, base):
    """The opt-in repo-settings read permits only GitHub's plan restriction.
    Match one complete error body, never a successful page followed by an error.
    All other failed reads retain their classification and discard partial output.
    """
    rc, out, err = _gh(["api", "--paginate", "repos/%s/rules/branches/%s" % (slug, base),
                        "--jq", ".[]"])
    if rc != 0:
        plan = "Upgrade to GitHub Pro or make this repository public to enable this feature."
        try:
            body = json.loads(out)
        except ValueError:
            body = None
        if (isinstance(body, dict) and body.get("message") == plan
                and str(body.get("status")) == "403"
                and err.strip() == "gh: %s (HTTP 403)" % plan):
            return None
        raise Fail(_classify(rc, out, err, True), err or out)
    try:
        return _json_stream(out)
    except ValueError as e:
        raise Fail("partial", "unparseable list output: %s" % e)


def v_required_checks(a):
    _need(a, "slug", "base")
    rc, out, err = _gh(["api", "--paginate", "repos/%s/rules/branches/%s" % (a["slug"], a["base"]),
                        "--jq", ".[]"])
    if rc != 0:
        low = err.lower()
        if "403" in low and ("upgrade" in low or "not available" in low):
            return ["REQUIRED_NONE_READABLE plan"]
        if "404" in low and "403" not in low:
            return ["REQUIRED_NONE_READABLE unsupported"]
        raise Fail(_classify(rc, out, err, True), err or out)
    try:
        rules = _json_stream(out)
    except ValueError as e:
        raise Fail("partial", "unparseable rules: %s" % e)
    names = []
    for r in rules:
        if r.get("type") == "required_status_checks":
            for c in (r.get("parameters") or {}).get("required_status_checks") or []:
                if c.get("context") and c["context"] not in names:
                    names.append(c["context"])
    if not names:
        return ["REQUIRED_NONE_READABLE none"]
    return ["REQUIRED " + _pct(n) for n in names]


def v_mergeable(a):
    for attempt in (0, 1):
        doc = _pr_view(a, "mergeable,mergeStateStatus")
        m, st = doc.get("mergeable") or "UNKNOWN", doc.get("mergeStateStatus") or "UNKNOWN"
        if m != "UNKNOWN" or attempt:
            break
        time.sleep(float(os.environ.get("STU_FORGE_REQUERY_DELAY", "2")))
    return ["MERGEABLE %s %s" % (m, st)]


def v_repo_settings(a):
    _need(a, "slug")
    # The REST repo document, not `gh repo view --json`: repo view has no auto-merge field
    # (gh 2.92 rejects autoMergeAllowed). The allow_* keys are only present for a caller
    # with push access, so a missing one is an error rather than a guess.
    out = _gh_ok(["api", "repos/%s" % a["slug"]])
    try:
        doc = json.loads(out)
    except ValueError as e:
        raise Fail("forge", "unparseable repo document: %s" % e)
    if not isinstance(doc, dict):
        raise Fail("forge", "repo document is not an object")
    lines = []
    for name, key in (("squash", "allow_squash_merge"), ("merge", "allow_merge_commit"),
                      ("rebase", "allow_rebase_merge"), ("auto_merge", "allow_auto_merge")):
        if not isinstance(doc.get(key), bool):
            raise Fail("forge", "repo document lacks %s (push access needed)" % key)
        lines.append("SETTING %s %s" % (name, "on" if doc[key] else "off"))
    if a.get("base"):
        if a.get("allow-unavailable-rules"):
            rules = _rules_allow_unavailable(a["slug"], a["base"])
            if rules is None:
                lines.append("SETTING merge_queue unknown")
        else:
            try:
                rules = _rules(a["slug"], a["base"])
            except Fail as e:
                if e.cls in ("auth", "rate-limit", "partial"):
                    raise
                rules = None  # not readable: say nothing rather than guess
        if rules is not None:
            queue = any(r.get("type") == "merge_queue" for r in rules)
            lines.append("SETTING merge_queue " + ("on" if queue else "off"))
    return lines


METHODS = {"squash": "--squash", "merge": "--merge", "rebase": "--rebase"}


def _method(a):
    _need(a, "method")
    if a["method"] not in METHODS:
        raise Fail("usage", "--method must be squash|merge|rebase")
    return METHODS[a["method"]]


def _merge_args(a, auto):
    _need(a, "slug", "sha")
    args = ["pr", "merge", _pr_number(a), "-R", a["slug"], _method(a), "--match-head-commit", a["sha"]]
    if auto:
        args.insert(args.index("--match-head-commit"), "--auto")
    return args


def _merge_fail(rc, out, err):
    low = err.lower()
    if "head branch was modified" in low or "match-head-commit" in low or "expected head" in low:
        return "moved-head"
    return _classify(rc, out, err)


def v_merge_at(a):
    rc, out, err = _gh(_merge_args(a, False))
    if rc != 0:
        raise Fail(_merge_fail(rc, out, err), err or out)
    return ["MERGED " + a["sha"]]


def v_arm(a):
    args = _merge_args(a, True)  # validates before any write
    lines = []
    if a.get("label"):
        rc, out, err = _gh(["pr", "edit", a["pr"], "-R", a["slug"], "--add-label", a["label"]])
        if rc != 0:
            raise Fail(_classify(rc, out, err), "step=label " + (err or out))
        lines.append("ARMED label")
    elif "no-auto" in a:
        raise Fail("usage", "nothing to arm: no --label and --no-auto")
    if "no-auto" not in a:
        rc, out, err = _gh(args)
        if rc != 0:
            raise Fail(_merge_fail(rc, out, err), "step=auto " + (err or out))
        lines.append("ARMED auto")
    return lines


def _branch_runs(a, branch):
    path = "repos/%s/actions/workflows/%s/runs?branch=%s" % (a["slug"], quote(a["workflow"], safe=""),
                                                              quote(branch, safe=""))
    return _gh_list(path, ".workflow_runs[]")


def _unfinished(runs):
    return [r for r in runs if r.get("status") != "completed"]


def v_disarm(a):
    _need(a, "slug")
    pr = _pr_number(a)
    lines, errors = [], []

    def step(name, fn):
        try:
            lines.extend(fn())
        except Fail as e:
            errors.append((e.cls, "step=%s %s" % (name, e.detail)))

    def label():
        if not a.get("label"):
            return []
        _gh_ok(["pr", "edit", pr, "-R", a["slug"], "--remove-label", a["label"]])
        return ["DISARMED label"]

    def auto():
        _gh_ok(["pr", "merge", pr, "-R", a["slug"], "--disable-auto"])
        return ["DISARMED auto"]

    def cancel():
        if not a.get("workflow"):
            return []
        branch = _pr_view(a, "headRefName").get("headRefName")
        if not branch:
            raise Fail("forge", "PR has no head branch")
        done = []
        for r in _unfinished(_branch_runs(a, branch)):
            _gh_ok(["run", "cancel", str(r.get("id")), "-R", a["slug"]])
            done.append("CANCELLED %s" % r.get("id"))
        return done

    step("label", label)
    step("auto", auto)
    step("runs", cancel)
    if errors:
        for ln in lines:
            print(ln)
        raise Fail(errors[0][0], errors[0][1])
    return lines


def v_claim_state(a):
    _need(a, "slug")
    doc = _pr_view(a, "labels,autoMergeRequest,headRefName")
    names = [x.get("name") for x in (doc.get("labels") or [])]
    lines = ["LABEL " + ("present" if a.get("label") and a["label"] in names else "absent"),
             "AUTO_MERGE " + ("on" if doc.get("autoMergeRequest") else "off")]
    n = 0
    if a.get("workflow"):
        n = len(_unfinished(_branch_runs(a, doc.get("headRefName") or "")))
    lines.append("RUNS_UNFINISHED %d" % n)
    return lines


def v_workflow_runs(a):
    _need(a, "slug", "workflow", "sha")
    path = "repos/%s/actions/workflows/%s/runs?head_sha=%s" % (a["slug"], quote(a["workflow"], safe=""), a["sha"])
    if a.get("event"):
        path += "&event=" + quote(a["event"], safe="")
    runs = sorted(_gh_list(path, ".workflow_runs[]"), key=lambda r: -(r.get("id") or 0))
    return ["RUN %s %s %s" % (r.get("id"), r.get("status") or "-", r.get("conclusion") or "-") for r in runs]


def v_run_head(a):
    _need(a, "slug", "run")
    out = _gh_ok(["run", "view", a["run"], "-R", a["slug"], "--json", "headSha"])
    try:
        sha = json.loads(out).get("headSha")
    except (ValueError, AttributeError):
        sha = None
    if not sha:
        raise Fail("forge", "run has no head sha")
    return ["HEAD_SHA " + sha]


def v_run_jobs(a):
    _need(a, "slug", "run")
    jobs = _gh_list("repos/%s/actions/runs/%s/jobs" % (a["slug"], a["run"]), ".jobs[]")
    return ["JOB %s %s %s %s" % (j.get("id"), j.get("status") or "-", j.get("conclusion") or "-",
                                 _pct(j.get("name") or "")) for j in jobs]


def v_rerun_failed(a):
    _need(a, "slug", "run")
    _gh_ok(["run", "rerun", a["run"], "-R", a["slug"], "--failed"])
    return ["RERUN " + a["run"]]


def v_default_branch(a):
    _need(a, "slug")
    out = _gh_ok(["repo", "view", a["slug"], "--json", "defaultBranchRef"])
    try:
        name = (json.loads(out).get("defaultBranchRef") or {}).get("name")
    except (ValueError, AttributeError):
        name = None
    if not name:
        raise Fail("forge", "no default branch")
    return ["DEFAULT " + name]


def v_visibility(a):
    _need(a, "slug")
    out = _gh_ok(["repo", "view", a["slug"], "--json", "visibility"])
    try:
        v = str(json.loads(out).get("visibility") or "").lower()
    except (ValueError, AttributeError):
        v = ""
    if v == "public":
        return ["VISIBILITY public"]
    if v in ("private", "internal"):
        return ["VISIBILITY private"]
    raise Fail("forge", "unknown visibility %r" % v)


# ---- local git --------------------------------------------------------------------------

def _is_ancestor(path, anc, desc):
    rc, _, _ = _git(path, ["merge-base", "--is-ancestor", anc, desc])
    return rc == 0


def v_push_if_base_equals(a):
    _need(a, "path", "remote", "base", "sha", "expect")
    p, r, b, x, e = a["path"], a["remote"], a["base"], a["sha"], a["expect"]
    if not _is_ancestor(p, e, x):
        raise Fail("usage", "expect is not an ancestor of sha")
    rc, out, err = _git(p, ["push", "--force-with-lease=refs/heads/%s:%s" % (b, e), r,
                            "%s:refs/heads/%s" % (x, b)])
    if rc == 0:
        return ["PUSHED " + x]
    low = (err + out).lower()
    if "stale info" in low or "fetch first" in low:
        raise Fail("base-moved", err)
    if "[remote rejected]" in low or "gh006" in low or "protected" in low or "permission" in low:
        raise Fail("forbidden", err)
    raise Fail("forge", err)


def _fetch_base(p, r, b):
    _git_ok(p, ["fetch", "-q", r, "+refs/heads/%s:refs/remotes/%s/%s" % (b, r, b)])


def v_landed(a):
    _need(a, "path", "remote", "base", "sha")
    p, r, b, x = a["path"], a["remote"], a["base"], a["sha"]
    tip = "refs/remotes/%s/%s" % (r, b)
    pr_form = bool(a.get("pr") or a.get("slug"))
    if pr_form == bool(a.get("branch")):
        raise Fail("usage", "give --slug and --pr, or --branch")
    _fetch_base(p, r, b)
    if not pr_form:
        return ["LANDED " + x] if _is_ancestor(p, x, tip) else ["NOT_LANDED"]
    _need(a, "slug", "pr")
    doc = _pr_view(a, "state,headRefOid,mergeCommit")
    if str(doc.get("state") or "").upper() != "MERGED":
        return ["NOT_LANDED"]
    if doc.get("headRefOid") != x:
        raise Fail("moved-head", "merged with head %s" % doc.get("headRefOid"))
    oid = (doc.get("mergeCommit") or {}).get("oid")
    if oid and _is_ancestor(p, oid, tip):
        return ["LANDED " + oid]
    return ["NOT_LANDED"]


def _fmt_regex(fmt):
    if "{version}" not in fmt:
        raise Fail("usage", "format needs {version}")
    pre, _, post = fmt.partition("{version}")
    return re.compile(re.escape(pre) + r"([0-9]+)\.([0-9]+)\.([0-9]+)" + re.escape(post))


def _semver_tags(p, fmt, contains=None):
    rx = _fmt_regex(fmt)
    args = ["tag", "--list"] + (["--contains", contains] if contains else [])
    found = []
    for name in _git_ok(p, args).splitlines():
        m = rx.fullmatch(name)
        if m:
            found.append((tuple(int(g) for g in m.groups()), name))
    return sorted(found)


def v_tag_for(a):
    _need(a, "path", "remote", "sha", "format")
    p = a["path"]
    _fetch_tags(p, a["remote"])
    found = _semver_tags(p, a["format"], a["sha"])
    return ["TAG " + (found[0][1] if found else "NONE")]


def _fetch_tags(p, r):
    _git_ok(p, ["fetch", "-q", "--tags", r])


SEMVER = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")


def v_next_version(a):
    _need(a, "path", "remote", "sha", "format")
    p, fmt = a["path"], a["format"]
    _fmt_regex(fmt)
    msg = _git_ok(p, ["log", "-1", "--format=%B", a["sha"]])
    bump = "patch"
    for ln in msg.splitlines():
        m = re.fullmatch(r"Release:\s*(\S+)\s*", ln)
        if m:
            bump = m.group(1)
    if bump not in ("major", "minor", "patch"):
        raise Fail("usage", "Release: must be major|minor|patch, got %r" % bump)
    if a.get("initial") and not SEMVER.fullmatch(a["initial"]):
        raise Fail("usage", "--initial must be MAJOR.MINOR.PATCH")
    _fetch_tags(p, a["remote"])
    tags = _semver_tags(p, fmt)
    if not tags:
        if a.get("initial"):
            return ["VERSION " + fmt.replace("{version}", a["initial"])]
        raise Fail("no-previous-tag", "no tag matches the format; set the initial_version key")
    ma, mi, pa = tags[-1][0]
    new = {"major": (ma + 1, 0, 0), "minor": (ma, mi + 1, 0), "patch": (ma, mi, pa + 1)}[bump]
    return ["VERSION " + fmt.replace("{version}", "%d.%d.%d" % new)]


def _peel(p, ref):
    rc, out, _ = _git(p, ["rev-parse", "--verify", "-q", ref + "^{commit}"])
    return out.strip() if rc == 0 else None


def peel(path, remote, tag):
    """The commit sha REMOTE's tag TAG peels to, read with `git ls-remote --tags`; "" when
    the remote has no such tag. Raises Fail when the remote cannot be read."""
    ls = _git_ok(path, ["ls-remote", "--tags", remote, "refs/tags/" + tag,
                        "refs/tags/%s^{}" % tag])
    refs = {}
    for ln in ls.splitlines():
        sha, _, name = ln.partition("\t")
        refs[name] = sha
    return refs.get("refs/tags/%s^{}" % tag) or refs.get("refs/tags/" + tag) or ""


def v_tag_create(a):
    _need(a, "path", "remote", "sha", "name", "message")
    p, r, t = a["path"], a["remote"], a["name"]
    x = _peel(p, a["sha"])
    if not x:
        raise Fail("usage", "unknown sha")
    _fetch_tags(p, r)
    have = _peel(p, "refs/tags/" + t)
    if have is None:
        _git_ok(p, ["tag", "-a", t, x, "-m", a["message"]])
    elif have != x:
        raise Fail("tag-exists", "%s exists at %s" % (t, have))
    rc, out, err = _git(p, ["push", r, "refs/tags/" + t])
    if rc != 0:
        raise Fail("forge", err)
    remote = peel(p, r, t)
    if remote != x:
        raise Fail("mismatch", "remote tag peels to %s, want %s" % (remote, x))
    return ["TAG %s %s" % (t, x)]


def v_gate_preflight(a):
    _need(a, "path", "slug", "base")
    p = a["path"]
    if bool(a.get("pr")) == bool(a.get("branch")):
        raise Fail("usage", "give --pr or --branch")
    if _git_ok(p, ["status", "--porcelain", "--untracked-files=no"]).strip():
        raise Fail("dirty", "tracked files are modified")
    cur = _git_ok(p, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()
    if a.get("branch"):
        if cur != a["branch"]:
            raise Fail("mismatch", "branch: on %s, want %s" % (cur, a["branch"]))
        return ["PREFLIGHT ok"]
    head = _git_ok(p, ["rev-parse", "HEAD"]).strip()
    doc = _pr_view(a, "headRefName,headRefOid,baseRefName,url")
    m = re.match(r"https?://[^/]+/([^/]+/[^/]+)/pull/", str(doc.get("url") or ""))
    if not m or m.group(1).lower() != a["slug"].lower():
        raise Fail("mismatch", "slug: PR is in %s" % (m.group(1) if m else "?"))
    if doc.get("headRefName") != cur:
        raise Fail("mismatch", "head-ref: PR head %s, on %s" % (doc.get("headRefName"), cur))
    if doc.get("headRefOid") != head:
        raise Fail("mismatch", "head-sha: PR head %s, HEAD %s" % (doc.get("headRefOid"), head))
    if doc.get("baseRefName") != a["base"]:
        raise Fail("mismatch", "base-ref: PR base %s, want %s" % (doc.get("baseRefName"), a["base"]))
    return ["PREFLIGHT ok"]


def v_changed_files(a):
    _need(a, "path", "base", "sha")
    out = _git_ok(a["path"], ["diff", "--name-only", "--no-renames", "-z",
                              "%s...%s" % (a["base"], a["sha"])])
    names = [n for n in out.split("\0") if n]
    if any("\n" in n for n in names):
        raise Fail("forge", "a changed path contains a newline")
    return ["FILE " + n for n in names]


# verb -> (handler, value flags, boolean flags, uses gh)
VERBS = {
    "pr-state": (v_pr_state, ("slug", "pr"), (), True),
    "checks": (v_checks, ("slug", "sha"), (), True),
    "required-checks": (v_required_checks, ("slug", "base"), (), True),
    "mergeable": (v_mergeable, ("slug", "pr"), (), True),
    "repo-settings": (v_repo_settings, ("slug", "base"), ("allow-unavailable-rules",), True),
    "merge-at": (v_merge_at, ("slug", "pr", "sha", "method"), (), True),
    "arm": (v_arm, ("slug", "pr", "sha", "method", "label"), ("no-auto",), True),
    "disarm": (v_disarm, ("slug", "pr", "label", "workflow"), (), True),
    "claim-state": (v_claim_state, ("slug", "pr", "label", "workflow"), (), True),
    "workflow-runs": (v_workflow_runs, ("slug", "workflow", "sha", "event"), (), True),
    "run-head": (v_run_head, ("slug", "run"), (), True),
    "run-jobs": (v_run_jobs, ("slug", "run"), (), True),
    "rerun-failed": (v_rerun_failed, ("slug", "run"), (), True),
    "push-if-base-equals": (v_push_if_base_equals, ("path", "remote", "base", "sha", "expect"), (), False),
    "landed": (v_landed, ("path", "remote", "base", "sha", "slug", "pr", "branch"), (), True),
    "tag-for": (v_tag_for, ("path", "remote", "sha", "format"), (), False),
    "next-version": (v_next_version, ("path", "remote", "sha", "format", "initial"), (), False),
    "tag-create": (v_tag_create, ("path", "remote", "sha", "name", "message"), (), False),
    "gate-preflight": (v_gate_preflight, ("path", "slug", "base", "pr", "branch"), (), True),
    "default-branch": (v_default_branch, ("slug",), (), True),
    "visibility": (v_visibility, ("slug",), (), True),
    "changed-files": (v_changed_files, ("path", "base", "sha"), (), False),
}


def _parse(argv, values, bools, uses_gh):
    allowed = set(values) | set(bools) | ({"host"} if uses_gh else set())
    a, i = {}, 0
    while i < len(argv):
        tok = argv[i]
        if not tok.startswith("--") or len(tok) < 3:
            raise Fail("usage", "unexpected argument %r" % tok)
        name = tok[2:]
        if name not in allowed:
            raise Fail("usage", "unknown flag %s" % tok)
        if name in bools:
            a[name] = True
            i += 1
            continue
        if i + 1 >= len(argv):
            raise Fail("usage", "%s needs a value" % tok)
        a[name] = argv[i + 1]
        i += 2
    return a


def main(argv):
    try:
        if not argv or argv[0] not in VERBS:
            raise Fail("usage", "verb is one of: " + " ".join(sorted(VERBS)))
        fn, values, bools, uses_gh = VERBS[argv[0]]
        a = _parse(argv[1:], values, bools, uses_gh)
        State.host, State.slug = a.get("host"), a.get("slug")
        lines = fn(a)
    except Fail as e:
        return _done(False, e.cls, e.detail)
    except Exception as e:  # fail closed: never a traceback, never a missing terminal line
        return _done(False, "forge", "%s: %s" % (type(e).__name__, e))
    for ln in lines:
        print(ln)
    return _done(True)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
