#!/usr/bin/env python3
"""A `gh` test double, shared by the suites that need a forge.

Install it on PATH as `gh` (a symlink in a temp bin/ directory). Behaviour comes from
the environment:

  FAKE_GH_FIXTURES  path to a JSON file: {"<argv prefix>": <response or [responses]>}
  FAKE_GH_STATE     path to a scratch file holding the per-key position of a response list
  FAKE_GH_LOG       if set, every argv line is appended to this file
  FAKE_GH_ENV_LOG   if set, one `GH_HOST=<v|-> GH_REPO=<v|->` line per call is appended
                    here (same order as FAKE_GH_LOG), so a test can see the environment

A response is {"rc": int, "json": <raw API/CLI JSON>, "stderr": str} or
{"rc": int, "stdout": str, "stderr": str}. A list of responses is served in order and
the last one repeats. With "json", the double applies the caller's --jq / -q program
(through the real `jq`, printing raw strings as gh does) or --json field selection, so the
code under test does its own parsing. --paginate treats "json" as a list of pages and
emits each page's result.

The key is matched against the positional words of argv (flags and their values
stripped), longest prefix wins. Nothing matched: exit 1 with `fake_gh: unmatched: ...`.

A key may end in ` @<field>` (e.g. `pr view 7 @mergeable`): it then matches only a call whose
--json field list contains that field, and beats the same key without the suffix, so two
reads of one PR can keep separate response lists.
"""
import json
import os
import subprocess
import sys

VALUE_FLAGS = {"--json", "--jq", "-q", "-R", "--repo", "-f", "-F", "--field",
               "--raw-field", "-H", "--header", "--method", "-X", "--template", "-t",
               "-L", "--limit", "--hostname", "--input", "-b", "--body", "-t", "--title",
               "--base", "--head", "--label", "-l", "--add-label", "--remove-label",
               "--branch", "--workflow", "--event", "--commit", "--match-head-commit"}


def split_argv(argv):
    words, flags, i = [], {}, 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--") and "=" in a:
            k, _, v = a.partition("=")
            flags[k] = v
        elif a in VALUE_FLAGS:
            flags[a] = argv[i + 1] if i + 1 < len(argv) else ""
            i += 1
        elif a.startswith("-") and len(a) > 1:
            flags[a] = True
        else:
            words.append(a)
        i += 1
    return words, flags


def pick(fixtures, words, flags=None):
    best, best_score = None, None
    fields = str((flags or {}).get("--json") or "").split(",")
    for key in fixtures:
        head, _, cons = key.partition(" @")
        kw = head.split()
        if words[:len(kw)] != kw or (cons and cons not in fields):
            continue
        score = (len(kw), 1 if cons else 0)
        if best is None or score > best_score:
            best, best_score = key, score
    return best


def next_response(key, value):
    if not isinstance(value, list):
        return value
    state_path = os.environ.get("FAKE_GH_STATE")
    state = {}
    if state_path and os.path.exists(state_path):
        try:
            with open(state_path) as f:
                state = json.load(f)
        except ValueError:
            state = {}
    pos = state.get(key, 0)
    resp = value[min(pos, len(value) - 1)]
    state[key] = pos + 1
    if state_path:
        with open(state_path, "w") as f:
            json.dump(state, f)
    return resp


def jq(program, doc):
    p = subprocess.run(["jq", "-r", program], input=json.dumps(doc), capture_output=True,
                       text=True)
    if p.returncode != 0:
        sys.stderr.write(p.stderr)
        sys.exit(p.returncode)
    return p.stdout


def render(doc, flags):
    prog = flags.get("--jq") or flags.get("-q")
    if prog:
        return jq(prog, doc)
    fields = flags.get("--json")
    if fields:
        names = [n for n in fields.split(",") if n]

        def pick_fields(o):
            return {n: o.get(n) for n in names} if isinstance(o, dict) else o
        sel = [pick_fields(o) for o in doc] if isinstance(doc, list) else pick_fields(doc)
        return json.dumps(sel, separators=(",", ":")) + "\n"
    return json.dumps(doc, separators=(",", ":")) + "\n"


def main(argv):
    log = os.environ.get("FAKE_GH_LOG")
    if log:
        with open(log, "a") as f:
            f.write(" ".join(argv) + "\n")
    env_log = os.environ.get("FAKE_GH_ENV_LOG")
    if env_log:
        with open(env_log, "a") as f:
            f.write("GH_HOST=%s GH_REPO=%s\n" % (os.environ.get("GH_HOST", "-"),
                                                  os.environ.get("GH_REPO", "-")))
    path = os.environ.get("FAKE_GH_FIXTURES")
    fixtures = {}
    if path and os.path.exists(path):
        with open(path) as f:
            fixtures = json.load(f)
    words, flags = split_argv(argv)
    key = pick(fixtures, words, flags)
    if key is None:
        sys.stderr.write("fake_gh: unmatched: %s\n" % " ".join(argv))
        return 1
    resp = next_response(key, fixtures[key])
    if resp.get("stderr"):
        sys.stderr.write(resp["stderr"] if resp["stderr"].endswith("\n")
                         else resp["stderr"] + "\n")
    if "json" in resp:
        doc = resp["json"]
        pages = doc if (flags.get("--paginate") and isinstance(doc, list)) else [doc]
        for page in pages:
            sys.stdout.write(render(page, flags))
    elif "stdout" in resp:
        sys.stdout.write(resp["stdout"])
    return int(resp.get("rc", 0))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
