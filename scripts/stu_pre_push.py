#!/usr/bin/env python3
"""The publish guard's enforcement point: a git pre-push hook.

Git hands a pre-push hook the exact refs and shas being pushed, so no command text is
parsed, a push from a script or a make target is seen, and any nonzero exit stops the
push (it fails closed by construction).

  stu-pre-push --install [--path P]   write the hook into P's hooks directory (git's
                                      `--git-path hooks`: honours core.hooksPath, shared by
                                      every worktree), chaining an existing pre-push
  stu-pre-push --check [--path P]     print INSTALLED or MISSING; exit 0 / 1
  stu-pre-push REMOTE URL             the hook itself: ref lines on stdin

Rule (strict rows only; any other row exits 0 at once):
  before-push row: the tip commit of every pushed ref (for a tag, the commit it peels to)
  must be in RUN_HOME/approvals.tsv, else the push is refused, naming the sha and the
  `! stu-approve` line the owner types. Deleting a ref is always allowed.
  public row: the pushed range's commit messages and added lines, the ref name and an
  annotated tag's message are scanned for the names of the family's private rows (their
  slugs, distinctive paths, issue references); a hit refuses the push, naming the item
  and where it was found.
Exit 1 with a reason on refusal and on any internal error. A repo with no stu config is
the one case that exits 0 without a decision.
"""
import os
import re
import shlex
import stat
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import push_policy  # noqa: E402
import stu_env  # noqa: E402

ROOT = os.path.dirname(HERE)
MARKER = "# stu-pre-push: managed hook"


def say(msg):
    sys.stderr.write("stu-pre-push: %s\n" % msg)


# ---- the hook ---------------------------------------------------------------------------

def approve_line(sha):
    return '! "%s" <id> %s' % (os.path.join(ROOT, "bin", "stu-approve"), sha)


def peel(sha):
    """The commit SHA names (a tag object peels to the commit it points at)."""
    rc, out = push_policy.git(os.getcwd(), "rev-parse", "--verify", "--quiet",
                              sha + "^{commit}")
    if rc != 0 or not push_policy.FULL_SHA.fullmatch(out):
        raise RuntimeError("cannot resolve %s to a commit" % sha)
    return out


def git_out(*args):
    rc, out = push_policy.git(os.getcwd(), *args)
    return rc, out


def pushed_range(remote, row, lsha, rsha):
    """-> the rev arguments selecting the commits this ref update publishes."""
    if set(rsha) != {"0"}:
        if git_out("cat-file", "-e", rsha + "^{commit}")[0] == 0:
            return [rsha + ".." + lsha]
    else:
        base = "%s/%s" % (remote, row["BASE"])
        if git_out("rev-parse", "--verify", "--quiet", base + "^{commit}")[0] == 0:
            return [base + ".." + lsha]
    # The base is not known locally. Two cases land here: a new ref whose <remote>/<base> does
    # not resolve (a URL remote, or no tracking ref), and an update whose old remote SHA is
    # not a local commit. Scanning rather than refusing is deliberate: refusing would block
    # every such push, while this still checks the new work. It scans every commit reachable
    # from the pushed SHA that no remote-tracking ref holds, the whole history when there are
    # none. Residual: a commit held only by another remote's tracking ref is not scanned.
    return [lsha, "--not", "--remotes"]


def added_text(revs):
    """-> (commit messages text, {path: added lines text}) of the commits REVS selects."""
    rc, out = push_policy.git(os.getcwd(), "-c", "core.quotepath=false", "log", "-p", "-U0",
                              "--no-color", "--no-ext-diff", "--format=%x01%B%x02", *revs)
    if rc != 0:
        raise RuntimeError("cannot read the pushed commits")
    return parse_log(out)


def parse_log(out):
    messages, files, path, in_msg, header = [], {}, None, False, False
    for ln in out.split("\n"):
        if ln.startswith("\x01"):
            in_msg, path, header = True, None, False
            ln = ln[1:]
        if in_msg:
            if "\x02" in ln:
                ln, in_msg = ln.split("\x02", 1)[0], False
                messages.append(ln)
            else:
                messages.append(ln)
            continue
        if ln.startswith("diff --git "):
            header, path = True, None
        elif ln.startswith("@@"):
            header = False
        elif header:
            if ln.startswith("+++ "):
                tgt = ln[4:]
                path = tgt[2:] if tgt.startswith("b/") else None
        elif ln.startswith("+") and path:
            files.setdefault(path, []).append(ln[1:])
    return "\n".join(messages), {p: "\n".join(v) for p, v in files.items()}


