#!/usr/bin/env bash
# Ensure a project worktree follows the agent-memory file convention.
# Two correct layouts are accepted, chosen by what the repository itself
# already carries; the helper never converts one correct layout into the
# other.
# - Pointer layout (created by default): AGENTS.md is the real
#   project-intrinsic knowledge file and CLAUDE.md is a real regular file
#   whose canonical content is the two-line @AGENTS.md pointer that Claude
#   Code inlines at load time.
# - Alias layout (accepted, never created): the repository's own convention
#   keeps the real instructions in CLAUDE.md and carries AGENTS.md as a
#   symlink to that file. A correct alias - one resolving to the sibling
#   real CLAUDE.md - is preserved; the self-governance section is still
#   injected idempotently through the link into the real instructions file,
#   and no CLAUDE.md pointer is written there because CLAUDE.md is that
#   file. Dangling or foreign AGENTS.md symlinks are refused.
# Migration from the pointer layout, for a repository inside a workspace whose
# own convention is the alias layout:
#   mv AGENTS.md CLAUDE.md      # real memory replaces the disposable two-line pointer
#   ln -s CLAUDE.md AGENTS.md   # re-create the alias (bare relative target)
#   git add AGENTS.md CLAUDE.md
# The swap is lossless because the canonical pointer's two lines are disposable
# by design, git records the symlink as mode 120000, and the bare relative
# target resolves inside fresh clones and linked worktrees alike. After it the
# helper is idempotent ("unchanged: AGENTS.md -> CLAUDE.md alias layout"),
# injecting the self-governance section once if it is missing. On hosts without
# symlink support (Windows without core.symlinks=true plus developer mode) a
# fresh clone materializes AGENTS.md as a small plain file; Linux and macOS
# fleets are unaffected. The reverse direction - only when a repository leaves
# the alias workspace - is: rm AGENTS.md, mv CLAUDE.md AGENTS.md, then write
# the canonical two-line pointer into CLAUDE.md.
# Creates a minimal AGENTS.md skeleton when neither file exists, promotes a
# real CLAUDE.md file when it is the only file present (unless it is already
# the canonical pointer), converts a correct CLAUDE.md -> AGENTS.md symlink
# into the pointer file, and refuses to clobber distinct real files or wrong
# symlinks.
# Owns the canonical "## Maintaining this file" self-governance wording for
# project AGENTS.md files, injecting it idempotently into created skeletons,
# promoted CLAUDE.md files, any existing AGENTS.md that still lacks it, and,
# through a correct AGENTS.md -> CLAUDE.md alias, the real instructions file.
# Owns the canonical CLAUDE.md pointer content (the exact two-line @AGENTS.md
# form). A real-file pointer cannot follow a write into AGENTS.md, which is why
# the installer never creates a CLAUDE.md symlink.
# Refuses a case-variant real memory file such as a lowercase agents.md, so the
# pointer's @AGENTS.md import resolves to a real AGENTS.md on a case-sensitive
# filesystem (issue #389). The real-file pointer also eliminates the old
# uppercase-literal-target dangling-symlink hazard that a CLAUDE.md -> AGENTS.md
# link would have carried for that same mismatch.
# This is a worktree utility for crewmates, not a supervision script, so it does
# not call fm-guard.sh.
# Usage: fm-ensure-agents-md.sh [repo-or-worktree-dir]
set -eu

usage() {
  echo "usage: fm-ensure-agents-md.sh [repo-or-worktree-dir]" >&2
}

case "${1:-}" in
  -h|--help)
    usage
    exit 0
    ;;
esac
[ "$#" -le 1 ] || { usage; exit 1; }

DIR=${1:-.}
[ -d "$DIR" ] || { echo "error: not a directory: $DIR" >&2; exit 1; }
DIR=$(cd "$DIR" && pwd -P)
cd "$DIR"

AGENTS=AGENTS.md
CLAUDE=CLAUDE.md

write_maintenance_section() {
  cat <<'EOF'
## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
EOF
}

write_maintenance_section_with_eol() {
  local eol=$1 line
  while IFS= read -r line; do
    printf '%s%s' "$line" "$eol"
  done < <(write_maintenance_section)
}

