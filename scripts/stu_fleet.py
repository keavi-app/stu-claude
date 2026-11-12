#!/usr/bin/env python3
"""stu-fleet: the merge hold and lock, and the fleet program, board, spend and next.

  stu-fleet hold set --reason TEXT      set the hold; prints the lock holder to disarm
  stu-fleet hold clear                  clear the hold; re-arms nothing
  stu-fleet hold status                 exit 10 while the hold is set, else 0
  stu-fleet lock take --slug OWNER/REPO --pr N --sha SHA [--label NAME]
                                        take the lock in one locked step
  stu-fleet lock release --pr N [--slug OWNER/REPO] [--landed]
                                        release it (idempotent); --landed records a landing
  stu-fleet lock status                 the holder, if any

  stu-fleet program check PROGRAM       parse and validate a fleet program file
  stu-fleet board show PROGRAM          print the board (a queued row for every run with none)
  stu-fleet board launch PROGRAM --run SLUG
                                        mark a run live; records the cycle count it resumes from
  stu-fleet board record PROGRAM --run SLUG --return FILE
                                        fold a supervisor return into the run's board line
  stu-fleet board requeue PROGRAM --run SLUG
                                        settle|relaunch|owner -> queued
  stu-fleet spend PROGRAM               cycles and launches per run, and the fleet cycle budget
  stu-fleet next PROGRAM                one decision line per run, then hold and lanes

State: <RUN_HOME>/merge-hold.json (override: STU_FLEET_FILE), RUN_HOME from stu-env. Every
read-modify-write runs under an exclusive flock on a sibling `.lock` file and replaces the
state file atomically. An unreadable state file is an error (exit 3), never "no hold".

The program file (docs/fleet-design.md, "The program file") carries the board in its
`## Fleet board` section, one line per run, in Runs order:

  - <slug> | state: <queued|live|settle|relaunch|owner|done> | cycles: <n> | launches: <n> |
    from: <n> | handoff: <abs path|none> | stop: <none|STOP-CONDITION verbatim>

(one physical line; `|` inside copied text is written `/`). Only stu-fleet writes it: under an
exclusive flock on `<program>.lock`, replacing the program file atomically and touching nothing
outside that section. `cycles` is fleet-cumulative; `from` is the count the current launch
resumed from, taken from the objective's `Run state:` and `Cycles used:` by `resume_count`
(the run skill's "The cycle cap"). A board line naming a slug not in Runs, or a malformed one,
is an error (exit 3), never dropped. `program check` prints a normalized summary, or one
`line N BLOCKED: <detail>` per problem then `BLOCKED`. Every other program command refuses a
program with problems the same way (exit 1). `board record` validates the return with
`run_check.check_supervisor_return` (the same validator as `stu-run-check
--supervisor-return`), refuses a return for another objective, and refuses unless the run is
live and the cycle delta is not negative.

`next` prints, in Runs order, `start|wait|settle|owner|relaunch|live|done <slug>` lines (`—` separates the reason), then
`hold: set — <reason>` or `hold: clear`, then `lanes: <live>/<cap>`. Before that it observes the
merge lock holder on the forge and releases it when its PR merged, closed or lost its label
(`lock: released ...`); a holder the forge cannot answer for stays held, the full output is still
printed, and the exit is 12. The effective lane cap is the program's `Max live lanes:`, else
FLEET_MAX_LANES from stu-env (default 4), lowered by `runtime_lane_limit()` where a runtime
reports a slot limit (none on Claude).

`lock take`, in one locked step: if the lock is held by another PR, the holder is checked on
the forge (`stu-forge pr-state`) and released when its PR is merged or closed, or when its
merge label is gone, its auto-merge is off, and the lock is older than a grace period (a gate takes the lock before it
labels, so a fresh lock with no label yet is not abandoned). The forge being unreachable is a
refusal, never an assumption. Then it refuses if the hold is set, then if another PR still
holds the lock; otherwise it records slug, PR, sha and time (re-entrant for the same slug+PR).

The environment variables STU_FLEET_FILE, STU_FLEET_FORGE, STU_FLEET_NOW,
STU_FLEET_LABEL_GRACE and STU_FLEET_MAX_LANES are TEST-ONLY hooks (state file path, stand-in
forge command, clock, grace, lane cap used when the program has no `Max live lanes:`); nothing
in a real run sets them. `hold status` and `lock status` are read-only: they take no
flock (writes replace the file atomically) and never call the forge. `program check`,
`board show` and `spend` are read-only too.

Exit codes: 0 ok; 1 the program file or a supervisor return is invalid (BLOCKED lines);
2 usage; 3 error (state file, run home, unreadable program, malformed board); 10 refused, hold
set; 11 refused, lock held; 12 refused, holder not checkable on the forge; 13 refused, board
state (launching a live or done run, recording into a run that is not live, a negative cycle
delta, requeuing from a state that cannot be requeued). A refusal prints one line that
begins `REFUSED ` followed by the reason text a gate returns (`fleet-hold: ...`,
`fleet-lock: ...` or `fleet-board: ...`).
"""
import fcntl
import json
import os
import re
import secrets
import subprocess
import sys
import stat
import tempfile
import time
from datetime import datetime, timezone

EXIT_INVALID, EXIT_USAGE, EXIT_ERROR = 1, 2, 3
EXIT_HOLD, EXIT_LOCKED, EXIT_FORGE, EXIT_BOARD = 10, 11, 12, 13
FMT = "%Y-%m-%dT%H:%M:%SZ"
DEFAULT_GRACE = 900  # seconds a lock may sit without its label before it counts as abandoned
HERE = os.path.dirname(os.path.abspath(__file__))


class Fail(Exception):
    def __init__(self, code, msg):
        Exception.__init__(self, msg)
        self.code = code
        self.msg = msg


def now_epoch():
    override = os.environ.get("STU_FLEET_NOW")  # tests only
    return float(override) if override else time.time()


def stamp(epoch=None):
    return datetime.fromtimestamp(now_epoch() if epoch is None else epoch,
                                  timezone.utc).strftime(FMT)


def parse_stamp(text):
    return datetime.strptime(text, FMT).replace(tzinfo=timezone.utc).timestamp()


def state_path():
    override = os.environ.get("STU_FLEET_FILE")
    if override:
        return override
    sys.path.insert(0, HERE)
    try:
        import stu_env
        try:
            try:
                env = stu_env.resolve(require_config=True)
            except stu_env.NoConfig:
                env = stu_env.resolve(require_config=False)
        except stu_env.ConfigError as e:
            raise Fail(EXIT_ERROR, "cannot resolve RUN_HOME: %s" % e)
        except stu_env.NotInRepo as e:
            raise Fail(EXIT_ERROR, "cannot resolve RUN_HOME (%s); set STU_FLEET_FILE" % e)
        return os.path.join(env["RUN_HOME"], "merge-hold.json")
    except Fail:
        raise
    except Exception as e:
        raise Fail(EXIT_ERROR, "cannot resolve RUN_HOME: %s: %s" % (type(e).__name__, e))


