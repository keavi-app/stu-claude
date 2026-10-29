#!/usr/bin/env python3
"""The publish guard's tool-call hook (PreToolUse). The enforcement lives in the git
pre-push hook (stu_pre_push.py); this script keeps plain-text checks that no git hook can
make, and parses no shell commands.

  1. Approval file, in any repo, from any seat: deny a Write/Edit/MultiEdit/NotebookEdit
     whose resolved path has the basename approvals.tsv, and a Bash command whose text
     contains approvals.tsv or a word whose basename is stu-approve or stu_approve.py.
  2. Hook bypass on a strict row: deny a Bash command with `--no-verify` beside `git` and
     `push`, or with core.hooksPath, when the payload cwd is inside a strict row (or its
     worktrees dir) or the text names a strict row's path, worktrees dir or slug.

  3. Text published through the forge on a public row: for `gh pr create|edit|comment|
     merge|review`, `gh issue create|edit|comment`, `gh release create|edit` and `gh gist
     create` whose target is a public row (a -R/--repo slug naming a row, else the payload
     cwd), scan the command text and any --body-file/-F/--notes-file for the names of the
     family's private rows. An mcp__ tool that writes (push, create, update, merge,
     comment, release, fork, gist) and names a public row's slug is denied: use git or gh
     so the text can be scanned.

hooks/publish-guard.sh starts this only for a payload that can concern it. Any error in
here denies only when check 2's or 3's strict-row condition holds (a Write/Edit gets check 1
only); in an unconfigured repo an error allows.

Output on refusal: the PreToolUse deny JSON on stdout, exit 0. Otherwise nothing, exit 0.
"""
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import push_policy  # noqa: E402
import stu_env  # noqa: E402

WRITE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")
APPROVAL_FILE = "approvals.tsv"
APPROVE_NAMES = ("stu-approve", "stu_approve.py")
MCP_WRITE_WORDS = ("push", "create", "update", "merge", "comment", "release", "fork", "gist")
GH_PUBLISH = re.compile(
    r"(?<![A-Za-z0-9_-])gh\s+(?:-\S+\s+)*(?:pr\s+(?:create|edit|comment|merge|review)"
    r"|issue\s+(?:create|edit|comment)|release\s+(?:create|edit)|gist\s+create)\b",
    re.IGNORECASE)
GH_REPO_FLAG = re.compile(r"(?:^|\s)(?:-R|--repo)(?:=|\s+)[\"']?([^\s\"']+)")
GH_BODY_FILE = re.compile(r"(?:^|\s)(?:--body-file|--notes-file|-F)(?:=|\s+)[\"']?([^\s\"']+)")
WORD = re.compile(r"[^\s;&|()<>\"'`=$]+")


def _text(payload):
    ti = payload.get("tool_input")
    return ti.get("command", "") if isinstance(ti, dict) else ""


# ---- check 1: the approval file ---------------------------------------------------------

def _file_target(payload):
    ti = payload.get("tool_input")
    if not isinstance(ti, dict):
        return ""
    p = ti.get("file_path") or ti.get("notebook_path") or ""
    return p if isinstance(p, str) else ""


def _approval_text(text):
    low = text.lower()
    if APPROVAL_FILE in low:
        return "the approvals file is written only by the owner (stu-approve); an agent " \
               "never names it"
    for w in WORD.findall(low):
        if os.path.basename(w) in APPROVE_NAMES:
            return "stu-approve is typed by the owner (`! stu-approve ...`), never run " \
                   "by an agent"
    return ""


def check_approval_file(payload):
    tool = payload.get("tool_name", "")
    if tool == "Bash":
        return _approval_text(_text(payload))
    if tool in WRITE_TOOLS:
        path = _file_target(payload)
        if not path:
            return ""
        cwd = payload.get("cwd") or os.getcwd()
        full = path if os.path.isabs(path) else os.path.join(cwd, path)
        names = (os.path.basename(full), os.path.basename(os.path.realpath(full)))
        if any(n.lower() == APPROVAL_FILE for n in names):
            return "%s is written only by the owner (stu-approve); an agent never edits " \
                   "it" % APPROVAL_FILE
    return ""


