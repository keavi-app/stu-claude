---
name: init
description: Use when setting up stu for a repo, or editing its stu config — /stu:init. Also use when the owner says "set up stu here", "configure stu for this repo", or a stu skill reports that no config was found.
---

# `/stu:init` — write this repo's stu config, one question at a time

**Startup:** run `stu-env --defaults` (it needs no config) and show the owner the derived values: `PROJECT`, `OWNER`, `PROJECT_GUIDE`, `RUN_HOME`, `WORKTREES_DIR`, `GITHUB_REPO`, `MAIN_CHECKOUT`, and `CONFIG_PATH` (empty when no config exists yet). It also prints the row defaults it would use: `REMOTE`, `BASE` (empty when no base branch resolves), `VISIBILITY` (`unset` until set), `MERGE_METHOD`, `CI_KIND`. Then read `${CLAUDE_PLUGIN_ROOT}/skills/init/stu.template.md`: its frontmatter keys and its `## <section-id>` sections are the whole questionnaire.

The config is a Markdown file with frontmatter keys and one section per question the plugin asks about this repo. A section left empty makes the plugin use the default its question names, so **skipping is always safe and never wrong.** Nothing here needs to be committed to the repo. You write one file and nothing else.

## 1. Choose where the config lives

If `CONFIG_PATH` is non-empty, a config exists: go to **Re-running** below instead.

Otherwise ask, in one message, with a recommendation:

- `<MAIN_CHECKOUT>/.claude/stu.md` — `MAIN_CHECKOUT` as `stu-env --defaults` printed it, not the current worktree root; committed, so the whole team shares one config.
- `~/.stu/<PROJECT>/stu.md` — private to this machine, never committed. It works with no change to the repo. `PROJECT` is the slug `stu-env --defaults` printed.

(`$STU_CONFIG`, if set, overrides both. Mention it only if the owner asks where else a config can go.)

## 2. Frontmatter

Show the derived values and ask once whether any is wrong. Write only the keys the owner sets (or that have no derivation, such as `github_repo` when it printed unresolved). **Leave every other key blank** (`owner:` with no value): blank means derive, and the file stays diffable against the template. Keep the template's `# ci_*` comment lines and its `ci_*` defaults. The `ci_*` keys and `triage_extra` are asked only if the owner raises CI or issue triage; otherwise leave them as the template has them.

### Row keys

A flat config is one repo, and it may set every row key in its frontmatter. Ask these five, one per message, after the frontmatter check and before the sections, each with its default and a prefill:

- `ci` — `aggregator` (one check gates merge), `list` (a fixed list of required checks, which then needs `required_checks`) or `none`.
- `base` — the branch pull requests merge into.
- `remote` — the git remote that holds it.
- `merge_method` — how the gate merges (default `squash`).
- `visibility` — `public`, `private` or `unset`.

