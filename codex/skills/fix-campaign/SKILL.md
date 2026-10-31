---
name: fix-campaign
description: Use when triaging open GitHub issues and starting a Stu fix campaign.
---

Use the live shared Stu contract for this skill. Resolve this file's **absolute** path from
its skill catalog entry. The package root is `Path(absolute_skill_path).resolve().parents[3]`
(`codex/skills/fix-campaign/SKILL.md` is four levels below the package root).
Do not derive it from the current repository, cwd, or a guessed installation location.

Run the following with that resolved absolute package root, from the target repository:

```sh
PATH="<absolute package root>/bin:$PATH" STU_RUNTIME=codex "<absolute package root>/bin/stu-codex" contract fix-campaign
```

Read the complete returned runtime binding and canonical contract, then follow them for the
owner's request. Every child receives the absolute helper command and explicit PATH/runtime
binding, reads its own role contract, and starts with a fresh context. The shared files own
all objectives, scoreboard fields, safety rules, gates and return formats; this wrapper
contains no alternate workflow. A failed helper or runtime-drift error stops the skill;
report its stderr and preserve a concrete handoff instead of inventing missing instructions.
