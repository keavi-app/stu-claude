#!/usr/bin/env bash
# Content lint: no unresolved {{PLACEHOLDER}}, no kit-era paths, no unprefixed agent or
# skill names anywhere in the plugin's instruction text.
cd "$(dirname "$0")/.." || exit 1
fails=0
none() {  # description, then grep args; passes when grep prints nothing
  local desc="$1"; shift
  local out; out=$(grep -rnE "$@" 2>/dev/null)
  if [ -n "$out" ]; then
    echo "FAIL $desc"; printf '%s\n' "$out" | head -40 | sed 's/^/    /'
    echo "    ($(printf '%s\n' "$out" | wc -l | tr -d ' ') hits)"; fails=$((fails + 1))
  else echo "ok   $desc"; fi
}
none "no {{PLACEHOLDER}}" '\{\{[A-Z_]+\}\}' skills agents scripts bin
none "no .claude/skills/ paths" '\.claude/skills/' skills agents scripts bin
none "no .claude/agents/ paths" '\.claude/agents/' skills agents scripts bin
none "no scripts/ paths in skills/agents (use stu-claims, stu-ctx, stu-ci-wait)" \
  'scripts/(run_claims|ctx|ci-wait)' skills agents
none "no unprefixed subagent_type" \
  'subagent_type: "(orchestrator|implementer|reviewer|merge-gate|scout|verifier)"' skills agents
none "no unprefixed backticked agent names" \
  '`(orchestrator|implementer|reviewer|merge-gate|scout|verifier)`' skills agents
none "no /autonomous-run" '/autonomous-run' skills agents scripts bin
none "no bare autonomous-run" 'autonomous-run' skills agents
none "no unprefixed /settle" '(^|[^a-z])/settle([^/]|$)' skills agents scripts bin
none "no unprefixed /fix-campaign" '(^|[^a-z])/fix-campaign([^/]|$)' skills agents scripts bin
none "no python3 run_claims/ctx invocation" 'python3 .*(run_claims|ctx)\.py' skills agents
none "no PROJECT-SPECIFIC blocks (answers live in the stu config)" 'PROJECT-SPECIFIC' skills agents
if grep -q 'No pre-gate CI wait where the merge label also gates CI' agents/orchestrator.md
then echo "ok   orchestrator states the label-gates-CI exception"
else echo "FAIL orchestrator states the label-gates-CI exception"; fails=$((fails + 1)); fi

