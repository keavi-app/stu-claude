#!/usr/bin/env python3
"""Render live shared Stu policy with a small, fail-closed Codex runtime binding.

Only runtime-owned regions are replaced. Heading and literal assertions intentionally make
upstream runtime drift visible instead of silently retaining incompatible instructions.
"""
import argparse
import hashlib
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

SOURCES = {name: 'skills/' + name + '/SKILL.md'
           for name in ('init', 'run', 'settle', 'fix-campaign')}
SOURCES.update({name: 'agents/' + name + '.md' for name in
                ('orchestrator', 'implementer', 'reviewer', 'merge-gate', 'scout', 'verifier')})
SOURCES.update({'charter': 'skills/fix-campaign/orchestrator-charter.md',
                'overnight': 'skills/run/overnight.md'})


# Hash only replaced runtime regions, never shared policy. Any upstream edit inside one
# needs deliberate adapter review; a new policy sentence must never be silently discarded.
RUNTIME_REGIONS = {
    '### Liveness: one deadline timer per dispatch, not a poll\n': 'd33d92df2bf3371c137055438b71d6683eaf0ecd985d32ec78a0ae5c1f24fc7c',
    '## Routing: which agent, which model\n': 'd1a7bd58144c0bdd9e04ab068db524faa002c9a6a45fa9b6a023bf7260971c85',
    '## Turn discipline\n': 'a36c37dbf7ccf144b58733f060c211b3fdb437d6d362a6d6a28f8054d91626f0',
    '**After a repair has been sent, a prose-only stop is still interim:**': '5263f78ffb0a85270ee60a1f230b3eb795d1efa9dfd6b8ff5ebe6edfac506b40',
    '## How to wait — never `sleep`\n': '0d2bb69da5f5937b79c49e0a63a42fb35d1c0c8413e866265b4d6998bed41b29',
    '## Never background-and-wait on anything\n': '178042a380ef11e25f4ee1508ecb5ea91c08e5c5041b9bf1a4e47c24376ae303',
    'Dispatch **one** orchestrator, `subagent_type: "stu:orchestrator"`, pointed at\n': 'bdc1e0a5e2c1ad38a43d3b85da42917c6c1586850325ef2e5044d320ecd209d4',
    '## Model selection — dispatch by agent name, not by model\n': '34df0c3f9e2e810d391b549920c786f3b321bc595907d6219dc758c2b8609c86',
}

class ContractDrift(ValueError):
    pass


def replace(text, old, new, count=1):
    if text.count(old) != count:
        raise ContractDrift('runtime anchor drift: ' + old[:110])
    return text.replace(old, new)


def region(text, start, end, new):
    if text.count(start) != 1 or text.count(end) != 1:
        raise ContractDrift('runtime section drift: ' + start)
    before, tail = text.split(start, 1)
    if end not in tail:
        raise ContractDrift('runtime section order drift: ' + start)
    removed = start + tail.split(end, 1)[0]
    if hashlib.sha256(removed.encode()).hexdigest() != RUNTIME_REGIONS[start]:
        raise ContractDrift('runtime section content drift: ' + start)
    return before + new.rstrip() + '\n\n' + end + tail.split(end, 1)[1]


