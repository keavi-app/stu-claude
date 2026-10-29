#!/usr/bin/env python3
"""stu-run-check: the supervisor's mechanical checks on one orchestrator return.

  stu-run-check --objective PATH --return PATH
      One line per affected ID, then exactly one terminal line.
        <id> CLOSED <how>      <id> OPEN <why>
        <id> WAITING <needs>   <id> BLOCKED <reason-code>: <detail>
      Terminal `OK` (exit 0) or `BLOCKED` (exit 1, printed iff some line is BLOCKED).
      OPEN and WAITING lines still end `OK`.
  stu-run-check --approved --objective PATH
      `<id> APPROVED <sha>` for each `Awaiting approval:` entry whose id AND full sha have a
      record in the approvals file, then `OK`. It reads that file itself, so no seat ever
      names it. A record for another id at the same sha does not count here.

Exit 3 (the tool cannot judge): NOTHING goes to stdout and one line
`stu-run-check: <class>: <detail>` goes to stderr. Every terminal line ever printed is
therefore `OK` or `BLOCKED`, and a caller treats "no terminal line" as BLOCKED. Causes: a
usage error; an unreadable or missing --objective / --return; an unparseable unit table
(class `table`); a bare ID in a family of two or more rows, or an ID whose `<repo>` prefix
differs from its `repo` column (class `id-form`); an unknown repo or any stu-env error
(`unknown-repo`, `config`); a forge or git failure (the `stu-forge` classes `auth`,
`rate-limit`, `not-found`, `partial`, `forge`, ...); a flat config run from outside its repo
(`config`). Evidence that merely disagrees (wrong sha, not an ancestor, a moved branch) is
BLOCKED, not exit 3.

==== FORMAT BLOCK (Tasks 8a, 8b and 10a copy from here) =====================================

Every SHA anywhere is a full 40-character lowercase hex commit sha; anything else (short,
uppercase, 64-hex) is `BLOCKED non-full-sha`.

Unit IDs. In a family of two or more rows an ID is `<repo>#<n>` (an issue in that row's
`issues_repo`) or `<repo>:<slug>`, `<repo>` being the row's name. In a one-row family a bare
ID is legal (a qualified one is too).

Return fields (plain `KEY: value` lines; the first line for a key wins; `NONE` or absent
reads empty; entries split on `,` unless noted):
  CLOSED_IDS:       <id>, ...
  MERGED_IDS:       <id>@<landed sha>, ...      the `@<landed sha>` is ALWAYS required, so the
                    supervisor can verify every merge (a flat `direct` run's return changes
                    accordingly: today's bare ids are `BLOCKED merged-needs-sha`)
  READY_IDS:        <id>@<slug>#<pr>@<sha>, ... same shape as PASSED_IDS; <slug> is the row's
                    REPO_SLUG. A bare id, or an entry missing slug, pr or sha, is
                    `BLOCKED ready-needs-pr-and-sha`. A flat label-handoff run's return
                    changes accordingly, exactly as MERGED_IDS gains `@<sha>`.
  PASSED_IDS:       <id>@<slug>#<pr>@<sha>, ...
  TAGGED_IDS:       <id>=<tag>@<sha>, ...
  AFTER_PASS_FAILED: <id> <step>, ...
  WAITING_IDS:      <id> needs: <action> <ref>; ...        (entries split on `;`)
                    <action> is `merge <slug>#<pr>`, `tag <repo> at <sha>` or
                    `approve <id> at <sha>`
  APPROVAL_IDS:     <id>@<branch>@<sha>, ...
  INTEGRATED_IDS:   <id>@<unit head sha>, ...     (only under `completion: integrated`)
  MOVED_IDS:        <id>@<branch head sha>, ...
  UNITS_CHANGED:    <parent ids> -> <new ids> -- <reason>      (the separator is an em dash
  UNITS_ADDED:      <new ids> -- <reason>                       or ` -- `)
  REMAINING_IDS, PARKED_IDS, INTEGRATING_IDS: read but never printed; an ID in them (or in
                    MOVED_IDS / the UNITS_CHANGED and UNITS_ADDED children) that cannot be
                    resolved to a row is exit 3, like an ID in an affected field.

Objective file. The unit table is a Markdown table whose header (case-insensitive) has an
`id` column; columns `repo` and `after` are optional. Without `repo` every unit is the home
row (legal only in a one-row family); without `after` every unit has none. `after` is
`<id> (landed)`, `<id> (landed, tagged)`, or `-`/empty. Today's `| ID | What it is |
Contended resource |` table is valid as it is. An objective given only an epic number has no
table: every issued ID is a home-row unit with no `after`.
Other lines: `completion: ready|merged|integrated` (absent: the first word of the project's
`## completion-mode` section, else `merged`) and `Base branch: [<repo>:] <branch>[, ...]
[note]` (an `origin/` prefix stripped, a note after ` -- ` ignored, a note must not contain
a comma; an unprefixed branch belongs to the home row).
Scoreboard: the lines of the `## Scoreboard` section (every lane's block is unioned;
repeats of a key add to it). A value is the text after `Key:` with parentheticals dropped.
  accumulated: Units issued, Merged: <id>@<sha>, Readied: <id>@<sha>, Passed:
  <id>@<slug>#<pr>@<sha>, Tagged: <id>=<tag>@<sha>, Approved: <id>@<sha>, Closed: <id>
  (a `Merged/readied:` line from before the split is read as both Merged and Readied);
  current state, rewritten each cycle: Awaiting approval: <id>@<branch>@<sha>, ...,
  Waiting: <id> needs: <action> <ref>; ...

Issued set = the scoreboard's `Units issued` plus the children named by this return's
UNITS_CHANGED / UNITS_ADDED. The unit table never widens it (an objective given only an epic
number has no table), so a unit that is in the table but not yet in `Units issued` is
`BLOCKED not-issued`. Every ID in a field must be in the issued set.
Affected IDs (one line each, first-seen order over the fields below) are those in CLOSED_IDS,
MERGED_IDS, READY_IDS, PASSED_IDS, APPROVAL_IDS, INTEGRATED_IDS, TAGGED_IDS, MOVED_IDS,
WAITING_IDS and AFTER_PASS_FAILED. Status precedence BLOCKED > OPEN > WAITING > CLOSED.

Closing, by the unit's row (field = the gate field that closes it):
  merge_mode direct / direct-push   MERGED_IDS
  label-handoff                     READY_IDS under completion ready or integrated (the final
                                    unit), MERGED_IDS under merged
  report-only (mode: pr-only)       PASSED_IDS
  human_checkpoints before-push     APPROVAL_IDS (leg 1) or PASSED_IDS (leg 2, report-only
                                    rows only); MERGED_IDS and READY_IDS never close it
  completion: integrated, any row   INTEGRATED_IDS
  Any other gate field on a row is `BLOCKED wrong-field-for-mode`. A CLOSED_IDS entry with no
  gate field is a legal no-PR close in every mode (`CLOSED no-pr`) EXCEPT on a row whose
  human_checkpoints contain before-push: there it is `BLOCKED closed-without-gate-field`,
  because a before-push unit closes only through APPROVAL_IDS or its PASSED_IDS leg-2 field.
  An ID with an AFTER_PASS_FAILED entry is `OPEN after-pass-failed:<step>`, never CLOSED, even
  when it is also in MERGED_IDS. A failed `required: false` step is never relayed, so it does
  not hold a unit open. A unit whose row is `mode: park` that appears in ANY ID-bearing field
  of the return (the affected fields, REMAINING_IDS, PARKED_IDS, INTEGRATING_IDS, the children
  of UNITS_CHANGED / UNITS_ADDED) is `BLOCKED park-row`. Otherwise REMAINING_IDS / PARKED_IDS
  entries print no line, except that an ID in REMAINING_IDS, PARKED_IDS or INTEGRATING_IDS that
  is also in CLOSED_IDS or in its row's closing field is `BLOCKED closed-but-remaining`: a unit
  closed this return is not outstanding. An AFTER_PASS_FAILED entry for the ID exempts its
  closing field (that entry keeps the unit outstanding) but never a CLOSED_IDS entry.
  Leg 2 of a before-push unit: a PASSED_IDS entry on a before-push row needs an approvals
  record for exactly that id and sha, else `BLOCKED leg2-unapproved`. A MERGED_IDS or
  READY_IDS entry for a before-push row is `BLOCKED wrong-field-for-mode`. A before-push row
  whose merge_mode is `direct` or `label-handoff` has no leg-2 close in this version (PASSED_IDS
  is the wrong field for it too): it blocks loudly rather than closing without the gate.

<how> tokens, joined with `,` when several apply: merged-on-base, approval-branch-at-sha,
integrated, tagged, no-pr, passed:<slug>#<pr>@<sha12>, ready-labelled:<slug>#<pr> (with
auto-merge-on or auto-merge-off). <why> tokens (OPEN): after-pass-failed:<step>, moved.
Reason codes (BLOCKED): non-full-sha, not-issued, park-row, wrong-field-for-mode,
merged-needs-sha, merged-not-on-base, approval-needs-branch-and-sha, approval-branch-moved,
approval-repeat, integrated-needs-sha, integrated-not-on-base, tag-malformed,
tag-peel-mismatch, tag-without-merged-sha, tag-sha-not-merged-sha, malformed-entry,
closed-without-gate-field, passed-needs-pr-and-sha, passed-other-slug, passed-wrong-sha,
passed-pr-closed, ready-needs-pr-and-sha, ready-other-slug, ready-wrong-sha, ready-pr-closed,
ready-label-absent, leg2-unapproved, waiting-without-after, waiting-predecessor-not-closed,
waiting-predecessor-landed, predecessor-not-landed, predecessor-not-tagged,
predecessor-unverified, predecessor-moved-head, closed-but-remaining.

Evidence (what each check proves):
  MERGED_IDS     after `git fetch <remote> <base>`, the sha is an ancestor of
                 `<remote>/<row base>` or of a branch the objective's `Base branch:` names for
                 that row (the scope-verified base of an epic-branch unit).
  INTEGRATED_IDS the sha is an ancestor of a named `Base branch:` of the row, else of its base.
  APPROVAL_IDS   `refs/heads/<branch>` in the row's checkout is exactly the sha; an entry whose
                 id and sha repeat an `Awaiting approval:` entry is `approval-repeat` (leg 1
                 cannot be returned twice).
  PASSED_IDS     `stu-forge pr-state`: the PR is in the row's slug, its head is exactly the sha
                 and it is not closed unmerged.
  READY_IDS      the same pr-state test, and `stu-forge claim-state` says the row's
                 CI_MERGE_LABEL is present on the PR (an empty CI_MERGE_LABEL is exit 3).
  WAITING_IDS    judged only by this test: the unit has `after:`; its predecessor is closed (in
                 this return's CLOSED_IDS or the scoreboard's `Closed:`); and the `after:`
                 condition is NOT yet met (see the next paragraph). Otherwise BLOCKED.
                 The `<action> <ref>` text is echoed, not judged.
  after:         a unit that closes (any gate field, CLOSED_IDS, TAGGED_IDS) or is in MOVED_IDS
                 needs its predecessor verified: the predecessor's landing sha comes from this
                 return's or the scoreboard's `Merged:` (ancestry of the base, so a squash merge
                 is verified), else its `Passed:` entry or this return's READY_IDS entry
                 (`stu-forge landed --slug --pr --sha`; a head that moved after the gate is
                 `predecessor-moved-head`), else a scoreboard `Readied:` sha (ancestry only; a
                 squash-merged readied predecessor reads as not landed). Nothing found:
                 `predecessor-unverified`. `(landed, tagged)` also needs the predecessor's tag:
                 for tag_by stu a `Tagged:` entry (this return or the scoreboard) whose tag peels
                 to the landing sha, for tag_by human `stu-forge tag-for` not NONE; a row with no
                 tag_by is exit 3.
  TAGGED_IDS     `git ls-remote --tags` on the row's remote peels the tag to the sha, and the
                 sha equals the unit's own Merged sha (this return's MERGED_IDS, else the
                 scoreboard's `Merged:`).
Base branches: a MERGED_IDS entry is judged against the row's base plus the `Base branch:`
names for that row; the line is split on commas, so a branch name or note holding a comma is
misread (stated limitation).
Residual, stated plainly: PASSED_IDS, APPROVAL_IDS and READY_IDS prove a state of the forge or
of git, not that the gate passed; an orchestrator holding `gh` could fabricate that state.
The gate's provenance comment (label-handoff) is the only gate-side record today. For READY_IDS
the label is required and AUTO_MERGE is reported, not required (no config key says whether a
row uses native auto-merge). This tool does not read the claims file.

==== END FORMAT BLOCK ========================================================================

Rows come from stu-env (`resolve(repo=<name>, forge_lookup=False)`), so a flat config must be
run from inside its repo. Python 3.9, standard library only.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import push_policy  # noqa: E402
import stu_env  # noqa: E402
import stu_forge  # noqa: E402

GH_VERBS = ("pr-state", "claim-state", "landed")
PR_ENTRY = re.compile(r"^([^#@\s/]+/[^#@\s/]+)#([0-9]+)@(\S*)$")
FULL_SHA = re.compile(r"[0-9a-f]{40}")
GATE_FIELDS = ("MERGED_IDS", "READY_IDS", "PASSED_IDS", "APPROVAL_IDS", "INTEGRATED_IDS")
ORDER = ("CLOSED_IDS", "MERGED_IDS", "READY_IDS", "PASSED_IDS", "APPROVAL_IDS",
         "INTEGRATED_IDS", "TAGGED_IDS", "MOVED_IDS", "WAITING_IDS", "AFTER_PASS_FAILED")
COMPLETIONS = ("ready", "merged", "integrated")
PREFIX = re.compile(r"^([^#:\s]+)[#:]\S")


class ToolError(Exception):
    """The tool cannot judge: exit 3, nothing on stdout."""

    def __init__(self, cls, detail):
        Exception.__init__(self, detail)
        self.cls = cls
        self.detail = detail


# ---- parsing ----------------------------------------------------------------------------

def read_text(path, what):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError as e:
        raise ToolError("unreadable", "cannot read %s %s: %s" % (what, path, e.strerror or e))


def strip_paren(v):
    return re.sub(r"\([^)]*\)", "", v)


def items(value, sep=r"[,\s]+"):
    v = strip_paren(value or "").strip()
    if not v or v.upper() == "NONE":
        return []
    out = [p.strip() for p in re.split(sep, v)]
    return [p for p in out if p and p.upper() != "NONE"]


_KV = re.compile(r"^\s*(?:[-*]\s+)?([A-Z][A-Z0-9_]*):[ \t]*(.*?)\s*$")


def parse_return(text):
    fields = {}
    for line in text.splitlines():
        m = _KV.match(line)
        if m and m.group(1) not in fields:
            fields[m.group(1)] = m.group(2)
    return fields


_DASH = re.compile(r"\s+(?:—|–|--)\s+")


def head_of(value):
    return _DASH.split(value, 1)[0]


def unit_children(fields):
    kids = []
    for ent in items(head_of(fields.get("UNITS_ADDED", ""))):
        kids.append(ent)
    changed = head_of(fields.get("UNITS_CHANGED", ""))
    if "->" in changed:
        kids.extend(items(changed.split("->", 1)[1]))
    return kids


def _cells(line):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip().strip("`").strip() for c in s.split("|")]


_AFTER = re.compile(r"^(\S+)\s*\(\s*landed(\s*,\s*tagged)?\s*\)$")


def parse_table(text):
    """-> list of {id, repo, after} from the first table with an `id` header, or None."""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        if not lines[i].strip().startswith("|"):
            i += 1
            continue
        j = i
        while j < len(lines) and lines[j].strip().startswith("|"):
            j += 1
        block = lines[i:j]
        i = j
        header = [c.lower() for c in _cells(block[0])]
        if "id" not in header:
            continue
        idx = header.index("id")
        ri = header.index("repo") if "repo" in header else None
        ai = header.index("after") if "after" in header else None
        rows, seen = [], set()
        for ln in block[1:]:
            cells = _cells(ln)
            if all(re.fullmatch(r":?-+:?", c) for c in cells if c) and any(cells):
                continue
            if len(cells) != len(header):
                raise ToolError("table", "unit table row has %d cells, header has %d: %s"
                                % (len(cells), len(header), ln.strip()[:80]))
            ident = cells[idx]
            if not ident or re.search(r"\s", ident):
                raise ToolError("table", "unit table row has no usable ID: %s" % ln.strip()[:80])
            if ident in seen:
                raise ToolError("table", "unit table lists %s twice" % ident)
            seen.add(ident)
            after = None
            cell = cells[ai] if ai is not None else ""
            if cell not in ("", "-"):
                m = _AFTER.match(cell)
                if not m:
                    raise ToolError("table", "unit %s: the after cell %r is not '<id> (landed"
                                    "[, tagged])' or '-'" % (ident, cell))
                after = (m.group(1), bool(m.group(2)))
            rows.append({"id": ident, "repo": (cells[ri] if ri is not None else "") or None,
                         "after": after})
        return rows
    return None


def parse_scoreboard(text):
    """-> {lowercase key: [value, ...]} over the `## Scoreboard` section."""
    board, inside = {}, False
    for line in text.splitlines():
        if re.match(r"^##(?!#)\s", line):
            inside = bool(re.match(r"^##\s+Scoreboard\b", line))
            continue
        if not inside:
            continue
        m = re.match(r"^\s*([A-Za-z][A-Za-z /-]*?)\s*:\s*(.*?)\s*$", line)
        if m:
            board.setdefault(m.group(1).lower(), []).append(m.group(2))
    return board


def board_items(board, *keys, **kw):
    out = []
    for k in keys:
        for v in board.get(k, []):
            out.extend(items(v, kw.get("sep", r"[,\s]+")))
    return out


def parse_completion(text):
    for line in text.splitlines():
        m = re.match(r"(?i)^\s*completion:\s*(ready|merged|integrated)\s*(?:[(—-].*)?$", line)
        if m:
            return m.group(1).lower()
    return None


def parse_bases(text):
    """-> [(repo or None, branch)] from the `Base branch:` line."""
    m = re.search(r"(?mi)^\s*Base branch:\s*(.+?)\s*$", text)
    if not m:
        return []
    val = strip_paren(_DASH.split(m.group(1), 1)[0])
    out = []
    for part in val.split(","):
        words = part.strip().split()
        if not words:
            continue
        word, repo = words[0], None
        pm = re.match(r"^([^:/\s]+):(.+)$", word)
        if pm:
            repo, word = pm.group(1), pm.group(2)
        out.append((repo, word))
    return out


def read_approvals(run_home):
    """-> [(id, full sha)] from the approvals file. Missing file: none. Never writes."""
    path = push_policy.approvals_path(run_home)
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except FileNotFoundError:
        return []
    except OSError as e:
        raise ToolError("unreadable", "cannot read approvals: %s" % (e.strerror or e))
    out = []
    for line in text.splitlines():
        cols = line.split("\t")
        if len(cols) >= 2:
            out.append((cols[0].strip(), cols[1].strip().lower()))
    return out


# ---- rows and git -----------------------------------------------------------------------

class Check:
    def __init__(self, objective_text, fields):
        self.otext = objective_text
        self.fields = fields
        self.rows = parse_table(objective_text) or []
        self.table = dict((r["id"], r) for r in self.rows)
        self.board = parse_scoreboard(objective_text)
        self.bases = parse_bases(objective_text)
        self.envs = {}
        self.row_cache = {}
        self.fetched = set()
        self.approvals = {}

    # row resolution
    def env(self, name):
        if name not in self.envs:
            try:
                self.envs[name] = stu_env.resolve(repo=name, forge_lookup=False)
            except stu_env.ConfigError as e:
                low = str(e)
                cls = "unknown-repo" if ("no repo row named" in low or "one-repo config" in low) \
                    else "config"
                raise ToolError(cls, low.splitlines()[0] if low else "config error")
            except (stu_env.NoConfig, stu_env.NotInRepo, stu_env.UsageError) as e:
                raise ToolError("config", str(e).splitlines()[0] if str(e) else "config error")
        return self.envs[name]

    def row_of(self, ident):
        if ident in self.row_cache:
            return self.row_cache[ident]
        m = PREFIX.match(ident)
        prefix = m.group(1) if m else None
        col = (self.table.get(ident) or {}).get("repo")
        if prefix and col and prefix != col:
            raise ToolError("id-form", "unit %s: the repo prefix %r differs from its repo "
                            "column %r" % (ident, prefix, col))
        e = self.env(col or prefix)
        if not prefix and int(e.get("FAMILY_ROWS") or 1) > 1:
            raise ToolError("id-form", "bare unit id %r in a family of %s repos; write "
                            "<repo>#<n> or <repo>:<slug>" % (ident, e["FAMILY_ROWS"]))
        self.row_cache[ident] = e
        return e

    def completion(self, e):
        c = parse_completion(self.otext)
        if c:
            return c
        text = stu_env.section(e.get("_BODY", ""), "completion-mode")
        words = set(re.findall(r"(?<![A-Za-z0-9-])(ready|merged|integrated)(?![A-Za-z0-9-])",
                               text.lower()))
        if len(words) == 1:
            return next(iter(words))
        if not text.strip():
            return "merged"
        raise ToolError("config", "cannot read the completion mode from '## completion-mode'"
                        "; add a 'completion: ready|merged|integrated' line to the objective")

    def scope_bases(self, e, only_named=False):
        base = e["BASE"]
        extras = []
        for repo, branch in self.bases:
            if repo == e["REPO_NAME"] or (repo is None and e["IS_HOME"] == "1"):
                for pre in (e["REMOTE"] + "/", "origin/"):
                    if branch.startswith(pre):
                        branch = branch[len(pre):]
                        break
                extras.append(branch)
        if only_named and extras:
            return extras
        if not base:
            raise ToolError("config", "no base branch resolves for row %s; set 'base:' under "
                            "its '### %s' block" % (e["REPO_NAME"], e["REPO_NAME"]))
        return [base] + [b for b in extras if b != base]

    def on_base(self, e, sha, only_named=False):
        path, remote = e["MAIN_CHECKOUT"], e["REMOTE"]
        for b in self.scope_bases(e, only_named):
            key = (path, remote, b)
            if key not in self.fetched:
                stu_forge._fetch_base(path, remote, b)
                self.fetched.add(key)
            if stu_forge._is_ancestor(path, sha, "refs/remotes/%s/%s" % (remote, b)):
                return "%s/%s" % (remote, b)
        return None

    def forge(self, verb, e, soft=(), **flags):
        """Run one stu-forge verb by subprocess -> {RESULT KEY: value}. A missing terminal
        line or an ERROR is exit 3, except the classes named in `soft`, which come back as
        {"ERROR": <class>}."""
        argv = [sys.executable, os.path.join(HERE, "stu_forge.py"), verb]
        for k, v in flags.items():
            argv += ["--" + k, str(v)]
        if verb in GH_VERBS and e.get("GH_HOST"):
            argv += ["--host", e["GH_HOST"]]
        p = subprocess.run(argv, capture_output=True, text=True)
        lines = p.stdout.splitlines()
        last = lines[-1] if lines else ""
        if last.startswith("ERROR "):
            cls = last.split()[1]
            if cls in soft:
                return {"ERROR": cls}
            raise ToolError(cls, "stu-forge %s: %s" % (verb, last[6:]))
        if last != "OK" or p.returncode != 0:
            raise ToolError("forge", "stu-forge %s printed no terminal line" % verb)
        out = {}
        for ln in lines[:-1]:
            k, _, v = ln.partition(" ")
            out.setdefault(k, v)
        return out

    def approvals_for(self, e):
        if e["RUN_HOME"] not in self.approvals:
            self.approvals[e["RUN_HOME"]] = read_approvals(e["RUN_HOME"])
        return self.approvals[e["RUN_HOME"]]


class Unit:
    def __init__(self):
        self.blocked, self.open, self.waiting, self.closed = [], [], [], []

    def block(self, code, detail):
        self.blocked.append("%s: %s" % (code, detail))

    def add_closed(self, how):
        if how not in self.closed:
            self.closed.append(how)

    def line(self, ident):
        if self.blocked:
            return "%s BLOCKED %s" % (ident, self.blocked[0]), True
        if self.open:
            return "%s OPEN %s" % (ident, self.open[0]), False
        if self.waiting:
            return "%s WAITING %s" % (ident, self.waiting[0]), False
        return "%s CLOSED %s" % (ident, ",".join(self.closed)), False


# ---- entries ----------------------------------------------------------------------------

def gather(fields):
    """-> (order, {field: {ident: [entry dict, ...]}}). Malformed entries keep their ident."""
    order, got = [], {}

    def add(field, ident, **entry):
        if ident not in order:
            order.append(ident)
        got.setdefault(field, {}).setdefault(ident, []).append(entry)

    for field in ORDER:
        raw = fields.get(field, "")
        if field == "CLOSED_IDS":
            for r in items(raw):
                add(field, r)
        elif field in ("MERGED_IDS", "INTEGRATED_IDS", "MOVED_IDS", "READY_IDS", "PASSED_IDS"):
            for r in items(raw):
                ident, at, rest = r.partition("@")
                if field in ("READY_IDS", "PASSED_IDS"):
                    add(field, ident, raw=rest if at else None)
                else:
                    add(field, ident, sha=rest if at else None)
        elif field == "APPROVAL_IDS":
            for r in items(raw):
                parts = r.split("@")
                if len(parts) >= 3:
                    add(field, parts[0], branch="@".join(parts[1:-1]), sha=parts[-1])
                else:
                    add(field, parts[0], branch=None, sha=None)
        elif field == "TAGGED_IDS":
            for r in items(raw):
                ident, eq, rest = r.partition("=")
                tag, at, sha = rest.rpartition("@")
                if eq and at and tag:
                    add(field, ident, tag=tag, sha=sha)
                else:
                    add(field, ident.split()[0] if ident else r, tag=None, sha=None)
        elif field == "WAITING_IDS":
            for r in items(raw, sep=r"\s*;\s*"):
                add(field, r.split()[0], raw=r)
        else:  # AFTER_PASS_FAILED
            for r in items(raw, sep=r"\s*,\s*"):
                bits = r.split(None, 1)
                add(field, bits[0], step=(bits[1].strip() if len(bits) > 1 else "-"))
    return order, got


def allowed_fields(chk, e, ident, got):
    mm = e["MERGE_MODE"]
    if mm in ("direct", "direct-push"):
        allowed = set(["MERGED_IDS"])
    elif mm == "report-only":
        allowed = set(["PASSED_IDS"])
    else:
        allowed = set(["MERGED_IDS"] if chk.completion(e) == "merged" else ["READY_IDS"])
    if before_push(e):
        # Only the plan's two fields close a before-push row; MERGED_IDS and READY_IDS are
        # the wrong field here whatever the merge mode.
        allowed.discard("MERGED_IDS")
        allowed.discard("READY_IDS")
        allowed.add("APPROVAL_IDS")
    if ident in got.get("INTEGRATED_IDS", {}) and chk.completion(e) == "integrated":
        allowed.add("INTEGRATED_IDS")
    return allowed


def before_push(e):
    return "before-push" in e["HUMAN_CHECKPOINTS"].split(",")


def full(sha):
    return bool(sha) and FULL_SHA.fullmatch(sha) is not None


def merged_shas(chk, ident, got):
    """Every sha this unit is recorded as merged at: this return, then the scoreboard."""
    shas = [en["sha"] for en in got.get("MERGED_IDS", {}).get(ident, []) if full(en["sha"])]
    for ent in board_items(chk.board, "merged", "merged/readied"):
        i, at, sha = ent.partition("@")
        if i == ident and at and full(sha):
            shas.append(sha)
    return shas


def pr_entries(chk, pid, got, fields, board_key):
    """Every (slug, pr, sha) recorded for pid in this return's fields, then the scoreboard."""
    raws = []
    for f in fields:
        raws.extend(en.get("raw") for en in got.get(f, {}).get(pid, []))
    for ent in board_items(chk.board, board_key):
        i, at, rest = ent.partition("@")
        if i == pid and at:
            raws.append(rest)
    out = []
    for raw in raws:
        m = PR_ENTRY.match(raw or "")
        if m and full(m.group(3)):
            out.append((m.group(1), m.group(2), m.group(3)))
    return out


