#!/usr/bin/env python3
"""stu-fleet: the merge hold and the merge lock, one file under the run home.

  stu-fleet hold set --reason TEXT      set the hold; prints the lock holder to disarm
  stu-fleet hold clear                  clear the hold; re-arms nothing
  stu-fleet hold status                 exit 10 while the hold is set, else 0
  stu-fleet lock take --slug OWNER/REPO --pr N --sha SHA [--label NAME]
                                        take the lock in one locked step
  stu-fleet lock release --pr N [--slug OWNER/REPO] [--landed]
                                        release it (idempotent); --landed records a landing
  stu-fleet lock status                 the holder, if any

State: <RUN_HOME>/merge-hold.json (override: STU_FLEET_FILE), RUN_HOME from stu-env. Every
read-modify-write runs under an exclusive flock on a sibling `.lock` file and replaces the
state file atomically. An unreadable state file is an error (exit 3), never "no hold".

`lock take`, in one locked step: if the lock is held by another PR, the holder is checked on
the forge (`stu-forge pr-state`) and released when its PR is merged or closed, or when its
merge label is gone and the lock is older than a grace period (a gate takes the lock before it
labels, so a fresh lock with no label yet is not abandoned). The forge being unreachable is a
refusal, never an assumption. Then it refuses if the hold is set, then if another PR still
holds the lock; otherwise it records slug, PR, sha and time (re-entrant for the same slug+PR).

Exit codes: 0 ok; 2 usage; 3 error (state file, run home); 10 refused, hold set; 11 refused,
lock held; 12 refused, holder not checkable on the forge. A refusal prints one line that
begins `REFUSED ` followed by the reason text a gate returns (`fleet-hold: ...` or
`fleet-lock: ...`).
"""
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

EXIT_USAGE, EXIT_ERROR = 2, 3
EXIT_HOLD, EXIT_LOCKED, EXIT_FORGE = 10, 11, 12
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


def save(path, doc):
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(prefix=".merge-hold-", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


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
    """-> (state, labels) of one PR via stu-forge pr-state; raises Fail(EXIT_FORGE)."""
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
    return got["STATE"], labels


def holder_gone(lock):
    """Observe the lock holder. -> (gone?, why) where why is merged|closed|label-gone|None."""
    state, labels = forge_state(lock["slug"], lock["pr"])
    if state in ("merged", "closed"):
        return True, state
    label = lock.get("label") or ""
    if label and label not in labels:
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


def cmd_hold(sub, a):
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
        # status
        if doc["hold"] is None:
            print("HOLD none")
            return 0
        print("HOLD set %s (since %s)" % (doc["hold"]["reason"], doc["hold"].get("set_at", "?")))
        print(disarm_line(doc["lock"]))
        for e in doc["landed_during_hold"]:
            print("LANDED-DURING-HOLD %s#%s %s %s" % (e["slug"], e["pr"], e["sha"], e["at"]))
        return EXIT_HOLD


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


# ---- command line -----------------------------------------------------------------------

SPEC = {
    ("hold", "set"): (("reason",), ()),
    ("hold", "clear"): ((), ()),
    ("hold", "status"): ((), ()),
    ("lock", "take"): (("slug", "pr", "sha", "label"), ()),
    ("lock", "release"): (("pr", "slug"), ("landed",)),
    ("lock", "status"): ((), ()),
}


def parse(argv):
    if len(argv) < 2 or (argv[0], argv[1]) not in SPEC:
        raise Fail(EXIT_USAGE, "usage: stu-fleet hold set|clear|status | "
                               "lock take|release|status [flags]")
    values, bools = SPEC[(argv[0], argv[1])]
    a, i, rest = {}, 0, argv[2:]
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
    return argv[0], argv[1], a


def main(argv):
    try:
        group, sub, a = parse(argv)
        return cmd_hold(sub, a) if group == "hold" else cmd_lock(sub, a)
    except Fail as e:
        sys.stderr.write("stu-fleet: %s\n" % e.msg)
        return e.code
    except Exception as e:  # fail closed: a gate reads a nonzero exit as a refusal
        sys.stderr.write("stu-fleet: %s: %s\n" % (type(e).__name__, e))
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
