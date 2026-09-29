#!/usr/bin/env bash
# Ordinary Treehouse worker custody, shared by fresh spawn and teardown.
# Source this library; fm_slot_claim and fm_slot_check take
# <project> <worktree> <state> <id> <token>.
# fm_slot_release takes the same arguments and is only called AFTER a guarded
# return succeeds. A failed spawn retains its claim for explicit recovery.
#
# Pool identity is the project's canonical Git common directory plus Git's
# registered linked worktree, never an origin URL or a directory basename.
# Separate same-origin clones are deliberately unsupported: no implicit adoption.
# Claims live in the linked worktree's Git admin directory, outside checked-out
# bytes and shared across Firstmate homes. Exclusive mkdir reserves publication;
# incomplete, existing, symlinked, or foreign claims refuse, never get repaired.
# The exact record binds project, worktree, state directory, task and generation.
# No process liveness, stale-time heuristic, or --force can transfer ownership.

fm_slot_identity() { # <project> <worktree>
  local project=$1 worktree=$2 project_common worktree_common top admin registered
  FM_SLOT_PROJECT=$(cd "$project" 2>/dev/null && pwd -P) || return 1
  FM_SLOT_WORKTREE=$(cd "$worktree" 2>/dev/null && pwd -P) || return 1
  project_common=$(git -C "$project" rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || return 1
  project_common=$(cd "$project_common" 2>/dev/null && pwd -P) || return 1
  worktree_common=$(git -C "$worktree" rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || return 1
  worktree_common=$(cd "$worktree_common" 2>/dev/null && pwd -P) || return 1
  if [ "$project_common" != "$worktree_common" ]; then
    printf "error: slot custody identity mismatch: project '%s' uses '%s', worktree '%s' uses '%s'; refusing before freshen or launch\n" \
      "$project" "$project_common" "$worktree" "$worktree_common" >&2
    return 1
  fi
  top=$(git -C "$worktree" rev-parse --show-toplevel 2>/dev/null) || return 1
  top=$(cd "$top" 2>/dev/null && pwd -P) || return 1
  [ "$top" = "$FM_SLOT_WORKTREE" ] && [ "$top" != "$FM_SLOT_PROJECT" ] || return 1
  registered=$(git -C "$project" -c core.quotePath=false worktree list --porcelain) || return 1
  printf '%s\n' "$registered" | grep -Fx "worktree $FM_SLOT_WORKTREE" >/dev/null || return 1
  admin=$(git -C "$worktree" rev-parse --absolute-git-dir 2>/dev/null) || return 1
  admin=$(cd "$admin" 2>/dev/null && pwd -P) || return 1
  [ "$(dirname "$admin")" = "$project_common/worktrees" ] || return 1
  FM_SLOT_CLAIM="$admin/fm-slot-claim"
}

fm_slot_record() { # <state> <id> <token>
  local state
  state=$(cd "$1" 2>/dev/null && pwd -P) || return 1
  # Records are line-oriented. Ambiguous paths or identifiers cannot own a slot.
  case "$state$2$3$FM_SLOT_PROJECT$FM_SLOT_WORKTREE" in *$'\n'*|*$'\r'*) return 1 ;; esac
  [ -n "$2" ] && [ -n "$3" ] || return 1
  printf 'v1\n%s\n%s\n%s\n%s\n%s\n' "$FM_SLOT_PROJECT" "$FM_SLOT_WORKTREE" "$state" "$2" "$3"
}

fm_slot_refuse() {
  printf "error: cannot prove task '%s' slot custody: project '%s', worktree '%s', claim '%s'; preserving the slot\n" \
    "$3" "$1" "$2" "${FM_SLOT_CLAIM:-unresolved}" >&2
  return 1
}

fm_slot_claim() { # <project> <worktree> <state> <id> <token>
  local record
  FM_SLOT_CLAIM=
  fm_slot_identity "$1" "$2" || { fm_slot_refuse "$1" "$2" "$4"; return 1; }
  record=$(fm_slot_record "$3" "$4" "$5") || return 1
  # Never rewrite a previous claim, even one naming the same task.
  if ! mkdir -m 700 "$FM_SLOT_CLAIM" 2>/dev/null; then
    fm_slot_refuse "$1" "$2" "$4"; return 1
  fi
  (umask 077; printf '%s\n' "$record" > "$FM_SLOT_CLAIM/owner") || return 1
  fm_slot_check "$@"
}

fm_slot_check() { # <project> <worktree> <state> <id> <token>
  local record
  FM_SLOT_CLAIM=
  fm_slot_identity "$1" "$2" || { fm_slot_refuse "$1" "$2" "$4"; return 1; }
  record=$(fm_slot_record "$3" "$4" "$5") || { fm_slot_refuse "$1" "$2" "$4"; return 1; }
  if [ ! -d "$FM_SLOT_CLAIM" ] || [ -L "$FM_SLOT_CLAIM" ] \
     || [ ! -f "$FM_SLOT_CLAIM/owner" ] || [ -L "$FM_SLOT_CLAIM/owner" ] \
     || ! printf '%s\n' "$record" | cmp -s - "$FM_SLOT_CLAIM/owner"; then
    fm_slot_refuse "$1" "$2" "$4"; return 1
  fi
}

# Compatibility for records predating custody. They may only clean slots with
# no claim at all; removing a token from a new record never authorizes cleanup.
fm_slot_check_record() { # <project> <worktree> <state> <id> <token>
  local admin
  admin=$(git -C "$2" rev-parse --absolute-git-dir 2>/dev/null || true)
  if [ -n "$5" ] || [ -e "$admin/fm-slot-claim" ] || [ -L "$admin/fm-slot-claim" ]; then
    fm_slot_check "$@" || return 1
  fi
}

fm_slot_release() { # <project> <worktree> <state> <id> <token>
  fm_slot_check "$@" || return 1
  rm -- "$FM_SLOT_CLAIM/owner" && rmdir -- "$FM_SLOT_CLAIM"
}
