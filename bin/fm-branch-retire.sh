#!/usr/bin/env bash
# fm-branch-retire.sh - retire a landed ship task's local branch from its
# project clone, so finished tasks stop accumulating refs in the shared
# repository (GitHub auto-deletes merged PR heads; this owns the LOCAL half,
# including direct-push and local-only lanes where no PR head ever existed).
#
# This is the guarded branch half of task cleanup. It runs only after a ship
# task's cleanup has succeeded - the ordinary landed-work and slot-original
# safety gates in bin/fm-teardown.sh stay unchanged and run first - and it
# deletes ONLY the local branch recorded for that one task id, resolved as
# fm/<id> with a legacy fm-<id> fallback for older branch naming.
#
# Guards (all required; any refusal leaves the branch exactly in place):
#   - The task record must be kind=ship. A missing record, or another kind
#     (scout, secondmate), is a silent no-op skip, not an error.
#   - Exactly one candidate branch may exist: fm/<id> or legacy fm-<id>. Both
#     existing is ambiguous and refused; neither existing is idempotent
#     success. No other ref is ever derived, globbed, or touched, so archive
#     refs and every other task's branches are out of reach by construction.
#   - The branch must not be checked out in any worktree of the shared
#     repository whose directory still exists. A registration whose directory
#     is gone records a returned worktree that holds nothing, so it does not
#     block retirement; any dead registration that would make git refuse the
#     deletion is pruned (registrations only, never directories, pool slots,
#     or live worktrees) before one retried deletion.
#   - Landing is re-proved here before deletion, independent of whatever the
#     caller already checked: the branch head is an ancestor of the up-to-date
#     origin default branch (fetched here when origin exists), or an ancestor
#     of the local default branch (the direct-push lane where the branch
#     itself was the landing, such as a local-only fast-forward merge), or the
#     branch introduces no content the default branch lacks (squash-merge
#     lanes, judged by the same merge-tree tree-equality test
#     bin/fm-teardown.sh uses). An unprovable branch keeps its ref and the
#     refusal says why: it may be the sole remaining copy of that work. A
#     failed origin fetch only disables the squash-lane content proof; a
#     positive ancestry proof on an already-fetched ref stays valid.
#   - Deletion is one plain `git branch -D` of the proven ref, re-verified
#     immediately before deletion. The -D form is required because
#     squash-landed branches are intentionally not merge-ancestors (plain -d
#     would refuse them); it is safe here because it only ever runs after the
#     landing proof and checkout guard passed, never as a way around them.
#
# Callers: bin/fm-teardown.sh (after its destructive cleanup and project
# refresh, with --project because the task record is already removed by then)
# and the interrupted-cleanup replay in bin/fm-bootstrap.sh (record still
# present, default resolution). Both callers hold the task's meta lock, so
# this script reads state/<id>.meta without taking that lock itself; a
# standalone run without the lock only risks a torn read, which fails safely
# into a refusal. The project clone's refs are the only thing this script
# mutates; it never touches worktrees, pool slots, or another home's
# namespace.
#
# Usage: fm-branch-retire.sh <task-id> [--project <path>]
#        fm-branch-retire.sh --help
# Exit codes: 0 retired, already retired, or not applicable (skip);
#             1 refused (the branch was kept; stderr says why);
#             2 usage error.
set -eu

usage() {
  cat <<'EOF'
Usage: fm-branch-retire.sh <task-id> [--project <path>]

Retire a landed ship task's local branch (fm/<id>, legacy fm-<id>) from its
project clone. Guards: ship record required; single unambiguous branch
candidate; not checked out in any existing worktree; landing proven (ancestor
of the up-to-date origin default branch, ancestor of the local default branch,
or no content the default branch lacks). Idempotent: an already-deleted branch
is success. A refused branch is kept and the reason goes to stderr.
EOF
}

die() {
  echo "REFUSED: $*" >&2
  exit 1
}

# Skips (not applicable) are deliberately silent: callers embed this script in
# teardown and the session-start replay, where a routine no-op must not add
# digest noise. Refusals and retirements are the only reported outcomes.
skip() {
  exit 0
}

if [ "${1:-}" = "--help" ]; then
  usage
  exit 0
fi
if [ "$#" -lt 1 ] || [ "$#" -gt 3 ]; then
  usage >&2
  exit 2
fi
ID=$1
case $ID in
  ''|.*|*[!A-Za-z0-9._-]*) die "invalid task id '$ID'" ;;
esac
shift
EXPLICIT_PROJECT=
while [ "$#" -gt 0 ]; do
  case $1 in
    --project)
      if [ "$#" -lt 2 ]; then
        usage >&2
        exit 2
      fi
      EXPLICIT_PROJECT=$2
      shift 2
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FM_HOME="${FM_HOME:-${FM_ROOT_OVERRIDE:-$(cd "$SCRIPT_DIR/.." && pwd)}}"
STATE="${FM_STATE_OVERRIDE:-$FM_HOME/state}"
META="$STATE/$ID.meta"

meta_value() {  # <key>
  sed -n "s/^$1=//p" "$META" | head -1
}

if [ -n "$EXPLICIT_PROJECT" ]; then
  PROJ=$EXPLICIT_PROJECT
else
  if [ ! -f "$META" ] || [ -L "$META" ]; then
    skip "task $ID has no record at $META; nothing names its project clone"
  fi
  PROJ=$(meta_value project)
  if [ -z "$PROJ" ]; then
    die "task $ID's record at $META names no project clone"
  fi
fi
if [ -f "$META" ] && [ ! -L "$META" ]; then
  KIND=$(meta_value kind)
  if [ -n "$KIND" ] && [ "$KIND" != ship ]; then
    skip "task $ID is kind=$KIND, not a ship task; branch retirement does not apply"
  fi
