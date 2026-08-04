#!/usr/bin/env bash
# MeoLoom project-init — scaffold a spec-driven project.
# Usage:
#   init.sh <project-name> [--profile <name>] [--desc "<one-liner>"]   # greenfield: creates ./<project-name>
#   init.sh --here [--profile <name>] [--desc "<one-liner>"]           # brownfield: current dir, never overwrites
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TPL="$DIR/templates"

NAME="" ; HERE=false ; PROFILE="laravel-react" ; DESC="(fill in: one sentence — what this is and for whom)"
while [ $# -gt 0 ]; do
  case "$1" in
    --here) HERE=true ;;
    --profile) PROFILE="$2"; shift ;;
    --desc) DESC="$2"; shift ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) NAME="$1" ;;
  esac
  shift
done

PROF="$TPL/profiles/$PROFILE"
if [ ! -d "$PROF" ]; then
  echo "✗ Unknown profile '$PROFILE'. Available:"; ls "$TPL/profiles/"; exit 1
fi

case "$NAME" in
  /*|*".."*)
    if ! $HERE; then echo "✗ Unsafe project name: path traversal and absolute paths are not allowed"; exit 1; fi
    ;;
esac

if $HERE; then
  TARGET="$(pwd)"
  NAME="${NAME:-$(basename "$TARGET")}"
  PYTHON=""
  for candidate in python3 python py; do
    if command -v "$candidate" >/dev/null 2>&1; then PYTHON="$candidate"; break; fi
  done
  if [ -z "$PYTHON" ]; then
    echo "✗ BROWNFIELD_PYTHON_REQUIRED: install Python 3, then rerun; no files were changed"
    exit 1
  fi
  # Read-only and fail-closed: this MUST run before mkdir/cp/sed/mv/git init.
  "$PYTHON" "$DIR/scripts/contract_check.py" --target "$TARGET" || {
    echo "✗ Generate the read-only migration plan before changing files:"
    echo '  python "<MEOLOOM_ROOT>/scripts/contract_check.py" --target . --migration-plan'
    echo "✗ BROWNFIELD_CONTRACT_CONFLICT: migrate manually; see $DIR/docs/codex.md"
    exit 1
  }
else
  if [ -z "$NAME" ]; then echo "✗ Usage: init.sh <project-name> | init.sh --here"; exit 1; fi
  TARGET="$(pwd)/$NAME"
  if [ -e "$TARGET" ] && [ -n "$(ls -A "$TARGET" 2>/dev/null)" ]; then
    echo "✗ '$TARGET' exists and is not empty. Use: cd $NAME && init.sh --here"; exit 1
  fi
  mkdir -p "$TARGET"
fi

CREATED=0; SKIPPED=0
copy_if_missing() { # $1 src, $2 dst
  if [ -L "$2" ]; then echo "✗ UNSAFE_SYMLINK: ${2#"$TARGET"/}"; exit 1
  elif [ -e "$2" ]; then echo "  skip (exists): ${2#"$TARGET"/}"; SKIPPED=$((SKIPPED+1))
  else mkdir -p "$(dirname "$2")"; cp "$1" "$2"; echo "  + ${2#"$TARGET"/}"; CREATED=$((CREATED+1)); fi
}

validate_manifest_path() { # $1 canonical relative POSIX path
  local value="$1" part
  local -a manifest_parts=()
  [ -n "$value" ] || return 1
  # Allowlist (not denylist): a manifest path may contain only these
  # characters. Everything else — shell metacharacters, backslashes,
  # controls, spaces, quotes — is rejected before any file is written.
  case "$value" in
    /*) return 1 ;;
    *[!A-Za-z0-9._/-]*) return 1 ;;
  esac
  IFS='/' read -r -a manifest_parts <<< "$value"
  for part in "${manifest_parts[@]}"; do
    [ -n "$part" ] && [ "$part" != "." ] && [ "$part" != ".." ] || return 1
    case "$part" in *' '|*.) return 1 ;; esac
  done
}

materialize_manifest() { # validates every row before publishing any file
  local manifest="$DIR/templates/common/.meoloom-files.tsv"
  local header source target ownership action revision lifecycle extra target_key prior_key
  local -a sources=() targets=() ownerships=() actions=() revisions=() lifecycles=()
  [ -f "$manifest" ] || { echo "✗ SCAFFOLD_MANIFEST_MISSING: $manifest"; exit 1; }
  IFS= read -r header < "$manifest"
  case "$header" in
    '# GENERATED FROM REGISTRY — DO NOT EDIT; source_revision='*) ;;
    *) echo "✗ SCAFFOLD_MANIFEST_INVALID: bad provenance header"; exit 1 ;;
  esac
  while IFS=$'\t' read -r source target ownership action revision lifecycle extra; do
    [ -n "$source$target$ownership$action$revision$lifecycle$extra" ] || continue
    if [ -n "$extra" ] || ! validate_manifest_path "$source" || ! validate_manifest_path "$target"; then
      echo "✗ SCAFFOLD_MANIFEST_INVALID: malformed row"; exit 1
    fi
    case "$ownership" in dat-kit|adapter|user) ;; *) echo "✗ SCAFFOLD_MANIFEST_INVALID: ownership"; exit 1 ;; esac
    case "$action" in copy|render-pointer|preserve|RETIRE_LEGACY) ;; *) echo "✗ SCAFFOLD_MANIFEST_INVALID: action"; exit 1 ;; esac
    case "$lifecycle" in repo_only|migration_ready|scaffold_active|retired) ;; *) echo "✗ SCAFFOLD_MANIFEST_INVALID: lifecycle"; exit 1 ;; esac
    # render-pointer is defined as "render pointer semantics", not "byte-copy
    # the template" — Bash cannot render, so an active render-pointer row must
    # fail closed here, during validation, before anything is published.
    if [ "$lifecycle" = "scaffold_active" ] && [ "$action" = "render-pointer" ]; then
      echo "✗ SCAFFOLD_ACTION_UNIMPLEMENTED: active render-pointer rows require the Python renderer"; exit 1
    fi
    [[ "$revision" =~ ^(dat-kit|MeoLoom)\ [0-9]+\.[0-9]+(\.[0-9]+)?$ ]] || {
      echo "✗ SCAFFOLD_MANIFEST_INVALID: revision"; exit 1;
    }
    if ! { [ -f "$DIR/$source" ] && [ ! -L "$DIR/$source" ]; }; then
      echo "✗ SCAFFOLD_MANIFEST_INVALID: missing or linked source $source"; exit 1
    fi
    target_key="$(printf '%s' "$target" | tr '[:upper:]' '[:lower:]')"
    for prior_key in "${targets[@]}"; do
      [ "$target_key" != "$(printf '%s' "$prior_key" | tr '[:upper:]' '[:lower:]')" ] || {
        echo "✗ SCAFFOLD_MANIFEST_INVALID: duplicate target $target"; exit 1;
      }
    done
    sources+=("$source"); targets+=("$target"); ownerships+=("$ownership")
    actions+=("$action"); revisions+=("$revision"); lifecycles+=("$lifecycle")
  done < <(tail -n +2 "$manifest")
  local index
  for index in "${!sources[@]}"; do
    [ "${lifecycles[$index]}" = "scaffold_active" ] || continue
    case "${actions[$index]}" in
      copy) copy_if_missing "$DIR/${sources[$index]}" "$TARGET/${targets[$index]}" ;;
      *) echo "✗ SCAFFOLD_MANIFEST_INVALID: active non-materializing action"; exit 1 ;;
    esac
  done
}

fill_name() { # $1 file — replace placeholders in place (portable, no sed -i)
  local tmp; tmp="$(mktemp)"
  # escape sed-special chars in user input (\, &, and the | delimiter)
  local desc_esc; desc_esc=$(printf '%s' "$DESC" | sed -e 's/[\\&|]/\\&/g')
  local name_esc; name_esc=$(printf '%s' "$NAME" | sed -e 's/[\\&/]/\\&/g')
  sed -e "s/{{PROJECT_NAME}}/$name_esc/g" -e "s/{{PROFILE_NAME}}/$PROFILE/g" -e "s|{{PROJECT_DESC}}|$desc_esc|g" "$1" > "$tmp" && mv "$tmp" "$1"
}

echo "Scaffolding '$NAME' (profile: $PROFILE) into $TARGET"

# spec skeleton + lessons + canonical contract
for f in "$TPL"/common/spec/*.md; do copy_if_missing "$f" "$TARGET/spec/$(basename "$f")"; done
copy_if_missing "$TPL/common/lessons-learned/lessons-learned.md" "$TARGET/lessons-learned/lessons-learned.md"
copy_if_missing "$TPL/common/CONTEXT.md" "$TARGET/CONTEXT.md"
[ -e "$TARGET/CONTEXT.md" ] && fill_name "$TARGET/CONTEXT.md"
AGENTS_EXISTED=false
[ -e "$TARGET/AGENTS.md" ] && AGENTS_EXISTED=true
materialize_manifest
[ -e "$TARGET/lessons-learned/lessons-learned.md" ] && fill_name "$TARGET/lessons-learned/lessons-learned.md"
if ! $AGENTS_EXISTED; then fill_name "$TARGET/AGENTS.md"; fi

# Agent working rules — assemble profile sections beneath the canonical contract
if [ -e "$TARGET/docs/agent-working-rules.md" ]; then
  echo "  skip (exists): docs/agent-working-rules.md  → review $PROF/*.md and merge manually"; SKIPPED=$((SKIPPED+1))
else
  sed -e "/{{PROFILE_ARCHITECTURE}}/r $PROF/architecture.md" -e "/{{PROFILE_ARCHITECTURE}}/d" \
      -e "/{{PROFILE_GATES}}/r $PROF/gates.md"               -e "/{{PROFILE_GATES}}/d" \
      -e "/{{PROFILE_TRAPS}}/r $PROF/traps.md"               -e "/{{PROFILE_TRAPS}}/d" \
      "$TPL/common/docs/agent-working-rules.md.tpl" > "$TARGET/docs/agent-working-rules.md"
  fill_name "$TARGET/docs/agent-working-rules.md"
  echo "  + docs/agent-working-rules.md"; CREATED=$((CREATED+1))
fi

# git init (greenfield only, best-effort)
if ! $HERE && command -v git >/dev/null 2>&1 && [ ! -d "$TARGET/.git" ]; then
  (cd "$TARGET" && git init -q) && echo "  + git init" || echo "  ! git init failed (continue manually)"
fi

echo ""
echo "Done: $CREATED created, $SKIPPED skipped (existing files are never overwritten)."
echo "Next steps:"
echo "  1. Fill spec/ in order: 00-vision → 01-features → 02-architecture → 03-db-schema → 04-build-phases"
echo "  2. Review AGENTS.md and docs/agent-working-rules.md (profile: $PROFILE) — adjust gate commands to your compose services"
echo "  3. Start building: open Claude Code or Codex and run the MeoLoom build-loop (preflight first for autopilot)"