LIVENESS = '''### Liveness: one deadline timer per dispatch, not a poll

Use the native bounded waits and persisted clock deadlines in the Codex runtime binding.
Every lane has its own 90-minute check. A completed orchestrator with a live descendant is
alive, never a reason to restart. The six-hour bound from the first check, cycle's single
repair, final 90-minute repair deadline, and one restart per lane remain in force. A status
request is answered from a fresh agent tree inventory. Unknown child state fails closed.
'''
ROUTING = '''## Routing: which agent, which model

Dispatch by logical role using the Codex runtime binding's fresh-worker contract command.
`stu:scout` is mandatory for locating questions, for you and every agent you dispatch.
`stu:verifier` checks premises, `stu:implementer` builds one brief, `stu:reviewer` independently
reviews an exact SHA, `stu:merge-gate` collects gate evidence, and `stu:orchestrator` grooms
and dispatches. The binding owns supported model/effort selection. Record configured or
default selection; never infer model metadata from the role name. The canonical numbered
escalation conditions still apply, including the literal ESCALATION line and scoreboard count.
'''
WAITING = '''## How to wait — never `sleep`

**Children:** use bounded native waits and live tree inspection from the runtime binding.
The parent owns its children and reads their reports directly. Never end a role on a waiting
line while work remains live. A repair after silence first establishes the child's state
from its report, worktree and PR, never from silence alone.

**CI:** execute this helper and retain any returned shell session ID, collecting its terminal
line with bounded `write_stdin` calls:

```
STU_CONFIG=<CONFIG_PATH> stu-ci-wait --pr <n> --slug <the row's REPO_SLUG>
```

Its terminal line remains:

```
CI: PASS | FAIL | FLAKY_RERUN_PASSED | UNKNOWN | TIMEOUT | SHA_MOVED | BLOCKED_CONFLICT | MERGED | NONE  … verdict=… failed=…
```

`NONE` means the configured row has no CI. Direct-push and before-push units have no PR CI
wait; the gate's verification row applies. On a label-handoff row whose merge label also
gates CI, do not wait before the gate applies that label: no run exists yet. The gate's
landed-merge confirmation gathers that CI evidence.
'''


