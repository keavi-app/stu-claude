"""Parsers and checkers for the `stu:groomer` and `stu:designer` return blocks (handoff-format.md,
"Groomer return" and "Designer return").

Pure text in, a list of problems out; `stu-run-check --groomer-return PATH` and
`--designer-return PATH` are the command lines. Standard library only, like settler_return.py.
"""
import os
import re

GROOMER_STATUSES = ("DONE", "SPLIT", "BLOCKED")
DESIGNER_STATUSES = ("READY", "BLOCKED")
GROOMER_KINDS = ("groom", "audit")
_DASH = re.compile(r"\s+(?:—|–|--)\s+")
_TOP = re.compile(r"^(GROOMER|DESIGNER|JOB|KIND|OUTPUT|ISSUES|OBJECTIVES|LEDGER|NOT-REACHED|SPLIT|"
                  r"ROUND|ARTIFACTS|DECISION):[ \t]*(.*?)\s*$")
_SCOPE = re.compile(r"^S(\d+):[ \t]*(.*?)\s*$")
_OPTION = re.compile(r"^D(\d+):[ \t]*(.*?)\s*$")


def is_usage_limit(summary):
    """True for a BLOCKED reason that starts with `usage limit` (the text after the dash)."""
    return summary.strip().lower().startswith("usage limit")


def _list(value):
    v = value.strip()
    if not v or v.lower() == "none":
        return []
    return [p for p in re.split(r"\s*,\s*", v) if p]


def parse(text, head):
    """-> (block, problems). `head` is GROOMER or DESIGNER. The block carries the status and
    summary from the head line, every top-level field as written (None when absent), the S lines
    as (k, text) and the D lines as (k, text)."""
    b = {"status": None, "summary": "", "fields": {}, "scopes": [], "options": []}
    problems = []
    for line in text.splitlines():
        s = _SCOPE.match(line)
        if s and head == "GROOMER":
            b["scopes"].append((int(s.group(1)), s.group(2)))
            continue
        o = _OPTION.match(line)
        if o and head == "DESIGNER":
            b["options"].append((int(o.group(1)), o.group(2)))
            continue
        m = _TOP.match(line)
        if not m:
            continue
        key, val = m.group(1), m.group(2)
        if key in b["fields"] or (key == head and b["status"] is not None):
            problems.append("duplicate %s line" % key)
            continue
        if key == head:
            parts = _DASH.split(val, 1)
            b["status"] = parts[0].strip()
            b["summary"] = parts[1].strip() if len(parts) > 1 else ""
        else:
            b["fields"][key] = val
    return b, problems


def _abs(value, label, problems):
    if not value:
        problems.append("%s must not be empty" % label)
    elif not os.path.isabs(value):
        problems.append("%s must be an absolute path, got %r" % (label, value))


def _need(b, key, problems):
    v = b["fields"].get(key)
    if v is None:
        problems.append("missing %s line" % key)
    return v


def _common(b, job, problems):
    j = _need(b, "JOB", problems)
    if j is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", j):
        problems.append("JOB must be a job slug, got %r" % j)
    elif j is not None and job is not None and j != job:
        problems.append("JOB is %s, but this return is for job %s" % (j, job))
    n = _need(b, "NOT-REACHED", problems)
    if n is not None and not re.fullmatch(r"\d+", n):
        problems.append("NOT-REACHED must be a non-negative integer, got %r" % n)


def _paths(b, key, problems, allow_none=True):
    v = _need(b, key, problems)
    if v is None:
        return []
    items = _list(v)
    if not items and not (allow_none and v.strip().lower() == "none"):
        problems.append("%s needs at least one absolute path (a design round ends in something "
                        "to look at)" % key if key == "ARTIFACTS" else
                        "%s must be a comma list of paths or none" % key)
    for p in items:
        _abs(p, "%s entry" % key, problems)
    return items