def pred_landing(chk, pid, got):
    """-> (state, landing sha). state: landed | not-landed | moved-head | unverified."""
    e = chk.row_of(pid)
    shas = [en["sha"] for en in got.get("MERGED_IDS", {}).get(pid, [])]
    for ent in board_items(chk.board, "merged", "merged/readied"):
        i, at, sha = ent.partition("@")
        if i == pid and at:
            shas.append(sha)
    for sha in shas:
        if full(sha):
            return ("landed", sha) if chk.on_base(e, sha) else ("not-landed", sha)
    prs = pr_entries(chk, pid, got, ("PASSED_IDS",), "passed")
    prs += pr_entries(chk, pid, got, ("READY_IDS",), "readied")
    for slug, pr, sha in prs:
        if slug.lower() != e["REPO_SLUG"].lower():
            continue
        for b in chk.scope_bases(e):
            r = chk.forge("landed", e, soft=("moved-head",), path=e["MAIN_CHECKOUT"],
                          remote=e["REMOTE"], base=b, sha=sha, slug=slug, pr=pr)
            if r.get("ERROR") == "moved-head":
                return "moved-head", None
            if "LANDED" in r:
                return "landed", r["LANDED"]
        return "not-landed", sha
    for ent in board_items(chk.board, "readied"):
        i, at, sha = ent.partition("@")
        if i == pid and at and full(sha):
            return ("landed", sha) if chk.on_base(e, sha) else ("not-landed", sha)
    return "unverified", None