def adapt(name, text):
    if text.startswith('---\n'):
        parts = text.split('---\n', 2)
        if len(parts) != 3:
            raise ContractDrift('invalid frontmatter: ' + name)
        text = parts[2].lstrip('\n')
    # Frontmatter-only runtime comments are not policy. Refuse changed comments rather than
    # stripping all comments: shared explanatory comments must survive.
    for comment in (
        '<!-- The turn-guard hook warns at the 120-turn budget; `maxTurns` is the hard stop. -->\n',
        '<!-- `cacheTtl: 1h` is for this role alone: see design-rationale.md, "Cache TTL". -->\n',
        '<!-- The turn-guard hook warns at the 140-turn budget; `maxTurns` is the hard stop. -->\n',
    ):
        if comment in text:
            text = replace(text, comment, '')
    if name == 'run':
        text = replace(text, "stu-forge repo-settings --slug <REPO_SLUG> --base <the row's BASE>",
                       "stu-forge repo-settings --slug <REPO_SLUG> --base <the row's BASE> --allow-unavailable-rules")
        text = region(text, '### Liveness: one deadline timer per dispatch, not a poll\n',
                      '### Restart once per lane\n', LIVENESS)
        text = region(text, '## Routing: which agent, which model\n',
                      '## Work patterns this routes to\n', ROUTING)
        text = region(text, '## Turn discipline\n', '\n---\n\n# The standing contract',
                      '## Turn discipline\n\nUse bounded native waits, batch independent calls, and '
                      'append handoff state with the next dispatch. Keep status concise.')
        text = region(text, '**After a repair has been sent, a prose-only stop is still interim:**',
                      '**Never accept `MERGED_IDS`,',
                      '''**After a repair has been sent, a prose-only stop is still interim.**
Keep the final repair deadline; no second repair or deadline reset. If it expires without a
schema, mark the lane BLOCKED and preserve a handoff. Native tree state distinguishes live
children and shell sessions from an idle parent; never infer idle from a completed parent.

**Only the current cycle's orchestrator schema is a return.** Discard closed-cycle
redeliveries. A nested worker report belongs to its orchestrator, never to the supervisor's
return checks. No nested notification relay is needed. A malformed schema still earns the
single repair and then fails closed; an interim prose return stays under its existing deadline.''')
        text = replace(text, '**Stale contract.** The skills and agents load from the installed plugin (`${CLAUDE_PLUGIN_ROOT}`), not from the repo, so there is no checkout to compare: a stale contract means a stale plugin install. Never update it mid-run; if the owner wants the newest contract, they run `/plugin update stu` between runs.',
                       '**Stale contract.** Contracts render from the installed package root. Never update the package mid-run; update the Codex skill installation between runs, keeping it paired with its package helper.')
        text = replace(text, 'Dispatch one `stu:orchestrator` — **never a `fork`**, which cannot spawn subagents and will\nsilently do the campaign itself.',
                       'Dispatch one fresh `stu:orchestrator` using the runtime binding; it must be able to spawn its own workers.')
        text = replace(text, 'These are **your** bands (`ctx.py`). The orchestrator and implementer carry their own, tighter\npairs in `scripts/turn-guard.py` (`AGENT_CTX_BANDS`), stated in their definitions.',
                       'These are **your** bands (`stu-ctx`). The orchestrator and implementer carry their own tighter bands in their contracts. The Codex runtime binding governs usage availability and advisory hooks.')
    elif name == 'orchestrator':
        text = replace(text, 'You are NOT a fork: you can and must dispatch subagents.',
                       'You are a fresh orchestrator: you can and must dispatch workers using the runtime binding.')
        text = replace(text, 'These carry their own model and effort. **Never pass `model`** except below.',
                       'These are logical roles. Use the runtime binding for supported model and effort selection.')
        text = replace(text, '### Opus escalation: name the condition or do not escalate',
                       '### Model escalation: name the condition or do not escalate')
        text = replace(text, '"Orchestrator contract history > Opus escalation".',
                       '"Orchestrator contract history > Model escalation".')
        text = replace(text, 'Pass `model: "opus"` only when one of these holds, and open the dispatch prompt with this',
                       'Escalate model or effort only when one of these holds, using only caller-supported settings, and open the dispatch prompt with this')
        text = replace(text, 'Anything else runs on the agent\'s own frontmatter model; "important", "subtle" or "high risk"\ndescribes every issue in the queue.',
                       'Anything else uses the runtime binding\'s ordinary supported model/effort; "important", "subtle" or "high risk" describes every issue in the queue.')
        text = region(text, '## How to wait — never `sleep`\n',
                      'On `CI: BLOCKED_CONFLICT`', WAITING)
        text = replace(text, 'A `PostToolUse` hook (`scripts/turn-guard.py`, `AGENT_CTX_BANDS`) reads both numbers from your\ntranscript and tells you which one tripped: once on approach, again at the bar, then every 25 turns\npast it. That message is this budget speaking, not a suggestion to weigh against finishing.',
                       'Check usage with `stu-ctx`; the Codex usage hook, when installed, is advisory. Unknown usage is hard-exceeded and requires a handoff. Track work and turn limits as policy; do not assume a hard harness limit.')
        text = replace(text, '**The only reliable stop signal is the completion\nnotification**; treat its absence as dispositive.',
                       '**A terminal agent report plus native tree inspection is required to establish termination**; a completed parent with a live descendant still owns work.')
    elif name == 'implementer':
        text = replace(text, 'You do not have to track either number yourself: `turn-guard.py` fires on both and names which\none tripped. It reports late rather than early, so treat its first warning as already overdue.',
                       'Track both policy limits and check `stu-ctx`. A Codex usage hook is advisory when installed; unknown usage is hard-exceeded and requires a handoff.')
        text = region(text, '## Never background-and-wait on anything\n',
                      '## Wrap-up runs in a small context\n',
                      '''## Never background-and-wait on anything

Keep ownership of all long shell commands. Use `exec_command`; when it returns a session ID,
retain it and collect completion using bounded `write_stdin` calls. For a review job, inspect
its branch-scoped listing under a deadline. Never end your turn or return while an unresolved
command still owns work. Use native bounded waits for your own read-only worker reports.''')
        text = replace(text, 'already is, same as everything else. `turn-guard.py` does not fire at this line — it is silent\nbelow 150k — so check your own context yourself at the moment you finish implementation and',
                       'already is, same as everything else. Check your own context with `stu-ctx` at the moment you finish implementation and')
        text = replace(text, '120k stage into `turn-guard.py` is a separate change, out of scope here.',
                       '120k stage into an advisory usage hook is a separate change, out of scope here.')
        text = replace(text, 'dispatch a subagent (general-purpose, no model\n  override) with written pass criteria.',
                       'dispatch a fresh visual verifier using the runtime binding and available image tools, with written pass criteria.')
    elif name == 'reviewer':
        text = replace(text, '**Read-only covers shared infrastructure, not just files.** `Edit` and `Write` are blocked; that\nconstraint is absent for everything reachable through `Bash` — a shared database, a cache, an\nobject store, a build daemon.',
                       '**Read-only covers shared infrastructure, not just files.** Editing and writing are forbidden by this role contract, regardless of available tools. Shell commands can reach a shared database, cache, object store or build daemon, so the same restriction applies there.')
    elif name == 'merge-gate':
        text = replace(text, '**You have no `Write` or `Edit`,** the boundary `stu:reviewer` also carries: a seat that judges\ncode must not be able to change it, and a boundary of prose fails when it matters. Your `Bash` is for',
                       '**You must not edit source or shared state outside the allowed gate actions.** Generic Codex workers inherit tool permissions; this is a role policy, not a claim that editing tools are blocked. Your shell is for')
    elif name == 'settle':
        text = replace(text, '! "<plugin root>/bin/stu-approve" <id> <sha>',
                       'PATH="<plugin root>/bin:$PATH" STU_RUNTIME=codex STU_CONFIG="<CONFIG_PATH>" "<plugin root>/bin/stu-approve" <id> <sha>')
    elif name == 'fix-campaign':
        text = region(text, 'Dispatch **one** orchestrator, `subagent_type: "stu:orchestrator"`, pointed at\n',
                      '### Respawning is yours, and a campaign stalls without it\n',
                      '''Dispatch **one** fresh `stu:orchestrator` using the runtime binding and the rendered
`charter` contract, plus your ordered issue list and per-issue traps. It must be able to spawn
its own workers. It dispatches the logical roles `stu:scout`, `stu:verifier`, `stu:implementer`,
`stu:reviewer` and `stu:merge-gate`, each loaded through the contract helper in a clean context.
Use the binding's supported model and effort selection. Stay out of its implementation;
verify load-bearing claims, decide merges, and respawn it when its tracked handoff requires it.''')
        text = replace(text, 'Do not pass `model`. Do not dispatch two.',
                       'Use the runtime binding for model/effort selection. Do not dispatch two.')
    elif name == 'charter':
        text = replace(text, 'You are NOT a fork — you can and must dispatch subagents with the `Agent` tool.',
                       'You are a fresh orchestrator — you can and must dispatch workers using the native dispatch tool.')
        text = replace(text, '  To resume one, `SendMessage` that exact ID. `general-purpose` / `Explore` / `claude` are\n  **types, not addresses** — putting one in `to:` misroutes or dead-ends.',
                       '  To contact one, use its returned ID with the native messaging or follow-up tool. Logical role names are not returned agent IDs.')
        text = replace(text, '- Never dispatch a `fork` for anything — forks can\'t spawn subagents and report to main.',
                       '- Dispatch every role with a clean context under the native runtime binding; orchestrators must retain nested delegation capability.')
        text = region(text, '## Model selection — dispatch by agent name, not by model\n',
                      '## Merging\n',
                      '''## Model selection — dispatch by logical role

Use the Codex runtime binding for supported model and reasoning settings. The role-to-work
mapping and numbered escalation conditions live in the rendered orchestrator contract.
A locator is `stu:scout`, premise verification is `stu:verifier`, implementation is
`stu:implementer`, review is `stu:reviewer`, and merge evidence is `stu:merge-gate`.
Two prior runs on the same item failing for the same reason can earn an escalation on the
third attempt, with its numbered condition and literal ESCALATION line. Different failures
do not establish a model limit. Record supported selection explicitly; never infer it from a role.''')
        text = replace(text, 'Dispatch `stu:reviewer` by name, no\n`model`, with',
                       'Dispatch a fresh `stu:reviewer` with an exact SHA and the binding\'s supported model/effort selection, with')
    elif name == 'init':
        text = replace(text, '<MAIN_CHECKOUT>/.claude/stu.md', '<MAIN_CHECKOUT>/.stu/stu.md')
        text = replace(text, 'the language servers listed in `.claude/settings.json` (name the ones seen; do not guess at the rest)',
                       'the caller\'s available language-server tools and project configuration (name the ones seen; do not guess)')
        text = replace(text, 'the repo\'s own project skills (the skills directory under `.claude`)',
                       'the repo\'s own available Codex/project skills (inspect the caller\'s skill inventory)')
    return text