def empty_state():
    return {"hold": None, "lock": None, "landed_during_hold": []}


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        return empty_state()
    except OSError as e:
        raise Fail(EXIT_ERROR, "cannot read %s: %s" % (path, e))
    try:
        doc = json.loads(text)
    except ValueError as e:
        raise Fail(EXIT_ERROR, "%s is not valid JSON (%s); fix or remove it" % (path, e))
    if not isinstance(doc, dict) or not isinstance(doc.get("landed_during_hold", []), list) \
            or not all(isinstance(doc.get(k), (dict, type(None))) for k in ("hold", "lock")):
        raise Fail(EXIT_ERROR, "%s has an unexpected shape; fix or remove it" % path)
    for k, v in empty_state().items():
        doc.setdefault(k, v)
    return doc


def atomic_write(path, text, prefix=".merge-hold-"):
    """Replace `path` with `text` atomically (temp file in the same directory, fsync, rename)."""
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix=prefix, dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.chmod(tmp, stat.S_IMODE(os.stat(path).st_mode))
        except OSError:
            pass
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save(path, doc):
    atomic_write(path, json.dumps(doc, indent=2, sort_keys=True) + "\n")


class Locked:
    """Exclusive flock on <state>.lock for the with-block; .doc is the loaded state."""

    def __init__(self, path):
        self.path = path

    def __enter__(self):
        d = os.path.dirname(self.path) or "."
        try:
            os.makedirs(d, exist_ok=True)
            self.fh = open(self.path + ".lock", "a")
            fcntl.flock(self.fh, fcntl.LOCK_EX)
        except OSError as e:
            raise Fail(EXIT_ERROR, "cannot lock %s: %s" % (self.path, e))
        try:
            self.doc = load(self.path)
        except BaseException:
            self.fh.close()
            raise
        return self

    def save(self):
        save(self.path, self.doc)

    def __exit__(self, *exc):
        self.fh.close()  # closing drops the flock
        return False


def ref(h):
    return "%s#%s" % (h["slug"], h["pr"])


# ---- forge ------------------------------------------------------------------------------


def forge_state(slug, pr):
    """-> (state, labels, auto_merge_on) of one PR via stu-forge pr-state; raises Fail(EXIT_FORGE)."""
    cmd = os.environ.get("STU_FLEET_FORGE")  # tests only: a stand-in for stu-forge
    argv = ([cmd] if cmd else [sys.executable, os.path.join(HERE, "stu_forge.py")]) + \
        ["pr-state", "--slug", slug, "--pr", str(pr)]
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=90,
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as e:
        raise Fail(EXIT_FORGE, "forge unreachable")
    lines = p.stdout.splitlines()
    if p.returncode != 0 or not lines or lines[-1] != "OK":
        detail = lines[-1] if lines else (p.stderr.strip().splitlines() or ["no output"])[-1]
        raise Fail(EXIT_FORGE, "forge unreachable (%s)" % " ".join(detail.split())[:120])
    got = {}
    for ln in lines[:-1]:
        k, _, v = ln.partition(" ")
        got[k] = v
    if got.get("STATE") not in ("open", "merged", "closed"):
        raise Fail(EXIT_FORGE, "forge unreachable (no PR state)")
    labels = [] if got.get("LABELS", "-") == "-" else got["LABELS"].split(",")
    return got["STATE"], labels, got.get("AUTO_MERGE") != "off"


def holder_gone(lock):
    """Observe the lock holder. -> (gone?, why) where why is merged|closed|label-gone|None."""
    state, labels, auto_on = forge_state(lock["slug"], lock["pr"])
    if state in ("merged", "closed"):
        return True, state
    label = lock.get("label") or ""
    # a PR with auto-merge still enabled is still armed, label or not
    if label and label not in labels and not auto_on:
        grace = float(os.environ.get("STU_FLEET_LABEL_GRACE", DEFAULT_GRACE))
        try:
            age = now_epoch() - parse_stamp(lock["taken_at"])
        except (KeyError, ValueError):
            age = 0.0
        if age > grace:
            return True, "label-gone"
    return False, None


def record_landing(doc, h, sha=None):
    if doc["hold"] is None:
        return False
    doc["landed_during_hold"].append({"slug": h["slug"], "pr": h["pr"],
                                      "sha": sha or h.get("sha") or "-", "at": stamp()})
    return True


# ---- hold -------------------------------------------------------------------------------


def disarm_line(lock):
    return "DISARM %s %s" % (ref(lock), lock.get("sha") or "-") if lock else "DISARM none"


def hold_status(doc):
    if doc["hold"] is None:
        print("HOLD none")
        return 0
    print("HOLD set %s (since %s)" % (doc["hold"]["reason"], doc["hold"].get("set_at", "?")))
    print(disarm_line(doc["lock"]))
    for e in doc["landed_during_hold"]:
        print("LANDED-DURING-HOLD %s#%s %s %s" % (e["slug"], e["pr"], e["sha"], e["at"]))
    return EXIT_HOLD


def cmd_hold(sub, a):
    if sub == "status":  # read-only: no flock, no forge (writes replace the file atomically)
        return hold_status(load(state_path()))
    with Locked(state_path()) as st:
        doc = st.doc
        if sub == "set":
            if not a.get("reason"):
                raise Fail(EXIT_USAGE, "hold set needs --reason")
            if doc["hold"] is None:
                doc["hold"] = {"reason": " ".join(a["reason"].split()), "set_at": stamp()}
                print("HOLD set %s" % doc["hold"]["reason"])
            else:
                print("HOLD already set %s" % doc["hold"]["reason"])
            doc["hold"]["disarm"] = (
                {"slug": doc["lock"]["slug"], "pr": doc["lock"]["pr"],
                 "sha": doc["lock"].get("sha")} if doc["lock"] else None)
            st.save()
            print(disarm_line(doc["lock"]))
            return 0
        if sub == "clear":
            if doc["hold"] is None:
                print("HOLD none")
            else:
                print("HOLD cleared; nothing re-armed")
            for e in doc["landed_during_hold"]:
                print("LANDED-DURING-HOLD %s#%s %s %s" % (e["slug"], e["pr"], e["sha"], e["at"]))
            doc["hold"] = None
            doc["landed_during_hold"] = []
            st.save()
            return 0
        raise Fail(EXIT_USAGE, "unreachable")


# ---- lock -------------------------------------------------------------------------------


def need(a, *names):
    for n in names:
        if not a.get(n):
            raise Fail(EXIT_USAGE, "missing --%s" % n)


def check_ids(a):
    if "pr" in a and not re.fullmatch(r"[0-9]+", a["pr"]):
        raise Fail(EXIT_USAGE, "--pr must be a number")
    if "slug" in a and not re.fullmatch(r"[^/\s]+/[^/\s]+", a["slug"]):
        raise Fail(EXIT_USAGE, "--slug must be owner/repo")
    if "sha" in a and not re.fullmatch(r"[0-9a-f]{7,64}", a["sha"]):
        raise Fail(EXIT_USAGE, "--sha must be hex")


def refuse(code, text):
    print("REFUSED " + text)
    return code