def pred_tagged(chk, pid, got, sha):
    e = chk.row_of(pid)
    by = e["TAG_BY"]
    if not by:
        raise ToolError("config", "an after: cell needs the tag of %s but its row has no "
                        "tag_by" % pid)
    if by == "stu":
        ents = [(en["tag"], en["sha"]) for en in got.get("TAGGED_IDS", {}).get(pid, [])
                if en["tag"]]
        for ent in board_items(chk.board, "tagged"):
            i, eq, rest = ent.partition("=")
            tag, at, tsha = rest.rpartition("@")
            if i == pid and eq and at:
                ents.append((tag, tsha))
        return any(t_sha == sha and stu_forge.peel(e["MAIN_CHECKOUT"], e["REMOTE"], tag) == sha
                   for tag, t_sha in ents)
    if not e["TAG_FORMAT"]:
        raise ToolError("config", "row %s has tag_by: %s but no tag_format" % (pid, by))
    r = chk.forge("tag-for", e, path=e["MAIN_CHECKOUT"], remote=e["REMOTE"], sha=sha,
                  format=e["TAG_FORMAT"])
    return r.get("TAG", "NONE") != "NONE"


def pred_status(chk, ident, got):
    """-> (ok, code, detail) for the unit's `after:` predecessor, and the (landed, tagged)
    facts for the WAITING test: ok True means the condition is met."""
    pid, need_tag = chk.table[ident]["after"]
    state, sha = pred_landing(chk, pid, got)
    if state == "moved-head":
        return False, "predecessor-moved-head", "%s was merged with a head other than the " \
            "gated sha" % pid
    if state == "unverified":
        return False, "predecessor-unverified", "no landing sha or PR is recorded for %s" % pid
    if state == "not-landed":
        return False, "predecessor-not-landed", "%s has not landed on its base" % pid
    if need_tag and not pred_tagged(chk, pid, got, sha):
        return False, "predecessor-not-tagged", "%s is landed but not tagged" % pid
    return True, "", ""


