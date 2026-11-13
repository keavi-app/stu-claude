#!/usr/bin/env python3
"""Prints one line per drift between the fleet skill's dispatch lines and the agent files'.
Run from the repo root by tests/content_lint_test.sh."""
import re
def keys(lines):
    return [re.match(r"([A-Z]+):", l).group(1) for l in lines]
skill = open("skills/fleet/SKILL.md").read()
def skill_block(seat):
    m = re.search(r"<!-- dispatch-lines: %s -->\s*```\n(.*?)```" % seat, skill, re.S)
    return [l.strip() for l in m.group(1).splitlines() if l.strip()] if m else None
def agent_lines(seat):
    t = open("agents/%s.md" % seat).read()
    if seat == "groomer":
        m = re.search(r"## Dispatch\n.*?```\n(.*?)```", t, re.S)
        return [l.strip() for l in m.group(1).splitlines() if l.strip()] if m else None
    if seat == "designer":
        m = re.search(r"## Dispatch\n\n(.*?)\n\n", t, re.S)
        if not m:
            return None
        return re.findall(r"`([A-Z]+: [^`]*)`", re.split(r"A\s+missing\s+line", m.group(1))[0])
    m = re.search(r"The dispatch carries one line, (.*?)\. No `MODE:`", t, re.S)
    if not m:
        return None
    return [x for x in re.findall(r"`(MODE: [a-z]+)`", m.group(1))]
for seat, full in (("groomer", True), ("designer", True), ("settler", False)):
    have, want = skill_block(seat), agent_lines(seat)
    if have is None:
        print("fleet skill has no dispatch-lines block for %s" % seat)
    elif not want:
        print("could not read %s's dispatch lines from agents/%s.md" % (seat, seat))
    elif full and have != want:
        print("%s dispatch lines differ: skill %r, agent %r" % (seat, have, want))
    elif not full and sorted(set(keys(have))) != sorted(set(keys(want))):
        print("%s dispatch keys differ: skill %r, agent %r" % (seat, keys(have), keys(want)))
