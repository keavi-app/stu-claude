#!/usr/bin/env python3
"""Shared publish-guard policy: which rows are strict, whether a commit is approved, and a
git runner that cannot be steered by the environment git sets for a hook.

A STRICT row is a row whose visibility is public or whose human_checkpoints include
before-push. Every other row (and every repo with no stu config) is untouched by the guard.

approvals.tsv, one line per approval, written only by `stu-approve` (never by an agent):
    <qualified id> TAB <full commit sha> TAB <UTC date>
"""
import fnmatch
import os
import posixpath
import re
import subprocess
import time

# Variables git sets for a hook that point at ONE repository. A git call aimed at another
# path must not inherit them: a hook run from a linked worktree has GIT_DIR set to that
# worktree, and `git -C <other> ...` would then read the wrong repository.
GIT_LOCATION_VARS = (
    "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_PREFIX",
    "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE",
    "GIT_QUARANTINE_PATH", "GIT_INDEX_VERSION", "GIT_CEILING_DIRECTORIES",
    "GIT_DISCOVERY_ACROSS_FILESYSTEM", "GIT_IMPLICIT_WORK_TREE",
)
FULL_SHA = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")


def clean_env(env=None):
    """A copy of ENV (default: os.environ) without git's repository-location variables."""
    e = dict(os.environ if env is None else env)
    for k in GIT_LOCATION_VARS:
        e.pop(k, None)
    return e


def scrub_environ():
    """Remove git's repository-location variables from this process, for good."""
    for k in GIT_LOCATION_VARS:
        os.environ.pop(k, None)


def git(path, *args):
    """-> (returncode, stdout stripped) of `git -C PATH ARGS` with a scrubbed environment."""
    p = subprocess.run(["git", "-C", path] + list(args), capture_output=True, text=True,
                       env=clean_env())
    return p.returncode, p.stdout.strip()


def _get(row, key):
    v = row.get(key.upper())
    if v is None:
        v = row.get(key.lower())
    return v or ""


def strict(row):
    """True for a public row or a row with before-push in its human checkpoints. ROW is a
    resolve() dict or a raw families() row. An unset visibility is private."""
    if _get(row, "visibility").strip().lower() == "public":
        return True
    cps = [c.strip().lower() for c in _get(row, "human_checkpoints").split(",")]
    return "before-push" in cps


def approvals_path(run_home):
    return os.path.join(run_home, "approvals.tsv")


def approved(run_home, sha):
    """Is SHA, a full commit sha, in RUN_HOME/approvals.tsv? A short prefix never counts.
    A missing file means no approvals; any other read error raises (the caller refuses)."""
    sha = sha.strip().lower()
    if not FULL_SHA.fullmatch(sha):
        return False
    try:
        with open(approvals_path(run_home), encoding="utf-8", errors="replace") as f:
            for line in f:
                cols = line.rstrip("\n").split("\t")
                if len(cols) >= 2 and cols[1].strip().lower() == sha:
                    return True
    except FileNotFoundError:
        return False
    return False


# ---- the private-name list and the scanner ----------------------------------------------

SCAN_BUDGET = 20.0  # seconds; past it a scan reports a hit named SCAN_BUDGET_HIT
SCAN_BUDGET_HIT = "scan-budget"
VENDORED_DIRS = ("vendor", "node_modules", "third_party", "pods")
COMMON_NAMES = ("readme*", "license*", "licence*", "changelog*", "contributing*",
                "makefile", "dockerfile", "package.json", "go.mod", "go.sum", "main.*",
                "index.*", "utils.*", "types.*", "config.*", "claude.md", "agents.md")
_TOKEN = re.compile(r"\w+")


def _word(ch):
    return ch.isalnum() or ch == "_"


def scan(text, items, regexes=(), budget=None, deadline=None):
    """-> the hits of ITEMS (whole-word, case-insensitive literals) and REGEXES (pattern
    strings, case-insensitive) in TEXT, in order of first appearance, without repeats.
    Past the budget (default SCAN_BUDGET seconds, or an absolute monotonic DEADLINE) the
    result gains a hit named scan-budget instead of stopping silently.

    Items are indexed by their first word token, so only the items whose first token occurs
    in TEXT are searched for, and a 10 000-item list over a large diff stays fast."""
    if deadline is None:
        deadline = time.monotonic() + (SCAN_BUDGET if budget is None else budget)
    low = text.lower()
    n = len(low)
    found = {}  # hit -> position of first appearance

    def note(hit, pos):
        if hit not in found or pos < found[hit]:
            found[hit] = pos

    for rx in regexes:
        for m in re.finditer(rx, text, re.IGNORECASE):
            note(m.group(0), m.start())
    buckets, odd = {}, []
    for it in items:
        k = it.lower()
        if not k:
            continue
        m = _TOKEN.match(k)
        if m:
            buckets.setdefault(m.group(0), []).append(k)
        else:
            odd.append(k)
    tokens = set(_TOKEN.findall(low))
    over = False
    cands = [k for t in tokens for k in buckets.get(t, ())] + odd
    for i, k in enumerate(cands):
        if i % 256 == 0 and time.monotonic() > deadline:
            over = True
            break
        start = low.find(k)
        while start != -1:
            end = start + len(k)
            if ((start == 0 or not _word(low[start - 1]))
                    and (end >= n or not _word(low[end]))):
                note(k, start)
                break
            start = low.find(k, start + 1)
    hits = sorted(found, key=found.get)
    if over:
        hits.append(SCAN_BUDGET_HIT)
    return hits


def _lines(path, *args):
    rc, out = git(path, *args)
    return [x for x in out.split("\n") if x] if rc == 0 else None