def check_pr_entry(chk, u, e, ident, field, en):
    f = field[:-4].lower()  # passed | ready
    m = PR_ENTRY.match(en.get("raw") or "")
    if not m:
        u.block("%s-needs-pr-and-sha" % f, "%s entry for %s needs <id>@<slug>#<pr>@<sha>"
                % (field, ident))
        return
    slug, pr, sha = m.groups()
    if not full(sha):
        u.block("non-full-sha", "%s sha %r is not a full 40-hex sha" % (field, sha))
        return
    if slug.lower() != e["REPO_SLUG"].lower():
        u.block("%s-other-slug" % f, "%s names %s, the row is %s" % (field, slug, e["REPO_SLUG"]))
        return
    if before_push(e) and (ident, sha) not in chk.approvals_for(e):
        u.block("leg2-unapproved", "%s is a before-push unit; %s has no approvals record at %s"
                % (ident, field, sha))
        return
    label = e.get("CI_MERGE_LABEL", "")
    if field == "READY_IDS" and not label:
        raise ToolError("config", "READY_IDS needs the row's merge label: set 'ci_merge_label:' "
                        "for row %s" % e["REPO_NAME"])
    st = chk.forge("pr-state", e, slug=slug, pr=pr)
    if st.get("SLUG", "-") not in ("-", "") and st["SLUG"].lower() != slug.lower():
        u.block("%s-other-slug" % f, "PR %s#%s is in %s" % (slug, pr, st["SLUG"]))
    elif st.get("HEAD_SHA") != sha:
        u.block("%s-wrong-sha" % f, "PR %s#%s head is %s, not %s" % (
            slug, pr, st.get("HEAD_SHA"), sha))
    elif st.get("STATE") == "closed":
        u.block("%s-pr-closed" % f, "PR %s#%s is closed unmerged" % (slug, pr))
    elif field == "PASSED_IDS":
        u.add_closed("passed:%s#%s@%s" % (slug, pr, sha[:12]))
    else:
        cs = chk.forge("claim-state", e, slug=slug, pr=pr, label=label)
        if cs.get("LABEL") != "present":
            u.block("ready-label-absent", "PR %s#%s does not carry the label %s" % (
                slug, pr, label))
        else:
            u.add_closed("ready-labelled:%s#%s" % (slug, pr))
            u.add_closed("auto-merge-%s" % cs.get("AUTO_MERGE", "off"))