def tag_message(lsha):
    if git_out("cat-file", "-t", lsha)[1] != "tag":
        return ""
    rc, out = git_out("cat-file", "tag", lsha)
    return out.split("\n\n", 1)[1] if rc == 0 and "\n\n" in out else ""


def _keep_issue_ref(token, slug):
    """A token naming the slug is dropped, except an issue reference on it: that stays a leak."""
    m = re.search(re.escape(slug) + r"#\d+", token, flags=re.IGNORECASE)
    return " " + m.group(0) + " " if m else " "


def strip_pin_text(text, slugs):
    """A pin file may name the private repo: drop its clone URLs and pinned shas."""
    for s in slugs:
        text = re.sub(r"\S*%s\S*" % re.escape(s), lambda m, s=s: _keep_issue_ref(m.group(0), s),
                      text, flags=re.IGNORECASE)
    return re.sub(r"\b[0-9a-f]{40}(?:[0-9a-f]{24})?\b", " ", text, flags=re.IGNORECASE)


def leak_refusals(row, remote, lref, lsha, rref, rsha, ctx):
    """-> refusal messages for private names in what this ref update would publish."""
    items, regexes, slugs, deadline = ctx
    pins = {p.strip() for p in row["PIN_FILES"].split(",") if p.strip()}
    pin_items = [i for i in items if i not in slugs]
    msg, files = added_text(pushed_range(remote, row, lsha, rsha))
    texts = [("a commit message", msg, items, regexes),
             ("the ref name", rref, items, regexes),
             ("the tag message", tag_message(lsha), items, regexes)]
    plain = {p: t for p, t in files.items() if p not in pins}
    for p, t in sorted(files.items()):
        if p in pins:
            texts.append(("an added line of " + p, strip_pin_text(t, slugs), pin_items,
                          regexes))
    if plain:
        texts.append(("an added line", "\n".join(plain.values()), items, regexes))
    out = []
    for where, text, its, rxs in texts:
        if not text:
            continue
        for hit in push_policy.scan(text, its, rxs, deadline=deadline):
            here = where
            if where == "an added line":  # name the file, not the line
                in_files = sorted(p for p, t in plain.items()
                                  if hit == push_policy.SCAN_BUDGET_HIT
                                  or push_policy.scan(t, [hit], rxs, deadline=deadline))
                here = "an added line of " + ", ".join(in_files[:3])
            out.append("%s -> %s: %s names the private-repo item '%s' (public repos must "
                       "not carry it); reword it and push again" % (lref, rref, here, hit))
    return out


def agent_push():
    """True when the pusher is a Claude Code process (CLAUDECODE set and non-empty). The
    before-push approval rule gates agents only; an unmarked push is the human's."""
    return bool(os.environ.get("CLAUDECODE"))


def enforce(row, lines, remote=""):
    """-> a list of refusal messages (empty: allowed). Raises on anything unexpected."""
    refusals = []
    agent = agent_push()
    skipped = False
    public = row["VISIBILITY"] == "public"
    ctx = None
    before_push = "before-push" in [c.strip().lower() for c in
                                    row["HUMAN_CHECKPOINTS"].split(",")]
    for line in lines:
        parts = line.split()
        if len(parts) != 4:
            raise ValueError("malformed ref line from git: %r" % line)
        lref, lsha, rref, rsha = parts
        if not push_policy.FULL_SHA.fullmatch(lsha) and set(lsha) != {"0"}:
            raise ValueError("malformed sha from git: %r" % lsha)
        if set(lsha) == {"0"}:  # a deletion publishes nothing
            continue
        if before_push:
            tip = peel(lsha)
            if not agent:
                # A human push is never refused on approval; note the skip only when the
                # check would have refused (an unreadable record counts as unapproved).
                try:
                    skipped = skipped or not push_policy.approved(row["RUN_HOME"], tip)
                except OSError:
                    skipped = True
            elif not push_policy.approved(row["RUN_HOME"], tip):
                refusals.append(
                    "%s -> %s: tip %s is not approved (human_checkpoints: before-push). "
                    "The owner approves a commit by typing:  %s"
                    % (lref, rref, tip, approve_line(tip)))
        if public:
            if ctx is None:
                ctx = scan_context(row)
            refusals.extend(leak_refusals(row, remote, lref, lsha, rref, rsha, ctx))
    if skipped and not refusals:
        say("the before-push approval check applies to Claude Code pushes only and was "
            "skipped for this push")
    return refusals


def scan_context(row):
    fam = push_policy.family_of(row["CONFIG_PATH"])
    if fam is None:
        return ([], [], [], time.monotonic() + push_policy.SCAN_BUDGET)
    return (push_policy.private_list(fam, row), push_policy.private_regexes(fam, row),
            set(push_policy.private_slugs(fam, row)),
            time.monotonic() + push_policy.SCAN_BUDGET)