fi
if ! git -C "$PROJ" rev-parse --git-dir >/dev/null 2>&1; then
  die "project clone $PROJ is not a readable git repository"
fi

CANON="fm/$ID"
LEGACY="fm-$ID"
BRANCH=
for cand in "$CANON" "$LEGACY"; do
  if git -C "$PROJ" show-ref --verify --quiet "refs/heads/$cand"; then
    if [ -n "$BRANCH" ]; then
      die "both $BRANCH and $cand exist in $PROJ; ambiguous which is task $ID's branch"
    fi
    BRANCH=$cand
  fi
done
if [ -z "$BRANCH" ]; then
  echo "already retired: no $CANON or $LEGACY branch exists in $PROJ"
  exit 0
fi
HEAD_SHA=$(git -C "$PROJ" rev-parse --verify --quiet "refs/heads/$BRANCH") \
  || die "cannot read branch $BRANCH in $PROJ"

# Checked-out guard: a registration whose directory still exists holds the
# branch; a registration whose directory is gone records a returned worktree
# and does not block (its dead registration is pruned below only if git would
# otherwise refuse the deletion).
holder=$(git -C "$PROJ" -c core.quotePath=false worktree list --porcelain 2>/dev/null \
  | awk -v want="refs/heads/$BRANCH" '
      /^worktree / { path=substr($0, 10); checked="" }
      $1 == "branch" { checked=$2 }
      checked == want && path != "" { print path; exit }
    ') || holder=
if [ -n "$holder" ] && [ -e "$holder" ]; then
  die "branch $BRANCH is checked out in worktree $holder; retire it only after that worktree is gone"
fi

default_branch() {
  local ref branch
  ref=$(git -C "$PROJ" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null || true)
  if [ -n "$ref" ]; then
    printf '%s\n' "${ref#origin/}"
    return 0
  fi
  for branch in main master; do
    if git -C "$PROJ" show-ref --verify --quiet "refs/heads/$branch"; then
      printf '%s\n' "$branch"
      return 0
    fi
  done
  return 1
}

DEFAULT=$(default_branch) \
  || die "cannot determine the default branch of $PROJ; expected origin/HEAD, main, or master"
ORIGIN_DEFAULT="refs/remotes/origin/$DEFAULT"
LOCAL_DEFAULT="refs/heads/$DEFAULT"
has_origin=0
fetched=0
if git -C "$PROJ" remote get-url origin >/dev/null 2>&1; then
  has_origin=1
  if git -C "$PROJ" fetch --quiet origin "+refs/heads/$DEFAULT:$ORIGIN_DEFAULT" >/dev/null 2>&1; then
    fetched=1
  fi
fi

landed=
if git -C "$PROJ" merge-base --is-ancestor "$HEAD_SHA" "$ORIGIN_DEFAULT" 2>/dev/null; then
  landed="ancestor of the up-to-date $ORIGIN_DEFAULT"
elif git -C "$PROJ" merge-base --is-ancestor "$HEAD_SHA" "$LOCAL_DEFAULT" 2>/dev/null; then
  landed="ancestor of local default branch $DEFAULT (direct-push lane)"
else
  # Squash-merge lanes: the branch's commits are intentionally not ancestors,
  # so require a fresh origin ref (a failed fetch leaves the comparison to a
  # stale default unconclusive) or the local default, then prove the branch
  # adds no content the default lacks. Same standard as bin/fm-teardown.sh's
  # content_in_default.
  content_ref=
  if [ "$has_origin" = 1 ] && [ "$fetched" = 1 ]; then
    content_ref=$ORIGIN_DEFAULT
  elif git -C "$PROJ" show-ref --verify --quiet "$LOCAL_DEFAULT"; then
    content_ref=$LOCAL_DEFAULT
  fi
  if [ -n "$content_ref" ]; then
    default_tree=$(git -C "$PROJ" rev-parse --verify --quiet "$content_ref^{tree}" 2>/dev/null || true)
    merged_tree=$(git -C "$PROJ" merge-tree --write-tree "$content_ref" "$HEAD_SHA" 2>/dev/null | head -1 || true)
    if [ -n "$default_tree" ] && [ "$merged_tree" = "$default_tree" ]; then
      landed="content already present in $content_ref (squash-merge lane)"
    fi
  fi
fi
if [ -z "$landed" ]; then
  die "cannot prove branch $BRANCH ($HEAD_SHA) landed in $DEFAULT of $PROJ; leaving it in place as the possible sole remaining copy of that work"
fi

current=$(git -C "$PROJ" rev-parse --verify --quiet "refs/heads/$BRANCH") || current=
if [ "$current" != "$HEAD_SHA" ]; then
  die "branch $BRANCH moved while retiring (proved $HEAD_SHA, found ${current:-nothing}); rerun to re-prove the new head"
fi
if ! git -C "$PROJ" branch -D -- "$BRANCH" >/dev/null 2>&1; then
  # A dead registration of a returned worktree can make git refuse the
  # deletion; prune registrations of missing directories only (never
  # directories, pool slots, or live worktrees), then retry once loudly.
  git -C "$PROJ" worktree prune >/dev/null 2>&1 || true
  git -C "$PROJ" branch -D -- "$BRANCH" >/dev/null
fi
if git -C "$PROJ" show-ref --verify --quiet "refs/heads/$BRANCH"; then
  die "branch $BRANCH still exists after the deletion attempt in $PROJ"
fi
echo "retired: deleted landed branch $BRANCH (was $HEAD_SHA) from $PROJ [$landed]"
