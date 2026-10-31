#!/usr/bin/env python3
"""stu-env: resolve repo paths and per-repo config at run time.

  stu-env [--json] [--defaults] [--repo NAME]
                            KEY=value lines (shell-quoted); --defaults needs no config
  stu-env section ID [--repo NAME]
                            body of "## ID" (a non-home row: "## ID @NAME"); empty if absent
  stu-env rows              one line per repo row: NAME<TAB>PATH<TAB>SLUG<TAB>VISIBILITY<TAB>HOME|-
  stu-env records ID [--repo NAME]
                            one JSON object per "### name" record in the section
  stu-env commands ID [--repo NAME]
                            the lines inside fenced blocks of the section, comments dropped

Exit codes: 0 ok; 1 not in a git repo; 2 no config; 3 config invalid, ambiguous, no row
matches, a mandatory key is missing, or no base branch resolves; 4 usage error.

Config lookup: $STU_CONFIG (the only candidate) -> <main checkout>/.claude/stu.md ->
~/.stu/<project>/stu.md -> every ~/.stu/*/stu.md with a `## repos` table that names the
repo. Config = flat `key: value` frontmatter + Markdown `## id` sections. A `## repos`
section holds one `### name` block of `key: value` lines per repo; the first is home. Any
`ci_<name>` frontmatter key is exported as `CI_<NAME>`; `triage_extra` as `TRIAGE_EXTRA`.
HTML comments in a section (the template's /stu:init questions) are not part of its body.
A flat config (no table) is a family of one; every row key may sit in its frontmatter.
"""
import contextlib
import glob
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys

NO_CONFIG = "stu: no config for this repo — run /stu:init"
BASE_KEYS = ["MAIN_CHECKOUT", "REPO_ROOT", "PROJECT", "OWNER", "PROJECT_GUIDE",
             "RUN_HOME", "WORKTREES_DIR", "GITHUB_REPO", "CONFIG_PATH"]
ROW_KEYS = ["REPO_NAME", "REPO_SLUG", "REMOTE", "BASE", "BASE_SOURCE", "VISIBILITY", "MODE",
            "MERGE_MODE", "MERGE_METHOD", "CI_KIND", "REQUIRED_CHECKS", "TAG_BY",
            "TAG_FORMAT", "VERSION_RULE", "PIN_FILES", "HUMAN_CHECKPOINTS", "ISSUES_REPO",
            "FAMILY_ROWS", "IS_HOME", "GH_HOST", "GH_REPO", "INITIAL_VERSION",
            "CI_SKIPPED_IS_SUCCESS"]
MERGE_MODES = ("direct", "label-handoff", "report-only", "direct-push")
MODES = ("work", "pr-only", "park")
CI_KINDS = ("aggregator", "list", "none")
FAMILY_ONLY_KEYS = ("run_home", "project", "owner", "triage_extra", "completion_mode",
                    "stop_condition_2", "deep_pass_model")
FAMILY_ONLY_SECTIONS = ("completion-mode", "stop-condition-2", "deep-pass-model")
MANDATORY = ("slug", "remote", "base", "visibility", "mode", "merge_mode", "ci")


class NoConfig(Exception):
    """No config found (exit 2)."""


class ConfigError(Exception):
    """Config invalid, ambiguous, or unresolvable (exit 3)."""


class NotInRepo(Exception):
    """Not inside a git repository (exit 1)."""


class UsageError(Exception):
    """Bad command line (exit 4)."""


@contextlib.contextmanager
def _in(path):
    """Prefix a bare ConfigError message with the config file it came from."""
    try:
        yield
    except ConfigError as e:
        msg = str(e)
        if msg.startswith("stu: "):
            raise
        raise ConfigError("stu: config error in %s: %s" % (path, msg))


def _git(cwd, *args):
    try:
        p = subprocess.run(["git"] + list(args), cwd=cwd, capture_output=True, text=True)
    except OSError:
        return ""
    return p.stdout.strip() if p.returncode == 0 else ""


def _github_repo(main, host=""):
    env = dict(os.environ)
    if host:
        env["GH_HOST"] = host
    try:
        p = subprocess.run(["gh", "repo", "view", "--json", "nameWithOwner",
                            "-q", ".nameWithOwner"], cwd=main, capture_output=True,
                           text=True, timeout=5, stdin=subprocess.DEVNULL, env=env)
        out = p.stdout.strip()
        if p.returncode == 0 and "/" in out:
            return out
    except (OSError, subprocess.SubprocessError):
        pass
    sys.stderr.write("stu: warning: GITHUB_REPO unresolved\n")
    return ""