# ---- check 2: bypassing the pre-push hook on a strict row -------------------------------

def _bypass_text(text):
    low = text.lower()
    if "hookspath" in low:
        return "core.hooksPath"
    if "--no-verify" in low and re.search(r"\bgit\b", low) and re.search(r"\bpush\b", low):
        return "--no-verify on a push"
    return ""


def _under(path, base):
    path, base = os.path.realpath(path), os.path.realpath(base)
    return path == base or path.startswith(base.rstrip(os.sep) + os.sep)


def strict_targets(cwd):
    """-> [(path, worktrees_dir, slug)] for every strict row. Empty values are dropped
    here, so an empty path (a flat row) can never match by substring."""
    out = []
    for _cfg, rows in stu_env.families():
        for r in rows:
            if r.get("_flat") or not r.get("path") or not push_policy.strict(r):
                continue
            path = os.path.expanduser(r["path"])
            wt, slug = r.get("worktrees_dir") or "", r.get("slug") or ""
            try:
                got = stu_env.resolve(cwd=path, forge_lookup=False)
                path, wt, slug = got["MAIN_CHECKOUT"], got["WORKTREES_DIR"], got["REPO_SLUG"]
            except Exception:  # noqa: BLE001  keep the raw row
                wt = os.path.expanduser(wt) if wt else path + "-worktrees"
            out.append((path, wt, slug))
    try:  # a flat row is found only through the payload cwd
        got = stu_env.resolve(cwd=cwd, forge_lookup=False)
        if push_policy.strict(got):
            out.append((got["MAIN_CHECKOUT"], got["WORKTREES_DIR"], got["REPO_SLUG"]))
    except (stu_env.NoConfig, stu_env.NotInRepo, stu_env.ConfigError):
        pass
    return out


def strict_condition(payload, text):
    """Is the payload cwd inside a strict row (or its worktrees dir), or does TEXT name a
    strict row's path, worktrees dir or slug?"""
    cwd = payload.get("cwd") or os.getcwd()
    if os.path.isdir(cwd):
        os.chdir(cwd)
    low = text.lower()
    try:  # a worktree anywhere is the row stu-env resolves it to (git common dir)
        if push_policy.strict(stu_env.resolve(cwd=cwd, forge_lookup=False)):
            return True
    except (stu_env.NoConfig, stu_env.NotInRepo, stu_env.ConfigError):
        pass
    for path, wt, slug in strict_targets(cwd):
        if any(b and _under(cwd, b) for b in (path, wt)):
            return True
        if any(b and b in text for b in (path, wt)) or (slug and slug.lower() in low):
            return True
    return False


def _root_like(path):
    """A path that names no single checkout: empty, the filesystem root, or the home dir."""
    norm = os.path.normpath(path) if path else ""
    if not norm or norm.strip(os.sep) == "":
        return True
    return os.path.realpath(norm) in (os.sep, os.path.realpath(os.path.expanduser("~")))


def _unreadable_names(payload, text):
    """-> the config path of a family that fails to load and whose raw `path:` lines hold
    the payload cwd or appear in TEXT, else "". families() lists a broken config with no
    rows, so it is the only place such a family can still be seen."""
    cwd = payload.get("cwd") or os.getcwd()
    for cfg, rows in stu_env.families():
        if rows:
            continue
        try:
            with open(cfg, encoding="utf-8", errors="replace") as fh:
                raw = fh.read()
        except OSError:
            return cfg
        for x in stu_env._PATH_RE.findall(raw):
            ex = os.path.expanduser(x.strip().strip("\"'"))
            if _root_like(ex):  # never a usable target: it would match every command
                continue
            if ex.startswith("/") and (_under(cwd, ex) or ex in text):
                return cfg
    return ""


