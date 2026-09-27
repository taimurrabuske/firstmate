#!/usr/bin/env bash
# Tests for bin/fm-branch-retire.sh's guarded, idempotent branch retirement.
#
# A landed ship task's local branch is deleted from its project clone only
# after cleanup succeeded, and only under every guard the script's header
# owns. Matrix:
#   (a) branch head ancestor of up-to-date origin/main      -> RETIRE
#   (b) branch head ancestor of local main only (direct-push /
#       local-only lane, origin behind)                     -> RETIRE
#   (c) squash-merge lane: branch content already in fresh
#       origin/main, commits not ancestors                  -> RETIRE
#   (d) unlanded branch (real content, nothing landed)      -> REFUSE, kept
#   (e) branch checked out in another existing worktree,
#       even landed                                         -> REFUSE, kept
#   (f) branch checked out in another existing worktree
#       that is dirty                                       -> REFUSE, kept
#   (g) idempotent: rerun after retirement                  -> success
#   (h) legacy fm-<id> naming                               -> RETIRE
#   (i) both fm/<id> and fm-<id> exist                      -> REFUSE, kept
#   (j) stale worktree registration (directory gone)        -> RETIRE (prune)
#   (k) kind=scout record                                   -> skip, kept
#   (l) missing record: skip without --project, retire with it
#   (m) failed origin fetch still honors an ancestry proof
#       on already-fetched refs                             -> RETIRE
#   (n) --help exits 0
set -u

# shellcheck source=tests/lib.sh disable=SC1091
. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
fm_git_identity fmtest fmtest@example.invalid

RETIRE="$ROOT/bin/fm-branch-retire.sh"
TMP_ROOT=$(fm_test_tmproot fm-branch-retire-tests)
ID=task-br1
CANON="fm/$ID"
LEGACY="fm-$ID"

# Build a fresh sandbox for one test case. Sets up:
#   $CASE/state/        - firstmate state dir holding $ID.meta
#   $CASE/origin.git/   - bare upstream with one commit on main
#   $CASE/project/      - clone of origin; the firstmate project dir
# Echoes the case dir.
make_case() {
  local name=$1 case_dir seed
  case_dir="$TMP_ROOT/$name"
  mkdir -p "$case_dir/state"
  git init -q --bare "$case_dir/origin.git"
  git -C "$case_dir/origin.git" symbolic-ref HEAD refs/heads/main
  seed="$case_dir/_seed"
  git clone -q "$case_dir/origin.git" "$seed"
  printf 'baseline\n' > "$seed/README.md"
  git -C "$seed" add README.md
  git -C "$seed" -c user.name=t -c user.email=t@t commit -qm "origin baseline"
  git -C "$seed" push -q origin main
  rm -rf "$seed"
  git clone -q "$case_dir/origin.git" "$case_dir/project"
  git -C "$case_dir/project" remote set-head origin main 2>/dev/null || true
  write_meta "$case_dir" ship
  printf '%s\n' "$case_dir"
}

write_meta() {  # <case-dir> <kind> [extra kv...]
  local case_dir=$1 kind=$2
  shift 2
  fm_write_meta "$case_dir/state/$ID.meta" \
    "window=firstmate:fm-$ID" \
    "endpoint_task_id=$ID" \
    "worktree=$case_dir/wt" \
    "project=$case_dir/project" \
    "harness=claude" \
    "kind=$kind" \
    "mode=no-mistakes" \
    "yolo=off" \
    "spawn_gen=spawn-$ID" \
    "$@"
}

# Commit a real file on the task branch in the project clone, then return the
# project's checkout to main so the branch itself is not checked out there.
branch_commit() {  # <case-dir> <file> <content>
  local case_dir=$1 file=$2 content=$3
  git -C "$case_dir/project" checkout -q -B "$CANON" origin/main
  printf '%s\n' "$content" > "$case_dir/project/$file"
  git -C "$case_dir/project" add -- "$file"
  git -C "$case_dir/project" -c user.name=t -c user.email=t@t commit -qm "add $file"
  git -C "$case_dir/project" checkout -q main
}