def bind(text, root):
    """Bind mechanical names and helper commands without owning shared policy."""
    root = root.resolve()
    prefix = 'PATH=' + shlex.quote(str(root / 'bin')) + ':$PATH STU_RUNTIME=codex '
    helper = shlex.quote(str(root / 'bin/stu-codex'))
    text = text.replace('${CLAUDE_PLUGIN_ROOT}', str(root))
    text = text.replace('<plugin root>', str(root))
    for name in ('init', 'run', 'settle', 'fix-campaign'):
        text = text.replace('/stu:' + name, '$stu:' + name)
    # References into runtime-bearing contracts must be rendered, not read raw. Formats,
    # templates and rationale remain the canonical files and are never duplicated here.
    references = {str(root / path): name for name, path in SOURCES.items()}
    for path, name in sorted(references.items(), key=lambda item: -len(item[0])):
        text = text.replace('`' + path + '`', '`' + prefix + helper + ' contract ' + name + '` (read its output)')
    for old, new in (('`SendMessage`', '`collaboration.send_message`'),
                     ('SendMessage anyone', 'message another agent'),
                     ('`ListAgents`', '`collaboration.list_agents`'),
                     ('`TaskStop`', '`collaboration.interrupt_agent`'),
                     ('`Agent`', '`collaboration.spawn_agent`'),
                     ('`Bash`', '`exec_command`'), ('ONE Bash call', 'ONE shell call')):
        text = text.replace(old, new)
    # Shared bodies use a few role/runtime idioms outside their runtime sections.
    text = text.replace('completion notification', 'terminal agent report')
    text = text.replace('"never tell a subagent to `collaboration.send_message` anyone"',
                        '"subagents report to their parent using their final return"')
    text = text.replace('You have no `Read`:', 'Your supervisor role may not read this return file:')
    text = text.replace('as `Read`, which is why `Read` is not in\n   `allowed-tools`.',
                        'as reading through any other tool; this is a role restriction, regardless of exposed tools.')
    # Bind ordinary supporting documents as absolute paths and runtime-bearing references
    # through the renderer. Exact backtick spans avoid rewriting prose or path substrings.
    relative = {'agents/orchestrator.md': 'orchestrator', 'orchestrator.md': 'orchestrator',
                'agents/merge-gate.md': 'merge-gate', 'merge-gate.md': 'merge-gate',
                'fix-campaign/SKILL.md': 'fix-campaign', 'overnight.md': 'overnight',
                'SKILL.md': 'run', 'orchestrator-charter.md': 'charter'}
    for path, role in relative.items():
        text = text.replace('`' + path + '`', '`' + prefix + helper + ' contract ' + role + '` (read its output)')
    for path in ('handoff-format.md', 'brief-format.md'):
        text = text.replace('`' + path + '`', '`' + str(root / 'skills/run' / path) + '`')
    # Parse fenced blocks separately. A whole-document backtick regex consumes a fence
    # together with the next inline span and makes adaptation depend on surrounding text.
    command = re.compile(r'(?<![\w/:$-])(stu-[a-z][a-z-]*)(?=\s|$)')
    def inline(match):
        value = match.group(1)
        if value.startswith(prefix) or not re.search(r'(?<![\w/:$-])stu-[a-z-]+(?:\s|$)', value):
            return match.group(0)
        return '`' + command.sub(lambda found: prefix + found.group(1), value) + '`'
    result = []
    chunk = []
    fenced = False
    for line in text.splitlines(keepends=True):
        if line.lstrip().startswith('```'):
            if not fenced:
                result.append(re.sub(r'(?<!`)`([^`]+)`(?!`)', inline, ''.join(chunk)))
                chunk = []
            result.append(line)
            fenced = not fenced
        elif fenced:
            if not line.lstrip().startswith('#') and prefix not in line:
                line = command.sub(lambda match: prefix + match.group(1), line)
            result.append(line)
        else:
            chunk.append(line)
    result.append(re.sub(r'(?<!`)`([^`]+)`(?!`)', inline, ''.join(chunk)))
    return ''.join(result)