_REMOTE = re.compile(
    r"^(?:(?:https?|ssh|git)://)?(?:[^@/\s]+@)?"
    r"([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)(?::\d+)?[:/]+([^/\s:]+)/([^/\s]+?)(?:\.git)?/?$")


def _parse_remote(url):
    """(host, owner/repo) parsed offline from a remote URL (https or ssh forms), or None."""
    m = _REMOTE.match(url.strip())
    return (m.group(1), "%s/%s" % (m.group(2), m.group(3))) if m else None


def _remote_info(main, remote, warn=False):
    """(host, slug) of one remote ("", "" when it is absent or not a forge URL). With
    warn, a second forge remote prints a stderr warning naming both and the one chosen."""
    got = _parse_remote(_git(main, "remote", "get-url", remote)) if main else None
    if got and warn:
        others = []
        for name in _git(main, "remote").split():
            if name != remote:
                o = _parse_remote(_git(main, "remote", "get-url", name))
                if o:
                    others.append("%s=%s" % (name, o[1]))
        if others:
            sys.stderr.write(
                "stu: warning: several forge remotes (%s, %s=%s); using '%s' (%s). Set "
                "'slug:' or 'remote:' in the config to choose.\n"
                % (", ".join(others), remote, got[1], remote, got[1]))
    return got if got else ("", "")


def _split_config(text):
    """-> (frontmatter dict, body text)."""
    lines = text.splitlines()
    fm, body_start = {}, 0
    close = None
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                close = i
                break
    if close is not None:
        body_start = close + 1
        for i in range(1, close):
            s = lines[i].strip()
            if not s or s.startswith("#") or ":" not in s:
                continue
            k, _, v = s.partition(":")
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                v = v[1:-1]
            k = k.strip().lower()
            if k.startswith("ci_") and not re.fullmatch(r"ci_[a-z0-9_]+", k):
                sys.stderr.write("stu: warning: ignoring invalid config key %r\n" % k)
                continue
            fm[k] = v
    return fm, "\n".join(lines[body_start:])


def _read(path):
    with open(path, encoding="utf-8-sig") as f:
        return f.read()


def _ex(p):
    return os.path.expanduser(p)


def _slug(github, main):
    if github:
        return github.replace("/", "-")
    h = hashlib.sha1(main.encode("utf-8")).hexdigest()[:6]
    return "%s-%s" % (os.path.basename(main), h)


def _locate(cwd):
    """-> (top, main checkout) realpaths. Raises NotInRepo."""
    top = _git(cwd, "rev-parse", "--show-toplevel")
    common = _git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if not top or not common:
        raise NotInRepo("stu: not inside a git repository")
    return os.path.realpath(top), os.path.realpath(os.path.dirname(common.rstrip("/")))


def _uncomment(line, in_comment):
    """Drop <!-- ... --> spans (which may span lines). -> (kept text, still in comment)."""
    out = ""
    while line:
        if in_comment:
            end = line.find("-->")
            if end < 0:
                return out, True
            line, in_comment = line[end + 3:], False
        else:
            start = line.find("<!--")
            if start < 0:
                return out + line, False
            out, line, in_comment = out + line[:start], line[start + 4:], True
    return out, in_comment


def _sections(body):
    """-> (ordered unique headings, {heading: [lines]}); fences and comments respected."""
    order, got = [], {}
    cur, fence, comment = None, False, False
    for line in body.splitlines():
        if not comment and line.lstrip().startswith("```"):
            fence = not fence
        elif not fence:
            was_comment = comment
            line, comment = _uncomment(line, comment)
            if not was_comment and line.startswith("## "):
                cur = line[3:].strip()
                if cur not in got:
                    order.append(cur)
                    got[cur] = []
                continue
            if was_comment and not line.strip():
                continue
        if cur is not None:
            got[cur].append(line)
    return order, got


def section(body, sid, repo=None, home=True):
    """Body of "## sid" (a non-home row: "## sid @repo"), minus HTML comments.

    A family-only section has one body for the whole family, so it always reads the
    top-level "## sid", whichever row asks."""
    target = sid if (home or not repo or sid in FAMILY_ONLY_SECTIONS) else "%s @%s" % (sid, repo)
    return "\n".join(_sections(body)[1].get(target, [])).strip()


