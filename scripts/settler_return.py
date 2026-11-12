"""Parser and checker for the `stu:settler` return block (handoff-format.md, "Settler return").

Pure text in, a list of problems out; `stu-run-check --settler-return PATH` is the command line.
Standard library only.
"""
import os
import re

STATUSES = ("DRAFTED", "WRITTEN", "BLOCKED")
VERIFIERS = ("HOLDS", "STALE", "WRONG", "VACUOUS", "PARTIAL", "UNVERIFIED")
FLAGS = ("owner-only", "sc2-candidate", "reversal")
OWNER_ONLY_ROWS = ("2", "3", "4", "5", "6")
_DASH = re.compile(r"\s+(?:—|–|--)\s+")
_RULING = re.compile(r"^R(\d+):\s*(.*)$")
_TOP = re.compile(r"^(SETTLER|OBJECTIVE|DRAFT|RULINGS|WRITTEN|UNANSWERED|HOLD|SCOREBOARD-TODO|BRIEF):[ \t]*(.*?)\s*$")


_TODO_ID = r"[^\s—–]+"
TODO_FORMS = ("unpark <id>", "drop <id>", "add <id> — <one line>")


def parse_todo(value):
    """-> (verb, id, text) for a well-formed SCOREBOARD-TODO value, else None. The grammar is
    exactly `unpark <id>`, `drop <id>` or `add <id> — <one line>` (the dash may be — – or --)."""
    v = value.strip()
    m = re.fullmatch(r"(unpark|drop)\s+(%s)" % _TODO_ID, v)
    if m:
        return m.group(1), m.group(2), ""
    m = re.fullmatch(r"add\s+(%s)(?:\s+(?:—|–|--)\s+(\S.*))" % _TODO_ID, v)
    if m:
        return "add", m.group(1), m.group(2).strip()
    return None


def _ids(value):
    v = value.strip()
    if not v or v.lower() == "none":
        return []
    return [p for p in re.split(r"[,\s]+", v) if p]


def parse(text):
    """Return (block, problems). `block` has the parsed fields; problems is a list of strings."""
    problems = []
    b = {"status": None, "summary": "", "objective": None, "draft": None, "rulings_n": None,
         "rulings": [], "written": None, "unanswered": None, "hold": None, "todos": [],
         "brief": None}
    seen = set()
    lines = text.splitlines()
    brief_at = None
    for i, line in enumerate(lines):
        m = _TOP.match(line)
        if m and m.group(1) == "BRIEF":
            brief_at = i
            break
        r = _RULING.match(line)
        if r:
            b["rulings"].append((int(r.group(1)), r.group(2)))
            continue
        if not m:
            continue
        key, val = m.group(1), m.group(2)
        if key == "SCOREBOARD-TODO":
            b["todos"].append(val)
            continue
        if key in seen:
            problems.append("duplicate %s line" % key)
            continue
        seen.add(key)
        if key == "SETTLER":
            head = _DASH.split(val, 1)
            b["status"] = head[0].strip()
            b["summary"] = head[1].strip() if len(head) > 1 else ""
        elif key == "OBJECTIVE":
            b["objective"] = val
        elif key == "DRAFT":
            b["draft"] = val
        elif key == "RULINGS":
            b["rulings_n"] = val
        elif key == "WRITTEN":
            b["written"] = _ids(val)
        elif key == "UNANSWERED":
            b["unanswered"] = _ids(val)
        elif key == "HOLD":
            b["hold"] = val
    if brief_at is not None:
        b["brief"] = "\n".join(lines[brief_at + 1:]).strip("\n")
    return b, problems


def _check_ruling(k, body, problems):
    parts = [p.strip() for p in body.split(" | ")]
    if len(parts) != 7:
        problems.append("R%d: want 7 ' | '-separated fields (id, rec, reverses-if, precondition, "
                        "row, verifier, flags), got %d" % (k, len(parts)))
        return None
    qid, rec, rev, pre, row, ver, flg = parts
    vals = {}
    for label, raw in (("rec", rec), ("reverses-if", rev), ("precondition", pre), ("row", row),
                       ("verifier", ver), ("flags", flg)):
        if not raw.startswith(label + ":"):
            problems.append("R%d: field %r must start with %s:" % (k, raw[:24], label))
            return None
        vals[label] = raw[len(label) + 1:].strip()
    if not qid:
        problems.append("R%d: empty question id" % k)
    for label in ("rec", "reverses-if", "precondition"):
        if not vals[label]:
            problems.append("R%d: %s is empty (write 'none' for no precondition)" % (k, label))
    if vals["row"] not in ("1", "2", "3", "4", "5", "6", "7"):
        problems.append("R%d: row must be 1-7, got %r" % (k, vals["row"]))
    if vals["verifier"] not in VERIFIERS:
        problems.append("R%d: verifier must be one of %s, got %r" % (
            k, "/".join(VERIFIERS), vals["verifier"]))
    flags = _ids(vals["flags"]) if vals["flags"].lower() != "none" else []
    if not vals["flags"]:
        problems.append("R%d: flags is empty (write 'none')" % k)
    for f in flags:
        if f not in FLAGS:
            problems.append("R%d: unknown flag %r" % (k, f))
    if "sc2-candidate" in flags and "owner-only" not in flags:
        problems.append("R%d: sc2-candidate implies owner-only; add the owner-only flag" % k)
    if vals["row"] in OWNER_ONLY_ROWS and "owner-only" not in flags:
        problems.append("R%d: row %s is always the owner's and must carry the owner-only flag" % (
            k, vals["row"]))
    return flags