def _vendored(path_lc, attr_vendored):
    parts = path_lc.split("/")
    return (any(p in VENDORED_DIRS for p in parts[:-1]) or path_lc in attr_vendored)


def _vendored_set(path, files):
    p = subprocess.run(["git", "-C", path, "check-attr", "-z", "--stdin", "linguist-vendored"],
                       input="\0".join(files) + "\0", capture_output=True, text=True,
                       env=clean_env())
    out = set()
    if p.returncode == 0:
        f = p.stdout.split("\0")
        for i in range(0, len(f) - 2, 3):
            if f[i + 2] in ("set", "true"):
                out.add(f[i].lower())
    return out


def _is_common(base_lc):
    return any(fnmatch.fnmatchcase(base_lc, pat) for pat in COMMON_NAMES)


def _public_names(public_path):
    names = set()
    for f in _lines(public_path, "-c", "core.quotepath=false", "ls-files") or []:
        lc = f.lower()
        names.add(lc)
        names.add(posixpath.basename(lc))
    return names


def _file_items(private_path, public_names):
    """The tracked paths and basenames of a private checkout that are distinctive enough to
    name it: not vendored, not shared with the public repo, not a common name."""
    files = _lines(private_path, "-c", "core.quotepath=false", "ls-files") or []
    vend = _vendored_set(private_path, files) if files else set()
    items = set()
    for f in files:
        lc = f.lower()
        if _vendored(lc, vend):
            continue
        base = posixpath.basename(lc)
        generic = "." not in base or base.startswith(".") or _is_common(base)
        if "/" in lc:
            if lc not in public_names:
                items.add(lc)
        elif generic:
            continue
        elif lc not in public_names:
            items.add(lc)
        if "/" in lc and not generic and base not in public_names:
            items.add(base)
    return sorted(items)


def _head(path):
    rc, out = git(path, "rev-parse", "--verify", "--quiet", "HEAD")
    return out if rc == 0 and FULL_SHA.fullmatch(out) else ""


def _org(slug):
    return slug.split("/")[0] if "/" in slug else ""


def private_rows(family, public_row):
    """-> [(name, path, slug)] for every private row of FAMILY (a families() pair), the
    public row excluded. Values come from resolve() where it works, else from the raw row."""
    import stu_env
    cfg, rows = family
    out = []
    for r in rows:
        if r.get("_flat") or _get(r, "visibility").strip().lower() == "public":
            continue
        name, path, slug = r.get("name", ""), r.get("path", ""), r.get("slug", "")
        if name == public_row.get("REPO_NAME"):
            continue
        try:
            got = stu_env.resolve(cwd=public_row["MAIN_CHECKOUT"], repo=name,
                                  forge_lookup=False)
            path, slug = got["MAIN_CHECKOUT"], got["REPO_SLUG"]
        except Exception:  # noqa: BLE001  keep the raw row
            path = os.path.expanduser(path)
        out.append((name, path, slug))
    return out


def private_list(family, public_row):
    """The names a public push must not carry: for each private row of FAMILY (a
    families() pair), its slug, its org unless a public row shares it, and its distinctive
    tracked paths and basenames (cached under RUN_HOME/visibility, keyed by the private
    and public HEADs). The bare repo name and tag names are never in it."""
    cfg, rows = family
    public_orgs = {_org(public_row.get("REPO_SLUG", "")).lower()}
    for r in rows:
        if _get(r, "visibility").strip().lower() == "public":
            public_orgs.add(_org(r.get("slug", "")).lower())
    public_orgs.discard("")
    public_path = public_row["MAIN_CHECKOUT"]
    public_head = _head(public_path)
    public_names = None
    items = []
    for name, path, slug in private_rows(family, public_row):
        if slug:
            items.append(slug.lower())
            org = _org(slug).lower()
            if org and org not in public_orgs:
                items.append(org)
        if not path or not os.path.isdir(path):
            continue
        head = _head(path)
        cache = ""
        if head and public_head:
            cache = os.path.join(public_row["RUN_HOME"], "visibility",
                                 "%s-%s-%s.txt" % (name, head, public_head))
        cached = None
        if cache:
            try:
                with open(cache, encoding="utf-8") as f:
                    cached = [x for x in f.read().split("\n") if x]
            except OSError:
                cached = None
        if cached is None:
            if public_names is None:
                public_names = _public_names(public_path)
            cached = _file_items(path, public_names)
            if cache:
                try:
                    os.makedirs(os.path.dirname(cache), exist_ok=True)
                    tmp = "%s.%d.tmp" % (cache, os.getpid())
                    with open(tmp, "w", encoding="utf-8") as f:
                        f.write("\n".join(cached) + "\n")
                    os.replace(tmp, cache)
                except OSError:
                    pass
        items.extend(cached)
    seen, out = set(), []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out


def private_regexes(family, public_row):
    """Issue references into a private repo: org/name#n and name#n."""
    pats = []
    for name, _path, slug in private_rows(family, public_row):
        names = {name.lower()}
        if slug:
            names.add(slug.lower().split("/")[-1])
            if "/" in slug:
                pats.append(r"\b%s#[0-9]+" % re.escape(slug.lower()))
        for n in sorted(x for x in names if x):
            pats.append(r"\b%s#[0-9]+" % re.escape(n))
    return pats


def private_slugs(family, public_row):
    return [s.lower() for _n, _p, s in private_rows(family, public_row) if s]


def family_of(config_path):
    """The families() pair whose config is CONFIG_PATH, or None."""
    import stu_env
    want = os.path.realpath(config_path) if config_path else ""
    for cfg, rows in stu_env.families():
        if want and os.path.realpath(cfg) == want:
            return (cfg, rows)
    return None