def cmd_lock(sub, a):
    check_ids(a)
    if sub == "status":
        doc = load(state_path())
        lock = doc["lock"]
        print("LOCK none" if not lock else "LOCK %s %s since %s" % (
            ref(lock), lock.get("sha") or "-", lock.get("taken_at", "?")))
        return 0
    if sub == "release":
        need(a, "pr")
        with Locked(state_path()) as st:
            lock = st.doc["lock"]
            if not lock or str(lock["pr"]) != a["pr"] or \
                    (a.get("slug") and lock["slug"] != a["slug"]):
                print("LOCK not held for PR %s" % a["pr"])
                return 0
            if a.get("landed") and record_landing(st.doc, lock):
                print("LANDED-DURING-HOLD %s" % ref(lock))
            st.doc["lock"] = None
            st.save()
            print("LOCK released %s" % ref(lock))
            return 0
    need(a, "slug", "pr", "sha")
    with Locked(state_path()) as st:
        doc, lock = st.doc, st.doc["lock"]
        same = lock and lock["slug"] == a["slug"] and str(lock["pr"]) == a["pr"]
        if lock and not same:
            try:
                gone, why = holder_gone(lock)
            except Fail as e:
                if doc["hold"] is None:
                    return refuse(EXIT_FORGE, "fleet-lock: held by %s, %s" % (ref(lock), e.msg))
                gone, why = False, None  # the hold refuses below; nothing to assume
            if gone:
                if why == "merged":
                    record_landing(doc, lock)
                print("LOCK released %s (%s)" % (ref(lock), why))
                doc["lock"] = lock = None
                st.save()
        if doc["hold"] is not None:
            return refuse(EXIT_HOLD, "fleet-hold: %s" % doc["hold"]["reason"])
        if lock and not same:
            return refuse(EXIT_LOCKED, "fleet-lock: held by %s" % ref(lock))
        doc["lock"] = {"slug": a["slug"], "pr": int(a["pr"]), "sha": a["sha"],
                       "label": a.get("label") or "",
                       "taken_at": lock["taken_at"] if same else stamp()}
        if same:
            doc["lock"]["updated_at"] = stamp()
        st.save()
        print("LOCK held %s %s" % (ref(doc["lock"]), a["sha"]))
        return 0


# ---- program file -----------------------------------------------------------------------

SLUG_RE = r"[A-Za-z0-9][A-Za-z0-9._-]*"
STATES = ("queued", "live", "settle", "relaunch", "owner", "done")
NEXT_STATE = {"none": "done", "settle": "settle", "relaunch": "relaunch", "owner": "owner"}
HEADER_KEYS = ("Owner", "Max live lanes", "Cycle budget", "Judgment jobs", "Stop at",
               "Settle mode", "Merge lock")
STOP_AT_RE = r"\d{4}-\d\d-\d\dT\d\d:\d\d(?::\d\d)?(?:Z|[+-]\d\d:\d\d)"
JUDGMENT_KINDS = ("groom", "audit", "design")
SEC_RUNS, SEC_JUDGMENT, SEC_EXCLUDED, SEC_LIMITS, SEC_BOARD = (
    "runs", "judgment", "excluded", "limits", "board")


def section_of(heading):
    """Map a `## ...` heading to its section key, or None when it is not one of the five."""
    h = heading[2:].strip().lower()
    for key, word in ((SEC_RUNS, "runs"), (SEC_JUDGMENT, "judgment work"),
                      (SEC_EXCLUDED, "excluded"), (SEC_LIMITS, "machine limits"),
                      (SEC_BOARD, "fleet board")):
        if h == word or h.startswith(word + " ") or h.startswith(word + "("):
            return key
    return None


def read_text(path, what="file"):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError) as e:
        raise Fail(EXIT_ERROR, "cannot read %s %s: %s" % (what, path, e))


def objective_facts(path):
    """-> (cap or None, counted lanes, mode) from an objective file's header lines and scoreboard.
    counted lanes = the number of `Lane: <name>` headings, at least 1 (plain runs, and an
    overnight run that has not written its lane blocks yet, count as one lane); mode is
    `overnight` when the header says `Mode: overnight`, else `plain`."""
    text = read_text(path, "objective")
    head = []
    for ln in text.splitlines():
        if ln.startswith("## "):
            break
        head.append(ln)
    m = re.search(r"\bCycle cap:\s*(\d+)", "\n".join(head))
    cap = int(m.group(1)) if m and int(m.group(1)) >= 1 else None
    mm = re.search(r"\bMode:\s*(\w+)", "\n".join(head))
    mode = "overnight" if mm and mm.group(1) == "overnight" else "plain"
    lanes = len(re.findall(r"(?m)^\s*(?:#+\s*)?Lane:\s*\S", text))
    return cap, max(1, lanes), mode


def resume_count(text):
    """The count a supervisor resuming from this objective starts from (the run skill's "The
    cycle cap", At Resume): the scoreboard's `Cycles used:` numerator when `Run state:` reads
    `settled <date> -- nothing to settle`, or reads `stopped --` and any `Lane state:` line
    carries `self-stop:`; 0 otherwise, every other state (`fleet-relaunch`, `/stu:settle` lines,
    running) and any missing field included."""
    if "## Scoreboard" in text:
        text = text[text.index("## Scoreboard"):]
    dash = r"(?:—|–|--|-)"
    state = re.search(r"(?m)^\s*Run state:\s*(.*)$", text)
    used = re.search(r"(?m)^\s*Cycles used:\s*(\d+)\s*/\s*\d+", text)
    if not state or not used:
        return 0
    st = state.group(1).strip()
    cont = bool(re.match(r"settled\s+\S+\s*%s\s*nothing to settle" % dash, st))
    if not cont and re.match(r"stopped\s*%s" % dash, st):
        cont = any("self-stop:" in ln for ln in text.splitlines()
                   if re.match(r"\s*Lane state:", ln))
    return int(used.group(1)) if cont else 0


def split_list(v):
    return [x.strip() for x in v.split(",") if x.strip()]


NOTICE_IDS = ("cycle-80", "cycle-100", "judgment-80", "judgment-100", "stop-at")
V2_LINE = (r"- (%s) \| state: (\S+) \| cycles: (\d+) \| launches: (\d+) \| from: (\d+) \| "
           r"closed: (\d+) \| dry: (\d+) \| nonce: (\S+) \| handoff: (.+?) \| stop: (.+)" % SLUG_RE)
V1_LINE = (r"- (%s) \| state: (\S+) \| cycles: (\d+) \| launches: (\d+) \| from: (\d+) \| "
           r"handoff: (.+?) \| stop: (.+)" % SLUG_RE)
FLEET_LINE = r"- fleet \| judgment: (\d+) \| notices: (\S+)"