def check_waiting(chk, u, ident, got, en):
    m = re.match(r"^\S+\s+(needs:\s*(?:merge|tag|approve)\s+\S.*)$", en["raw"])
    if not m:
        u.block("malformed-entry", "WAITING_IDS entry %r needs '<id> needs: <merge|tag|approve> "
                "<ref>'" % en["raw"])
        return
    entry = chk.table.get(ident)
    if not entry or not entry["after"]:
        u.block("waiting-without-after", "%s has no after: predecessor, so it cannot be waiting"
                % ident)
        return
    pid = entry["after"][0]
    closed = set(got.get("CLOSED_IDS", {})) | set(board_items(chk.board, "closed"))
    if pid not in closed:
        u.block("waiting-predecessor-not-closed", "%s is not closed, so %s is not waiting on a "
                "landing" % (pid, ident))
        return
    ok, code, detail = pred_status(chk, ident, got)
    if ok:
        u.block("waiting-predecessor-landed", "the after: condition of %s is already met; it "
                "should not be waiting" % ident)
    elif code in ("predecessor-moved-head", "predecessor-unverified"):
        u.block(code, detail)
    else:
        u.waiting.append(m.group(1))


def evaluate(chk, ident, got, issued, awaiting, held):
    u = Unit()
    if ident not in issued:
        u.block("not-issued", "%s is not in this run's issued set" % ident)
    e = chk.row_of(ident)
    if e["MODE"] == "park":
        u.block("park-row", "%s belongs to a row with mode: park" % ident)
        return u
    present = [f for f in ORDER if ident in got.get(f, {})]
    gate_present = [f for f in GATE_FIELDS if f in present]
    allowed = set()
    if gate_present:
        allowed = allowed_fields(chk, e, ident, got)
        for f in gate_present:
            if f not in allowed:
                u.block("wrong-field-for-mode", "%s is not a closing field for a %s row%s"
                        % (f, e["MERGE_MODE"], " (before-push)" if before_push(e) else ""))
    path, remote = e["MAIN_CHECKOUT"], e["REMOTE"]

    for en in got.get("MERGED_IDS", {}).get(ident, []):
        if "MERGED_IDS" not in allowed:
            break
        if en["sha"] is None:
            u.block("merged-needs-sha", "MERGED_IDS entry for %s has no @<landed sha>" % ident)
        elif not full(en["sha"]):
            u.block("non-full-sha", "MERGED_IDS sha %r is not a full 40-hex sha" % en["sha"])
        else:
            where = chk.on_base(e, en["sha"])
            if where:
                u.add_closed("merged-on-base")
            else:
                u.block("merged-not-on-base", "%s is not an ancestor of the base of %s"
                        % (en["sha"], e["REPO_NAME"]))
    for field in ("READY_IDS", "PASSED_IDS"):
        if field in allowed:
            for en in got.get(field, {}).get(ident, []):
                check_pr_entry(chk, u, e, ident, field, en)
    for en in got.get("APPROVAL_IDS", {}).get(ident, []):
        if "APPROVAL_IDS" not in allowed:
            break
        if en["sha"] is None:
            u.block("approval-needs-branch-and-sha",
                    "APPROVAL_IDS entry for %s needs <id>@<branch>@<sha>" % ident)
        elif not full(en["sha"]):
            u.block("non-full-sha", "APPROVAL_IDS sha %r is not a full 40-hex sha" % en["sha"])
        elif (ident, en["sha"]) in awaiting:
            u.block("approval-repeat", "%s at %s is already awaiting approval" % (
                ident, en["sha"]))
        elif stu_forge._peel(path, "refs/heads/" + en["branch"]) != en["sha"]:
            u.block("approval-branch-moved", "branch %s is not at %s in %s" % (
                en["branch"], en["sha"], e["REPO_NAME"]))
        else:
            u.add_closed("approval-branch-at-sha")
    for en in got.get("INTEGRATED_IDS", {}).get(ident, []):
        if "INTEGRATED_IDS" not in allowed:
            break
        if en["sha"] is None:
            u.block("integrated-needs-sha", "INTEGRATED_IDS entry for %s has no @<sha>" % ident)
        elif not full(en["sha"]):
            u.block("non-full-sha", "INTEGRATED_IDS sha %r is not a full 40-hex sha" % en["sha"])
        elif chk.on_base(e, en["sha"], only_named=True):
            u.add_closed("integrated")
        else:
            u.block("integrated-not-on-base", "%s is not an ancestor of the integration base"
                    % en["sha"])
    for en in got.get("TAGGED_IDS", {}).get(ident, []):
        if en["tag"] is None:
            u.block("tag-malformed", "TAGGED_IDS entry for %s needs <id>=<tag>@<sha>" % ident)
        elif not full(en["sha"]):
            u.block("non-full-sha", "TAGGED_IDS sha %r is not a full 40-hex sha" % en["sha"])
        elif stu_forge.peel(path, remote, en["tag"]) != en["sha"]:
            u.block("tag-peel-mismatch", "tag %s does not peel to %s on %s" % (
                en["tag"], en["sha"], remote))
        else:
            known = merged_shas(chk, ident, got)
            if not known:
                u.block("tag-without-merged-sha", "%s has no Merged sha to tag" % ident)
            elif en["sha"] not in known:
                u.block("tag-sha-not-merged-sha", "tag %s is at %s, not at the merged sha"
                        % (en["tag"], en["sha"]))
            else:
                u.add_closed("tagged")
    for en in got.get("MOVED_IDS", {}).get(ident, []):
        if en["sha"] is None or not full(en["sha"]):
            u.block("non-full-sha", "MOVED_IDS entry for %s needs a full @<sha>" % ident)
        else:
            u.open.append("moved")
    for en in got.get("WAITING_IDS", {}).get(ident, []):
        check_waiting(chk, u, ident, got, en)
    for en in got.get("AFTER_PASS_FAILED", {}).get(ident, []):
        u.open.append("after-pass-failed:%s" % re.sub(r"\s+", "-", en["step"]))
    if ident in got.get("CLOSED_IDS", {}) and not gate_present:
        if before_push(e):
            u.block("closed-without-gate-field", "%s is a before-push unit; it closes only on "
                    "APPROVAL_IDS or its PASSED_IDS leg-2 field" % ident)
        else:
            u.add_closed("no-pr")
    # A failed after-pass step keeps a landed unit outstanding, so its closing field may sit
    # beside REMAINING_IDS; a CLOSED_IDS entry never may, since such a unit is never closed.
    closing = [] if ident in got.get("AFTER_PASS_FAILED", {}) else [
        f for f in gate_present if f in allowed]
    if ident in got.get("CLOSED_IDS", {}):
        closing.append("CLOSED_IDS")
    if ident in held and closing:
        u.block("closed-but-remaining", "%s is in %s and also in %s; a unit its closing field "
                "closes is not outstanding" % (ident, "/".join(closing), held[ident]))
    entry = chk.table.get(ident)
    if entry and entry["after"] and (set(present) & (set(GATE_FIELDS) | set(
            ["CLOSED_IDS", "MOVED_IDS", "TAGGED_IDS"]))):
        ok, code, detail = pred_status(chk, ident, got)
        if not ok:
            u.block(code, detail)
    return u