_KV = re.compile(r"^\s*([A-Za-z0-9_-]+)\s*:\s*(.*?)\s*$")


def records(text):
    """One dict per "### name" record: {"name": name, "<key>": "<value>", ...}."""
    out, cur, fence = [], None, False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        if line.startswith("### "):
            cur = {"name": line[4:].strip()}
            out.append(cur)
            continue
        m = _KV.match(line)
        if cur is not None and m:
            cur[m.group(1)] = m.group(2)
    return out


def commands(text):
    """Lines inside fenced blocks, one command per line; comments and blanks dropped."""
    out, fence = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fence = not fence
            continue
        s = line.strip()
        if fence and s and not s.startswith("#"):
            out.append(s)
    return out


def rows(fm, body):
    """The repo rows of a config. A `## repos` table -> one dict per `### name` block
    (keys lowercased, `path` expanded to a realpath); a flat config -> one implicit row of
    its frontmatter, with an empty `path`. Raises ConfigError."""
    order, got = _sections(body)
    if "repos" not in got:
        r = dict(fm)
        r["name"] = fm.get("project", "")
        r["path"] = ""
        r["_flat"] = True
        return [r]
    out, seen = [], set()
    for rec in records("\n".join(got["repos"])):
        name = rec.pop("name")
        r = {"name": name}
        for k, v in rec.items():
            k = k.lower().replace("-", "_")
            if k.startswith("ci_") and not re.fullmatch(r"ci_[a-z0-9_]+", k):
                sys.stderr.write("stu: warning: ignoring invalid config key %r\n" % k)
                continue
            r[k] = v
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
            raise ConfigError("repo row name %r is not usable; use letters, digits, '.', "
                              "'_' or '-'" % name)
        if name in seen:
            raise ConfigError("row %s: name appears twice under '## repos'; rename one"
                              % name)
        seen.add(name)
        for k in FAMILY_ONLY_KEYS:
            if k in r:
                raise ConfigError(
                    "row %s: key '%s' is family-only; move it to the frontmatter" % (name, k))
        if not r.get("path"):
            raise ConfigError("row %s: key 'path' is missing; add 'path: ~/Dev/%s' (the "
                              "checkout) under '### %s'" % (name, name, name))
        if not _ex(r["path"]).startswith("/"):
            raise ConfigError("row %s: path %r is not absolute; start it with '/' or '~'"
                              % (name, r["path"]))
        r["path"] = os.path.realpath(_ex(r["path"]))
        out.append(r)
    if not out:
        raise ConfigError("'## repos' has no '### name' rows; add one per repo")
    for h in order:
        m = re.fullmatch(r"(\S+)\s+@(\S+)", h)
        if not m:
            continue
        if m.group(1) in FAMILY_ONLY_SECTIONS:
            raise ConfigError("section '## %s' is family-only and cannot be per repo; "
                              "rename it to '## %s'" % (h, m.group(1)))
        if m.group(2) not in seen:
            raise ConfigError("section '## %s' names no repo row; use one of: %s"
                              % (h, ", ".join(sorted(seen))))
    return out


def row_for_path(rows_, path):
    """The one row whose realpath equals PATH. Raises ConfigError on none or several."""
    real = os.path.realpath(path)
    if len(rows_) == 1 and rows_[0].get("_flat"):
        return rows_[0]
    hit = [r for r in rows_ if r["path"] == real]
    if not hit:
        raise ConfigError("no repo row matches %s (rows: %s); add a '### <name>' block with "
                          "'path: %s' under '## repos'"
                          % (real, ", ".join("%s=%s" % (r["name"], r["path"]) for r in rows_),
                             real))
    if len(hit) > 1:
        raise ConfigError("%d rows share the path %s (%s); give each row its own checkout"
                          % (len(hit), real, ", ".join(r["name"] for r in hit)))
    return hit[0]


# ---- discovery -------------------------------------------------------------------------

def _load(path):
    """-> {path (realpath), fm, body, rows, table}. Raises ConfigError, NoConfig."""
    real = os.path.realpath(path)
    try:
        text = _read(real)
    except OSError as e:
        raise ConfigError("stu: config error in %s: cannot read it (%s); fix the file's "
                          "permissions" % (real, e.strerror or e))
    except ValueError:
        raise ConfigError("stu: config error in %s: not valid UTF-8; re-save the file as "
                          "UTF-8" % real)
    fm, body = _split_config(text)
    with _in(real):
        rs = rows(fm, body)
    return {"path": real, "fm": fm, "body": body, "rows": rs,
            "table": not rs[0].get("_flat")}