def parse_board_line(ln, where):
    """A v2 run line, or a v1 one (S9a's seven fields) read with closed 0, dry 0, nonce none."""
    ln = ln.rstrip("\n")
    m = re.fullmatch(V2_LINE, ln)
    if m and m.group(2) in STATES:
        g = m.groups()
        return {"slug": g[0], "state": g[1], "cycles": int(g[2]), "launches": int(g[3]),
                "from": int(g[4]), "closed": int(g[5]), "dry": int(g[6]), "nonce": g[7],
                "handoff": g[8], "stop": g[9]}
    m = re.fullmatch(V1_LINE, ln)
    if m and m.group(2) in STATES:
        g = m.groups()
        return {"slug": g[0], "state": g[1], "cycles": int(g[2]), "launches": int(g[3]),
                "from": int(g[4]), "closed": 0, "dry": 0, "nonce": "none",
                "handoff": g[5], "stop": g[6]}
    raise Fail(EXIT_ERROR, "%s: malformed board line %r; fix or delete it" % (where, ln.strip()))


def parse_fleet_line(ln, where):
    m = re.fullmatch(FLEET_LINE, ln.rstrip("\n"))
    notices = [] if not m or m.group(2) == "none" else m.group(2).split(",")
    if not m or any(x not in NOTICE_IDS for x in notices) or len(set(notices)) != len(notices):
        raise Fail(EXIT_ERROR, "%s: malformed fleet line %r; fix or delete it" % (where, ln.strip()))
    return {"judgment": int(m.group(1)), "notices": notices}


def board_line(b):
    clean = lambda v: str(v).replace("|", "/").replace("\n", " ")
    return ("- %s | state: %s | cycles: %d | launches: %d | from: %d | closed: %d | dry: %d | "
            "nonce: %s | handoff: %s | stop: %s") % (
        b["slug"], b["state"], b["cycles"], b["launches"], b["from"], b["closed"], b["dry"],
        b["nonce"], clean(b["handoff"]) or "none", clean(b["stop"]) or "none")


def fleet_line(f):
    return "- fleet | judgment: %d | notices: %s" % (f["judgment"], ",".join(f["notices"]) or "none")


def parse_program(text):
    """The one parse function. -> program dict; problems (list of `line N BLOCKED: ...`) in
    prog["problems"]. Raises Fail(EXIT_ERROR) for a malformed or foreign board line."""
    lines = text.splitlines(keepends=True)
    prog = {"name": "", "header": {}, "runs": [], "judgment": [], "board": {}, "problems": [],
            "board_span": None, "lines": lines, "fleet": {"judgment": 0, "notices": []}}
    fleet_seen = False
    bad = prog["problems"]

    def block(n, detail):
        bad.append("line %d BLOCKED: %s" % (n, detail))

    sec, start = None, 0
    seen_sections = set()
    for i, raw in enumerate(lines):
        n, ln = i + 1, raw.rstrip("\n")
        if ln.startswith("## "):
            if sec == SEC_BOARD:
                prog["board_span"] = (start, i)
            sec = section_of(ln)
            if sec is None:
                block(n, "unknown section %r; use Runs, Judgment work, Excluded, Machine "
                         "limits or Fleet board" % ln.strip())
                continue
            if sec in seen_sections:
                block(n, "section %r appears twice" % ln.strip())
            seen_sections.add(sec)
            if sec == SEC_BOARD:
                start = i
            continue
        if not ln.strip():
            continue
        if sec is None and ln.startswith("# "):
            prog["name"] = ln[2:].replace("Fleet program:", "").strip()
            continue
        if sec is None:
            m = re.match(r"([A-Z][A-Za-z ]*?):\s*(.*)$", ln)
            if not m:
                continue  # prose before the first section is ignored
            k, v = m.group(1), m.group(2).strip()
            if k not in HEADER_KEYS:
                block(n, "unknown header %r; the keys are %s" % (k, ", ".join(HEADER_KEYS)))
            elif k in prog["header"]:
                block(n, "header %r appears twice" % k)
            else:
                prog["header"][k] = (v, n)
        elif sec == SEC_RUNS:
            m = re.fullmatch(r"- (%s): (\S+) \| after: ([^|]+?) \| resources: ([^|]+?)"
                             r"(?: \| lanes: (\d+))?" % SLUG_RE, ln)
            if not m:
                block(n, "run line must be '- <slug>: <objective path> | after: <slug or none> "
                         "| resources: <names> [| lanes: <n>]'")
                continue
            after = [] if m.group(3).strip() == "none" else split_list(m.group(3))
            res = [] if m.group(4).strip() == "none" else split_list(m.group(4))
            prog["runs"].append({"slug": m.group(1), "objective": m.group(2), "after": after,
                                 "resources": res, "line": n,
                                 "declared": int(m.group(5)) if m.group(5) else None})
        elif sec == SEC_JUDGMENT:
            m = re.fullmatch(r"- (%s): (\S+) \| scope: (.+?) \| output: (\S+) \| feeds: (\S+)"
                             % SLUG_RE, ln)
            if not m or m.group(2) not in JUDGMENT_KINDS:
                block(n, "judgment line must be '- <slug>: <groom|audit|design> | scope: <one "
                         "line> | output: <path> | feeds: <run slug or none>'")
                continue
            prog["judgment"].append({"slug": m.group(1), "kind": m.group(2), "scope": m.group(3),
                                     "output": m.group(4), "feeds": m.group(5), "line": n})
        elif sec == SEC_BOARD:
            if fleet_seen:
                raise Fail(EXIT_ERROR, "line %d: the fleet line must be the last line of the "
                                       "board; fix or delete the lines after it" % n)
            if re.match(r"- fleet\b", ln):
                prog["fleet"] = parse_fleet_line(ln, "line %d" % n)
                fleet_seen = True
                continue
            b = parse_board_line(ln, "line %d" % n)
            if b["slug"] in prog["board"]:
                raise Fail(EXIT_ERROR, "line %d: board names %s twice; delete one line" % (n, b["slug"]))
            prog["board"][b["slug"]] = b
    if sec == SEC_BOARD:
        prog["board_span"] = (start, len(lines))
    validate_program(prog, block)
    for slug in prog["board"]:
        if slug not in [r["slug"] for r in prog["runs"]]:
            raise Fail(EXIT_ERROR, "board line for %r, which is not in Runs; delete the line "
                                   "or add the run" % slug)
    return prog