# ---- driver -----------------------------------------------------------------------------

def parse_args(argv):
    a = {"approved": False}
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok == "--approved":
            a["approved"] = True
            i += 1
        elif tok in ("--objective", "--return"):
            if i + 1 >= len(argv):
                raise ToolError("usage", "%s needs a path" % tok)
            a[tok[2:]] = argv[i + 1]
            i += 2
        else:
            raise ToolError("usage", "unexpected argument %r; usage: stu-run-check --objective "
                            "PATH --return PATH | --approved --objective PATH" % tok)
    if "objective" not in a:
        raise ToolError("usage", "--objective PATH is required")
    if a["approved"] and "return" in a:
        raise ToolError("usage", "--approved takes no --return")
    if not a["approved"] and "return" not in a:
        raise ToolError("usage", "--return PATH is required")
    return a


def check_ids(chk, ids):
    for ident in sorted(ids):
        chk.row_of(ident)


def run_approved(chk):
    out = []
    for raw in board_items(chk.board, "awaiting approval"):
        parts = raw.split("@")
        if len(parts) < 3 or not full(parts[-1]):
            continue
        ident, sha = parts[0], parts[-1]
        e = chk.row_of(ident)
        if (ident, sha) in chk.approvals_for(e):
            out.append("%s APPROVED %s" % (ident, sha))
    return out, False