branch_exists() {  # <case-dir> <branch>
  git -C "$case_dir/project" show-ref --verify --quiet "refs/heads/$2"
}

retire() {  # <case-dir> [args...]
  local case_dir=$1
  shift
  FM_ROOT_OVERRIDE="$ROOT" FM_STATE_OVERRIDE="$case_dir/state" \
    "$RETIRE" "$ID" "$@"
}

branch_gone() {  # <case-dir> <label> <branch>
  if branch_exists "$1" "$3"; then
    fail "$2: branch $3 should have been retired"
  fi
}

branch_kept() {  # <case-dir> <label> <branch>
  if ! branch_exists "$1" "$3"; then
    fail "$2: branch $3 should have been kept"
  fi
}

# (a) Landed: branch head is an ancestor of the up-to-date origin default.
test_landed_origin_ancestor_retires() {
  local case_dir out rc=0
  case_dir=$(make_case origin-ancestor)
  branch_commit "$case_dir" feature.txt hello
  git -C "$case_dir/project" checkout -q main
  git -C "$case_dir/project" merge -q --ff-only "$CANON"
  git -C "$case_dir/project" push -q origin main

  out=$(retire "$case_dir" 2>&1) || rc=$?
  expect_code 0 "$rc" "origin-ancestor: retirement should succeed: $out"
  branch_gone "$case_dir" "origin-ancestor" "$CANON"
  assert_contains "$out" "retired" "origin-ancestor: no retirement report"
  pass "branch whose head is an ancestor of origin main is retired"
}

# (b) Direct-push lane: branch fast-forwarded into local main only.
test_landed_local_default_ancestor_retires() {
  local case_dir out rc=0
  case_dir=$(make_case local-ancestor)
  branch_commit "$case_dir" feature.txt hello
  git -C "$case_dir/project" checkout -q main
  git -C "$case_dir/project" merge -q --ff-only "$CANON"

  out=$(retire "$case_dir" 2>&1) || rc=$?
  expect_code 0 "$rc" "local-ancestor: retirement should succeed: $out"
  branch_gone "$case_dir" "local-ancestor" "$CANON"
  pass "branch fast-forwarded into the local default branch (origin behind) is retired"
}

# (c) Squash-merge lane: content landed on origin main under a new commit.
test_squash_landed_retires() {
  local case_dir out rc=0 tmp
  case_dir=$(make_case squash-landed)
  branch_commit "$case_dir" feature.txt hello
  git -C "$case_dir/project" checkout -q main
  tmp="$case_dir/_land"
  git clone -q "$case_dir/origin.git" "$tmp"
  printf '%s\n' "hello" > "$tmp/feature.txt"
  git -C "$tmp" add feature.txt
  git -C "$tmp" -c user.name=t -c user.email=t@t commit -qm "squash feature"
  git -C "$tmp" push -q origin HEAD:main
  rm -rf "$tmp"

  out=$(retire "$case_dir" 2>&1) || rc=$?
  expect_code 0 "$rc" "squash-landed: retirement should succeed: $out"
  branch_gone "$case_dir" "squash-landed" "$CANON"
  pass "squash-landed branch (content in fresh origin main, not an ancestor) is retired"
}

# (d) Unlanded: real branch content that landed nowhere.
test_unlanded_branch_refuses() {
  local case_dir out rc=0
  case_dir=$(make_case unlanded)
  branch_commit "$case_dir" feature.txt "secret work"

  out=$(retire "$case_dir" 2>&1) || rc=$?
  expect_code 1 "$rc" "unlanded: retirement should refuse"
  branch_kept "$case_dir" "unlanded" "$CANON"
  assert_contains "$out" "cannot prove" "unlanded: refusal did not say why"
  pass "unlanded branch is refused and kept with the reason on stderr"
}