def check_groomer(text, job=None, kind=None):
    """-> (block, problems). `job` is the board job the return must name; `kind` is that job's
    kind (groom or audit) and must equal the KIND line."""
    b, problems = parse(text, "GROOMER")
    st = b["status"]
    if st not in GROOMER_STATUSES:
        problems.append("GROOMER line must start with one of %s" % "/".join(GROOMER_STATUSES))
        return b, problems
    if not b["summary"] and st == "BLOCKED":
        problems.append("BLOCKED needs a one-line reason after the dash")
    if st == "BLOCKED":
        j = b["fields"].get("JOB")
        if j is not None and job is not None and j != job:
            problems.append("JOB is %s, but this return is for job %s" % (j, job))
        return b, problems
    _common(b, job, problems)
    k = _need(b, "KIND", problems)
    if k is not None and k not in GROOMER_KINDS:
        problems.append("KIND must be one of %s, got %r" % ("/".join(GROOMER_KINDS), k))
    elif k is not None and kind is not None and k != kind:
        problems.append("KIND is %s, but the job is a %s job" % (k, kind))
    out = _need(b, "OUTPUT", problems)
    if out is not None:
        _abs(out, "OUTPUT", problems)
    issues = _need(b, "ISSUES", problems)
    if issues is not None:
        for i in _list(issues):
            if not re.fullmatch(r"#?\d+", i):
                problems.append("ISSUES entry %r is not an issue number" % i)
        if not _list(issues) and issues.strip().lower() != "none":
            problems.append("ISSUES must be a comma list or none")
    _paths(b, "OBJECTIVES", problems)
    _paths(b, "LEDGER", problems)
    if st == "SPLIT":
        n = _need(b, "SPLIT", problems)
        count = None
        if n is not None:
            if not re.fullmatch(r"\d+", n) or int(n) < 1:
                problems.append("SPLIT must be a positive integer, got %r" % n)
            else:
                count = int(n)
        nums = [k_ for k_, _ in b["scopes"]]
        if count is not None and len(nums) != count:
            problems.append("SPLIT says %d but %d S lines follow" % (count, len(nums)))
        if nums != list(range(1, len(nums) + 1)):
            problems.append("S lines must be numbered 1..n in order, got %s" % nums)
        for k_, scope in b["scopes"]:
            if not scope:
                problems.append("S%d has no scope text" % k_)
    else:
        if "SPLIT" in b["fields"] or b["scopes"]:
            problems.append("DONE must not carry SPLIT or S lines")
    return b, problems


def check_designer(text, job=None):
    """-> (block, problems)."""
    b, problems = parse(text, "DESIGNER")
    st = b["status"]
    if st not in DESIGNER_STATUSES:
        problems.append("DESIGNER line must start with one of %s" % "/".join(DESIGNER_STATUSES))
        return b, problems
    if st == "BLOCKED":
        if not b["summary"]:
            problems.append("BLOCKED needs a one-line reason after the dash")
        j = b["fields"].get("JOB")
        if j is not None and job is not None and j != job:
            problems.append("JOB is %s, but this return is for job %s" % (j, job))
        return b, problems
    _common(b, job, problems)
    r = _need(b, "ROUND", problems)
    if r is not None and (not re.fullmatch(r"\d+", r) or int(r) < 1):
        problems.append("ROUND must be a positive integer, got %r" % r)
    out = _need(b, "OUTPUT", problems)
    if out is not None:
        _abs(out, "OUTPUT", problems)
    _paths(b, "ARTIFACTS", problems, allow_none=False)
    dec = _need(b, "DECISION", problems)
    if dec is not None and not dec:
        problems.append("DECISION must not be empty")
    nums = [k for k, _ in b["options"]]
    if len(nums) < 2:
        problems.append("a decision needs at least two D options, got %d" % len(nums))
    if nums != list(range(1, len(nums) + 1)):
        problems.append("D lines must be numbered 1..n in order, got %s" % nums)
    rec = 0
    for k, body in b["options"]:
        parts = [p.strip() for p in body.split(" | ", 1)]
        if len(parts) != 2 or not parts[0] or not parts[1]:
            problems.append("D%d must be '<option> | <one line>'" % k)
        if "(recommended)" in body:
            rec += 1
    if rec > 1:
        problems.append("at most one option may be marked (recommended), got %d" % rec)
    return b, problems