# Config sections: every `stu-env section <id>` in skills/agents has a `## <id>` in the
# template, and every template section is referenced. The template is the closed registry.
TEMPLATE=skills/init/stu.template.md
refs=$(grep -rhoE 'stu-env (section|commands|records) [a-z0-9-]+' skills agents | awk '{print $3}' | sort -u)
heads=$(grep -E '^## ' "$TEMPLATE" | sed 's/^## //; s/[[:space:]]*$//' | sort -u)
check_set() {  # description, then the ids that should be empty
  if [ -n "$2" ]; then
    echo "FAIL $1"; printf '%s\n' "$2" | sed 's/^/    /'; fails=$((fails + 1))
  else echo "ok   $1"; fi
}
check_set "every referenced section has a template heading" "$(comm -23 <(printf '%s\n' "$refs") <(printf '%s\n' "$heads") | grep .)"
check_set "every template heading is referenced" "$(comm -13 <(printf '%s\n' "$refs") <(printf '%s\n' "$heads") | grep .)"
[ -n "$heads" ] || check_set "template has sections" "none found"
# Each section carries its /stu:init question as an HTML comment right under the heading.
uncommented=$(awk '/^## /{id=substr($0,4); want=1; next} want && NF{ if ($0 !~ /^<!--/) print id; want=0 }
  END{ if (want) print id }' "$TEMPLATE")
check_set "every template section opens with an HTML-comment question" "$uncommented"
# Spec H guards. skills/init/stu.template.md holds owner-written config answers, so the
# new checks below skip it; every other file under skills and agents is scanned.
EXCL=--exclude=stu.template.md
none "no literal origin/main" "$EXCL" 'origin/main' skills agents
none "no backticked main or == main used as a branch" "$EXCL" '`main`|== main' skills agents
none "no backticked origin/<branch> (use <remote>/<base>)" "$EXCL" '`origin/[^`]+`' skills agents

# A line starting with gh or $ gh is allowed only inside a fenced block whose first content
# line is "# GitHub example". Fence markers and that line may be indented. Inline mentions
# in prose are ignored.
rawgh=$(find skills agents -type f -name '*.md' ! -path skills/init/stu.template.md | sort | while read -r f; do
  awk -v F="$f" '
    /^[[:space:]]*```/ { if (infence) { infence = 0; exempt = 0 } else { infence = 1; first = 1; exempt = 0 } ; next }
    infence && first && NF { first = 0; if ($0 ~ /^[[:space:]]*# GitHub example[[:space:]]*$/) exempt = 1; next }
    /^[[:space:]]*(\$ )?gh / && !exempt { print F ":" NR ": " $0 }' "$f"
done)
check_set "no raw gh command outside a '# GitHub example' fence" "$rawgh"

# Every backticked `stu-forge <verb>` names a verb in the VERBS table of scripts/stu_forge.py
# (parsed as text; the module is never imported).
verbs=$(sed -n '/^VERBS = {/,/^}/p' scripts/stu_forge.py | grep -oE '^    "[a-z-]+"' | tr -d ' "' | sort -u)
[ -n "$verbs" ] || check_set "stu_forge.py VERBS table parsed" "none found"
badverbs=$(grep -rnoE '`stu-forge [a-z-]+' --exclude=stu.template.md skills agents | while IFS= read -r hit; do
  v=${hit##* }
  printf '%s\n' "$verbs" | grep -qxF "$v" || echo "$hit"
done)
check_set "every backticked stu-forge verb is in scripts/stu_forge.py" "$badverbs"

# In agents/, a repo-scoped stu-env section/commands/records call carries --repo. Family-only
# ids come from FAMILY_ONLY_SECTIONS in scripts/stu_env.py, read as text.
famonly=$(grep -E '^FAMILY_ONLY_SECTIONS' scripts/stu_env.py | grep -oE '"[a-z0-9-]+"' | tr -d '"')
[ -n "$famonly" ] || check_set "stu_env.py FAMILY_ONLY_SECTIONS parsed" "none found"
norepo=$(grep -rnE 'stu-env (section|commands|records) [a-z0-9-]+' agents | grep -vF -e '--repo' | while IFS= read -r hit; do
  id=$(printf '%s\n' "$hit" | grep -oE 'stu-env (section|commands|records) [a-z0-9-]+' | head -1 | awk '{print $3}')
  printf '%s\n' "$famonly" | grep -qxF "$id" || echo "$hit"
done)
check_set "repo-scoped stu-env calls in agents carry --repo" "$norepo"

# Required tokens: relay keys in the run skill and orchestrator, gate outcomes in the gate.
need() {  # file, tokens...
  local f="$1" t miss=""; shift
  for t in "$@"; do grep -qF -e "$t" "$f" || miss="$miss$f: missing $t"$'\n'; done
  printf '%s' "$miss"
}
missing=$(need skills/run/SKILL.md PASSED_IDS TAGGED_IDS AFTER_PASS_FAILED WAITING_IDS APPROVAL_IDS
  need agents/orchestrator.md PASSED_IDS TAGGED_IDS AFTER_PASS_FAILED WAITING_IDS APPROVAL_IDS
  need agents/merge-gate.md HUMAN_MERGE HUMAN_PUSH 'TAG:' 'AFTER_PASS:')
check_set "relay keys and gate outcomes are present" "$missing"

# The base-branch reading rule (J1) appears in the verifier and the scout.
read -r J1 <<'EOF_J1'
Read the base branch's files (`git fetch`, then `git show <remote>/<base>:<path>` or a fresh worktree), never the main checkout's working tree.
EOF_J1
missing=$(need agents/verifier.md "$J1"
  need agents/scout.md "$J1")
check_set "the base-branch reading rule is in the verifier and the scout" "$(printf '%s' "$missing" | sed 's/: missing .*/: J1 sentence missing/')"
# A nested child's completion reaches the supervisor, not the orchestrator, in a headless
# session; the supervisor relays it (content-free), and the orchestrator treats the relay as the
# child's own stop signal. Without both halves the orchestrator sleeps until the deadline timer.
missing=$(need skills/run/SKILL.md 'Relay: your background agent' 'never count the relay as the cycle'
  need agents/orchestrator.md 'Relay: your background agent')
check_set "nested completions are relayed to the orchestrator" "$missing"
# Cache TTL: only the orchestrator waits long enough to win back 1-hour writes (rationale,
# "Cache TTL"). The key must be in its frontmatter and in no other agent's.
fm() { awk 'NR==1&&/^---$/{f=1;next} f&&/^---$/{exit} f' "$1"; }
ttl=""
for f in agents/*.md; do
  if [ "$f" = agents/orchestrator.md ]; then
    fm "$f" | grep -qxE 'experimental:[[:space:]]*' && fm "$f" | grep -qxE '[[:space:]]+cacheTtl: 1h[[:space:]]*' \
      || ttl="$ttl$f: missing experimental: cacheTtl: 1h"$'\n'
  elif fm "$f" | grep -q 'cacheTtl'; then ttl="$ttl$f: carries cacheTtl"$'\n'; fi
done
check_set "only the orchestrator carries a 1-hour cache TTL" "$ttl"
exit $((fails > 0))