# Idempotently append the canonical self-governance section to AGENTS.md when it
# is absent. Sets MAINT_INJECTED=1 when it appends and 0 when the section is
# already present, so callers can report whether the file changed.
MAINT_INJECTED=0
ensure_maintenance_section() {
  MAINT_INJECTED=0
  if grep -Fqx '## Maintaining this file' "$AGENTS" ||
    grep -Fqx $'## Maintaining this file\r' "$AGENTS"; then
    return 0
  fi
  local eol=$'\n' sep=''
  if LC_ALL=C grep -q $'\r$' "$AGENTS"; then
    eol=$'\r\n'
  fi
  if [ -s "$AGENTS" ]; then
    if [ -n "$(tail -c 1 "$AGENTS")" ]; then
      sep="${eol}${eol}"
    else
      sep=$eol
    fi
  fi
  {
    printf '%s' "$sep"
    write_maintenance_section_with_eol "$eol"
  } >> "$AGENTS"
  MAINT_INJECTED=1
}

write_skeleton() {
  cat > "$AGENTS" <<'EOF'
# Project agent memory

This file is the project's committed home for project-intrinsic agent knowledge: build, test, release, architecture, and sharp-edge notes that should travel with the code.

- Add durable project-specific notes here as they are discovered through real work.
EOF
  ensure_maintenance_section
}

# Canonical CLAUDE.md pointer: a real file, never a symlink. Byte-identical
# two-line form so a stray write clobbers only this recoverable pointer.
claude_pointer_content() {
  cat <<'EOF'
<!-- Points Claude at AGENTS.md via import; edit AGENTS.md, not this file. -->
@AGENTS.md
EOF
}

is_canonical_claude_pointer() {
  [ -f "$CLAUDE" ] && [ ! -L "$CLAUDE" ] || return 1
  claude_pointer_content | cmp -s - "$CLAUDE"
}

# Write the canonical pointer as a regular file. Unlink a symlink first so the
# write cannot follow it and destroy AGENTS.md. Never overwrite a distinct real
# file; callers classify that as a conflict before invoking this.
install_claude_pointer() {
  if is_canonical_claude_pointer; then
    return 0
  fi
  if [ -L "$CLAUDE" ]; then
    rm -- "$CLAUDE"
  elif [ -e "$CLAUDE" ]; then
    echo "error: internal: refuse to overwrite existing CLAUDE.md" >&2
    exit 1
  fi
  claude_pointer_content > "$CLAUDE"
}

is_correct_claude_symlink() {
  [ -L "$CLAUDE" ] || return 1
  target=$(readlink "$CLAUDE")
  case "$target" in
    "$AGENTS"|"./$AGENTS") return 0 ;;
  esac
  [ -e "$AGENTS" ] || return 1
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$CLAUDE" "$AGENTS" <<'PY'
import os
import sys
sys.exit(0 if os.path.realpath(sys.argv[1]) == os.path.realpath(sys.argv[2]) else 1)
PY
    return $?
  fi
  return 1
}

# Alias layout: the repository's own convention keeps the real instructions in
# CLAUDE.md and carries AGENTS.md as a plain symlink to it. Correct means the
# link resolves to the sibling real CLAUDE.md - the bare or ./ relative form,
# or any target whose resolved path is that same file. CLAUDE.md must be a
# real regular file, so a dangling link, a foreign target, a two-link loop,
# or a link chain never matches.
is_correct_agents_alias() {
  [ -L "$AGENTS" ] || return 1
  [ -f "$CLAUDE" ] && [ ! -L "$CLAUDE" ] || return 1
  target=$(readlink "$AGENTS")
  case "$target" in
    "$CLAUDE"|"./$CLAUDE") return 0 ;;
  esac
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$AGENTS" "$CLAUDE" <<'PY'
import os
import sys
sys.exit(0 if os.path.realpath(sys.argv[1]) == os.path.realpath(sys.argv[2]) else 1)
PY
    return $?
  fi
  return 1
}

# Refuse a case-variant real memory file (issue #389). On a case-insensitive
# filesystem an existing lowercase agents.md satisfies every [ -e AGENTS.md ]
# test below, so the script would emit a CLAUDE.md pointer whose @AGENTS.md
# import dangles once the tree is checked out on a case-sensitive filesystem.
# Reading the real directory entries catches the mismatch on both filesystem
# kinds; surface it for manual reconciliation instead of writing the pointer
# against the wrong name.
for entry in *; do
  if [ ! -e "$entry" ] && [ ! -L "$entry" ]; then
    continue
  fi
  if [ "$entry" != "$AGENTS" ]; then
    case "$entry" in
      [Aa][Gg][Ee][Nn][Tt][Ss].[Mm][Dd])
        echo "conflict: memory file is named $entry in $DIR but the convention is AGENTS.md; rename it to AGENTS.md so CLAUDE.md's @AGENTS.md pointer resolves portably" >&2
        exit 1
        ;;
    esac
  fi