_TABLE_RE = re.compile(r"(?m)^## repos[ \t]*$")
_PATH_RE = re.compile(r"(?m)^\s*path\s*:\s*(.+?)\s*$")


def _scan(main=None, repo=None):
    """Every ~/.stu/*/stu.md with a `## repos` table, loaded. A table that fails to load is
    skipped with a stderr warning unless it could claim MAIN (a `path:` line equal to it),
    in which case its ConfigError propagates, so a broken family is never read as none."""
    out = []
    for p in sorted(glob.glob(os.path.join(_ex("~/.stu"), "*", "stu.md"))):
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        if not _TABLE_RE.search(text):
            continue
        try:
            out.append(_load(p))
        except ConfigError as e:
            paths = [os.path.realpath(_ex(x)) for x in _PATH_RE.findall(text)]
            named = repo and re.search(r"(?m)^### %s[ \t]*$" % re.escape(repo), text)
            if (main and main in paths) or named:
                raise
            sys.stderr.write("%s\nstu: warning: skipping that config (it does not name "
                             "this repo)\n" % e)
    return out


def _claimants(main, github):
    """The one config that claims MAIN, as a list of 0 or 1. Raises ConfigError when a
    family table shares the repo with any other config."""
    found = []

    def add(c):
        if all(c["path"] != f["path"] for f in found):
            found.append(c)

    local = os.path.join(main, ".claude", "stu.md")
    # Codex shares existing configurations, but may create a neutral one. Keep
    # Claude's lookup unchanged; two distinct local configs require a choice.
    if os.environ.get("STU_RUNTIME") == "codex":
        neutral = os.path.join(main, ".stu", "stu.md")
        if os.path.isfile(neutral):
            if os.path.isfile(local) and os.path.realpath(local) != os.path.realpath(neutral):
                raise ConfigError("stu: both .stu/stu.md and .claude/stu.md exist; "
                                  "set STU_CONFIG to the one shared configuration to use")
            local = neutral
    if os.path.isfile(local):
        add(_load(local))
    else:
        gh = github()
        fallback = _slug("", main)
        cands = [_slug(gh, main)] if gh else []
        if fallback not in cands:
            cands.append(fallback)
        for cand in cands:
            home_cfg = os.path.join(_ex("~/.stu"), cand, "stu.md")
            if os.path.isfile(home_cfg):
                c = _load(home_cfg)
                c["_cand"] = cand
                add(c)
                break
    for c in _scan(main=main):
        if any(r["path"] == main for r in c["rows"]):
            add(c)
    if len(found) > 1 and any(c["table"] for c in found):
        raise ConfigError(
            "stu: config error: several configs claim %s: %s; keep one (delete the others, "
            "or set STU_CONFIG to the one to use)"
            % (main, ", ".join(c["path"] for c in found)))
    return found[:1]


def families():
    """Every discovered config path with its rows, the same scan resolve uses. Never
    raises: an unreadable or invalid config appears with an empty row list and is
    reported on stderr."""
    paths = []
    env = os.environ.get("STU_CONFIG")
    if env:
        paths.append(_ex(env))
    else:
        try:
            _, main = _locate(os.getcwd())
            paths.append(os.path.join(main, ".claude", "stu.md"))
            if os.environ.get("STU_RUNTIME") == "codex":
                paths.append(os.path.join(main, ".stu", "stu.md"))
        except NotInRepo:
            pass
        paths.extend(sorted(glob.glob(os.path.join(_ex("~/.stu"), "*", "stu.md"))))
    out, seen = [], set()
    for p in paths:
        if not os.path.isfile(p) or os.path.realpath(p) in seen:
            continue
        seen.add(os.path.realpath(p))
        try:
            out.append((os.path.realpath(p), _load(p)["rows"]))
        except (ConfigError, OSError, ValueError) as e:
            sys.stderr.write("%s\n" % e)
            out.append((os.path.realpath(p), []))
    return out


def _holds(c, repo, main, github):
    """Does config C have the row (table) or project name (flat) REPO?"""
    if c["table"]:
        return any(r["name"] == repo for r in c["rows"])
    return repo in (c["fm"].get("project"), c.get("_cand"), _slug(github(), main))