def render(name, root):
    root = Path(root).resolve()
    body = bind(adapt(name, (root / SOURCES[name]).read_text()), root)
    runtime = (root / 'codex/runtime.md').read_text().replace('@STU_ROOT@', str(root))
    runtime = runtime.replace('@STU_BIN@', shlex.quote(str(root / 'bin')))
    runtime = runtime.replace('@STU_HELPER@', shlex.quote(str(root / 'bin/stu-codex')))
    forbidden = ('subagent_type:', 'run_in_background', 'TaskStop', 'SendMessage',
                 'ListAgents', 'claude -p', 'sleep 5400', 'maxTurns', 'cacheTtl')
    for token in forbidden:
        if token in body:
            raise ContractDrift('unadapted runtime syntax in ' + name + ': ' + token)
    return runtime.rstrip() + '\n\n---\n\n' + body


def doctor(root):
    """Report concrete local readiness without claiming hook trust or agent availability."""
    root = Path(root).resolve()
    print('Runtime: codex')
    print('Contract root: ' + str(root))
    codex = shutil.which('codex')
    if codex:
        try:
            version = subprocess.run([codex, '--version'], capture_output=True,
                                     text=True, timeout=5)
            print('Codex version: ' + (version.stdout.strip() if version.returncode == 0
                                      else 'unavailable (version command failed)'))
        except (OSError, subprocess.TimeoutExpired):
            print('Codex version: unavailable (version command failed)')
    else:
        print('Codex version: unavailable (CLI not on PATH; contract rendering still works)')
    missing = []
    for dependency in ('python3', 'git'):
        path = shutil.which(dependency)
        print('Dependency ' + dependency + ': ' + (path or 'MISSING'))
        if not path:
            missing.append(dependency)
    print('Optional forge gh: ' + (shutil.which('gh') or 'not on PATH; required only for GitHub rows'))
    env = dict(os.environ, STU_RUNTIME='codex')
    try:
        usage = subprocess.run([sys.executable, str(root / 'scripts/ctx.py')], env=env,
                               capture_output=True, text=True, timeout=5)
        if usage.returncode == 0 and usage.stdout.strip():
            print('Context telemetry: available; ' + ' '.join(usage.stdout.splitlines()))
        else:
            print('Context telemetry: unknown; an active run must treat unknown usage as hard-exceeded and hand off')
    except (OSError, subprocess.TimeoutExpired):
        print('Context telemetry: unknown; an active run must hand off')
    hook = root / 'codex/hooks.json'
    print('Hook manifest: ' + (str(hook) if hook.is_file() else 'not present'))
    print('Hook trust: MANUAL — inspect the installed plugin in Codex and explicitly trust/enable hooks; manifest presence is not trust')
    print('Agent tools and model inventory: inspect the active caller; local files cannot establish availability')
    return 1 if missing else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    command = commands.add_parser('contract', help='render a live shared contract for Codex')
    command.add_argument('name', choices=sorted(SOURCES))
    commands.add_parser('doctor', help='report local runtime readiness and manual trust requirements')
    args = parser.parse_args(argv)
    if args.command == 'doctor':
        return doctor(Path(__file__).resolve().parents[1])
    try:
        print(render(args.name, Path(__file__).resolve().parents[1]), end='')
    except (ContractDrift, OSError) as error:
        print('stu-codex: ' + str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