**The prefill source.** On a first run there is no config, so plain `stu-env` cannot run: take `ci`, `merge_method` and `remote` from the `stu-env --defaults` output, and `base` and `remote` from the repo itself (`git remote get-url <remote>` for the host and slug; the remote's head, from `git symbolic-ref refs/remotes/<remote>/HEAD`, for the base). `--defaults` leaves `BASE` empty and `VISIBILITY` at `unset` when nothing shows them, so ask plainly then. When a config already exists, plain `stu-env` prints the current values; use those.

**Public or before-push repos.** When `visibility` is `public`, or the repo has a before-push checkpoint (`human_checkpoints: before-push`), say that the push checks live in a git `pre-push` hook, not in a tool-call hook (agent pushes need the owner's approval of the tip on a before-push row; every push, agent or human, gets the leak scan on a public row), and offer, never silently, to run `stu-pre-push --install` for the repo's checkout. It chains an existing `pre-push` hook (the old one is kept as `pre-push.local` and runs first); the install refuses when both a hook and its chained `.local` already exist. A run refuses to start on such a row until `stu-pre-push --check` prints `INSTALLED`. Run the install only on a yes.

**A multi-repo table.** One config can describe several repos as a `## repos` table with one `### <name>` block of `key: value` lines per repo, the first being home; init does not write that table for you. When the owner has one, or wants one, tell them to edit it by hand, following the shape in the template's top comment: every row needs `path`, `slug`, `remote`, `base`, `visibility`, `mode`, `merge_mode` and `ci`, plus a `verification-commands` section with a fenced command (`## verification-commands @<name>` for a row other than home); a section that answers for one repo only is written `## <id> @<name>`; and `completion-mode`, `stop-condition-2` and `deep-pass-model` are family-only. Run `stu-env` afterwards: it exits 3 with the fix named when a row or section is wrong. In a config with a table, the five row keys above go on each row, not in the frontmatter.

## 3. Walk the sections

Go through the template's sections in order. For each one:

1. Send **one message, one question**: the question in plain words (from the section's comment), its shape example, a prefill if you have one (see below), and the option **"none here"** — meaning leave the section empty and take the default the comment names.
2. Wait for the answer. Write it under that heading, in plain Markdown, in the owner's words.
   For `merge-mode`, write `Mode: <word>` (`direct`, `label-handoff`, `report-only` or `direct-push`) as the first line of the answer, then any label-handoff detail below it. A non-empty `merge-mode` section needs that `Mode:` line (a lone mode word in prose is read with a warning; anything ambiguous is an error), so on a re-run flag an existing one that has none and offer to add it.
3. Move to the next section.

**Prefill only from what the repo shows, and say where it came from.** Read the file, quote the finding, and ask "use this?". Never fill a section from your general idea of what such a project does.

| Section | Look at |
|---|---|
| `verification-commands` | the project guide (`PROJECT_GUIDE`): its build, test, lint and format commands |
| `ci-traps`, and the `ci_*` keys | workflow names and the check each posts, in `.github/workflows/` |
| `language-servers` | the language servers listed in `.claude/settings.json` (name the ones seen; do not guess at the rest) |
| `implementer-traps`, `reviewer-invariants`, `stop-condition-2` | the project guide's non-negotiables or "never" rules, offered as candidates |
| `delivery-guide` | a delivery or contributing document the project guide links |
| `repo-map` | the top-level directories, one line per layer you can name from the guide |
| `routed-skills` | the repo's own project skills (the skills directory under `.claude`) |

Sections with no source in the repo (`merge-mode`, `auto-merge-setup`, `review-evidence`, `review-tool`, `pre-push-guard`, `escalation-*`, `park-or-decide-rows`, `reviewer-provisioning`, `completion-mode`, `deep-pass-model`, `product-taste`, `tooling-traps`): ask plainly, with the example for shape only. If a hook, merge label or review tool is visible in the repo, say so and ask whether it applies.

## 4. Write and confirm

Create the file by copying the template and filling it in. **Do not reformat the template's structure**: keep every heading, every comment and the order, so later template changes stay diffable. An answered section keeps its comment and gets the answer below it; an unanswered one stays as it is. Create the parent directory if needed.

Then run `stu-env` (with `STU_CONFIG` set to the new path if it is not on the lookup path) and confirm it exits 0 and that the `CONFIG_PATH` it prints equals the path you just wrote. If either fails, fix the file and rerun; do not report success on a failing parse. Unless every section was answered "none here", spot-check one answered section with `stu-env section <id>` to see that it reads back.

## 5. Finish

- **Committed location:** say the config is ready to commit, and leave committing to the owner. Never stage or commit it yourself.
- **Private location:** say where it is and that nothing needs committing.

End with exactly one line:

```
Next: /stu:run "<a one-unit objective>"
```

Put a plausible one-unit objective from the repo in the quotes only if the owner named one; otherwise leave the angle-bracket text for them to fill.

## Re-running

When a config exists, tell the owner its path and ask **which sections or keys to change**. Touch only those. Show the current answer, ask the question again (one per message), and write the new answer in place. Leave every other line byte-for-byte as it was, including sections the template has since added, which you mention in one line so the owner can opt to answer them. Then run `stu-env` to confirm exit 0 and finish as above.

## Rules

- **One question per message.** No exceptions, including the location question and the frontmatter check.
- **Never invent an answer.** If you cannot prefill, ask. If the owner says "I don't know", write nothing and move on.
- **Always offer "none here."**
- **Never commit the config**, never push, and never write anywhere but the config file.
- **Do not edit the template** (`${CLAUDE_PLUGIN_ROOT}/skills/init/stu.template.md`).