def _find(top, main, repo, github):
    """-> the config to use, or None. STU_CONFIG short-circuits everything."""
    env_cfg = os.environ.get("STU_CONFIG")
    if env_cfg:
        if not os.path.isfile(_ex(env_cfg)):
            raise NoConfig("stu: STU_CONFIG not found: %s" % env_cfg)
        return _load(_ex(env_cfg))
    claimed = None
    if main:
        found = _claimants(main, github)
        if found:
            claimed = found[0]
            if not repo or _holds(claimed, repo, main, github):
                return claimed
        elif not repo:
            return None
    elif not repo:
        raise NotInRepo("stu: not inside a git repository")
    # --repo with nothing claimed by the cwd repo (or no repo at all): a family naming it.
    scanned = _scan(main=main, repo=repo)
    hits = [c for c in scanned if any(r["name"] == repo for r in c["rows"])]
    if len(hits) > 1:
        raise ConfigError("stu: config error: several families have a row named %s: %s; "
                          "set STU_CONFIG to the one to use"
                          % (repo, ", ".join(c["path"] for c in hits)))
    if hits:
        return hits[0]
    if claimed:
        return claimed  # resolve() reports the missing row
    if scanned:
        raise ConfigError("stu: config error: no family has a row named %r (looked in: %s); "
                          "check the name or set STU_CONFIG"
                          % (repo, ", ".join(c["path"] for c in scanned)))
    if not main:
        raise NotInRepo("stu: not inside a git repository, and no config names a row %r"
                        % repo)
    return None


# ---- resolution ------------------------------------------------------------------------

def _mode_word(w, where):
    if w not in MERGE_MODES:
        raise ConfigError("%s names the merge mode %r; use one of %s"
                          % (where, w, "|".join(MERGE_MODES)))
    return w


def _flat_merge_mode(path, fm, body):
    """-> (mode, explicit). Frontmatter, then a `Mode:` line, then empty -> direct, then
    one-word prose (with a warning), else ConfigError."""
    if fm.get("merge_mode"):
        return _mode_word(fm["merge_mode"], "key merge_mode"), True
    text = section(body, "merge-mode")
    if not text:
        return "direct", False
    m = re.search(r"(?mi)^\s*Mode:\s*([A-Za-z-]+)", text)
    if m:
        return _mode_word(m.group(1).lower(), "## merge-mode"), True
    words = set(re.findall(
        r"(?<![A-Za-z0-9-])(direct-push|label-handoff|report-only|direct)(?![A-Za-z0-9-])",
        text))
    if len(words) == 1:
        w = next(iter(words))
        sys.stderr.write("stu: warning: %s: ## merge-mode is prose; read as '%s'. Add a "
                         "line 'Mode: %s' as its first line to silence this.\n" % (path, w, w))
        return w, True
    raise ConfigError(
        "## merge-mode needs a line 'Mode: direct|label-handoff|report-only|direct-push'; "
        "add one, e.g. 'Mode: label-handoff'")


def _csv(v):
    return ",".join(x.strip() for x in v.split(",") if x.strip())


def _enc_check(name):
    for ch, rep in (("%", "%25"), (" ", "%20"), ("\t", "%09"), ("\n", "%0A")):
        name = name.replace(ch, rep)
    return name


def _base(r, path, remote, slug, host, forge_lookup):
    """-> (base, source), or ("", "") when nothing resolves."""
    if r.get("base"):
        return r["base"], "config"
    if not path or not os.path.isdir(path):
        return "", ""
    prefix = "refs/remotes/%s/" % remote
    sym = _git(path, "symbolic-ref", "refs/remotes/%s/HEAD" % remote)
    # A remote whose default branch was renamed leaves a dangling HEAD: verify the target.
    if sym.startswith(prefix) and _git(path, "rev-parse", "--verify", "--quiet", sym):
        return sym[len(prefix):], "symbolic-ref"
    if forge_lookup:
        env = dict(os.environ)
        if host:
            env["GH_HOST"] = host
        cmd = ["gh", "repo", "view"] + ([slug] if slug else []) + ["--json", "defaultBranchRef"]
        try:
            p = subprocess.run(cmd, cwd=path, capture_output=True, text=True, timeout=5,
                               stdin=subprocess.DEVNULL, env=env)
            if p.returncode == 0:
                name = json.loads(p.stdout)["defaultBranchRef"]["name"]
                if isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9._/-]+", name):
                    return name, "forge"
        except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
            pass
    if _git(path, "rev-parse", "--verify", "--quiet", prefix + "main"):
        return "main", "fallback"
    return "", ""