def inherit_after(chk, fields):
    """A UNITS_CHANGED child that has no unit-table row yet (the supervisor appends it only
    after this check) takes the `after:` of the parent it replaces, so its predecessor is
    verified in the same return that closes it."""
    changed = head_of(fields.get("UNITS_CHANGED", ""))
    if "->" not in changed:
        return
    left, right = changed.split("->", 1)
    for parent in (chk.table.get(i.partition("@")[0]) for i in items(left)):
        if not parent or not parent["after"]:
            continue
        for kid in items(right):
            kid = kid.partition("@")[0]
            if kid not in chk.table:
                chk.table[kid] = {"id": kid, "repo": None, "after": parent["after"]}
        return


def run_returns(chk, fields):
    order, got = gather(fields)
    kids = unit_children(fields)
    inherit_after(chk, fields)
    issued = set(board_items(chk.board, "units issued")) | set(kids)
    check_ids(chk, set(chk.table) | issued | set(order))
    awaiting = set()
    for raw in board_items(chk.board, "awaiting approval"):
        parts = raw.split("@")
        if len(parts) >= 3:
            awaiting.add((parts[0], parts[-1]))
    held = {}
    for f in ("REMAINING_IDS", "PARKED_IDS", "INTEGRATING_IDS"):
        for i in items(fields.get(f, "")):
            held.setdefault(i.partition("@")[0], f)
    lines, any_blocked = [], False
    for ident in order:
        line, blocked = evaluate(chk, ident, got, issued, awaiting, held).line(ident)
        lines.append(line)
        any_blocked = any_blocked or blocked
    seen = set(order)
    extra = []
    for f in ("REMAINING_IDS", "PARKED_IDS", "INTEGRATING_IDS"):
        extra.extend(i.partition("@")[0] for i in items(fields.get(f, "")))
    extra.extend(i.partition("@")[0] for i in kids)
    for ident in extra:
        if ident in seen:
            continue
        seen.add(ident)
        e = chk.row_of(ident)
        if e["MODE"] == "park":
            lines.append("%s BLOCKED park-row: %s belongs to a row with mode: park" % (
                ident, ident))
            any_blocked = True
    return lines, any_blocked


def main(argv):
    try:
        args = parse_args(argv)
        chk_text = read_text(args["objective"], "objective")
        if args["approved"]:
            chk = Check(chk_text, {})
            check_ids(chk, set(chk.table))
            lines, blocked = run_approved(chk)
        else:
            fields = parse_return(read_text(args["return"], "return"))
            chk = Check(chk_text, fields)
            lines, blocked = run_returns(chk, fields)
    except ToolError as e:
        sys.stderr.write("stu-run-check: %s: %s\n" % (e.cls, e.detail))
        return 3
    except stu_forge.Fail as e:
        sys.stderr.write("stu-run-check: %s: %s\n" % (e.cls, e.detail or e.cls))
        return 3
    except Exception as e:  # fail closed: no terminal line, never a traceback
        sys.stderr.write("stu-run-check: internal: %s: %s\n" % (type(e).__name__, e))
        return 3
    for ln in lines:
        print(ln)
    print("BLOCKED" if blocked else "OK")
    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