def config_failure(payload, text=""):
    """-> a reason when the config that governs the payload cwd exists but cannot be read or
    validated (or a resolver raises), else "". NoConfig, NotInRepo and a readable config with
    no row for this repo are not failures, but a broken family the text names still is."""
    cwd = payload.get("cwd") or os.getcwd()
    try:
        stu_env.resolve(cwd=cwd, forge_lookup=False)
    except (stu_env.NoConfig, stu_env.NotInRepo):
        pass  # no config governs cwd; a broken family can still be named by the text
    except stu_env.ConfigError as e:
        first = (str(e).splitlines() or [""])[0]
        if "no repo row matches" not in first:  # a readable config with no row is no failure
            return "the stu config cannot be read (%s)" % first
    except BaseException as e:  # noqa: BLE001  SystemExit from a resolver included
        return "the stu config cannot be read (%s)" % (str(e).splitlines() or [type(e).__name__])[0]
    try:
        cfg = _unreadable_names(payload, text)
    except BaseException as e:  # noqa: BLE001
        return "the stu config cannot be read (%s)" % type(e).__name__
    if cfg:
        return "the stu config %s cannot be read or validated" % os.path.basename(
            os.path.dirname(cfg) or cfg)
    return ""


def check_bypass(payload):
    if payload.get("tool_name") != "Bash":
        return ""
    text = _text(payload)
    what = _bypass_text(text)
    if what and strict_condition(payload, text):
        return ("%s skips the pre-push approval hook, and this repo requires it; ask the "
                "owner to approve the commit with stu-approve and push normally" % what)
    if what:
        bad = config_failure(payload, text)
        if bad:
            return ("%s skips the pre-push approval hook, and %s, so the repo cannot be "
                    "shown to be exempt; fix the config" % (what, bad))
    return ""


# ---- check 3: text published through the forge on a public row -------------------------

def _public_rows():
    """-> [(family, resolve() dict)] for every public row with a checkout."""
    out = []
    for cfg, rows in stu_env.families():
        for r in rows:
            if r.get("_flat") or not r.get("path"):
                continue
            if (r.get("visibility") or "").strip().lower() != "public":
                continue
            try:
                got = stu_env.resolve(cwd=r["path"], forge_lookup=False)
            except Exception:  # noqa: BLE001
                continue
            out.append(((cfg, rows), got))
    return out


def _target_row(payload, text):
    """-> (family, public row dict) the command publishes to, or None when it is not a
    public row. A -R/--repo slug naming a family row wins, else the payload cwd."""
    cwd = payload.get("cwd") or os.getcwd()
    for m in GH_REPO_FLAG.finditer(text):
        slug = m.group(1).lower()
        for cfg, rows in stu_env.families():
            for r in rows:
                if (r.get("slug") or "").lower() == slug and r.get("path"):
                    if (r.get("visibility") or "").strip().lower() != "public":
                        return None
                    got = stu_env.resolve(cwd=r["path"], forge_lookup=False)
                    return (cfg, rows), got
    try:
        got = stu_env.resolve(cwd=cwd, forge_lookup=False)
    except (stu_env.NoConfig, stu_env.NotInRepo):
        return None
    if got["VISIBILITY"] != "public":
        return None
    fam = push_policy.family_of(got["CONFIG_PATH"])
    return (fam, got) if fam else None


def _body_files(text, cwd):
    out = []
    for m in GH_BODY_FILE.finditer(text):
        p = m.group(1)
        if p != "-":
            out.append(p if os.path.isabs(p) else os.path.join(cwd, p))
    return out