def validate_program(prog, block):
    h = prog["header"]
    if "Owner" not in h or not h["Owner"][0]:
        block(1, "Owner: is required")
    if "Settle mode" not in h or h["Settle mode"][0] not in ("draft", "auto-narrow"):
        block(h.get("Settle mode", ("", 1))[1], "Settle mode: is required, draft | auto-narrow")
    pos = lambda v: re.fullmatch(r"[0-9]+", v) and int(v) >= 1
    if "Max live lanes" in h and not pos(h["Max live lanes"][0]):
        block(h["Max live lanes"][1], "Max live lanes: must be a positive integer")
    for k in ("Cycle budget", "Judgment jobs"):
        if k in h and h[k][0] != "none" and not pos(h[k][0]):
            block(h[k][1], "%s: must be a positive integer or none" % k)
    if "Stop at" in h and h["Stop at"][0] != "none":
        v = h["Stop at"][0]
        ok = bool(re.fullmatch(STOP_AT_RE, v))
        if ok:
            try:
                datetime.fromisoformat(v.replace("Z", "+00:00"))
            except ValueError:
                ok = False
        if not ok:
            block(h["Stop at"][1], "Stop at: must be an ISO-8601 time with an offset "
                                   "(2026-11-12T18:00:00+00:00) or none")
    if "Merge lock" in h and h["Merge lock"][0] not in ("on", "off"):
        block(h["Merge lock"][1], "Merge lock: must be on or off")
    slugs = {}
    for r in prog["runs"]:
        if r["slug"] in slugs:
            block(r["line"], "run %s appears twice (first at line %d)" % (r["slug"], slugs[r["slug"]]))
        slugs[r["slug"]] = r["line"]
    if not prog["runs"]:
        block(1, "no runs: add '- <slug>: <objective path> | after: none | resources: none' "
                 "under '## Runs'")
    for r in prog["runs"]:
        if r["slug"] == "fleet":
            block(r["line"], "run slug 'fleet' is reserved for the board's fleet line")
        r["cap"], r["lanes"], r["mode"] = None, max(1, r["declared"] or 1), "plain"
        if not r["objective"].startswith("/"):
            block(r["line"], "run %s: objective path %r is not absolute" % (r["slug"], r["objective"]))
        elif not os.path.isfile(r["objective"]):
            block(r["line"], "run %s: objective %s does not exist" % (r["slug"], r["objective"]))
        else:
            try:
                r["cap"], counted, r["mode"] = objective_facts(r["objective"])
                r["lanes"] = max(r["declared"] or 0, counted, 1)
            except Fail as e:
                block(r["line"], "run %s: %s" % (r["slug"], e.msg))
            else:
                if r["declared"] is not None and r["declared"] < 1:
                    block(r["line"], "run %s: lanes: must be a positive integer" % r["slug"])
                elif r["mode"] == "overnight" and r["declared"] is None:
                    block(r["line"], "run %s: its objective is Mode: overnight, so the Runs line "
                                     "must declare '| lanes: <n>'" % r["slug"])
                elif r["mode"] == "plain" and r["declared"] not in (None, 1):
                    block(r["line"], "run %s: a plain objective runs one lane, but the Runs line "
                                     "declares lanes: %d" % (r["slug"], r["declared"]))
                if r["cap"] is None:
                    block(r["line"], "run %s: objective has no 'Cycle cap: <n>' line; a fleet "
                                     "objective states its cap (startup stop)" % r["slug"])
        mx = h.get("Max live lanes")
        if mx and pos(mx[0]) and r["lanes"] > int(mx[0]):
            block(r["line"], "run %s: its objective declares %d lanes but Max live lanes: is %s; "
                             "raise the cap or cut the lanes" % (r["slug"], r["lanes"], mx[0]))
        for a in r["after"]:
            if a not in slugs:
                block(r["line"], "run %s: after: names %r, which is not a run" % (r["slug"], a))
            elif a == r["slug"]:
                block(r["line"], "run %s: after: names itself" % r["slug"])
    cyc = after_cycle(prog["runs"])
    if cyc:
        block(slugs[cyc[0]], "after: cycle among runs: %s" % " -> ".join(cyc + cyc[:1]))
    judged = {}
    for j in prog["judgment"]:
        if j["slug"] in judged:
            block(j["line"], "judgment job %s appears twice" % j["slug"])
        judged[j["slug"]] = True
        if j["feeds"] != "none" and j["feeds"] not in slugs:
            block(j["line"], "judgment job %s: feeds: names %r, which is not a run" % (
                j["slug"], j["feeds"]))


def after_cycle(runs):
    """-> a list of slugs forming a cycle in the after: graph, or []."""
    deps = {r["slug"]: [a for a in r["after"]] for r in runs}
    state = {}

    def visit(s, path):
        state[s] = 1
        for d in deps.get(s, []):
            if d not in deps:
                continue
            if state.get(d) == 1:
                return path[path.index(d):] if d in path else [d]
            if d not in state:
                got = visit(d, path + [d])
                if got:
                    return got
        state[s] = 2
        return []

    for r in runs:
        if r["slug"] not in state:
            got = visit(r["slug"], [r["slug"]])
            if got:
                return got
    return []


def load_program(path):
    prog = parse_program(read_text(path, "program"))
    prog["path"] = path
    return prog


def need_valid(prog):
    if prog["problems"]:
        for p in prog["problems"]:
            print(p)
        print("BLOCKED")
        return EXIT_INVALID
    return 0


def effective_board(prog):
    """Board lines in Runs order, a queued row for every run that has none."""
    out = []
    for r in prog["runs"]:
        out.append(prog["board"].get(r["slug"]) or {
            "slug": r["slug"], "state": "queued", "cycles": 0, "launches": 0, "from": 0,
            "closed": 0, "dry": 0, "nonce": "none", "handoff": "none", "stop": "none"})
    return out


def render_program(prog, board, fleet):
    """The program file text with its Fleet board section replaced by `board` and the fleet line."""
    lines = list(prog["lines"])
    body = [board_line(b) + "\n" for b in board] + [fleet_line(fleet) + "\n"]
    if prog["board_span"] is None:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        return "".join(lines) + ("\n" if lines else "") + "## Fleet board\n" + "".join(body)
    a, b = prog["board_span"]
    heading = lines[a] if lines[a].endswith("\n") else lines[a] + "\n"
    tail = ["\n"] if b < len(lines) else []
    return "".join(lines[:a]) + heading + "".join(body) + "".join(tail) + "".join(lines[b:])


class ProgramLocked:
    """Exclusive flock on <program>.lock; .prog is the program re-read under the lock."""

    def __init__(self, path):
        self.path = path

    def __enter__(self):
        try:
            self.fh = open(self.path + ".lock", "a")
            fcntl.flock(self.fh, fcntl.LOCK_EX)
        except OSError as e:
            raise Fail(EXIT_ERROR, "cannot lock %s: %s" % (self.path, e))
        try:
            self.prog = load_program(self.path)
        except BaseException:
            self.fh.close()
            raise
        return self

    def write(self, board):
        atomic_write(self.path, render_program(self.prog, board, self.prog["fleet"]),
                     prefix=".fleet-program-")

    def __exit__(self, *exc):
        self.fh.close()
        return False


# ---- program, board, spend, next --------------------------------------------------------


def cmd_program(sub, a):
    prog = load_program(a["program"])
    rc = need_valid(prog)
    if rc:
        return rc
    h = {k: v[0] for k, v in prog["header"].items()}
    print("program: %s" % (prog["name"] or "-"))
    print("owner: %s" % h["Owner"])
    print("settle-mode: %s" % h["Settle mode"])
    print("max-live-lanes: %s" % h.get("Max live lanes", "config"))
    print("cycle-budget: %s" % h.get("Cycle budget", "sum-of-caps"))
    print("judgment-jobs: %s" % h.get("Judgment jobs", "none"))
    print("stop-at: %s" % h.get("Stop at", "none"))
    print("merge-lock: %s" % h.get("Merge lock", "on"))
    for r in prog["runs"]:
        print("run %s: objective %s | cap %d | lanes %d | after %s | resources %s" % (
            r["slug"], r["objective"], r["cap"], r["lanes"], ",".join(r["after"]) or "none",
            ",".join(r["resources"]) or "none"))
    for j in prog["judgment"]:
        print("judgment %s: %s | feeds %s" % (j["slug"], j["kind"], j["feeds"]))
    print("OK")
    return 0