def check(text):
    """Return a list of problem strings; empty means the block is well formed."""
    b, problems = parse(text)
    status = b["status"]
    if status not in STATUSES:
        problems.append("SETTLER line must start with one of %s" % "/".join(STATUSES))
        return problems
    if status == "BLOCKED":
        if not b["summary"]:
            problems.append("BLOCKED needs a one-line reason after the dash")
        return problems
    if not b["summary"]:
        problems.append("SETTLER line needs a one-line summary after the dash")
    for key, label in (("objective", "OBJECTIVE"), ("draft", "DRAFT")):
        if not b[key]:
            problems.append("missing %s line" % label)
        elif not os.path.isabs(b[key]):
            problems.append("%s must be an absolute path, got %r" % (label, b[key]))
    try:
        n = int(b["rulings_n"])
        if n < 0:
            raise ValueError
    except (TypeError, ValueError):
        problems.append("RULINGS must be a non-negative integer, got %r" % b["rulings_n"])
        n = None
    nums = [k for k, _ in b["rulings"]]
    if n is not None and len(nums) != n:
        problems.append("RULINGS says %d but %d R lines follow" % (n, len(nums)))
    if nums != list(range(1, len(nums) + 1)):
        problems.append("R lines must be numbered 1..n in order, got %s" % nums)
    ruling_flags = {}
    for k, body in b["rulings"]:
        fl = _check_ruling(k, body, problems)
        if fl is not None:
            ruling_flags[k] = fl
    ids = ["R%d" % k for k in nums]
    if status == "DRAFTED":
        for key, label in (("written", "WRITTEN"), ("unanswered", "UNANSWERED"),
                           ("hold", "HOLD")):
            if b[key] is not None:
                problems.append("DRAFTED must not carry %s" % label)
        if b["todos"]:
            problems.append("DRAFTED must not carry SCOREBOARD-TODO")
        if b["brief"] is None:
            problems.append("DRAFTED needs a BRIEF: block")
    if status == "DRAFTED" and b["brief"] is not None:
        last = [ln for ln in b["brief"].splitlines() if ln.strip()]
        if not last or not last[-1].startswith("Answer:"):
            problems.append("BRIEF must end in an Answer: line")
        items = {}
        for ln in b["brief"].splitlines():
            m = re.match(r"^\s*(\d+)\.\s", ln)
            if m:
                items.setdefault(int(m.group(1)), ln)
        for k, fl in ruling_flags.items():
            line = items.get(k)
            if line is None:
                if fl:
                    problems.append("BRIEF has no numbered line %d for R%d" % (k, k))
                continue
            for f in fl:
                if "[%s]" % f not in line:
                    problems.append("BRIEF line %d does not show the [%s] flag that R%d carries"
                                    % (k, f, k))
    if status == "WRITTEN":
        if b["written"] is None:
            problems.append("WRITTEN needs a WRITTEN: line")
        if b["unanswered"] is None:
            problems.append("WRITTEN needs an UNANSWERED: line (R ids or none)")
        if b["written"] is not None and b["unanswered"] is not None:
            both = sorted(set(b["written"]) & set(b["unanswered"]))
            if both:
                problems.append("ids both written and unanswered: %s" % ", ".join(both))
            if sorted(set(b["written"]) | set(b["unanswered"])) != sorted(ids):
                problems.append("WRITTEN and UNANSWERED together must cover exactly the R ids %s"
                                % ", ".join(ids))
        hold = b["hold"]
        if hold is None:
            problems.append("WRITTEN needs a HOLD: line (none | set — <reason>)")
        elif hold != "none" and not re.match(r"^set\s+(?:—|–|--)\s+\S", hold):
            problems.append("HOLD must be 'none' or 'set — <reason>', got %r" % hold)
        for t in b["todos"]:
            if not t:
                problems.append("empty SCOREBOARD-TODO line")
            elif parse_todo(t) is None:
                problems.append("SCOREBOARD-TODO %r is malformed; it is exactly one of %s" % (
                    t, " | ".join(TODO_FORMS)))
    return problems
