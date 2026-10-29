#!/usr/bin/env python3
"""Regression suite for stu_env.py (the run-time resolver). Temp git repos, HOME pointed at
a temp dir, and a fake `gh` first on PATH so nothing touches the network.

Run: python3 scripts/stu_env_test.py
"""
import contextlib
import json
import os
import shlex
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import stu_env  # noqa: E402

FAKE_GH = os.path.join(os.path.dirname(HERE), "tests", "fake_gh.py")
SCRIPT = os.path.join(HERE, "stu_env.py")
FAILURES = []
COUNT = [0]


def check(name, got, want):
    COUNT[0] += 1
    if got != want:
        FAILURES.append("%s: got %r, want %r" % (name, got, want))


def rp(p):
    return os.path.realpath(p)


def sh(cwd, *cmd):
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, text=True)


def make_repo(parent, name="alpha"):
    path = os.path.join(parent, name)
    os.makedirs(path)
    sh(path, "git", "init", "-q")
    sh(path, "git", "-c", "user.name=T", "-c", "user.email=t@e", "commit", "-q",
       "--allow-empty", "-m", "init")
    return rp(path)


def fake_gh(parent, repo=None):
    """A fake `gh` that prints REPO (or exits 1 when REPO is None). Returns its dir."""
    d = os.path.join(parent, "fakebin")
    os.makedirs(d, exist_ok=True)
    body = "echo %s\n" % repo if repo else "echo 'no remote' >&2\nexit 1\n"
    p = os.path.join(d, "gh")
    with open(p, "w") as f:
        f.write("#!/bin/sh\n" + body)
    os.chmod(p, 0o755)
    return d


def env_for(home, ghdir, **extra):
    e = dict(os.environ)
    for k in ("STU_CONFIG",):
        e.pop(k, None)
    e["HOME"] = home
    e["GIT_CONFIG_GLOBAL"] = os.path.join(home, ".gitconfig")
    e["PATH"] = ghdir + os.pathsep + e["PATH"]
    e.update(extra)
    return e