def hook(args):
    push_policy.scrub_environ()
    try:
        try:
            row = stu_env.resolve(cwd=os.getcwd(), forge_lookup=False)
        except stu_env.NoConfig:
            return 0  # no stu config: not a strict row, nothing to enforce
        if not push_policy.strict(row):
            return 0
        refusals = enforce(row, [x for x in sys.stdin.read().splitlines() if x.strip()],
                           args[0] if args else "")
    except (stu_env.ConfigError, stu_env.NotInRepo, stu_env.UsageError) as e:
        say("push refused: the stu config for this repo cannot be resolved (%s); fix it "
            "and push again" % e)
        return 1
    except BaseException as e:  # noqa: BLE001  fail closed on anything, SystemExit included
        say("push refused: internal error: %s: %s" % (type(e).__name__, e))
        return 1
    for r in refusals:
        say("push refused: " + r)
    return 1 if refusals else 0


# ---- install / check --------------------------------------------------------------------

def hooks_dir(path):
    rc, out = push_policy.git(path, "rev-parse", "--git-path", "hooks")
    if rc != 0 or not out:
        raise RuntimeError("%s is not inside a git repository" % path)
    return os.path.normpath(os.path.join(path, out))


HOOK_TEXT = """#!/bin/sh
%s
# Written by `stu-pre-push --install`; rerun it to refresh. An older pre-push hook is kept
# as pre-push.local and runs first.
tmp=$(mktemp "${TMPDIR:-/tmp}/stu-pre-push.XXXXXX") || exit 1
cat > "$tmp" || { rm -f "$tmp"; exit 1; }
dir=$(dirname "$0")
if [ ! -x %s ]; then
  rm -f "$tmp"
  echo "stu-pre-push: the stu plugin moved; run: %s --install --path <this repo>" >&2
  exit 1
fi
if [ -x "$dir/pre-push.local" ]; then
  "$dir/pre-push.local" "$@" < "$tmp" || { rc=$?; rm -f "$tmp"; exit $rc; }
fi
%s "$@" < "$tmp"
rc=$?
rm -f "$tmp"
exit $rc
"""


def hook_text():
    q = shlex.quote(os.path.join(ROOT, "bin", "stu-pre-push"))
    return HOOK_TEXT % (MARKER, q, q, q)


def hook_target(text):
    """-> the stu-pre-push path the hook text runs, or "" when it cannot be read."""
    for ln in text.splitlines():
        if ln.endswith('"$@" < "$tmp"') and not ln.startswith(('"$dir', ' ')):
            try:
                words = shlex.split(ln)
            except ValueError:
                return ""
            return words[0] if words else ""
    return ""


def read_hook(p):
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def install(path):
    d = hooks_dir(path)
    os.makedirs(d, exist_ok=True)
    target, local = os.path.join(d, "pre-push"), os.path.join(d, "pre-push.local")
    old = read_hook(target)
    if old is not None and MARKER not in old:
        if os.path.exists(local):
            raise RuntimeError("%s already has a pre-push and a pre-push.local; merge them "
                               "into pre-push.local first" % d)
        os.replace(target, local)
    with open(target, "w") as f:
        f.write(hook_text())
    os.chmod(target, os.stat(target).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print("installed: " + target)
    return 0


def check(path):
    try:
        target = os.path.join(hooks_dir(path), "pre-push")
    except RuntimeError:
        print("MISSING")
        return 1
    text = read_hook(target)
    ok = (text is not None and MARKER in text and os.access(target, os.X_OK)
          and os.path.isfile(os.path.join(ROOT, "bin", "stu-pre-push")))
    if ok:
        tgt = hook_target(text)
        if not (tgt and os.path.isfile(tgt) and os.access(tgt, os.X_OK)):
            say("the installed hook runs %s, which is gone; rerun: %s --install --path %s"
                % (tgt or "an unreadable path", os.path.join(ROOT, "bin", "stu-pre-push"),
                   path))
            ok = False
    print("INSTALLED" if ok else "MISSING")
    return 0 if ok else 1


def main(argv):
    args = argv[1:]
    if args and args[0] in ("--install", "--check"):
        path, rest = os.getcwd(), args[1:]
        if rest[:1] == ["--path"] and len(rest) == 2:
            path = os.path.abspath(rest[1])
        elif rest:
            say("usage: stu-pre-push --install|--check [--path P]")
            return 2
        try:
            return install(path) if args[0] == "--install" else check(path)
        except (RuntimeError, OSError) as e:
            say(str(e))
            return 1
    return hook(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