# (e) Landed but checked out in another existing worktree.
test_checked_out_elsewhere_refuses() {
  local case_dir out rc=0
  case_dir=$(make_case checked-out)
  branch_commit "$case_dir" feature.txt hello
  git -C "$case_dir/project" checkout -q main
  git -C "$case_dir/project" merge -q --ff-only "$CANON"
  git -C "$case_dir/project" push -q origin main
  git -C "$case_dir/project" worktree add -q "$case_dir/holder" "$CANON"

  out=$(retire "$case_dir" 2>&1) || rc=$?
  expect_code 1 "$rc" "checked-out: retirement should refuse"
  branch_kept "$case_dir" "checked-out" "$CANON"
  assert_contains "$out" "checked out" "checked-out: refusal did not name the holder"
  pass "landed branch checked out in an existing worktree is refused"
}

# (f) Same guard with a dirty holder worktree.
test_dirty_holder_refuses() {
  local case_dir out rc=0
  case_dir=$(make_case dirty-holder)
  branch_commit "$case_dir" feature.txt hello
  git -C "$case_dir/project" checkout -q main
  git -C "$case_dir/project" merge -q --ff-only "$CANON"
  git -C "$case_dir/project" push -q origin main
  git -C "$case_dir/project" worktree add -q "$case_dir/holder" "$CANON"
  printf 'uncommitted\n' > "$case_dir/holder/scratch.txt"

  out=$(retire "$case_dir" 2>&1) || rc=$?
  expect_code 1 "$rc" "dirty-holder: retirement should refuse"
  branch_kept "$case_dir" "dirty-holder" "$CANON"
  pass "dirty worktree holding the branch is refused"
}

# (g) Idempotent: the run after a successful retirement is success.
test_idempotent_rerun_succeeds() {
  local case_dir out rc=0
  case_dir=$(make_case idempotent)
  branch_commit "$case_dir" feature.txt hello
  git -C "$case_dir/project" checkout -q main
  git -C "$case_dir/project" merge -q --ff-only "$CANON"
  git -C "$case_dir/project" push -q origin main

  out=$(retire "$case_dir" 2>&1) || fail "first retirement failed: $out"
  out=$(retire "$case_dir" 2>&1) || rc=$?
  expect_code 0 "$rc" "idempotent: rerun should succeed: $out"
  assert_contains "$out" "already retired" "idempotent: rerun did not report already retired"
  pass "rerunning retirement on an already-deleted branch is success"
}

# (h) Legacy fm-<id> naming alone is retired.
test_legacy_prefix_retires() {
  local case_dir out rc=0
  case_dir=$(make_case legacy)
  git -C "$case_dir/project" checkout -q -B "$LEGACY" origin/main
  printf '%s\n' hello > "$case_dir/project/feature.txt"
  git -C "$case_dir/project" add feature.txt
  git -C "$case_dir/project" -c user.name=t -c user.email=t@t commit -qm "legacy work"
  git -C "$case_dir/project" checkout -q main
  git -C "$case_dir/project" merge -q --ff-only "$LEGACY"
  git -C "$case_dir/project" push -q origin main

  out=$(retire "$case_dir" 2>&1) || rc=$?
  expect_code 0 "$rc" "legacy: retirement should succeed: $out"
  branch_gone "$case_dir" "legacy" "$LEGACY"
  pass "legacy fm-<id> branch naming is resolved and retired"
}

# (i) Both candidate namings exist: ambiguous, refuse, keep both.
test_ambiguous_candidates_refuse() {
  local case_dir out rc=0
  case_dir=$(make_case ambiguous)
  branch_commit "$case_dir" feature.txt hello
  git -C "$case_dir/project" branch -q "$LEGACY" "$CANON"

  out=$(retire "$case_dir" 2>&1) || rc=$?
  expect_code 1 "$rc" "ambiguous: retirement should refuse"
  branch_kept "$case_dir" "ambiguous" "$CANON"
  branch_kept "$case_dir" "ambiguous" "$LEGACY"
  assert_contains "$out" "ambiguous" "ambiguous: refusal did not explain"
  pass "both candidate branches existing is refused with both kept"
}