def find_run(prog, slug):
    for r in prog["runs"]:
        if r["slug"] == slug:
            return r
    raise Fail(EXIT_USAGE, "--run %s is not a run in this program" % slug)


def scoreboard(text):
    """The objective text from `## Scoreboard` on (all of it when there is no such heading)."""
    return text[text.index("## Scoreboard"):] if "## Scoreboard" in text else text


def closed_ids(text):
    """The distinct unit IDs in an objective's `Closed:` lines (the union across `Lane:` blocks;
    `NONE` is none). An entry is the first word of each comma-separated item."""
    ids = set()
    for m in re.finditer(r"(?m)^\s*Closed:[ \t]*(.*)$", scoreboard(text)):
        for item in m.group(1).split(","):
            word = item.split()[0] if item.split() else ""
            if word and word != "NONE":
                ids.add(word)
    return ids


def closed_count(text):
    return len(closed_ids(text))


def cycles_used(text):
    m = re.search(r"(?m)^\s*Cycles used:\s*(\d+)\s*/\s*\d+", scoreboard(text))
    return int(m.group(1)) if m else 0


def last_handoff(text):
    m = re.search(r"(?m)^\s*Last handoff:[ \t]*(\S.*?)\s*$", scoreboard(text))
    return m.group(1) if m else "none"


def new_nonce():
    override = os.environ.get("STU_FLEET_NONCE")  # tests only
    return override or "stu-" + secrets.token_hex(8)


def begin_launch(run, b):
    """What `board launch` does to a board line; -> the new nonce."""
    text = read_text(run["objective"], "objective")
    b["from"] = resume_count(text)
    b["closed"] = closed_count(text)
    b["state"] = "live"
    b["launches"] += 1
    b["nonce"] = new_nonce()
    return b["nonce"]


def loop_guard(run, b):
    """Always on. Count the closed IDs now; a launch that closed nothing new adds to `dry`.
    A `relaunch` outcome with dry >= 2 becomes `owner`."""
    now = closed_count(read_text(run["objective"], "objective"))
    b["dry"] = b["dry"] + 1 if now <= b["closed"] else 0
    if b["state"] == "relaunch" and b["dry"] >= 2:
        b["state"] = "owner"
        b["stop"] = "loop guard \u2014 2 launches closed no unit; last stop: %s" % b["stop"]


# ---- limits and the next policy ---------------------------------------------------------


def limits(prog, board, fleet):
    """The one evaluation of the program's limits. -> dict of
    cycle (used, limit or None, spent), judgment (same), stop (text or None, passed)."""
    h = {k: v[0] for k, v in prog["header"].items()}
    used = sum(b["cycles"] for b in board)
    raw = h.get("Cycle budget")
    limit = None if raw == "none" else int(raw) if raw else sum(r["cap"] for r in prog["runs"])
    jraw = h.get("Judgment jobs", "none")
    jlimit = None if jraw == "none" else int(jraw)
    stop = h.get("Stop at")
    if stop == "none":
        stop = None
    passed = bool(stop) and now_epoch() >= datetime.fromisoformat(
        stop.replace("Z", "+00:00")).timestamp()
    return {"cycle": (used, limit, limit is not None and used >= limit),
            "judgment": (fleet["judgment"], jlimit, jlimit is not None and fleet["judgment"] >= jlimit),
            "stop": (stop, passed)}


def limit_text(lim):
    """Why a new dispatch is refused, or None. Cycle budget first."""
    used, limit, spent = lim["cycle"]
    if spent:
        return "cycle budget spent %d/%d" % (used, limit)
    if lim["stop"][1]:
        return "stop at %s passed" % lim["stop"][0]
    return None


def fmt_limit(t):
    return "%d/%s" % (t[0], "none" if t[1] is None else t[1])


def decide(prog, board, cap, lim):
    """The one policy: -> [(slug, word, text)] in Runs order, and the live lane count.
    word is start|wait|settle|owner|relaunch|live|done."""
    runs = {r["slug"]: r for r in prog["runs"]}
    live, held = 0, {}
    for slug, b in board.items():
        if b["state"] == "live":
            live += runs[slug]["lanes"]
            for x in runs[slug]["resources"]:
                held.setdefault(x, slug)
    shown_live = live
    out = []
    for r in prog["runs"]:
        b, slug = board[r["slug"]], r["slug"]
        if b["state"] in ("queued", "relaunch"):
            pending = [x for x in r["after"] if board[x]["state"] != "done"]
            clash = [(x, held[x]) for x in r["resources"] if x in held]
            word = "start" if b["state"] == "queued" else "relaunch"
            if pending:
                out.append((slug, "wait", "after %s" % ",".join(pending)))
            elif clash:
                out.append((slug, "wait", "resource %s held by %s" % clash[0]))
            elif r["lanes"] > cap:
                out.append((slug, "owner", "needs %d lanes, cap %d" % (r["lanes"], cap)))
            elif live + r["lanes"] > cap:
                out.append((slug, "wait", "lane cap %d/%d" % (live, cap)))
            elif limit_text(lim):
                out.append((slug, "owner", limit_text(lim)))
            else:
                out.append((slug, word, b["stop"] if word == "relaunch" else ""))
                live += r["lanes"]
                for x in r["resources"]:
                    held.setdefault(x, slug)
        elif b["state"] == "settle":
            out.append((slug, "settle", "owner-only" if re.match(r"[23]\b", b["stop"]) else ""))
        elif b["state"] == "owner":
            out.append((slug, "owner", b["stop"]))
        else:
            out.append((slug, b["state"], ""))
    return out, shown_live


def decision_line(slug, word, text):
    if word == "settle":
        return "settle %s%s" % (slug, " " + text if text else "")
    if text:
        return "%s %s \u2014 %s" % (word, slug, text)
    return "%s %s" % (word, slug)


def new_notices(lim, seen):
    """-> [(id, text)] of the notices not yet in `seen`, in print order."""
    out = []
    for key, name, pre in (("cycle", "cycle-budget", "cycle"), ("judgment", "judgment-jobs", "judgment")):
        used, limit, _ = lim[key]
        if limit is None:
            continue
        for pct in (80, 100):
            nid = "%s-%d" % (pre, pct)
            if used * 100 >= pct * limit and nid not in seen:
                out.append((nid, "notice: %s %d%% (%d/%d)" % (name, pct, used, limit)))
    if lim["stop"][1] and "stop-at" not in seen:
        out.append(("stop-at", "notice: stop-at passed (%s)" % lim["stop"][0]))
    return out


# ---- program, board, spend, next --------------------------------------------------------