def _validate(r, name, strict, home, body, mode, ci_kind):
    """Mandatory keys in a family of two or more rows, and enumerated values."""
    if strict:
        for k in MANDATORY:
            if k == "merge_mode" and mode == "pr-only":
                continue
            if not r.get(k):
                raise ConfigError(
                    "row %s: mandatory key '%s' is missing; add '%s: <value>' under '### %s'"
                    % (name, k, k, name))
        if not commands(section(body, "verification-commands", name, home)):
            raise ConfigError(
                "row %s: mandatory section 'verification-commands' is missing or has no "
                "fenced commands; add '## verification-commands%s' with a fenced block"
                % (name, "" if home else " @" + name))
    if mode not in MODES:
        raise ConfigError("row %s: mode %r must be one of %s; fix the 'mode:' line"
                          % (name, mode, "|".join(MODES)))
    if ci_kind not in CI_KINDS:
        raise ConfigError("row %s: ci %r must be one of %s; fix the 'ci:' line"
                          % (name, ci_kind, "|".join(CI_KINDS)))


def resolve(cwd=None, require_config=True, repo=None, forge_lookup=True):
    """Resolve the run environment. Raises NoConfig when require_config and no config,
    ConfigError for an invalid or ambiguous config, NotInRepo outside a git repository.
    Never SystemExit. forge_lookup=False never calls `gh` (hooks)."""
    return _resolve(cwd, require_config, repo, forge_lookup, True)