# (j) Stale registration: holder worktree directory gone, registration left.
test_stale_registration_allows() {
  local case_dir out rc=0
  case_dir=$(make_case stale-registration)
  branch_commit "$case_dir" feature.txt hello
  git -C "$case_dir/project" checkout -q main
  git -C "$case_dir/project" merge -q --ff-only "$CANON"
  git -C "$case_dir/project" push -q origin main
  git -C "$case_dir/project" worktree add -q "$case_dir/holder" "$CANON"
  git -C "$case_dir/project" checkout -q main
  rm -rf "$case_dir/holder"

  out=$(retire "$case_dir" 2>&1) || rc=$?
  expect_code 0 "$rc" "stale-registration: retirement should succeed: $out"
  branch_gone "$case_dir" "stale-registration" "$CANON"
  pass "a returned worktree's stale registration does not block retirement"
}

# (k) A scout record is a silent skip, not a deletion.
test_scout_record_skips() {
  local case_dir out rc=0
  case_dir=$(make_case scout)
  branch_commit "$case_dir" feature.txt hello
  write_meta "$case_dir" scout

  out=$(retire "$case_dir" 2>&1) || rc=$?
  expect_code 0 "$rc" "scout: skip should exit 0: $out"
  branch_kept "$case_dir" "scout" "$CANON"
  [ -z "$out" ] || fail "scout: skip should be silent, got: $out"
  pass "scout records skip silently with the branch kept"
}

# (l) Missing record: skip without --project; explicit project still retires.
test_missing_record_skip_and_explicit_project() {
  local case_dir out rc=0
  case_dir=$(make_case no-record)
  branch_commit "$case_dir" feature.txt hello
  git -C "$case_dir/project" checkout -q main
  git -C "$case_dir/project" merge -q --ff-only "$CANON"
  git -C "$case_dir/project" push -q origin main
  rm -f "$case_dir/state/$ID.meta"

  out=$(retire "$case_dir" 2>&1) || rc=$?
  expect_code 0 "$rc" "no-record: skip should exit 0: $out"
  branch_kept "$case_dir" "no-record" "$CANON"
  [ -z "$out" ] || fail "no-record: skip should be silent, got: $out"

  out=$(retire "$case_dir" --project "$case_dir/project" 2>&1) || rc=$?
  expect_code 0 "$rc" "no-record: explicit project should retire: $out"
  branch_gone "$case_dir" "no-record" "$CANON"
  pass "missing record skips, while --project still retires a landed branch"
}

# (m) A failed origin fetch must not invalidate an ancestry proof on
# already-fetched refs.
test_failed_fetch_keeps_ancestry_proof() {
  local case_dir out rc=0
  case_dir=$(make_case fetch-fails)
  branch_commit "$case_dir" feature.txt hello
  git -C "$case_dir/project" checkout -q main
  git -C "$case_dir/project" merge -q --ff-only "$CANON"
  git -C "$case_dir/project" push -q origin main
  git -C "$case_dir/project" remote set-url origin "$case_dir/does-not-exist.git"

  out=$(retire "$case_dir" 2>&1) || rc=$?
  expect_code 0 "$rc" "fetch-fails: ancestry proof should still retire: $out"
  branch_gone "$case_dir" "fetch-fails" "$CANON"
  pass "a failed origin fetch does not invalidate an ancestry proof"
}

# (n) --help exits 0 and prints usage.
test_help_exits_zero() {
  local out rc=0
  out=$("$RETIRE" --help 2>&1) || rc=$?
  expect_code 0 "$rc" "help should exit 0"
  assert_contains "$out" "Usage:" "help did not print usage"
  pass "--help prints usage and exits 0"
}

test_landed_origin_ancestor_retires
test_landed_local_default_ancestor_retires
test_squash_landed_retires
test_unlanded_branch_refuses
test_checked_out_elsewhere_refuses
test_dirty_holder_refuses
test_idempotent_rerun_succeeds
test_legacy_prefix_retires
test_ambiguous_candidates_refuse
test_stale_registration_allows
test_scout_record_skips
test_missing_record_skip_and_explicit_project
test_failed_fetch_keeps_ancestry_proof
test_help_exits_zero