def check_forge(payload):
    tool = payload.get("tool_name", "")
    if tool.startswith("mcp__"):
        return _check_mcp(payload, tool)
    if tool != "Bash":
        return ""
    text = _text(payload)
    if not GH_PUBLISH.search(text):
        return ""
    target = _target_row(payload, text)
    if not target or not target[0]:
        bad = config_failure(payload, text)
        if bad:
            return ("this command publishes text through gh, and %s, so the repo cannot be "
                    "shown to be exempt from the scan; fix the config" % bad)
        return ""
    fam, row = target
    cwd = payload.get("cwd") or os.getcwd()
    items = push_policy.private_list(fam, row)
    rxs = push_policy.private_regexes(fam, row)
    texts = [("the command text", text)]
    for f in _body_files(text, cwd):
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                texts.append(("the body file " + os.path.basename(f), fh.read()))
        except OSError as e:
            return ("the body file %s cannot be read (%s), so its text cannot be scanned "
                    "before it is published on %s" % (os.path.basename(f), e.strerror,
                                                      row["REPO_SLUG"]))
    deadline = time.monotonic() + push_policy.SCAN_BUDGET
    for where, t in texts:
        hits = push_policy.scan(t, items, rxs, deadline=deadline)
        if hits:
            return ("%s would publish the private-repo item '%s' on %s; reword it"
                    % (where, hits[0], row["REPO_SLUG"]))
    return ""


def _mcp_writes(tool):
    return any(w in tool.lower() for w in MCP_WRITE_WORDS)


def _check_mcp(payload, tool):
    if not _mcp_writes(tool):
        return ""
    blob = json.dumps(payload.get("tool_input", {})).lower()
    for _fam, row in _public_rows():
        slug = row["REPO_SLUG"].lower()
        if slug and slug in blob:
            return ("%s writes to the public repo %s through a tool whose text cannot be "
                    "scanned; use git or gh so the text can be scanned" % (tool, row["REPO_SLUG"]))
    return ""


# ---- driver -----------------------------------------------------------------------------

def evaluate(payload):
    """-> a deny reason, or None. Never raises."""
    try:
        return (check_approval_file(payload) or check_bypass(payload)
                or check_forge(payload) or None)
    except BaseException:  # noqa: BLE001  SystemExit from a resolver included
        return on_error(payload)


def on_error(payload):
    """Some check failed: deny only where check 1 (plain text) or check 2's strict-row
    condition holds, else allow. A Write/Edit gets check 1 only."""
    try:
        tool = payload.get("tool_name", "")
        if tool in WRITE_TOOLS:
            return _fallback_file(payload) or None
        if tool.startswith("mcp__"):
            if _mcp_writes(tool) and strict_condition(payload, json.dumps(
                    payload.get("tool_input", {}))):
                return "a guard check failed on a write through %s in a strict repo; use " \
                       "git or gh so the text can be scanned" % tool
            return None
        if tool != "Bash":
            return None
        text = _text(payload)
        if _approval_text(text):
            return _approval_text(text)
        bypass, forge = _bypass_text(text), GH_PUBLISH.search(text)
        if bypass or forge:
            bad = config_failure(payload, text)
            if bad:
                return "a guard check failed on a command that %s, and %s; fix the config" % (
                    "bypasses the pre-push hook" if bypass else "publishes through gh", bad)
        if bypass and strict_condition(payload, text):
            return "a guard check failed on a command that bypasses the pre-push hook of " \
                   "a strict repo; run it as the owner or fix the config"
        if forge and strict_condition(payload, text):
            return "a guard check failed on text published through gh from a strict repo; " \
                   "fix the config and try again"
    except BaseException:  # noqa: BLE001
        pass
    return None


def _fallback_file(payload):
    if os.path.basename(_file_target(payload)).lower() == APPROVAL_FILE:
        return "%s is written only by the owner (stu-approve)" % APPROVAL_FILE
    return ""


def main():
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        if not isinstance(payload, dict):
            payload = {}
    except Exception:  # noqa: BLE001
        payload = {}
    reason = evaluate(payload)
    if reason:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": "stu publish guard: " + reason}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