def run(cwd, env, *args):
    p = subprocess.run([sys.executable, SCRIPT] + list(args), cwd=cwd, env=env,
                       capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def parse(out):
    d = {}
    for line in out.splitlines():
        k, _, v = line.partition("=")
        d[k] = " ".join(shlex.split(v)) if v else ""
    return d


def setup(tmp, gh="octo/alpha", name="alpha"):
    home = os.path.join(tmp, "home")
    os.makedirs(home)
    home = rp(home)
    parent = os.path.join(tmp, "p")
    os.makedirs(parent)
    repo = make_repo(parent, name)
    return home, repo, fake_gh(tmp, gh)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def test_defaults_from_main_checkout():
    with tempfile.TemporaryDirectory() as tmp:
        home, repo, gh = setup(tmp)
        rc, out, err = run(repo, env_for(home, gh), "--defaults")
        v = parse(out)
        check("defaults exit 0", rc, 0)
        check("PROJECT", v["PROJECT"], "octo-alpha")
        check("GITHUB_REPO", v["GITHUB_REPO"], "octo/alpha")
        check("RUN_HOME", v["RUN_HOME"], os.path.join(home, ".stu", "octo-alpha"))
        check("WORKTREES_DIR", v["WORKTREES_DIR"], repo + "-worktrees")
        check("MAIN_CHECKOUT", v["MAIN_CHECKOUT"], repo)
        check("REPO_ROOT", v["REPO_ROOT"], repo)
        check("CONFIG_PATH empty", v["CONFIG_PATH"], "")
        check("PROJECT_GUIDE fallback", v["PROJECT_GUIDE"], "AGENTS.md")
        write(os.path.join(repo, "CLAUDE.md"), "x")
        rc, out, err = run(repo, env_for(home, gh), "--defaults")
        check("PROJECT_GUIDE CLAUDE.md", parse(out)["PROJECT_GUIDE"], "CLAUDE.md")
        rc, out, err = run(repo, env_for(home, gh), "--defaults", "--json")
        check("json PROJECT", json.loads(out)["PROJECT"], "octo-alpha")


def test_resolves_main_checkout_from_worktree():
    with tempfile.TemporaryDirectory() as tmp:
        home, repo, gh = setup(tmp)
        wt = os.path.join(tmp, "wt")
        sh(repo, "git", "worktree", "add", "-q", wt, "-b", "feat")
        rc, out, err = run(wt, env_for(home, gh), "--defaults")
        v = parse(out)
        check("MAIN_CHECKOUT from worktree", v["MAIN_CHECKOUT"], repo)
        check("REPO_ROOT is worktree", v["REPO_ROOT"], rp(wt))


def test_no_github_remote():
    with tempfile.TemporaryDirectory() as tmp:
        home, repo, gh = setup(tmp, gh=None)
        rc, out, err = run(repo, env_for(home, gh), "--defaults")
        v = parse(out)
        check("exit 0", rc, 0)
        check("GITHUB_REPO empty", v["GITHUB_REPO"], "")
        check("warning", "GITHUB_REPO unresolved" in err, True)
        import re
        check("fallback slug", bool(re.fullmatch(r"alpha-[0-9a-f]{6}", v["PROJECT"])), True)


def test_same_dirname_distinct_slugs():
    with tempfile.TemporaryDirectory() as tmp:
        home, r1, gh = setup(tmp, gh=None)
        p2 = os.path.join(tmp, "other")
        os.makedirs(p2)
        r2 = make_repo(p2, "alpha")
        a = parse(run(r1, env_for(home, gh), "--defaults")[1])["PROJECT"]
        b = parse(run(r2, env_for(home, gh), "--defaults")[1])["PROJECT"]
        check("distinct", a != b, True)


def test_missing_config_exits_2():
    with tempfile.TemporaryDirectory() as tmp:
        home, repo, gh = setup(tmp)
        rc, out, err = run(repo, env_for(home, gh))
        check("exit 2", rc, 2)
        check("message", "stu: no config for this repo — run /stu:init" in err, True)
        rc, out, err = run(repo, env_for(home, gh), "section", "x")
        check("section needs config", rc, 2)


def test_defaults_flag_needs_no_config():
    with tempfile.TemporaryDirectory() as tmp:
        home, repo, gh = setup(tmp)
        rc, out, err = run(repo, env_for(home, gh), "--defaults")
        check("exit 0", rc, 0)


def test_lookup_order():
    with tempfile.TemporaryDirectory() as tmp:
        home, repo, gh = setup(tmp)
        env = env_for(home, gh)
        home_cfg = os.path.join(home, ".stu", "octo-alpha", "stu.md")
        write(home_cfg, "---\nowner: home\n---\n")
        v = parse(run(repo, env)[1])
        check("home config used", (v["OWNER"], v["CONFIG_PATH"]), ("home", home_cfg))
        repo_cfg = os.path.join(repo, ".claude", "stu.md")
        write(repo_cfg, "---\nowner: repo\n---\n")
        v = parse(run(repo, env)[1])
        check("repo config beats home", (v["OWNER"], v["CONFIG_PATH"]), ("repo", repo_cfg))
        env_cfg = os.path.join(tmp, "env.md")
        write(env_cfg, "---\nowner: env\n---\n")
        v = parse(run(repo, env_for(home, gh, STU_CONFIG=env_cfg))[1])
        check("STU_CONFIG beats repo", (v["OWNER"], v["CONFIG_PATH"]), ("env", rp(env_cfg)))


def test_frontmatter_overrides():
    with tempfile.TemporaryDirectory() as tmp:
        home, repo, gh = setup(tmp)
        write(os.path.join(repo, ".claude", "stu.md"),
              "---\nrun_home: ~/x\nproject: custom\nguide: DOCS.md\n"
              "worktrees_dir: ~/wts\ngithub_repo: a/b\nci_wait_cmd: make ci\n"
              "ci_Some_Thing: 'quoted val'\n# comment\n---\nbody\n")
        v = parse(run(repo, env_for(home, gh))[1])
        check("run_home expanded", v["RUN_HOME"], os.path.join(home, "x"))
        check("project", v["PROJECT"], "custom")
        check("guide", v["PROJECT_GUIDE"], "DOCS.md")
        check("worktrees", v["WORKTREES_DIR"], os.path.join(home, "wts"))
        check("github_repo", v["GITHUB_REPO"], "a/b")
        check("ci passthrough", v["CI_WAIT_CMD"], "make ci")
        check("ci uppercased, unquoted", v["CI_SOME_THING"], "quoted val")


def test_section_body():
    with tempfile.TemporaryDirectory() as tmp:
        home, repo, gh = setup(tmp)
        write(os.path.join(repo, ".claude", "stu.md"),
              "---\nowner: o\n---\n\n## alpha\n\nline1\n```\n## not-a-heading\n```\n\n"
              "## blank\n\n   \n## beta\nb\n")
        env = env_for(home, gh)
        rc, out, err = run(repo, env, "section", "alpha")
        check("body", (rc, out), (0, "line1\n```\n## not-a-heading\n```\n"))
        rc, out, err = run(repo, env, "section", "missing")
        check("absent", (rc, out), (0, ""))
        rc, out, err = run(repo, env, "section", "blank")
        check("blank", (rc, out), (0, ""))
        rc, out, err = run(repo, env, "section", "beta")
        check("last", out, "b\n")


def eval_ci(repo, home, gh, frontmatter, var="CI_X"):
    write(os.path.join(repo, ".claude", "stu.md"), frontmatter)
    p = subprocess.run(["sh", "-c", 'eval "$(%s %s)"; printf %%s "$%s"' % (
        sys.executable, SCRIPT, var)], cwd=repo, env=env_for(home, gh),
        capture_output=True, text=True)
    return p.stdout, p.stderr


def test_shell_safety():
    with tempfile.TemporaryDirectory() as tmp:
        home, repo, gh = setup(tmp)
        marker = os.path.join(tmp, "pwned")
        out, err = eval_ci(repo, home, gh,
                           "---\nci_x;touch %s: v\nci_x: ok\n---\n" % marker)
        check("malicious key not executed", os.path.exists(marker), False)
        check("malicious key warned", "invalid config key" in err, True)
        check("good key survives", out, "ok")
        val = "a b 'single' \"double\" $HOME `x`"
        out, err = eval_ci(repo, home, gh, "---\nci_x: %s\n---\n" % val)
        check("value round-trips", out, val)


def test_offline_origin_and_home_lookup():
    with tempfile.TemporaryDirectory() as tmp:
        home, repo, gh = setup(tmp, gh=None)
        sh(repo, "git", "remote", "add", "origin", "git@github.com:octo/alpha.git")
        cfg = os.path.join(home, ".stu", "octo-alpha", "stu.md")
        write(cfg, "---\nowner: h\n---\n")
        rc, out, err = run(repo, env_for(home, gh))
        v = parse(out)
        check("ssh origin", (rc, v["PROJECT"], v["CONFIG_PATH"]), (0, "octo-alpha", rp(cfg)))
        check("no gh warning when origin known", "unresolved" in err, False)
        sh(repo, "git", "remote", "set-url", "origin", "https://github.com/octo/alpha")
        check("https origin", parse(run(repo, env_for(home, gh), "--defaults")[1])["GITHUB_REPO"],
              "octo/alpha")


def test_home_lookup_hash_slug_fallback():
    with tempfile.TemporaryDirectory() as tmp:
        home, repo, gh = setup(tmp, gh="octo/alpha")
        slug = parse(run(repo, env_for(home, fake_gh(tmp + "/x", None)), "--defaults")[1])["PROJECT"]
        cfg = os.path.join(home, ".stu", slug, "stu.md")
        write(cfg, "---\nowner: h\n---\n")
        rc, out, err = run(repo, env_for(home, gh))
        check("hash-slug config found when gh resolves", (rc, parse(out)["CONFIG_PATH"]), (0, rp(cfg)))


def test_stu_config_missing():
    with tempfile.TemporaryDirectory() as tmp:
        home, repo, gh = setup(tmp)
        missing = os.path.join(tmp, "nope.md")
        write(os.path.join(repo, ".claude", "stu.md"), "---\nowner: r\n---\n")
        rc, out, err = run(repo, env_for(home, gh, STU_CONFIG=missing))
        check("exit 2", rc, 2)
        check("message", "stu: STU_CONFIG not found: %s" % missing in err, True)


def test_bom_unclosed_and_exact_section():
    with tempfile.TemporaryDirectory() as tmp:
        home, repo, gh = setup(tmp)
        cfg = os.path.join(repo, ".claude", "stu.md")
        with open(cfg, "wb") if os.makedirs(os.path.dirname(cfg), exist_ok=True) is None else None as f:
            f.write(b"\xef\xbb\xbf---\nowner: bom\n---\n## repo-map\nM\n## repo\nR\n")
        env = env_for(home, gh)
        check("BOM frontmatter", parse(run(repo, env)[1])["OWNER"], "bom")
        check("section exact", run(repo, env, "section", "repo")[1], "R\n")
        write(cfg, "---\nowner: partial\nci_a: 1\n")
        v = parse(run(repo, env)[1])
        check("unclosed: no partial keys", (v["OWNER"] != "partial", "CI_A" in v), (True, False))


def test_section_comments_and_triage_extra():
    """The template's per-section HTML-comment questions never count as an answer, and
    `triage_extra` (read by /stu:fix-campaign) is exported as TRIAGE_EXTRA."""
    with tempfile.TemporaryDirectory() as tmp:
        home, repo, gh = setup(tmp)
        write(os.path.join(repo, ".claude", "stu.md"),
              "---\ntriage_extra: \"-label:wontfix\"\n---\n"
              "## unanswered\n<!--\nQuestion?\n## not-a-heading\n-->\n\n"
              "## answered\n<!-- Q? -->\nA1\n<!-- inline --> A2\n"
              "## fenced\n```\n<!-- kept -->\n```\n")
        env = env_for(home, gh)
        check("comment-only section is empty", run(repo, env, "section", "unanswered"), (0, "", ""))
        check("comments stripped from answer", run(repo, env, "section", "answered")[1], "A1\n A2\n")
        check("comment inside fence kept", run(repo, env, "section", "fenced")[1],
              "```\n<!-- kept -->\n```\n")
        check("TRIAGE_EXTRA", parse(run(repo, env)[1]).get("TRIAGE_EXTRA"), "-label:wontfix")
        write(os.path.join(repo, ".claude", "stu.md"), "---\nowner: o\n---\n")
        check("TRIAGE_EXTRA default empty", parse(run(repo, env)[1]).get("TRIAGE_EXTRA"), "")



# ---- v3: families, rows, structured sections --------------------------------------------

def fgh(tmp, fixtures=None):
    """Install tests/fake_gh.py as `gh`. -> (bin dir, extra env incl. the call log path)."""
    d = os.path.join(tmp, "ghbin")
    os.makedirs(d, exist_ok=True)
    link = os.path.join(d, "gh")
    if not os.path.exists(link):
        os.symlink(FAKE_GH, link)
    fx = os.path.join(tmp, "fixtures.json")
    with open(fx, "w") as f:
        json.dump(fixtures or {}, f)
    log = os.path.join(tmp, "gh.log")
    if os.path.exists(log):
        os.remove(log)
    return d, {"FAKE_GH_FIXTURES": fx, "FAKE_GH_LOG": log,
               "FAKE_GH_STATE": os.path.join(tmp, "gh.state")}


def gh_calls(extra):
    try:
        with open(extra["FAKE_GH_LOG"]) as f:
            return f.read().splitlines()
    except OSError:
        return []


@contextlib.contextmanager
def inproc(env, cwd=None):
    old_env, old_cwd = dict(os.environ), os.getcwd()
    os.environ.clear()
    os.environ.update(env)
    if cwd:
        os.chdir(cwd)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(old_env)
        os.chdir(old_cwd)


def fam_text(app, lib, app_over=None, lib_over=None, fm="", body=None, lib_section=True):
    """A two-row family config. *_over: key -> value (None drops the key)."""
    def block(name, path, base):
        d = dict(base)
        d["path"] = path
        d.update(over(name))
        lines = ["### " + name] + ["%s: %s" % (k, v) for k, v in d.items() if v is not None]
        return "\n".join(lines)

    def over(name):
        return (app_over if name == "app" else lib_over) or {}

    app_base = {"slug": "acme/app", "remote": "origin", "base": "main",
                "visibility": "public", "mode": "work", "merge_mode": "direct",
                "ci": "aggregator"}
    lib_base = {"slug": "acme/lib", "remote": "origin", "base": "main",
                "visibility": "private", "mode": "work", "merge_mode": "report-only",
                "ci": "none"}
    text = "---\nowner: o\n%s---\n\n## repos\n%s\n%s\n\n## verification-commands\n```\nmake test\n```\n" % (
        fm, block("app", app, app_base), block("lib", lib, lib_base))
    if lib_section:
        text += "\n## verification-commands @lib\n```\n./check\n```\n"
    if body:
        text += "\n" + body
    return text


def fam_setup(tmp, **kw):
    """-> (home, app, lib, gh bin dir, fake extra env, config path)."""
    home = os.path.join(tmp, "home")
    os.makedirs(home)
    home = rp(home)
    parent = os.path.join(tmp, "x")
    os.makedirs(parent)
    app = make_repo(parent, "app")
    lib = make_repo(parent, "lib")
    ghdir, extra = fgh(tmp)
    cfg = os.path.join(home, ".stu", "fam", "stu.md")
    write(cfg, fam_text(app, lib, **kw))
    return home, app, lib, ghdir, extra, cfg


def test_flat_config_equivalence():
    with tempfile.TemporaryDirectory() as tmp:
        home, repo, gh = setup(tmp)
        write(os.path.join(repo, ".claude", "stu.md"),
              "---\nowner: me\nworktrees_dir: ~/w\nguide: G.md\nci_gate_check: build\n---\n")
        v = parse(run(repo, env_for(home, gh))[1])
        want = {"MAIN_CHECKOUT": repo, "REPO_ROOT": repo, "PROJECT": "octo-alpha",
                "OWNER": "me", "PROJECT_GUIDE": "G.md",
                "RUN_HOME": os.path.join(home, ".stu", "octo-alpha"),
                "WORKTREES_DIR": os.path.join(home, "w"), "GITHUB_REPO": "octo/alpha",
                "CONFIG_PATH": os.path.join(repo, ".claude", "stu.md"),
                "CI_GATE_CHECK": "build", "TRIAGE_EXTRA": "",
                "FAMILY_ROWS": "1", "IS_HOME": "1", "MERGE_MODE": "direct",
                "CI_KIND": "aggregator", "REPO_SLUG": "octo/alpha", "GH_REPO": "octo/alpha",
                "REPO_NAME": "octo-alpha", "REMOTE": "origin", "MODE": "work",
                "MERGE_METHOD": "squash", "GH_HOST": "github.com",
                "CI_SKIPPED_IS_SUCCESS": "false", "ISSUES_REPO": "octo/alpha"}
        for k, w in want.items():
            check("flat equivalence " + k, v.get(k), w)


def flat_mode_run(tmp, section_text, fm="owner: o\n"):
    home, repo, gh = setup(tmp)
    write(os.path.join(repo, ".claude", "stu.md"),
          "---\n%s---\n\n## merge-mode\n%s\n" % (fm, section_text))
    return run(repo, env_for(home, gh)), repo


def test_flat_merge_mode():
    with tempfile.TemporaryDirectory() as tmp:
        (rc, out, err), repo = flat_mode_run(tmp, "Mode: label-handoff. Label `go`.")
        check("Mode line", (rc, parse(out)["MERGE_MODE"], "warning" in err),
              (0, "label-handoff", False))
    with tempfile.TemporaryDirectory() as tmp:
        (rc, out, err), repo = flat_mode_run(
            tmp, "It is not direct; label-handoff, with a label.")
        check("two-word prose exit 3", rc, 3)
        cfg = os.path.join(repo, ".claude", "stu.md")
        check("prose error names file, section and fix",
              (cfg in err, "## merge-mode" in err, "Mode:" in err), (True, True, True))
    with tempfile.TemporaryDirectory() as tmp:
        (rc, out, err), repo = flat_mode_run(tmp, "We use label-handoff here.")
        check("one-word prose", (rc, parse(out)["MERGE_MODE"]), (0, "label-handoff"))
        check("one-word prose warns",
              ("## merge-mode" in err, "Mode: label-handoff" in err), (True, True))
    with tempfile.TemporaryDirectory() as tmp:
        (rc, out, err), repo = flat_mode_run(tmp, "", fm="merge_mode: report-only\n")
        check("frontmatter merge_mode", (rc, parse(out)["MERGE_MODE"]), (0, "report-only"))
    with tempfile.TemporaryDirectory() as tmp:
        (rc, out, err), repo = flat_mode_run(tmp, "")
        check("empty section is direct", (rc, parse(out)["MERGE_MODE"]), (0, "direct"))
    with tempfile.TemporaryDirectory() as tmp:
        (rc, out, err), repo = flat_mode_run(tmp, "Mode: bogus")
        check("unknown Mode word", rc, 3)


def test_flat_frontmatter_row_keys():
    with tempfile.TemporaryDirectory() as tmp:
        home, repo, gh = setup(tmp)
        write(os.path.join(repo, ".claude", "stu.md"),
              "---\nci: none\nbase: trunk\nvisibility: public\nmerge_method: rebase\n"
              "required_checks: a\n---\n")
        v = parse(run(repo, env_for(home, gh))[1])
        check("flat row keys", (v["CI_KIND"], v["BASE"], v["BASE_SOURCE"], v["VISIBILITY"],
                                v["MERGE_METHOD"]),
              ("none", "trunk", "config", "public", "rebase"))
        write(os.path.join(repo, ".claude", "stu.md"), "---\nowner: o\n---\n")
        v = parse(run(repo, env_for(home, gh))[1])
        check("visibility unset, not private", v["VISIBILITY"], "unset")
        write(os.path.join(repo, ".claude", "stu.md"),
              "---\nci: list\nrequired_checks: build / unit, lint\n---\n")
        v = parse(run(repo, env_for(home, gh))[1])
        check("required_checks encoding", v["REQUIRED_CHECKS"], "build%20/%20unit,lint")
        write(os.path.join(repo, ".claude", "stu.md"), "---\nci: list\n---\n")
        check("ci list needs checks", run(repo, env_for(home, gh))[0], 3)


def test_family_resolution():
    with tempfile.TemporaryDirectory() as tmp:
        home, app, lib, gh, extra, cfg = fam_setup(tmp)
        env = env_for(home, gh, **extra)
        wt = os.path.join(tmp, "elsewhere", "wt")
        sh(lib, "git", "worktree", "add", "-q", wt, "-b", "feat")
        a = parse(run(app, env)[1])
        rc, out, err = run(wt, env)
        b = parse(out)
        check("sibling exit", rc, 0)
        check("sibling row", (b["REPO_NAME"], b["IS_HOME"], b["PROJECT"], b["FAMILY_ROWS"]),
              ("lib", "0", "fam", "2"))
        check("home row", (a["REPO_NAME"], a["IS_HOME"]), ("app", "1"))
        check("same RUN_HOME", a["RUN_HOME"], b["RUN_HOME"])
        check("RUN_HOME from project", a["RUN_HOME"], os.path.join(home, ".stu", "fam"))
        check("worktree outside worktrees dir", (b["MAIN_CHECKOUT"], b["REPO_ROOT"]),
              (lib, rp(wt)))
        check("lib row keys", (b["REPO_SLUG"], b["VISIBILITY"], b["MERGE_MODE"], b["CI_KIND"],
                               b["BASE"], b["BASE_SOURCE"]),
              ("acme/lib", "private", "report-only", "none", "main", "config"))
        # --repo from a plain directory with STU_CONFIG
        plain = os.path.join(tmp, "plain")
        os.makedirs(plain)
        rc, out, err = run(plain, env_for(home, gh, STU_CONFIG=cfg, **extra), "--repo", "lib")
        v = parse(out)
        check("--repo from non-git dir", (rc, v.get("MAIN_CHECKOUT"), v.get("REPO_ROOT")),
              (0, lib, lib))
        rc, out, err = run(plain, env, "--repo", "lib")
        check("--repo scan from non-git dir", (rc, parse(out).get("REPO_NAME")), (0, "lib"))
        # --repo from the other row's checkout
        rc, out, err = run(app, env, "--repo", "lib")
        v = parse(out)
        check("--repo other row", (rc, v["MAIN_CHECKOUT"], v["REPO_ROOT"], v["IS_HOME"]),
              (0, lib, lib, "0"))
        # section lookup keeps working
        rc, out, err = run(plain, env, "--repo", "nope")
        check("unknown row", rc, 3)
        # rows
        rc, out, err = run(app, env, "rows")
        check("rows", (rc, out.splitlines()), (0, [
            "app\t%s\tacme/app\tpublic\tHOME" % app, "lib\t%s\tacme/lib\tprivate\t-" % lib]))


def test_prefix_collision():
    with tempfile.TemporaryDirectory() as tmp:
        home = os.path.join(tmp, "home")
        os.makedirs(home)
        home = rp(home)
        parent = os.path.join(tmp, "x")
        os.makedirs(parent)
        app, docs, other = (make_repo(parent, n) for n in ("app", "app-docs", "app2"))
        ghdir, extra = fgh(tmp)
        cfg = os.path.join(home, ".stu", "fam", "stu.md")
        text = fam_text(app, docs, lib_over={"slug": "acme/app-docs"})
        write(cfg, text.replace("### lib", "### app-docs").replace("@lib", "@app-docs"))
        env = env_for(home, ghdir, **extra)
        check("prefix: app-docs", parse(run(docs, env)[1])["REPO_NAME"], "app-docs")
        rc, out, err = run(other, env_for(home, ghdir, STU_CONFIG=cfg, **extra))
        check("unlisted repo exits 3", (rc, "no repo row matches" in err), (3, True))
        check("unlisted repo without STU_CONFIG is just unconfigured", run(other, env)[0], 2)


def test_two_claims():
    with tempfile.TemporaryDirectory() as tmp:
        home, app, lib, gh, extra, cfg = fam_setup(tmp)
        env = env_for(home, gh, **extra)
        cfg2 = os.path.join(home, ".stu", "fam2", "stu.md")
        write(cfg2, fam_text(app, lib))
        rc, out, err = run(app, env)
        check("two families", (rc, rp(cfg) in err, rp(cfg2) in err), (3, True, True))
        os.remove(cfg2)
        os.rmdir(os.path.dirname(cfg2))
        local = os.path.join(app, ".claude", "stu.md")
        write(local, "---\nowner: r\n---\n")
        rc, out, err = run(app, env)
        check("family + repo-local", (rc, rp(cfg) in err, rp(local) in err), (3, True, True))
        # STU_CONFIG overrides the scan entirely
        rc, out, err = run(app, env_for(home, gh, STU_CONFIG=local, **extra))
        check("STU_CONFIG short-circuits", (rc, parse(out)["CONFIG_PATH"]), (0, rp(local)))
    with tempfile.TemporaryDirectory() as tmp:
        home, app, lib, gh, extra, cfg = fam_setup(tmp)
        env = env_for(home, gh, **extra)
        sh(app, "git", "remote", "add", "origin", "git@github.com:acme/app.git")
        flat = os.path.join(home, ".stu", "acme-app", "stu.md")
        write(flat, "---\nowner: f\n---\n")
        rc, out, err = run(app, env)
        check("flat project config + family", (rc, rp(cfg) in err, rp(flat) in err),
              (3, True, True))
    with tempfile.TemporaryDirectory() as tmp:
        home, repo, gh = setup(tmp)
        local = os.path.join(repo, ".claude", "stu.md")
        write(local, "---\nowner: repo\n---\n")
        write(os.path.join(home, ".stu", "octo-alpha", "stu.md"), "---\nowner: home\n---\n")
        rc, out, err = run(repo, env_for(home, gh))
        check("repo-local beats home flat", (rc, parse(out)["OWNER"], err), (0, "repo", ""))


def test_mandatory_and_structure():
    keys = ["slug", "remote", "base", "visibility", "mode", "merge_mode", "ci"]
    for key in keys + ["verification-commands"]:
        with tempfile.TemporaryDirectory() as tmp:
            kw = {"lib_section": False} if key == "verification-commands" else {
                "lib_over": {key: None}}
            home, app, lib, gh, extra, cfg = fam_setup(tmp, **kw)
            rc, out, err = run(app, env_for(home, gh, **extra), "--repo", "lib")
            check("mandatory %s" % key, (rc, key in err, rp(cfg) in err, "lib" in err),
                  (3, True, True, True))
    with tempfile.TemporaryDirectory() as tmp:
        home, app, lib, gh, extra, cfg = fam_setup(tmp, lib_over={"run_home": "~/x"})
        check("family-only key per repo", run(app, env_for(home, gh, **extra))[0], 3)
    with tempfile.TemporaryDirectory() as tmp:
        home, app, lib, gh, extra, cfg = fam_setup(
            tmp, body="## completion-mode @lib\nmerged\n")
        rc, out, err = run(app, env_for(home, gh, **extra))
        check("family-only section per repo", (rc, "completion-mode" in err), (3, True))
    with tempfile.TemporaryDirectory() as tmp:
        home, app, lib, gh, extra, cfg = fam_setup(tmp, body="## repo-map @nope\nx\n")
        check("section for unknown row", run(app, env_for(home, gh, **extra))[0], 3)
    for over, label in (({"mode": "pr-only", "merge_mode": "direct"}, "pr-only+direct"),
                        ({"tag_by": "stu"}, "tag_by on report-only"),
                        ({"mode": "pr-only", "merge_mode": None, "tag_by": "stu"},
                         "tag_by on pr-only"),
                        ({"merge_mode": "direct-push", "human_checkpoints": "before-push"},
                         "direct-push + before-push")):
        with tempfile.TemporaryDirectory() as tmp:
            home, app, lib, gh, extra, cfg = fam_setup(tmp, lib_over=over)
            rc, out, err = run(app, env_for(home, gh, **extra), "--repo", "lib")
            check("rejected: " + label, (rc, "lib" in err), (3, True))
    with tempfile.TemporaryDirectory() as tmp:
        home, app, lib, gh, extra, cfg = fam_setup(
            tmp, lib_over={"mode": "pr-only", "merge_mode": None})
        v = parse(run(app, env_for(home, gh, **extra), "--repo", "lib")[1])
        check("pr-only forces report-only", (v["MODE"], v["MERGE_MODE"]), ("pr-only", "report-only"))
    with tempfile.TemporaryDirectory() as tmp:
        home, app, lib, gh, extra, cfg = fam_setup(
            tmp, lib_over={"mode": "park", "required_checks": "x", "pin_files": "a, b",
                           "human_checkpoints": "before-push", "tag_format": "v{v}",
                           "initial_version": "1.4.0", "host": "ghe.acme.test"})
        v = parse(run(app, env_for(home, gh, **extra), "--repo", "lib")[1])
        check("lib extras", (v["MODE"], v["PIN_FILES"], v["HUMAN_CHECKPOINTS"], v["TAG_FORMAT"],
                             v["INITIAL_VERSION"], v["GH_HOST"], v["ISSUES_REPO"]),
              ("park", "a,b", "before-push", "v{v}", "1.4.0", "ghe.acme.test", "acme/lib"))


def test_sibling_isolation():
    with tempfile.TemporaryDirectory() as tmp:
        home, app, lib, gh, extra, cfg = fam_setup(
            tmp, body="## implementer-traps\nhome only text\n")
        env = env_for(home, gh, **extra)
        rc, out, err = run(app, env, "section", "implementer-traps", "--repo", "lib")
        check("sibling never reads home sections", (rc, out), (0, ""))
        rc, out, err = run(app, env, "section", "implementer-traps", "--repo", "app")
        check("home reads plain section", out, "home only text\n")
        rc, out, err = run(lib, env, "section", "implementer-traps")
        check("sibling from its own cwd", (rc, out), (0, ""))
        rc, out, err = run(lib, env, "section", "verification-commands")
        check("sibling reads its @ section", out, "```\n./check\n```\n")
    with tempfile.TemporaryDirectory() as tmp:
        home, app, lib, gh, extra, cfg = fam_setup(
            tmp, fm="ci_gate_check: build\nci_merge_label: go\nworktrees_dir: /w\n"
                    "triage_extra: -label:x\n")
        env = env_for(home, gh, **extra)
        v = parse(run(app, env, "--repo", "lib")[1])
        check("sibling has no home ci keys",
              ("CI_GATE_CHECK" in v, "CI_MERGE_LABEL" in v, v["TRIAGE_EXTRA"]),
              (False, False, ""))
        check("sibling worktrees dir", v["WORKTREES_DIR"], lib + "-worktrees")
        h = parse(run(app, env)[1])
        check("home keeps frontmatter ci keys",
              (h["CI_GATE_CHECK"], h["CI_MERGE_LABEL"], h["WORKTREES_DIR"], h["TRIAGE_EXTRA"]),
              ("build", "go", "/w", "-label:x"))
        write(cfg, fam_text(app, lib, fm="ci_gate_check: build\n",
                            lib_over={"ci_gate_check": "unit"}))
        v = parse(run(app, env, "--repo", "lib")[1])
        h = parse(run(app, env)[1])
        check("row-own ci key", (v["CI_GATE_CHECK"], h["CI_GATE_CHECK"]), ("unit", "build"))


def test_family_only_section_from_sibling():
    body = "## completion-mode\ncompletion: ready\n\n## stop-condition-2\nalways escalate\n"
    with tempfile.TemporaryDirectory() as tmp:
        home, app, lib, gh, extra, cfg = fam_setup(tmp, body=body)
        env = env_for(home, gh, **extra)
        rc, out, err = run(lib, env, "section", "completion-mode")
        check("family-only section from sibling cwd reads family",
              (rc, out), (0, "completion: ready\n"))
        rc, out, err = run(app, env, "section", "stop-condition-2", "--repo", "lib")
        check("family-only section with --repo sibling reads family",
              (rc, out), (0, "always escalate\n"))
        rc, out, err = run(app, env, "section", "completion-mode")
        check("family-only section from home unchanged", out, "completion: ready\n")


def test_exit_codes():
    with tempfile.TemporaryDirectory() as tmp:
        home, repo, gh = setup(tmp)
        check("no config is 2", run(repo, env_for(home, gh))[0], 2)
        write(os.path.join(home, ".stu", "fam", "stu.md"),
              "---\n---\n## repos\n### a\nslug: x/y\n")
        rc, out, err = run(repo, env_for(home, gh))
        check("broken family claiming nothing is skipped", rc, 2)
        write(os.path.join(home, ".stu", "fam", "stu.md"),
              "---\n---\n## repos\n### a\npath: %s\nslug: x/y\n### a\npath: /tmp\n" % repo)
        rc, out, err = run(repo, env_for(home, gh))
        check("broken family claiming the repo is 3", rc, 3)
        check("names the file", "fam/stu.md" in err, True)
        plain = os.path.join(tmp, "plain")
        os.makedirs(plain)
        e = env_for(home, gh)
        check("non-git refused", run(plain, e)[0], 1)
        check("usage error bad option", run(repo, e, "--bogus")[0], 4)
        check("usage error section without id", run(repo, e, "section")[0], 4)
        check("usage error --repo without value", run(repo, e, "--repo")[0], 4)
        check("usage error extra word", run(repo, e, "wat")[0], 4)


def init_origin(repo, url="git@github.com:acme/app.git"):
    sh(repo, "git", "remote", "add", "origin", url)


def test_base_resolution():
    with tempfile.TemporaryDirectory() as tmp:
        home, repo, _ = setup(tmp)
        init_origin(repo)
        write(os.path.join(repo, ".claude", "stu.md"), "---\nowner: o\n---\n")
        ghdir, extra = fgh(tmp)
        env = env_for(home, ghdir, **extra)
        sh(repo, "git", "update-ref", "refs/remotes/origin/trunk", "HEAD")
        sh(repo, "git", "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")
        v = parse(run(repo, env)[1])
        check("symbolic-ref", (v["BASE"], v["BASE_SOURCE"]), ("trunk", "symbolic-ref"))
        check("no gh call when symbolic-ref answers", gh_calls(extra), [])
        # dangling origin/HEAD is ignored
        sh(repo, "git", "update-ref", "-d", "refs/remotes/origin/trunk")
        ghdir, extra = fgh(tmp, {"repo view": {"rc": 0, "json": {
            "nameWithOwner": "acme/app", "defaultBranchRef": {"name": "dev"}}}})
        v = parse(run(repo, env_for(home, ghdir, **extra))[1])
        check("dangling HEAD falls to forge", (v["BASE"], v["BASE_SOURCE"]), ("dev", "forge"))
        # forge fails -> origin/main
        ghdir, extra = fgh(tmp, {})
        sh(repo, "git", "update-ref", "refs/remotes/origin/main", "HEAD")
        v = parse(run(repo, env_for(home, ghdir, **extra))[1])
        check("fallback", (v["BASE"], v["BASE_SOURCE"]), ("main", "fallback"))
        # forge_lookup=False never calls gh
        ghdir, extra = fgh(tmp, {"repo view": {"rc": 0, "json": {
            "defaultBranchRef": {"name": "dev"}}}})
        sh(repo, "git", "update-ref", "-d", "refs/remotes/origin/main")
        with inproc(env_for(home, ghdir, **extra)):
            e = stu_env.resolve(cwd=repo, forge_lookup=False)
        check("no base, no lookup: empty not error", (e["BASE"], e["BASE_SOURCE"]), ("", ""))
        check("forge_lookup=False never calls gh", gh_calls(extra), [])
    with tempfile.TemporaryDirectory() as tmp:
        home, repo, _ = setup(tmp)
        ghdir, extra = fgh(tmp, {"repo view": {"rc": 0, "json": {"nameWithOwner": "acme/z"}}})
        write(os.path.join(repo, ".claude", "stu.md"), "---\nowner: o\n---\n")
        with inproc(env_for(home, ghdir, **extra)):
            e = stu_env.resolve(cwd=repo, forge_lookup=False)
            s = stu_env.section(e["_BODY"], "x")
        check("slug lookup makes no gh call either", (gh_calls(extra), e["GITHUB_REPO"]), ([], ""))
    with tempfile.TemporaryDirectory() as tmp:
        home, repo, _ = setup(tmp)
        init_origin(repo)
        ghdir, extra = fgh(tmp, {})
        cfg = os.path.join(tmp, "solo.md")
        write(cfg, "---\nowner: o\n---\n## repos\n### solo\npath: %s\nslug: acme/app\n" % repo)
        rc, out, err = run(repo, env_for(home, ghdir, STU_CONFIG=cfg, **extra))
        check("no base resolvable exits 3 with hint",
              (rc, "base:" in err, "solo" in err, cfg in err), (3, True, True, True))


def test_remotes_and_host():
    with tempfile.TemporaryDirectory() as tmp:
        home, repo, gh = setup(tmp, gh=None)
        init_origin(repo)
        sh(repo, "git", "remote", "add", "upstream", "https://github.com/other/app")
        write(os.path.join(repo, ".claude", "stu.md"), "---\nowner: o\n---\n")
        rc, out, err = run(repo, env_for(home, gh))
        v = parse(out)
        check("two remotes: chosen slug and GH_REPO", (v["REPO_SLUG"], v["GH_REPO"], v["GITHUB_REPO"]),
              ("acme/app", "acme/app", "acme/app"))
        check("two remotes: warning names both",
              ("acme/app" in err, "other/app" in err, "origin" in err), (True, True, True))
        write(os.path.join(repo, ".claude", "stu.md"), "---\nremote: upstream\n---\n")
        v = parse(run(repo, env_for(home, gh))[1])
        check("remote key picks the slug", (v["REMOTE"], v["REPO_SLUG"]), ("upstream", "other/app"))
        write(os.path.join(repo, ".claude", "stu.md"), "---\nslug: me/mine\n---\n")
        rc, out, err = run(repo, env_for(home, gh))
        check("explicit slug: no warning", (parse(out)["GH_REPO"], "several" in err), ("me/mine", False))
    with tempfile.TemporaryDirectory() as tmp:
        home, repo, gh = setup(tmp, gh=None)
        init_origin(repo, "git@ghe.acme.test:acme/app.git")
        write(os.path.join(repo, ".claude", "stu.md"), "---\nowner: o\n---\n")
        v = parse(run(repo, env_for(home, gh))[1])
        check("host from remote url", (v["GH_HOST"], v["REPO_SLUG"]), ("ghe.acme.test", "acme/app"))
        write(os.path.join(repo, ".claude", "stu.md"), "---\nhost: other.acme.test\n---\n")
        check("host key", parse(run(repo, env_for(home, gh))[1])["GH_HOST"], "other.acme.test")


def test_sections_records_commands():
    with tempfile.TemporaryDirectory() as tmp:
        home, repo, gh = setup(tmp)
        write(os.path.join(repo, ".claude", "stu.md"),
              "---\nowner: o\n---\n## after-pass-steps\n### step-a\nwhen: landed\nrun: x\n"
              "### step-b\nwhen: pass\n\n## cmds\nprose\n```sh\n# a comment\nmake a\n\n"
              "make b --flag\n```\n")
        env = env_for(home, gh)
        rc, out, err = run(repo, env, "records", "after-pass-steps")
        check("records", (rc, [json.loads(x) for x in out.splitlines()]),
              (0, [{"name": "step-a", "when": "landed", "run": "x"},
                   {"name": "step-b", "when": "pass"}]))
        rc, out, err = run(repo, env, "commands", "cmds")
        check("commands", (rc, out.splitlines()), (0, ["make a", "make b --flag"]))
        check("commands on absent section", run(repo, env, "commands", "nope")[:2], (0, ""))
    check("records unit", stu_env.records("x\n### n\nk: v:w\n"), [{"name": "n", "k": "v:w"}])


def test_in_process_api():
    with tempfile.TemporaryDirectory() as tmp:
        plain = os.path.join(tmp, "plain")
        os.makedirs(plain)
        home = os.path.join(tmp, "home")
        os.makedirs(home)
        ghdir, extra = fgh(tmp)
        with inproc(env_for(home, ghdir, **extra)):
            try:
                stu_env.resolve(cwd=plain)
                got = "returned"
            except stu_env.NotInRepo:
                got = "NotInRepo"
            except BaseException as e:  # SystemExit must not escape
                got = type(e).__name__
        check("resolve never raises SystemExit", got, "NotInRepo")
        check("NotInRepo is an Exception", issubclass(stu_env.NotInRepo, Exception), True)
        check("SystemExit is not what callers see",
              issubclass(stu_env.NotInRepo, SystemExit), False)
    with tempfile.TemporaryDirectory() as tmp:
        home, app, lib, gh, extra, cfg = fam_setup(tmp)
        bad = os.path.join(home, ".stu", "bad", "stu.md")
        write(bad, "---\n---\n## repos\n### a\nslug: x/y\n")
        plain = os.path.join(tmp, "plain")
        os.makedirs(plain)
        with inproc(env_for(home, gh, **extra), cwd=plain):
            got = stu_env.families()
        check("families lists every config, never raises",
              [(os.path.basename(os.path.dirname(p)), [r["name"] for r in rs]) for p, rs in got],
              [("bad", []), ("fam", ["app", "lib"])])
        with inproc(env_for(home, gh, **extra)):
            c = stu_env._load(cfg)
            row = stu_env.row_for_path(c["rows"], app)
            try:
                stu_env.row_for_path(c["rows"], tmp)
                raised = False
            except stu_env.ConfigError:
                raised = True
        check("row_for_path", (row["name"], raised), ("app", True))
        check("rows() flat", [r["name"] for r in stu_env.rows({"project": "p"}, "")], ["p"])


def test_config_path_exported():
    with tempfile.TemporaryDirectory() as tmp:
        home, repo, gh = setup(tmp)
        cfg = os.path.join(tmp, "elsewhere.md")
        write(cfg, "---\nowner: o\n---\n")
        v = parse(run(repo, env_for(home, gh, STU_CONFIG=cfg))[1])
        check("CONFIG_PATH realpath", v["CONFIG_PATH"], rp(cfg))
        v = parse(run(repo, env_for(home, gh), "--defaults")[1])
        check("CONFIG_PATH empty with --defaults", v["CONFIG_PATH"], "")
        rc, out, err = run(repo, env_for(home, gh), "--json")
        check("no config with --json is 2", rc, 2)
        rc, out, err = run(repo, env_for(home, gh, STU_CONFIG=cfg), "--json")
        j = json.loads(out)
        check("json has new keys, no internals", ("REPO_NAME" in j, any(k.startswith("_") for k in j)),
              (True, False))


def test_review_round_one():
    # path with a space still claims the repo: a broken family fails closed (exit 3)
    with tempfile.TemporaryDirectory() as tmp:
        home = rp(os.makedirs(os.path.join(tmp, "home")) or os.path.join(tmp, "home"))
        parent = os.path.join(tmp, "my proj")
        os.makedirs(parent)
        app = make_repo(parent, "app")
        gh = fake_gh(tmp, None)
        row = "### app\npath: %s\nslug: acme/app\n"
        write(os.path.join(home, ".stu", "fam", "stu.md"),
              "---\nowner: o\n---\n\n## repos\n" + row % app + row % app)
        rc, out, err = run(app, env_for(home, gh))
        check("space in path, broken family claims repo", rc, 3)
    # --repo from a repo with its own flat config finds the family row
    with tempfile.TemporaryDirectory() as tmp:
        home, app, lib, gh, extra, cfg = fam_setup(tmp)
        env = env_for(home, gh, **extra)
        other = make_repo(os.path.join(tmp, "x"), "other")
        write(os.path.join(other, ".claude", "stu.md"), "---\nowner: r\n---\n")
        rc, out, err = run(other, env, "--repo", "lib")
        check("--repo from repo with flat config", (rc, parse(out).get("MAIN_CHECKOUT")),
              (0, lib))
        cfg2 = os.path.join(home, ".stu", "fam2", "stu.md")
        write(cfg2, fam_text(app, lib))
        rc, out, err = run(other, env, "--repo", "lib")
        check("--repo ambiguous families", (rc, rp(cfg) in err, rp(cfg2) in err),
              (3, True, True))
        os.remove(cfg2)
        os.rmdir(os.path.dirname(cfg2))
        rc, out, err = run(other, env, "--repo", "nope")
        check("--repo unknown from flat repo", rc, 3)
    # invalid UTF-8
    with tempfile.TemporaryDirectory() as tmp:
        home, app, lib, gh, extra, cfg = fam_setup(tmp)
        env = env_for(home, gh, **extra)
        data = open(cfg, "rb").read()
        with open(cfg, "wb") as f:
            f.write(data + b"\n\xff\xfe\n")
        rc, out, err = run(app, env)
        check("invalid utf-8 family claiming repo", (rc, "Traceback" in err, "UTF-8" in err),
              (3, False, True))
        other = make_repo(os.path.join(tmp, "x"), "other")
        rc, out, err = run(other, env, "--defaults")
        check("invalid utf-8 unrelated family does not break others", (rc, "Traceback" in err),
              (0, False))
        local = os.path.join(other, ".claude", "stu.md")
        os.makedirs(os.path.dirname(local))
        with open(local, "wb") as f:
            f.write(b"---\nowner: \xff\n---\n")
        rc, out, err = run(other, env)
        check("invalid utf-8 local config", (rc, "Traceback" in err), (3, False))
        sys.path.insert(0, os.path.dirname(SCRIPT))
        import stu_env
        with inproc(env, other):
            fams = stu_env.families()
        check("families never raises on bad bytes", any(p == rp(cfg) and r == [] for p, r in fams), True)


for t in (test_review_round_one, test_flat_config_equivalence, test_flat_merge_mode, test_flat_frontmatter_row_keys,
          test_family_resolution, test_prefix_collision, test_two_claims,
          test_mandatory_and_structure, test_sibling_isolation, test_family_only_section_from_sibling, test_exit_codes,
          test_base_resolution, test_remotes_and_host, test_sections_records_commands,
          test_in_process_api, test_config_path_exported,
          test_defaults_from_main_checkout, test_resolves_main_checkout_from_worktree,
          test_no_github_remote, test_same_dirname_distinct_slugs,
          test_missing_config_exits_2, test_defaults_flag_needs_no_config,
          test_lookup_order, test_frontmatter_overrides, test_section_body,
          test_shell_safety, test_offline_origin_and_home_lookup,
          test_home_lookup_hash_slug_fallback, test_stu_config_missing,
          test_bom_unclosed_and_exact_section, test_section_comments_and_triage_extra):
    t()

if FAILURES:
    print("FAIL: %d of %d checks" % (len(FAILURES), COUNT[0]))
    for f in FAILURES:
        print("  " + f)
    sys.exit(1)
print("ok: %d checks" % COUNT[0])