def cmd_program(sub, a):
    prog = load_program(a["program"])
    rc = need_valid(prog)
    if rc:
        return rc
    h = {k: v[0] for k, v in prog["header"].items()}
    print("program: %s" % (prog["name"] or "-"))
    print("owner: %s" % h["Owner"])
    print("settle-mode: %s" % h["Settle mode"])
    print("max-live-lanes: %s" % h.get("Max live lanes", "config"))
    print("cycle-budget: %s" % h.get("Cycle budget", "sum-of-caps"))
    print("judgment-jobs: %s" % h.get("Judgment jobs", "none"))
    print("stop-at: %s" % h.get("Stop at", "none"))
    print("merge-lock: %s" % h.get("Merge lock", "on"))
    for r in prog["runs"]:
        print("run %s: objective %s | cap %d | lanes %d | after %s | resources %s" % (
            r["slug"], r["objective"], r["cap"], r["lanes"], ",".join(r["after"]) or "none",
            ",".join(r["resources"]) or "none"))
    for j in prog["judgment"]:
        print("judgment %s: %s | feeds %s" % (j["slug"], j["kind"], j["feeds"]))
    print("OK")
    return 0


def find_run(prog, slug):
    for r in prog["runs"]:
        if r["slug"] == slug:
            return r
    raise Fail(EXIT_USAGE, "--run %s is not a run in this program" % slug)


def set_run_state(path, date):
    """Write `Run state: fleet-relaunch <date>` over the first `Run state:` line inside the
    objective's `## Scoreboard`, nothing else changed: under a flock on <objective>.lock, replacing
    the file atomically. -> None, or the refusal text when there is no such scoreboard or line."""
    try:
        with open(path + ".lock", "a") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            with open(path, encoding="utf-8", newline="") as f:
                text = f.read()
            at = text.find("## Scoreboard")
            m = re.compile(r"(?m)^([ \t]*Run state:)[ \t]*[^\r\n]*").search(text, at) if at >= 0 else None
            if not m:
                return ("fleet-board: %s has no '## Scoreboard' with a 'Run state:' line to "
                        "rewrite" % path)
            new = text[:m.start()] + "%s fleet-relaunch %s" % (m.group(1), date) + text[m.end():]
            atomic_write(path, new, prefix=".fleet-objective-")
            return None
    except OSError as e:
        raise Fail(EXIT_ERROR, "cannot rewrite objective %s: %s" % (path, e))


def cmd_board(sub, a):
    if sub == "show":
        prog = load_program(a["program"])
        rc = need_valid(prog)
        if rc:
            return rc
        for b in effective_board(prog):
            print(board_line(b))
        print(fleet_line(prog["fleet"]))
        return 0
    if sub == "judgment":
        return cmd_judgment(a)
    need(a, "run")
    if sub == "record":
        need(a, "return")
    with ProgramLocked(a["program"]) as st:
        prog = st.prog
        rc = need_valid(prog)
        if rc:
            return rc
        run = find_run(prog, a["run"])
        board = effective_board(prog)
        b = [x for x in board if x["slug"] == run["slug"]][0]
        nonce = None
        if sub == "launch":
            if b["state"] in ("live", "done"):
                return refuse(EXIT_BOARD, "fleet-board: %s is %s; %s" % (
                    run["slug"], b["state"],
                    "never two supervisors on one unit list" if b["state"] == "live"
                    else "a done run is not launched again"))
            nonce = begin_launch(run, b)
        elif sub == "relaunch":
            if b["state"] != "relaunch":
                return refuse(EXIT_BOARD, "fleet-board: %s is %s, not relaunch" % (
                    run["slug"], b["state"]))
            bmap = {x["slug"]: x for x in board}
            decided, _ = decide(prog, bmap, lane_cap(prog), limits(prog, board, prog["fleet"]))
            slug, word, text = [d for d in decided if d[0] == run["slug"]][0]
            if word != "relaunch":
                return refuse(EXIT_BOARD, "fleet-board: policy says %s for %s now, not relaunch" % (
                    decision_line(slug, word, text), run["slug"]))
            bad = set_run_state(run["objective"], stamp()[:10])
            if bad:
                return refuse(EXIT_BOARD, bad)
            nonce = begin_launch(run, b)
        elif sub == "idle":
            if b["state"] != "live":
                return refuse(EXIT_BOARD, "fleet-board: %s is %s, not live; nothing is idle" % (
                    run["slug"], b["state"]))
            text = read_text(run["objective"], "objective")
            used = cycles_used(text)
            if used < b["from"]:
                return refuse(EXIT_BOARD, "fleet-board: %s shows %d cycles used but resumed from "
                                          "%d; a negative delta is never clamped, so check the "
                                          "objective's scoreboard" % (run["slug"], used, b["from"]))
            b["cycles"] += used - b["from"]
            b["state"] = "relaunch"
            b["stop"] = "idle \u2014 no return"
            b["handoff"] = last_handoff(text)
            loop_guard(run, b)
        elif sub == "requeue":
            if b["state"] not in ("settle", "relaunch", "owner"):
                return refuse(EXIT_BOARD, "fleet-board: %s is %s; only settle, relaunch or "
                                          "owner can be requeued" % (run["slug"], b["state"]))
            b["state"] = "queued"
        else:  # record
            rc = record_return(run, b, a["return"])
            if rc:
                return rc
        st.write(board)
        print(board_line(b))
        if nonce:
            print("nonce: %s" % nonce)
        return 0


def cmd_judgment(a):
    need(a, "job")
    with ProgramLocked(a["program"]) as st:
        prog = st.prog
        rc = need_valid(prog)
        if rc:
            return rc
        if a["job"] not in [j["slug"] for j in prog["judgment"]]:
            print("BLOCKED: %s is not a line under '## Judgment work'" % a["job"])
            return EXIT_INVALID
        board = effective_board(prog)
        lim = limits(prog, board, prog["fleet"])
        if lim["judgment"][2]:
            return refuse(EXIT_BOARD, "fleet-board: judgment jobs spent %s" % fmt_limit(lim["judgment"]))
        if lim["stop"][1]:
            return refuse(EXIT_BOARD, "fleet-board: stop at %s passed" % lim["stop"][0])
        prog["fleet"]["judgment"] += 1
        st.write(board)
        print("judgment-jobs: %d/%s" % (prog["fleet"]["judgment"],
                                        "none" if lim["judgment"][1] is None else lim["judgment"][1]))
        return 0


def record_return(run, b, ret_path):
    import run_check
    text = read_text(ret_path, "supervisor return")
    bad = run_check.check_supervisor_return(text)
    if bad:
        for p in bad:
            print(p)
        print("BLOCKED")
        return EXIT_INVALID
    f = {}
    for ln in text.splitlines():
        m = run_check.SUP_KEY.match(ln)
        if m and m.group(1) not in f:
            f[m.group(1)] = m.group(2)
    if os.path.realpath(f["OBJECTIVE"]) != os.path.realpath(run["objective"]):
        return refuse(EXIT_BOARD, "fleet-board: the return is for objective %s, not %s's %s" % (
            f["OBJECTIVE"], run["slug"], run["objective"]))
    if b["state"] != "live":
        return refuse(EXIT_BOARD, "fleet-board: %s is %s, not live; nothing to record into" % (
            run["slug"], b["state"]))
    used = int(f["CYCLES"].split("/")[0])
    if used < b["from"]:
        return refuse(EXIT_BOARD, "fleet-board: %s returned %d cycles used but resumed from %d; "
                                  "a negative delta is never clamped, so check the objective's "
                                  "scoreboard" % (run["slug"], used, b["from"]))
    b["cycles"] += used - b["from"]
    b["state"] = NEXT_STATE[f["NEXT"]]
    b["handoff"] = f["LAST-HANDOFF"]
    b["stop"] = f["STOP-CONDITION"]
    loop_guard(run, b)
    return 0