done

if [ -L "$AGENTS" ]; then
  if is_correct_agents_alias; then
    ensure_maintenance_section
    if [ "$MAINT_INJECTED" -eq 1 ]; then
      echo "updated: added ## Maintaining this file to the AGENTS.md -> CLAUDE.md alias in $DIR"
    else
      echo "unchanged: AGENTS.md -> CLAUDE.md alias layout in $DIR"
    fi
    exit 0
  fi
  if [ ! -e "$AGENTS" ]; then
    echo "conflict: AGENTS.md is a broken symlink in $DIR; expected it to resolve to the real CLAUDE.md" >&2
    exit 1
  fi
  if [ ! -f "$CLAUDE" ] || [ -L "$CLAUDE" ]; then
    echo "conflict: AGENTS.md is a symlink in $DIR but CLAUDE.md is not a real file for it to alias" >&2
    exit 1
  fi
  echo "conflict: AGENTS.md -> $(readlink "$AGENTS") in $DIR does not resolve to the real CLAUDE.md; an AGENTS.md alias must point at the repository's real instructions file" >&2
  exit 1
fi
if [ -e "$AGENTS" ] && [ ! -f "$AGENTS" ]; then
  echo "conflict: AGENTS.md exists in $DIR but is not a regular file" >&2
  exit 1
fi

if [ -e "$AGENTS" ]; then
  if [ -L "$CLAUDE" ]; then
    if is_correct_claude_symlink; then
      ensure_maintenance_section
      install_claude_pointer
      if [ "$MAINT_INJECTED" -eq 1 ]; then
        echo "updated: added ## Maintaining this file to AGENTS.md and wrote CLAUDE.md @AGENTS.md pointer in $DIR"
      else
        echo "updated: replaced CLAUDE.md symlink with @AGENTS.md pointer in $DIR"
      fi
      exit 0
    fi
    echo "conflict: CLAUDE.md is a symlink in $DIR but does not point to AGENTS.md" >&2
    exit 1
  fi
  if [ ! -e "$CLAUDE" ]; then
    ensure_maintenance_section
    install_claude_pointer
    if [ "$MAINT_INJECTED" -eq 1 ]; then
      echo "updated: added ## Maintaining this file to AGENTS.md and wrote CLAUDE.md @AGENTS.md pointer in $DIR"
    else
      echo "wrote: CLAUDE.md @AGENTS.md pointer in $DIR"
    fi
    exit 0
  fi
  if [ -f "$CLAUDE" ]; then
    if is_canonical_claude_pointer; then
      ensure_maintenance_section
      if [ "$MAINT_INJECTED" -eq 1 ]; then
        echo "updated: added ## Maintaining this file to AGENTS.md in $DIR"
      else
        echo "unchanged: AGENTS.md with CLAUDE.md @AGENTS.md pointer in $DIR"
      fi
      exit 0
    fi
    echo "conflict: both AGENTS.md and CLAUDE.md are real files in $DIR; reconcile them manually" >&2
    exit 1
  fi
  echo "conflict: CLAUDE.md exists in $DIR but is not a regular file or symlink" >&2
  exit 1
fi

if [ -L "$CLAUDE" ]; then
  if is_correct_claude_symlink; then
    write_skeleton
    install_claude_pointer
    echo "created: AGENTS.md and wrote CLAUDE.md @AGENTS.md pointer in $DIR"
    exit 0
  fi
  echo "conflict: CLAUDE.md is a symlink in $DIR but AGENTS.md is missing and the link does not point to AGENTS.md" >&2
  exit 1
fi

if [ -e "$CLAUDE" ]; then
  if [ -f "$CLAUDE" ]; then
    if is_canonical_claude_pointer; then
      write_skeleton
      echo "created: AGENTS.md and kept CLAUDE.md @AGENTS.md pointer in $DIR"
      exit 0
    fi
    mv "$CLAUDE" "$AGENTS"
    ensure_maintenance_section
    install_claude_pointer
    echo "promoted: moved CLAUDE.md to AGENTS.md and wrote CLAUDE.md @AGENTS.md pointer in $DIR"
    exit 0
  fi
  echo "conflict: CLAUDE.md exists in $DIR but is not a regular file or symlink" >&2
  exit 1
fi

write_skeleton
install_claude_pointer
echo "created: AGENTS.md and CLAUDE.md @AGENTS.md pointer in $DIR"