def _resolve(cwd, require_config, repo, forge_lookup, full):
    cwd = cwd or os.getcwd()
    try:
        top, main = _locate(cwd)
    except NotInRepo:
        top = main = None
    memo = {}

    def forge_slug(path):
        """Today's slug fallbacks, once per path: the origin URL, then gh."""
        if path not in memo:
            v = _remote_info(path, "origin")[1]
            if not v and forge_lookup and path:
                v = _github_repo(path)
            memo[path] = v
        return memo[path]

    cfg = _find(top, main, repo, lambda: forge_slug(main))
    if cfg is None:
        if require_config:
            raise NoConfig(NO_CONFIG)
        if not main:
            raise NotInRepo("stu: not inside a git repository")
        cfg = {"path": "", "fm": {}, "body": "", "table": False,
               "rows": [{"name": "", "path": "", "_flat": True}]}
    fm, body, rows_, cpath, table = cfg["fm"], cfg["body"], cfg["rows"], cfg["path"], cfg["table"]
    label = cpath or "(defaults)"

    # Which row?
    if table:
        if repo:
            hit = [x for x in rows_ if x["name"] == repo]
            if not hit:
                raise ConfigError("stu: config error in %s: no repo row named %r; rows: %s"
                                  % (cpath, repo, ", ".join(x["name"] for x in rows_)))
        else:
            if not main:
                raise NotInRepo("stu: not inside a git repository (name a row with --repo)")
            with _in(cpath):
                hit = [row_for_path(rows_, main)]
        r = dict(hit[0])
        row_path = r["path"]
    else:
        if not main:
            raise NotInRepo("stu: not inside a git repository")
        r = dict(rows_[0])
        row_path = main
    home = rows_[0]["name"] == r["name"] if table else True
    strict = table and len(rows_) >= 2
    remote = r.get("remote") or "origin"

    # Slug and host.
    explicit_slug = r.get("slug") or r.get("github_repo") or ""
    url_host, url_slug = _remote_info(row_path, remote, warn=not (explicit_slug or r.get("remote")))
    host = r.get("host") or url_host
    slug = explicit_slug or url_slug
    if not slug and forge_lookup:
        slug = forge_slug(row_path) if row_path == main else _github_repo(row_path, host)

    # Names.
    if table:
        name = r["name"]
        if fm.get("project"):
            project = fm["project"]
        elif os.path.dirname(os.path.dirname(cpath)) == os.path.realpath(_ex("~/.stu")):
            project = os.path.basename(os.path.dirname(cpath))
        else:
            project = _slug(rows_[0].get("slug", ""), rows_[0]["path"])
    else:
        project = fm.get("project") or cfg.get("_cand") or _slug(slug, main)
        name = project
        if repo and repo != project:
            raise ConfigError("stu: config error in %s: this is a one-repo config named "
                              "%r, not %r" % (label, project, repo))

    def homeget(k):
        return r.get(k) or (fm.get(k, "") if home else "")

    guide = homeget("guide") or (
        "AGENTS.md" if os.environ.get("STU_RUNTIME") == "codex"
        and os.path.exists(os.path.join(row_path, "AGENTS.md")) else
        "CLAUDE.md" if os.path.exists(os.path.join(row_path, "CLAUDE.md")) else "AGENTS.md")
    wt = homeget("worktrees_dir")
    belongs = bool(main) and os.path.realpath(main) == os.path.realpath(row_path)

    visibility = r.get("visibility") or "unset"
    visibility = "private" if visibility == "internal" else visibility
    mode = r.get("mode") or "work"
    ci_kind = r.get("ci") or "aggregator"
    merge_mode, base, base_source, skipped = "direct", "", "", "false"
    if full:
        with _in(label):
            _validate(r, name, strict, home, body, mode, ci_kind)
            if visibility not in ("public", "private", "unset"):
                raise ConfigError("row %s: visibility %r must be public|private|unset; fix "
                                  "the 'visibility:' line" % (name, visibility))
            explicit = bool(r.get("merge_mode"))
            if explicit:
                merge_mode = _mode_word(r["merge_mode"], "row %s key merge_mode" % name)
            elif home and not strict:
                merge_mode, explicit = _flat_merge_mode(label, fm, body)
            if mode == "pr-only":
                if explicit and merge_mode != "report-only":
                    raise ConfigError(
                        "row %s: mode 'pr-only' means merge mode report-only but merge_mode "
                        "is %r; remove 'merge_mode:' or set it to report-only"
                        % (name, merge_mode))
                merge_mode = "report-only"
            if r.get("tag_by") == "stu" and merge_mode == "report-only":
                raise ConfigError(
                    "row %s: 'tag_by: stu' cannot combine with merge mode report-only (a "
                    "human merges, so stu has no commit to tag); remove 'tag_by:' or change "
                    "the merge mode" % name)
            if merge_mode == "direct-push" and "before-push" in _csv(
                    r.get("human_checkpoints", "")).split(","):
                raise ConfigError(
                    "row %s: merge mode direct-push cannot combine with 'human_checkpoints: "
                    "before-push' (there is no PR to wait on); drop one of them" % name)
            if ci_kind == "list" and not _csv(r.get("required_checks", "")):
                raise ConfigError("row %s: 'ci: list' needs 'required_checks:' (comma-"
                                  "separated check names); add it" % name)
            skipped = (homeget("ci_skipped_is_success") or "false").lower()
            if skipped not in ("true", "false"):
                raise ConfigError("row %s: ci_skipped_is_success must be true or false, "
                                  "not %r" % (name, skipped))
            base, base_source = _base(r, row_path, remote, slug, host, forge_lookup)
            if not base and forge_lookup and table and require_config:
                raise ConfigError("no base branch resolvable for row %s: set 'base:' under "
                                  "'### %s'" % (name, name))
        if not base and forge_lookup and not table and require_config and \
                _git(row_path, "remote", "get-url", remote):
            sys.stderr.write("stu: warning: no base branch resolvable for row %s: set "
                             "'base: <branch>' in %s\n" % (name, label))

    out = {
        "MAIN_CHECKOUT": row_path,
        "REPO_ROOT": top if (top and (belongs or not table)) else row_path,
        "PROJECT": project,
        "OWNER": fm.get("owner") or _git(top or row_path, "config", "user.name"),
        "PROJECT_GUIDE": guide,
        "RUN_HOME": _ex(fm["run_home"]) if fm.get("run_home")
        else os.path.join(_ex("~/.stu"), project),
        "WORKTREES_DIR": _ex(wt) if wt else row_path + "-worktrees",
        "GITHUB_REPO": slug,
        "CONFIG_PATH": cpath,
        "REPO_NAME": name,
        "REPO_SLUG": slug,
        "REMOTE": remote,
        "BASE": base,
        "BASE_SOURCE": base_source,
        "VISIBILITY": visibility,
        "MODE": mode,
        "MERGE_MODE": merge_mode,
        "MERGE_METHOD": r.get("merge_method") or "squash",
        "CI_KIND": ci_kind,
        "REQUIRED_CHECKS": ",".join(_enc_check(c.strip()) for c in
                                    r.get("required_checks", "").split(",") if c.strip()),
        "TAG_BY": r.get("tag_by", ""),
        "TAG_FORMAT": r.get("tag_format", ""),
        "VERSION_RULE": r.get("version_rule", ""),
        "PIN_FILES": _csv(r.get("pin_files", "")),
        "HUMAN_CHECKPOINTS": _csv(r.get("human_checkpoints", "")),
        "ISSUES_REPO": r.get("issues_repo") or slug,
        "FAMILY_ROWS": str(len(rows_)),
        "IS_HOME": "1" if home else "0",
        "GH_HOST": host or "github.com",
        "GH_REPO": slug,
        "INITIAL_VERSION": r.get("initial_version", ""),
    }
    out["TRIAGE_EXTRA"] = fm.get("triage_extra", "") if home else ""
    ci = {}
    if home:
        ci.update((k, v) for k, v in fm.items() if k.startswith("ci_") and len(k) > 3)
    ci.update((k, v) for k, v in r.items() if k.startswith("ci_") and len(k) > 3)
    for k in sorted(ci):
        out[k.upper()] = ci[k]
    out["CI_SKIPPED_IS_SUCCESS"] = skipped
    out["_BODY"] = body
    out["_HOME"] = home
    out["_NAME"] = name
    out["_ROWS"] = rows_
    out["_TABLE"] = table
    return out