def cmd_spend(sub, a):
    prog = load_program(a["program"])
    rc = need_valid(prog)
    if rc:
        return rc
    board = effective_board(prog)
    for b in board:
        print("run %s: cycles %d, launches %d, dry %d" % (b["slug"], b["cycles"], b["launches"], b["dry"]))
    lim = limits(prog, board, prog["fleet"])
    used, limit, _ = lim["cycle"]
    print("fleet: cycles %d" % used)
    if limit is None:
        print("budget: %d/none" % used)
    else:
        print("budget: %d/%d (%d%%)" % (used, limit, used * 100 // limit))
    print("judgment-jobs: %s" % fmt_limit(lim["judgment"]))
    print("stop-at: %s (%s)" % (lim["stop"][0] or "none", "passed" if lim["stop"][1] else "not passed"))
    return 0


def runtime_lane_limit():
    """The hook where a runtime that reports its own slot limit lowers the lane cap. Claude
    reports none, so this returns None; a runtime binding returns its limit as an int."""
    return None


def lane_cap(prog):
    raw = prog["header"].get("Max live lanes", (None,))[0]
    if raw is None:
        raw = os.environ.get("STU_FLEET_MAX_LANES")  # tests only
    if raw is None:
        sys.path.insert(0, HERE)
        import stu_env
        try:
            raw = stu_env.resolve(require_config=True).get("FLEET_MAX_LANES", "4")
        except stu_env.NoConfig:
            raw = "4"
        except Exception as e:
            raise Fail(EXIT_ERROR, "cannot resolve FLEET_MAX_LANES: %s; set 'Max live lanes:' "
                                   "in the program" % e)
    cap = int(raw)
    limit = runtime_lane_limit()
    return min(cap, limit) if limit else cap


def cmd_next(sub, a):
    prog = load_program(a["program"])
    rc = need_valid(prog)
    if rc:
        return rc
    cap = lane_cap(prog)
    code = 0
    lines = []
    with Locked(state_path()) as st:  # release by observation, the one write
        lock = st.doc["lock"]
        if lock:
            try:
                gone, why = holder_gone(lock)
            except Fail as e:
                lines.append("lock: held by %s \u2014 %s; not released" % (ref(lock), e.msg))
                code = e.code
            else:
                if gone:
                    if why == "merged":
                        record_landing(st.doc, lock)
                    st.doc["lock"] = None
                    st.save()
                    lines.append("lock: released %s (%s)" % (ref(lock), why))
        hold = st.doc["hold"]
    board = effective_board(prog)
    lim = limits(prog, board, prog["fleet"])
    if new_notices(lim, prog["fleet"]["notices"]):
        with ProgramLocked(a["program"]) as pl:  # each notice prints once, ever: record it first
            prog = pl.prog
            board = effective_board(prog)
            lim = limits(prog, board, prog["fleet"])
            fresh = new_notices(lim, prog["fleet"]["notices"])
            if fresh:
                prog["fleet"]["notices"] += [nid for nid, _ in fresh]
                pl.write(board)
    else:
        fresh = []
    decided, shown_live = decide(prog, {b["slug"]: b for b in board}, cap, lim)
    lines += [decision_line(*d) for d in decided]
    lines += [text for _, text in fresh]
    lines.append("hold: set \u2014 %s" % hold["reason"] if hold else "hold: clear")
    lines.append("lanes: %d/%d" % (shown_live, cap))
    lines.append("budget: %s" % fmt_limit(lim["cycle"]))
    lines.append("judgment-jobs: %s" % fmt_limit(lim["judgment"]))
    print("\n".join(lines))
    return code


# ---- command line -----------------------------------------------------------------------

SPEC = {
    ("hold", "set"): (("reason",), ()),
    ("hold", "clear"): ((), ()),
    ("hold", "status"): ((), ()),
    ("lock", "take"): (("slug", "pr", "sha", "label"), ()),
    ("lock", "release"): (("pr", "slug"), ("landed",)),
    ("lock", "status"): ((), ()),
}
# commands whose first argument after the subcommand is the program file
PROGRAM_SPEC = {
    ("program", "check"): ((), ()),
    ("board", "show"): ((), ()),
    ("board", "launch"): (("run",), ()),
    ("board", "record"): (("run", "return"), ()),
    ("board", "requeue"): (("run",), ()),
    ("board", "idle"): (("run",), ()),
    ("board", "relaunch"): (("run",), ()),
    ("board", "judgment"): (("job",), ()),
    ("spend", None): ((), ()),
    ("next", None): ((), ()),
}
USAGE = ("usage: stu-fleet hold set|clear|status | lock take|release|status [flags] | "
         "program check P | board show|launch|record|requeue|idle|relaunch|judgment P [flags] | spend P | next P")


def parse(argv):
    if argv and argv[0] in ("spend", "next"):
        key, rest = (argv[0], None), argv[1:]
    elif len(argv) >= 2 and (argv[0], argv[1]) in PROGRAM_SPEC:
        key, rest = (argv[0], argv[1]), argv[2:]
    elif len(argv) >= 2 and (argv[0], argv[1]) in SPEC:
        key, rest = (argv[0], argv[1]), argv[2:]
    else:
        raise Fail(EXIT_USAGE, USAGE)
    values, bools = (PROGRAM_SPEC if key in PROGRAM_SPEC else SPEC)[key]
    a, i = {}, 0
    if key in PROGRAM_SPEC:
        if not rest or rest[0].startswith("--"):
            raise Fail(EXIT_USAGE, "%s needs the program file path" % " ".join(
                x for x in key if x))
        a["program"], rest = rest[0], rest[1:]
    while i < len(rest):
        tok = rest[i]
        name = tok[2:] if tok.startswith("--") else ""
        if name in bools:
            a[name] = True
            i += 1
        elif name in values:
            if i + 1 >= len(rest):
                raise Fail(EXIT_USAGE, "%s needs a value" % tok)
            a[name] = rest[i + 1]
            i += 2
        else:
            raise Fail(EXIT_USAGE, "unexpected argument %r" % tok)
    return key[0], key[1], a


DISPATCH = {"hold": cmd_hold, "lock": cmd_lock, "program": cmd_program, "board": cmd_board,
            "spend": cmd_spend, "next": cmd_next}


def main(argv):
    try:
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except AttributeError:
            pass
        group, sub, a = parse(argv)
        return DISPATCH[group](sub, a)
    except Fail as e:
        sys.stderr.write("stu-fleet: %s\n" % e.msg)
        return e.code
    except Exception as e:  # fail closed: a gate reads a nonzero exit as a refusal
        sys.stderr.write("stu-fleet: %s: %s\n" % (type(e).__name__, e))
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