# ---- command line ----------------------------------------------------------------------

def _parse_args(args):
    """-> (command, positionals, flags). Raises UsageError."""
    cmd = None
    if args and args[0] in ("section", "rows", "records", "commands"):
        cmd, args = args[0], args[1:]
    pos, flags, i = [], {}, 0
    while i < len(args):
        a = args[i]
        if a in ("--json", "--defaults"):
            flags[a] = True
        elif a == "--repo":
            if i + 1 >= len(args) or args[i + 1].startswith("--"):
                raise UsageError("--repo needs a row name")
            flags["--repo"] = args[i + 1]
            i += 1
        elif a.startswith("--repo="):
            flags["--repo"] = a[7:]
        elif a.startswith("-"):
            raise UsageError("unknown option %s" % a)
        else:
            pos.append(a)
        i += 1
    return cmd, pos, flags


USAGE = ("usage: stu-env [--json] [--defaults] [--repo NAME] | section|records|commands ID "
         "[--repo NAME] | rows")


def main(argv):
    try:
        return _main(argv[1:])
    except UsageError as e:
        sys.stderr.write("%s\n%s\n" % (e, USAGE))
        return 4
    except NoConfig as e:
        sys.stderr.write(str(e) + "\n")
        return 2
    except ConfigError as e:
        msg = str(e)
        sys.stderr.write((msg if msg.startswith("stu: ") else "stu: config error: " + msg)
                         + "\n")
        return 3
    except NotInRepo as e:
        sys.stderr.write(str(e) + "\n")
        return 1


def _main(args):
    cmd, pos, flags = _parse_args(args)
    repo = flags.get("--repo")
    if cmd in ("section", "records", "commands"):
        if len(pos) != 1 or "--json" in flags or "--defaults" in flags:
            raise UsageError("%s takes exactly one section id" % cmd)
        env = _resolve(None, True, repo, True, False)
        text = section(env["_BODY"], pos[0], env["_NAME"], env["_HOME"])
        if cmd == "section":
            if text:
                sys.stdout.write(text + "\n")
        elif cmd == "records":
            for rec in records(text):
                sys.stdout.write(json.dumps(rec) + "\n")
        else:
            for c in commands(text):
                sys.stdout.write(c + "\n")
        return 0
    if cmd == "rows":
        if pos or flags:
            raise UsageError("rows takes no arguments")
        env = _resolve(None, True, None, True, False)
        for i, r in enumerate(env["_ROWS"]):
            if env["_TABLE"]:
                slug = r.get("slug", "")
                path = r["path"]
                name = r["name"]
            else:
                slug, path, name = env["GITHUB_REPO"], env["MAIN_CHECKOUT"], env["PROJECT"]
            vis = (r.get("visibility") or "unset")
            vis = "private" if vis == "internal" else vis
            sys.stdout.write("\t".join([name, path, slug, vis, "HOME" if i == 0 else "-"])
                             + "\n")
        return 0
    if pos:
        raise UsageError("unexpected argument %s" % pos[0])
    env = _resolve(None, "--defaults" not in flags, repo, True, True)
    for k in [k for k in env if k.startswith("_")]:
        env.pop(k)
    if "--json" in flags:
        sys.stdout.write(json.dumps(env, indent=2) + "\n")
    else:
        for k, v in env.items():
            if not re.fullmatch(r"[A-Z][A-Z0-9_]*", k):
                continue
            sys.stdout.write("%s=%s\n" % (k, shlex.quote(v)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
