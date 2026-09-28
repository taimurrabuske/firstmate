#!/usr/bin/env bash
# Regression tests for fm-spawn's pooled-worktree base refresh.
#
# A treehouse pool can return a clean detached worktree whose origin/main was
# advanced after the worktree was allocated.
# These tests drive the real spawn path with a fake terminal, then prove it
# starts the worker from the fetched origin/main tip or stops when origin is
# unreachable.
# Opt in to a real provider recheck with FM_TEST_REAL_TREEHOUSE=1; optionally set
# FM_TEST_TREEHOUSE_BIN to an absolute path to a staged, unmodified official binary.
# That probe uses only test-owned repositories, HOME and explicit Treehouse root;
# it never returns/resets a live slot or installs/patches the provider.
set -u

# shellcheck source=tests/fixtures.sh
. "$(dirname "${BASH_SOURCE[0]}")/fixtures.sh"

TMP_ROOT=$(fm_test_tmproot fm-spawn-pool-base-freshen)
TMP_ROOT=$(cd "$TMP_ROOT" && pwd -P)

make_case() {
  local name=$1 id=$2 default=${3:-main} case_dir home project origin pool publisher fakebin initial
  case_dir="$TMP_ROOT/$name"
  home="$case_dir/home"
  project="$case_dir/project"
  origin="$case_dir/origin.git"
  pool="$case_dir/pool"
  publisher="$case_dir/publisher"
  fakebin=$(make_spawn_fakebin "$case_dir/fake")

  mkdir -p "$home/data/$id" "$home/projects" "$home/state" "$home/config"
  printf 'codex\n' > "$home/config/crew-harness"
  printf 'brief for %s\n' "$id" > "$home/data/$id/brief.md"
  touch "$home/state/.last-watcher-beat"

  git init --quiet -b "$default" "$project"
  printf 'base\n' > "$project/README.md"
  git -C "$project" add README.md
  git -C "$project" -c user.name='Firstmate Tests' -c user.email='tests@example.invalid' commit -qm initial
  git clone --quiet --bare "$project" "$origin"
  git -C "$project" remote add origin "file://$origin"
  initial=$(git -C "$project" rev-parse HEAD)
  git -C "$project" worktree add --quiet --detach "$pool" "$initial"

  git clone --quiet "file://$origin" "$publisher"
  printf 'must survive a newly spawned branch\n' > "$publisher/advanced-main.txt"
  git -C "$publisher" add advanced-main.txt
  git -C "$publisher" -c user.name='Firstmate Tests' -c user.email='tests@example.invalid' commit -qm advance-main
  git -C "$publisher" push --quiet origin "$default"

  printf '%s\n' "$case_dir|$home|$project|$pool|$fakebin|$initial|$default"
}

read_case_record() {
  IFS='|' read -r CASE_DIR HOME_DIR PROJECT_DIR POOL_DIR FAKEBIN_DIR INITIAL_SHA DEFAULT_BRANCH <<EOF
$1
EOF
}

run_spawn() {
  local id=$1
  shift
  fm_test_run_spawn "$HOME_DIR" "$POOL_DIR" "$FAKEBIN_DIR" \
    "$id" "$PROJECT_DIR" "$@"
}

run_teardown() {
  local id=$1
  shift
  # No real process inventory or shared no-mistakes daemon is visible to cleanup.
  fm_fake_exit0 "$FAKEBIN_DIR" ps lsof no-mistakes gh gh-axi
  mkdir -p "$CASE_DIR/userhome"
  HOME="$CASE_DIR/userhome" FM_HOME="$HOME_DIR" FM_ROOT_OVERRIDE='' \
    FM_STATE_OVERRIDE="$HOME_DIR/state" FM_DATA_OVERRIDE="$HOME_DIR/data" \
    FM_CONFIG_OVERRIDE="$HOME_DIR/config" FM_PROJECTS_OVERRIDE="$HOME_DIR/projects" \
    FM_TEARDOWN_GUARD_DONE=1 PATH="$FAKEBIN_DIR:$PATH" \
    "$ROOT/bin/fm-teardown.sh" "$id" "$@" 2>&1
}

test_stale_pool_base_refreshes_before_branching() {
  local rec id out status current branch_head
  id='pool-current-base-r1'
  rec=$(make_case current-base "$id")
  read_case_record "$rec"

  out=$(run_spawn "$id" --mode no-mistakes --yolo off)
  status=$?
  expect_code 0 "$status" "spawn should refresh a stale pooled worktree"
  assert_contains "$out" "spawned $id" "spawn did not report success"
  current=$(git -C "$POOL_DIR" rev-parse origin/main)
  branch_head=$(git -C "$POOL_DIR" rev-parse HEAD)
  [ "$branch_head" = "$current" ] || fail "spawn left the pooled worktree on stale history"
  [ "$branch_head" != "$INITIAL_SHA" ] || fail "fixture did not prove origin/main advanced past the pool base"
  if [ "${FM_TEST_EVIDENCE:-0}" = 1 ]; then
    printf '# observed spawn: %s\n' "$(printf '%s\n' "$out" | tail -n 1)"
    printf '# observed base: HEAD=%s origin/main=%s advanced-main=%s\n' \
      "$branch_head" "$current" "$(cat "$POOL_DIR/advanced-main.txt")"
  fi

  out=$(run_teardown "$id")
  expect_code 0 "$?" "clean claimed task teardown failed: $out"
  id='pool-current-base-repeat-r1'
  mkdir -p "$HOME_DIR/data/$id"
  printf 'brief for %s\n' "$id" > "$HOME_DIR/data/$id/brief.md"
  out=$(run_spawn "$id" --mode no-mistakes --yolo off)
  status=$?
  expect_code 0 "$status" "repeating the base refresh should be idempotent"
  [ "$(git -C "$POOL_DIR" rev-parse HEAD)" = "$current" ] \
    || fail "an idempotent repeat moved the pool away from current origin/main"

  git -C "$POOL_DIR" checkout --quiet -b "fm/$id"
  git -C "$POOL_DIR" diff --exit-code origin/main...HEAD >/dev/null \
    || fail "a branch created after spawn differs from current origin/main"
  assert_grep 'must survive a newly spawned branch' "$POOL_DIR/advanced-main.txt" \
    "the branch created after spawn omitted advanced-main content"
  pass "a stale pooled worktree refreshes to current origin/main before a crew branch is created"
}

test_non_main_default_branch_refreshes_before_branching() {
  local rec id out status current branch_head
  id='pool-current-trunk-r2'
  rec=$(make_case current-trunk "$id" trunk)
  read_case_record "$rec"

  out=$(run_spawn "$id" --mode no-mistakes --yolo off)
  status=$?
  expect_code 0 "$status" "spawn should refresh a stale pooled worktree on a non-main default branch"
  current=$(git -C "$POOL_DIR" rev-parse "origin/$DEFAULT_BRANCH")
  branch_head=$(git -C "$POOL_DIR" rev-parse HEAD)
  [ "$branch_head" = "$current" ] || fail "spawn did not refresh to current origin/$DEFAULT_BRANCH"
  [ "$branch_head" != "$INITIAL_SHA" ] || fail "fixture did not prove origin/$DEFAULT_BRANCH advanced past the pool base"
  pass "a stale pooled worktree resolves and refreshes a non-main default branch"
}

test_unreachable_origin_refuses_stale_pool_base() {
  local rec id out status before after
  id='pool-unreachable-origin-r2'
  rec=$(make_case unreachable-origin "$id")
  read_case_record "$rec"
  git -C "$POOL_DIR" remote set-url origin "file://$CASE_DIR/missing-origin.git"
  before=$(git -C "$POOL_DIR" rev-parse HEAD)

  out=$(run_spawn "$id" --mode no-mistakes --yolo off)
  status=$?
  [ "$status" -ne 0 ] || fail "spawn succeeded despite an unreachable origin"
  assert_contains "$out" "could not fetch origin" \
    "spawn did not clearly refuse an unreachable origin"
  after=$(git -C "$POOL_DIR" rev-parse HEAD)
  [ "$after" = "$before" ] || fail "spawn changed the pooled worktree after origin became unreachable"
  if [ "${FM_TEST_EVIDENCE:-0}" = 1 ]; then
    printf '# observed unreachable-origin refusal: %s\n' "$(printf '%s\n' "$out" | tail -n 1)"
  fi
  pass "an unreachable origin refuses a potentially stale pooled worktree"
}

test_direct_pr_and_scout_refresh_before_launch() {
  local rec id out status contract current
  for contract in direct-pr scout; do
    id="pool-${contract}-r3"
    rec=$(make_case "$contract" "$id")
    read_case_record "$rec"
    if [ "$contract" = scout ]; then
      out=$(run_spawn "$id" --scout)
    else
      out=$(run_spawn "$id" --mode direct-PR --yolo off)
    fi
    status=$?
    expect_code 0 "$status" "$contract spawn should refresh a stale pooled worktree"
    current=$(git -C "$POOL_DIR" rev-parse origin/main)
    [ "$(git -C "$POOL_DIR" rev-parse HEAD)" = "$current" ] \
      || fail "$contract spawn did not start at current origin/main"
    assert_grep 'must survive a newly spawned branch' "$POOL_DIR/advanced-main.txt" \
      "$contract spawn omitted advanced-main content"
    if [ "${FM_TEST_EVIDENCE:-0}" = 1 ]; then
      printf '# observed %s spawn: %s\n' "$contract" "$(printf '%s\n' "$out" | tail -n 1)"
    fi
  done
  pass "direct-PR ships and scouts both refresh stale pooled worktrees before launch"
}

test_dirty_pool_refuses_without_discarding_work() {
  local rec id out status before
  id='pool-dirty-refusal-r4'
  rec=$(make_case dirty-refusal "$id")
  read_case_record "$rec"
  before=$(git -C "$POOL_DIR" rev-parse HEAD)
  printf 'keep this local work\n' > "$POOL_DIR/uncommitted.txt"
  git -C "$POOL_DIR" config status.showUntrackedFiles no

  out=$(run_spawn "$id" --mode no-mistakes --yolo off)
  status=$?
  [ "$status" -ne 0 ] || fail "spawn succeeded despite a dirty pooled worktree"
  assert_contains "$out" "is not clean" "spawn did not clearly refuse a dirty pooled worktree"
  [ "$(git -C "$POOL_DIR" rev-parse HEAD)" = "$before" ] \
    || fail "spawn moved HEAD while refusing a dirty pooled worktree"
  assert_grep 'keep this local work' "$POOL_DIR/uncommitted.txt" \
    "spawn discarded uncommitted work while refusing the pool"
  if [ "${FM_TEST_EVIDENCE:-0}" = 1 ]; then
    printf '# observed dirty refusal: %s; preserved=%s\n' \
      "$(printf '%s\n' "$out" | tail -n 1)" "$(cat "$POOL_DIR/uncommitted.txt")"
  fi
  pass "a dirty pooled worktree is refused without discarding its local work"
}

test_unresolved_remote_default_refuses_pool() {
  local rec id out status before
  id='pool-unresolved-default-r5'
  rec=$(make_case unresolved-default "$id")
  read_case_record "$rec"
  git --git-dir="$CASE_DIR/origin.git" symbolic-ref HEAD refs/heads/missing-default
  before=$(git -C "$POOL_DIR" rev-parse HEAD)

  out=$(run_spawn "$id" --mode no-mistakes --yolo off)
  status=$?
  [ "$status" -ne 0 ] || fail "spawn succeeded despite an unresolved remote default branch"
  assert_contains "$out" "could not resolve origin's current default branch" \
    "spawn did not clearly refuse an unresolved remote default branch"
  [ "$(git -C "$POOL_DIR" rev-parse HEAD)" = "$before" ] \
    || fail "spawn moved HEAD after failing to resolve the remote default branch"
  if [ "${FM_TEST_EVIDENCE:-0}" = 1 ]; then
    printf '# observed unresolved-default refusal: %s\n' "$(printf '%s\n' "$out" | tail -n 1)"
  fi
  pass "an unresolved remote default branch refuses the pooled worktree"
}

# A slot left on a stale submodule pin is the field failure this diagnosis exists
# for: a refresh moved the superproject and left the submodule behind, so the
# refusal fires a spawn later, on a slot whose own `git status` looks clean to the
# operator. Nothing here is converged - the gate only has to say why. The fixture
# only builds the repositories; the residue itself is produced by a real spawn, so
# these tests cover the reset that actually strands the submodule.
make_submodule_case() {  # <name> <id>
  local name=$1 id=$2 case_dir home project origin pool publisher fakebin sub subpin1 subpin2 advanced
  case_dir="$TMP_ROOT/$name"
  home="$case_dir/home"
  project="$case_dir/project"
  origin="$case_dir/origin.git"
  pool="$case_dir/pool"
  publisher="$case_dir/publisher"
  sub="$case_dir/sub-origin"
  fakebin=$(make_spawn_fakebin "$case_dir/fake")

  mkdir -p "$home/data/$id" "$home/projects" "$home/state" "$home/config"
  printf 'codex\n' > "$home/config/crew-harness"
  printf 'brief for %s\n' "$id" > "$home/data/$id/brief.md"
  touch "$home/state/.last-watcher-beat"

  git init --quiet -b main "$sub"
  printf 'pin one\n' > "$sub/lib.txt"
  git -C "$sub" add lib.txt
  git -C "$sub" -c user.name='Firstmate Tests' -c user.email='tests@example.invalid' commit -qm sub-one
  subpin1=$(git -C "$sub" rev-parse HEAD)
  printf 'pin two\n' > "$sub/lib.txt"
  git -C "$sub" -c user.name='Firstmate Tests' -c user.email='tests@example.invalid' commit -qam sub-two
  subpin2=$(git -C "$sub" rev-parse HEAD)
  git -C "$sub" checkout --quiet "$subpin1"

  git init --quiet -b main "$project"
  printf 'base\n' > "$project/README.md"
  git -C "$project" add README.md
  git -C "$project" -c protocol.file.allow=always -c user.name='Firstmate Tests' -c user.email='tests@example.invalid' \
    submodule --quiet add "file://$sub" ui
  git -C "$project" -c user.name='Firstmate Tests' -c user.email='tests@example.invalid' commit -qm initial
  git clone --quiet --bare "$project" "$origin"
  git -C "$project" remote add origin "file://$origin"
  git -C "$project" worktree add --quiet --detach "$pool" HEAD
  git -C "$pool" -c protocol.file.allow=always submodule --quiet update --init

  # Advance origin and move the submodule pin, exactly as the field incident did.
  git clone --quiet "file://$origin" "$publisher"
  git -C "$publisher" -c protocol.file.allow=always submodule --quiet update --init
  git -C "$publisher/ui" checkout --quiet "$subpin2"
  git -C "$publisher" -c user.name='Firstmate Tests' -c user.email='tests@example.invalid' commit -qam advance-pin
  git -C "$publisher" push --quiet origin main
  advanced=$(git -C "$publisher" rev-parse HEAD)

  printf '%s\n' "$case_dir|$home|$project|$pool|$fakebin|$subpin1|$subpin2|$advanced"
}

read_submodule_case() {
  IFS='|' read -r CASE_DIR HOME_DIR PROJECT_DIR POOL_DIR FAKEBIN_DIR SUBPIN1 SUBPIN2 ADVANCED_SHA <<EOF
$1
EOF
}

# The first of two consecutive spawns: it succeeds, resets the superproject onto
# the base that moved the pin, and leaves the submodule checkout on the pin the
# old base recorded. That reset is what strands the slot, so every case below
# starts from residue this code path actually produced rather than a hand-built one.
strand_submodule_pin_via_spawn() {  # <seed-id>
  local id=$1 out status
  mkdir -p "$HOME_DIR/data/$id"
  printf 'brief for %s\n' "$id" > "$HOME_DIR/data/$id/brief.md"
  out=$(run_spawn "$id" --scout)
  status=$?
  expect_code 0 "$status" "the spawn that moves the submodule pin should succeed"
  assert_contains "$out" "spawned $id" "the spawn that moves the submodule pin did not report success"
  [ "$(git -C "$POOL_DIR" rev-parse HEAD)" = "$ADVANCED_SHA" ] \
    || fail "the first spawn did not move the pooled base across the moved submodule pin"
  [ "$(git -C "$POOL_DIR/ui" rev-parse HEAD)" = "$SUBPIN1" ] \
    || fail "the first spawn did not strand the submodule on the pin the old base recorded"
  printf 'seed scout complete\n' > "$HOME_DIR/data/$id/report.md"
  printf 'decisions_reviewed=1\ndecision_keys=\n' >> "$HOME_DIR/state/$id.meta"
  out=$(run_teardown "$id")
  expect_code 0 "$?" "seed scout cleanup failed: $out"
}

test_stale_submodule_pin_explains_itself() {
  local rec id out status before before_sub
  id='pool-stale-pin-r7'
  rec=$(make_submodule_case stale-pin "$id")
  read_submodule_case "$rec"
  strand_submodule_pin_via_spawn 'pool-stale-pin-seed-r7'
  before=$(git -C "$POOL_DIR" rev-parse HEAD)
  before_sub=$(git -C "$POOL_DIR/ui" rev-parse HEAD)

  out=$(run_spawn "$id" --mode no-mistakes --yolo off)
  status=$?
  [ "$status" -ne 0 ] || fail "the second spawn launched from a slot carrying a stale submodule pin"
  assert_contains "$out" "stale submodule checkout" \
    "refusal did not name the cause as a stale submodule checkout"
  assert_contains "$out" "submodule 'ui'" "refusal did not name the submodule"
  assert_contains "$out" "$SUBPIN1" "refusal did not report the pin the slot actually has"
  assert_contains "$out" "$SUBPIN2" "refusal did not report the pin the base records"
  # No remedy is printed on purpose: the containment check reads local refs only,
  # so a stale remote-tracking ref can make an unpushed commit look contained, and
  # a checkout command on that judgement could cost the operator a commit.
  assert_not_contains "$out" "submodule update --checkout" \
    "refusal printed a remedy command the containment check cannot stand behind"
  assert_not_contains "$out" "refusing to discard uncommitted work" \
    "a stale pin was misreported as uncommitted work"
  [ "$(git -C "$POOL_DIR" rev-parse HEAD)" = "$before" ] \
    || fail "spawn moved HEAD while refusing a stale submodule pin"
  [ "$(git -C "$POOL_DIR/ui" rev-parse HEAD)" = "$before_sub" ] \
    || fail "spawn converged the submodule; this gate must never touch the slot"
  if [ "${FM_TEST_EVIDENCE:-0}" = 1 ]; then
    printf '# observed stale-pin refusal: %s\n' "$(printf '%s\n' "$out" | grep 'submodule' | head -n 1)"
  fi
  pass "two consecutive spawns across a moved submodule pin end in a refusal naming both pins and no remedy"
}

test_unpushed_submodule_commit_is_still_uncommitted_work() {
  local rec id out status unpushed before before_sub
  id='pool-sub-unpushed-r10'
  rec=$(make_submodule_case sub-unpushed "$id")
  read_submodule_case "$rec"
  strand_submodule_pin_via_spawn 'pool-sub-unpushed-seed-r10'
  # A commit made inside the submodule and never pushed leaves the submodule work
  # tree clean and the pins different - the same two facts a stale pin shows. Any
  # checkout of the recorded pin would move HEAD off this commit and leave it
  # unreferenced, so this case must keep the conservative refusal.
  printf 'unlanded submodule work\n' > "$POOL_DIR/ui/unlanded.txt"
  git -C "$POOL_DIR/ui" add unlanded.txt
  git -C "$POOL_DIR/ui" -c user.name='Firstmate Tests' -c user.email='tests@example.invalid' \
    commit -qm unlanded-submodule-work
  unpushed=$(git -C "$POOL_DIR/ui" rev-parse HEAD)
  [ -z "$(git -C "$POOL_DIR/ui" status --porcelain)" ] \
    || fail "fixture did not leave the submodule work tree clean"
  [ "$unpushed" != "$(git -C "$POOL_DIR" rev-parse "HEAD:ui")" ] \
    || fail "fixture did not leave the recorded pin different from what is checked out"
  before=$(git -C "$POOL_DIR" rev-parse HEAD)
  before_sub=$unpushed

  out=$(run_spawn "$id" --mode no-mistakes --yolo off)
  status=$?
  [ "$status" -ne 0 ] || fail "spawn launched from a slot holding an unpushed submodule commit"
  assert_contains "$out" "refusing to discard uncommitted work" \
    "an unpushed submodule commit was not refused as uncommitted work"
  assert_not_contains "$out" "stale submodule checkout" \
    "an unpushed submodule commit was misreported as a stale pin"
  assert_not_contains "$out" "is checked out at" \
    "an unpushed submodule commit still drew the stale-pin diagnosis"
  [ "$(git -C "$POOL_DIR/ui" rev-parse HEAD)" = "$before_sub" ] \
    || fail "spawn moved the submodule off its unpushed commit"
  git -C "$POOL_DIR/ui" cat-file -e "$unpushed^{commit}" \
    || fail "the unpushed submodule commit did not survive the refusal"
  assert_grep 'unlanded submodule work' "$POOL_DIR/ui/unlanded.txt" \
    "spawn discarded the unpushed submodule work while refusing the pool"
  [ "$(git -C "$POOL_DIR" rev-parse HEAD)" = "$before" ] \
    || fail "spawn moved HEAD while refusing a slot holding an unpushed submodule commit"
  pass "an unpushed submodule commit keeps the uncommitted-work refusal and survives it"
}

test_work_inside_submodule_is_still_uncommitted_work() {
  local rec id out status
  id='pool-sub-work-r8'
  rec=$(make_submodule_case sub-work "$id")
  read_submodule_case "$rec"
  strand_submodule_pin_via_spawn 'pool-sub-work-seed-r8'
  # Put the submodule back on the pin the base records, so the ONLY deviation is
  # real work inside it. This must never be softened into a stale-pin diagnosis.
  git -C "$POOL_DIR/ui" checkout --quiet "$SUBPIN2"
  printf 'work that must survive\n' > "$POOL_DIR/ui/keep-me.txt"

  out=$(run_spawn "$id" --mode no-mistakes --yolo off)
  status=$?
  [ "$status" -ne 0 ] || fail "spawn launched from a slot holding work inside a submodule"
  assert_contains "$out" "refusing to discard uncommitted work" \
    "work inside a submodule was not refused as uncommitted work"
  assert_not_contains "$out" "stale submodule checkout" \
    "real work inside a submodule was misreported as a stale pin"
  assert_grep 'work that must survive' "$POOL_DIR/ui/keep-me.txt" \
    "spawn discarded work inside the submodule while refusing the pool"
  pass "work inside a submodule is still refused as uncommitted work, not called stale"
}

test_stale_pin_carrying_real_work_is_not_called_stale() {
  local rec id out status
  id='pool-sub-both-r9'
  rec=$(make_submodule_case sub-both "$id")
  read_submodule_case "$rec"
  strand_submodule_pin_via_spawn 'pool-sub-both-seed-r9'
  # Stale pin AND real work inside it: calling this merely stale would be wrong, so
  # the refusal must stay the conservative one.
  printf 'work that must survive\n' > "$POOL_DIR/ui/keep-me.txt"

  out=$(run_spawn "$id" --mode no-mistakes --yolo off)
  status=$?
  [ "$status" -ne 0 ] || fail "spawn launched from a slot with a stale pin and work inside it"
  assert_contains "$out" "refusing to discard uncommitted work" \
    "a stale pin carrying real work was not refused as uncommitted work"
  assert_not_contains "$out" "stale submodule checkout" \
    "a submodule holding real work was reported as merely stale"
  assert_grep 'work that must survive' "$POOL_DIR/ui/keep-me.txt" \
    "spawn discarded work inside the submodule while refusing the pool"
  pass "a stale pin carrying real work is refused conservatively, never called stale"
}

test_stale_pin_beside_other_dirt_reports_one_verdict() {
  local rec id out status
  id='pool-sub-mixed-r11'
  rec=$(make_submodule_case sub-mixed "$id")
  read_submodule_case "$rec"
  strand_submodule_pin_via_spawn 'pool-sub-mixed-seed-r11'
  # Git sorts status paths, so the stale 'ui' entry is scanned before this file.
  # The conservative verdict must not arrive contradicted by a stale-pin line.
  printf 'notes the operator still wants\n' > "$POOL_DIR/zz-notes.txt"

  out=$(run_spawn "$id" --mode no-mistakes --yolo off)
  status=$?
  [ "$status" -ne 0 ] || fail "spawn launched from a slot with a stale pin beside an untracked file"
  assert_contains "$out" "refusing to discard uncommitted work" \
    "a stale pin beside an untracked file was not refused as uncommitted work"
  assert_not_contains "$out" "stale submodule checkout" \
    "a slot carrying more than a stale pin was reported as merely stale"
  assert_not_contains "$out" "is checked out at" \
    "the stale-pin diagnosis was printed alongside the conservative refusal"
  assert_grep 'notes the operator still wants' "$POOL_DIR/zz-notes.txt" \
    "spawn discarded the untracked file while refusing the pool"
  pass "a stale pin beside other dirt yields the conservative refusal alone, with no stale-pin line"
}

# Log the destructive refresh boundary, not implementation-source text.
record_git_calls() {
  local real_git
  real_git=$(command -v git)
  printf '#!/usr/bin/env bash\nprintf "%%s\\n" "$*" >> %q\nexec %q "$@"\n' \
    "$CASE_DIR/git-calls" "$real_git" > "$FAKEBIN_DIR/git"
  chmod +x "$FAKEBIN_DIR/git"
}

assert_no_refresh_or_launch() {
  if [ -f "$CASE_DIR/git-calls" ]; then
    assert_not_contains "$(cat "$CASE_DIR/git-calls")" ' fetch ' 'refusal fetched before proving custody'
    assert_not_contains "$(cat "$CASE_DIR/git-calls")" ' reset ' 'refusal reset before proving custody'
  fi
  assert_not_contains "$(cat "$CASE_DIR/launch.log" 2>/dev/null)" 'codex' 'refusal launched a worker'
}

commit_sentinel() {
  printf 'unique unlanded sentinel\n' > "$POOL_DIR/sentinel.txt"
  git -C "$POOL_DIR" add sentinel.txt
  git -C "$POOL_DIR" -c user.name=Tests -c user.email=tests@example.invalid commit -qm sentinel
  SENTINEL_HEAD=$(git -C "$POOL_DIR" rev-parse HEAD)
}

assert_sentinel() {
  [ "$(git -C "$POOL_DIR" rev-parse HEAD)" = "$SENTINEL_HEAD" ] || fail 'refusal changed sentinel HEAD'
  [ "$(cat "$POOL_DIR/sentinel.txt")" = 'unique unlanded sentinel' ] || fail 'refusal changed sentinel bytes'
  [ -z "$(git -C "$POOL_DIR" status --porcelain)" ] || fail 'refusal changed sentinel working tree'
}

test_separately_seeded_same_origin_refuses() {
  local id=pool-foreign-store out old_pool
  read_case_record "$(make_case foreign-store "$id")"
  old_pool=$POOL_DIR
  git clone --quiet "file://$CASE_DIR/origin.git" "$CASE_DIR/separate"
  POOL_DIR="$CASE_DIR/separate-slot"
  git -C "$CASE_DIR/separate" worktree add --quiet --detach "$POOL_DIR" HEAD
  [ "$(git -C "$POOL_DIR" remote get-url origin)" = "$(git -C "$PROJECT_DIR" remote get-url origin)" ] \
    || fail 'fixture origins do not match'
  commit_sentinel
  record_git_calls
  if out=$(FM_FAKE_LAUNCH_LOG="$CASE_DIR/launch.log" run_spawn "$id" --mode direct-PR --yolo off); then
    fail 'spawn adopted a separately seeded same-origin slot'
  fi
  assert_contains "$out" 'slot custody identity mismatch' 'missing identity diagnostic'
  assert_contains "$out" "$PROJECT_DIR/.git" 'missing expected common directory'
  assert_contains "$out" "$CASE_DIR/separate/.git" 'missing actual common directory'
  assert_contains "$out" "$POOL_DIR" 'missing refused slot path'
  assert_no_refresh_or_launch
  assert_sentinel
  [ "$(git -C "$old_pool" rev-parse HEAD)" = "$INITIAL_SHA" ] || fail 'refusal changed another slot'
  pass 'separately seeded same-origin slot refuses before refresh, preserving clean unlanded sentinel'
}

test_missing_and_incorrect_claim_refuse() {
  local variant id out claim before
  for variant in missing incorrect; do
    id="pool-claim-$variant"
    read_case_record "$(make_case "$id" "$id")"
    commit_sentinel
    claim="$(git -C "$POOL_DIR" rev-parse --absolute-git-dir)/fm-slot-claim"
    if [ "$variant" = incorrect ]; then
      (cd "$POOL_DIR" && bash "$ROOT/bin/fm-slot-custody.sh" claim "$PROJECT_DIR" "$HOME_DIR/state" other-task other-token) \
        || fail 'could not publish foreign fixture claim'
      before=$(cksum "$claim/owner")
    fi
    record_git_calls
    if out=$(FM_FAKE_SKIP_CLAIM=1 FM_FAKE_LAUNCH_LOG="$CASE_DIR/launch.log" run_spawn "$id" --mode direct-PR --yolo off); then
      fail "$variant claim allowed freshen/launch"
    fi
    assert_contains "$out" 'cannot prove task' 'missing claim refusal'
    assert_contains "$out" "$claim" 'missing exact claim path'
    assert_no_refresh_or_launch
    assert_sentinel
    if [ "$variant" = incorrect ]; then
      [ "$(cksum "$claim/owner")" = "$before" ] || fail 'foreign claim was changed'
      # Publication itself cannot overwrite an already-owned slot either.
      if (cd "$POOL_DIR" && bash "$ROOT/bin/fm-slot-custody.sh" claim "$PROJECT_DIR" "$HOME_DIR/state" "$id" replacement) >/dev/null 2>&1; then
        fail 'publisher adopted a foreign claim'
      fi
      [ "$(cksum "$claim/owner")" = "$before" ] || fail 'publisher rewrote foreign claim'
    else
      [ ! -e "$claim" ] || fail 'supervisor manufactured custody from a pane-path observation'
    fi
  done
  pass 'missing and foreign claims refuse before any refresh/launch and preserve unlanded bytes'
}

test_stale_same_store_path_cannot_claim_another_slot() {
  local id=pool-stale-same-store out actual
  read_case_record "$(make_case "$id" "$id")"
  commit_sentinel
  actual="$CASE_DIR/actual-acquired"
  git -C "$PROJECT_DIR" worktree add --quiet --detach "$actual" "$INITIAL_SHA"
  record_git_calls
  if out=$(FM_FAKE_ACQUIRED_PATH="$actual" FM_FAKE_LAUNCH_LOG="$CASE_DIR/launch.log" run_spawn "$id" --mode direct-PR --yolo off); then
    fail 'stale same-store observation acquired custody'
  fi
  assert_no_refresh_or_launch
  assert_sentinel
  [ ! -e "$(git -C "$POOL_DIR" rev-parse --absolute-git-dir)/fm-slot-claim" ] \
    || fail 'observed slot was claimed instead of actual acquired shell'
  pass 'same-store stale observation cannot manufacture a claim for an unowned slot'
}

test_teardown_requires_exact_custody() {
  local id=pool-teardown-custody out meta claim token before
  read_case_record "$(make_case "$id" "$id")"
  out=$(run_spawn "$id" --mode direct-PR --yolo off)
  expect_code 0 "$?" "valid claimed spawn failed: $out"
  meta="$HOME_DIR/state/$id.meta"
  claim="$(git -C "$POOL_DIR" rev-parse --absolute-git-dir)/fm-slot-claim"
  token=$(grep '^treehouse_claim=' "$meta" | cut -d= -f2-)
  [ -n "$token" ] && [ -f "$claim/owner" ] || fail 'spawn omitted durable custody'
  before=$(cksum "$claim/owner")
  cp "$claim/owner" "$CASE_DIR/owner.saved"
  # Wrong generation must refuse before branch, hook, endpoint or return cleanup.
  printf '\nforeign\n' >> "$claim/owner"
  git -C "$POOL_DIR" checkout --quiet -b "fm/$id"
  printf '#!/usr/bin/env bash\necho returned >> %q\n' "$CASE_DIR/returned" > "$FAKEBIN_DIR/treehouse"
  if out=$(run_teardown "$id" --force); then fail 'force teardown accepted incorrect custody'; fi
  assert_contains "$out" 'cannot prove task' 'teardown omitted custody refusal'
  [ ! -e "$CASE_DIR/returned" ] || fail 'teardown returned an incorrectly owned slot'
  [ "$(git -C "$POOL_DIR" branch --show-current)" = "fm/$id" ] || fail 'refusal detached branch'
  [ -f "$meta" ] || fail 'refusal removed task record'
  # Restore only this fixture's originally published owner record.
  cp "$CASE_DIR/owner.saved" "$claim/owner"
  [ "$(cksum "$claim/owner")" = "$before" ] || fail 'fixture did not restore exact claim'
  mv "$claim" "$claim.saved"
  if out=$(run_teardown "$id"); then fail 'teardown accepted missing custody'; fi
  [ ! -e "$CASE_DIR/returned" ] || fail 'missing claim reached return'
  mv "$claim.saved" "$claim"
  out=$(run_teardown "$id")
  expect_code 0 "$?" "valid custody teardown failed: $out"
  [ -f "$CASE_DIR/returned" ] || fail 'valid custody did not reach guarded return'
  [ ! -e "$claim" ] && [ ! -e "$meta" ] || fail 'successful teardown retained ownership'
  pass 'guarded teardown refuses wrong/missing custody and releases the exact successful claim'
}

test_explicit_canonical_mapping_publishes_and_releases() {
  local id=pool-canonical-linked out canonical claim token returned
  read_case_record "$(make_case canonical-linked "$id")"
  canonical=$PROJECT_DIR
  PROJECT_DIR="$CASE_DIR/registered clone"
  git clone --quiet "file://$CASE_DIR/origin.git" "$PROJECT_DIR"
  git -C "$PROJECT_DIR" config --local firstmate.treehouseRepository "$canonical"
  out=$(FM_FAKE_ALLOCATION_LOG="$CASE_DIR/allocation.log" run_spawn "$id" --mode direct-PR --yolo off)
  expect_code 0 "$?" "explicit canonical-linked spawn failed: $out"
  assert_contains "$(cat "$CASE_DIR/allocation.log")" "cd '$canonical' && treehouse get" \
    'allocation did not enter the explicit canonical repository'
  claim="$(git -C "$POOL_DIR" rev-parse --absolute-git-dir)/fm-slot-claim"
  token=$(grep '^treehouse_claim=' "$HOME_DIR/state/$id.meta" | cut -d= -f2-)
  [ -n "$token" ] && [ -f "$claim/owner" ] || fail 'canonical-linked claim was skipped'
  assert_grep 'v2' "$claim/owner" 'mapped claim did not bind the allocation source'
  [ "$(git -C "$POOL_DIR" rev-parse HEAD)" = "$(git -C "$POOL_DIR" rev-parse origin/main)" ] \
    || fail 'claimed canonical-linked slot did not freshen'
  returned="$CASE_DIR/returned-from"
  printf '#!/usr/bin/env bash\npwd -P > %q\n' "$returned" > "$FAKEBIN_DIR/treehouse"
  # A mapping change cannot transfer an already published claim at cleanup.
  git -C "$PROJECT_DIR" config --local --unset firstmate.treehouseRepository
  if out=$(run_teardown "$id"); then fail 'removed canonical mapping authorized cleanup'; fi
  [ ! -e "$returned" ] && [ -f "$claim/owner" ] || fail 'mapping refusal changed custody'
  git -C "$PROJECT_DIR" config --local firstmate.treehouseRepository "$canonical"
  out=$(run_teardown "$id")
  expect_code 0 "$?" "canonical-linked cleanup failed: $out"
  [ "$(cat "$returned")" = "$canonical" ] || fail 'return resolved a different pool than acquire'
  [ ! -e "$claim" ] || fail 'canonical-linked cleanup did not release its exact claim'
  pass 'explicit canonical mapping allocates, publishes, freshens and returns in the same Git store'
}

test_canonical_mapping_rejects_wrong_store_and_missing_claim() {
  local variant id out canonical wrong
  for variant in wrong-store missing-claim; do
    id="pool-canonical-$variant"
    read_case_record "$(make_case "$id" "$id")"
    canonical=$PROJECT_DIR
    PROJECT_DIR="$CASE_DIR/registered"
    git clone --quiet "file://$CASE_DIR/origin.git" "$PROJECT_DIR"
    git -C "$PROJECT_DIR" config --local firstmate.treehouseRepository "$canonical"
    if [ "$variant" = wrong-store ]; then
      wrong="$CASE_DIR/wrong-slot"
      git -C "$PROJECT_DIR" worktree add --quiet --detach "$wrong" HEAD
      POOL_DIR=$wrong
    fi
    commit_sentinel
    record_git_calls
    if out=$(FM_FAKE_SKIP_CLAIM=1 FM_FAKE_LAUNCH_LOG="$CASE_DIR/launch.log" run_spawn "$id" --mode direct-PR --yolo off); then
      fail "canonical $variant allowed freshen or launch"
    fi
    assert_no_refresh_or_launch
    assert_sentinel
    [ ! -e "$(git -C "$POOL_DIR" rev-parse --absolute-git-dir)/fm-slot-claim" ] \
      || fail 'canonical refusal manufactured a claim'
  done
  pass 'canonical mapping still refuses wrong-store and unpublished custody without touching unlanded bytes'
}

test_claimed_unlanded_head_refuses() {
  local id=pool-claimed-unlanded out
  read_case_record "$(make_case "$id" "$id")"
  commit_sentinel
  if out=$(run_spawn "$id" --mode direct-PR --yolo off); then fail 'freshen discarded a claimed unlanded HEAD'; fi
  assert_contains "$out" 'unlanded or unverifiable commits' 'missing preservation refusal'
  assert_sentinel
  pass 'even valid custody cannot freshen away unlanded commits'
}

test_treehouse_not_returned_preserves_claim() {
  local id=pool-return-exit3 out claim before head
  read_case_record "$(make_case "$id" "$id")"
  out=$(run_spawn "$id" --mode direct-PR --yolo off)
  expect_code 0 "$?" "exit-3 fixture spawn failed: $out"
  claim="$(git -C "$POOL_DIR" rev-parse --absolute-git-dir)/fm-slot-claim"
  before=$(cksum "$claim/owner")
  head=$(git -C "$POOL_DIR" rev-parse HEAD)
  printf '#!/usr/bin/env bash\necho attempted >> %q\necho "worktree not returned: cleaning declined" >&2\nexit 3\n' \
    "$CASE_DIR/return-attempts" > "$FAKEBIN_DIR/treehouse"
  if out=$(run_teardown "$id"); then fail 'Treehouse exit 3 was accepted as a successful return'; fi
  assert_contains "$out" 'worktree not returned' 'return-aborted diagnostic lost'
  [ "$(wc -l < "$CASE_DIR/return-attempts" | tr -d ' ')" = 1 ] || fail 'not-returned result was automatically retried'
  [ "$(cksum "$claim/owner")" = "$before" ] || fail 'exit 3 released or rewrote the claim'
  [ -f "$HOME_DIR/state/$id.meta" ] || fail 'exit 3 removed the task metadata'
  [ "$(git -C "$POOL_DIR" rev-parse HEAD)" = "$head" ] || fail 'exit 3 changed retained HEAD'
  pass 'Treehouse not-returned exit 3 refuses cleanup without retry or claim release'
}

test_invalid_mapping_refuses_before_allocation() {
  local variant id out mapping
  for variant in relative empty duplicate subdirectory missing; do
    id="pool-mapping-$variant"
    read_case_record "$(make_case "$id" "$id")"
    case "$variant" in
      relative) mapping=../project ;;
      empty) mapping= ;;
      duplicate) mapping=$PROJECT_DIR ;;
      subdirectory) mkdir "$PROJECT_DIR/subdir"; mapping="$PROJECT_DIR/subdir" ;;
      missing) mapping="$CASE_DIR/absent" ;;
    esac
    git -C "$PROJECT_DIR" config --local firstmate.treehouseRepository "$mapping"
    if [ "$variant" = duplicate ]; then
      git -C "$PROJECT_DIR" config --local --add firstmate.treehouseRepository "$mapping"
    fi
    if out=$(FM_FAKE_ALLOCATION_LOG="$CASE_DIR/allocation.log" run_spawn "$id" --mode direct-PR --yolo off); then
      fail "$variant repository mapping permitted allocation: $out"
    fi
    [ ! -e "$CASE_DIR/allocation.log" ] || fail "$variant mapping reached Treehouse allocation"
    [ "$(git -C "$POOL_DIR" rev-parse HEAD)" = "$INITIAL_SHA" ] || fail 'invalid mapping changed HEAD'
  done
  pass 'invalid or ambiguous explicit repository mappings refuse before allocation'
}

fixture_treehouse() { # <binary> <canonical-repository> <fixture-dir> [args...]
  local provider=$1 canonical=$2 fixture=$3
  shift 3
  # Placement and shell-origin environment from the worker must not escape the
  # explicit fixture root, including when testing newer official releases.
  (cd "$canonical" && env -u TREEHOUSE_DIR -u TREEHOUSE_WORKTREE_PATH \
    -u TREEHOUSE_UNIQUE_LEAF -u TREEHOUSE_APFS_SHARING \
    HOME="$fixture/provider-home" XDG_CONFIG_HOME="$fixture/provider-home/.config" \
    XDG_CACHE_HOME="$fixture/provider-home/.cache" \
    "$provider" --root "$fixture/provider-root" "$@")
}

# Opt-in provider capability probe: only disposable repositories, a private
# HOME (no operator hooks/config), and an explicit root beneath this fixture.
# No shared pool is discovered, no lease record is edited, and no return/reset
# is requested. Cleanup removes the entire test-owned world via tests/lib.sh.
# The ordinary suite keeps using fake terminals/providers; this probe tests
# the actual installed CLI, and prints its path/version for later rechecks.
test_installed_treehouse_lease_and_canonical_claim() {
  [ "${FM_TEST_REAL_TREEHOUSE:-0}" = 1 ] || return 0
  local id=pool-real-provider provider version provider_bytes canonical first second third first_path second_path third_path out before claim clean_head
  provider=${FM_TEST_TREEHOUSE_BIN:-$(command -v treehouse)}
  case "$provider" in /*) ;; *) fail 'real provider probe requires an absolute executable path' ;; esac
  [ -x "$provider" ] || fail 'real provider probe requires an executable treehouse binary'
  version=$("$provider" --version) || fail 'cannot read installed treehouse version'
  provider_bytes=$(cksum "$provider") || fail 'cannot identify installed provider bytes'
  printf '# installed provider: %s %s\n' "$provider" "$version"
  read_case_record "$(make_case "$id" "$id")"
  canonical=$PROJECT_DIR
  PROJECT_DIR="$CASE_DIR/registered clone"
  git clone --quiet "file://$CASE_DIR/origin.git" "$PROJECT_DIR"
  git -C "$PROJECT_DIR" config --local firstmate.treehouseRepository "$canonical"
  git -C "$canonical" fetch --quiet origin
  mkdir -p "$CASE_DIR/provider-home" "$CASE_DIR/provider-root"
  first=$(fixture_treehouse "$provider" "$canonical" "$CASE_DIR" get --lease --json --no-fetch --lease-holder "$id") \
    || fail 'isolated real provider acquire failed'
  first_path=$(printf '%s\n' "$first" | python3 -c 'import json,sys; print(json.load(sys.stdin)["path"])') \
    || fail 'provider did not return a JSON lease path'
  case "$first_path" in "$CASE_DIR/provider-root/"*) ;; *) fail 'provider escaped explicit fixture root' ;; esac
  POOL_DIR=$first_path
  # Real Git identity plus the existing acquired-shell stub proves publication
  # against a slot actually allocated from the explicitly mapped repository.
  out=$(run_spawn "$id" --mode direct-PR --yolo off)
  expect_code 0 "$?" "real-provider canonical slot did not publish/start: $out"
  claim="$(git -C "$POOL_DIR" rev-parse --absolute-git-dir)/fm-slot-claim"
  [ -f "$claim/owner" ] || fail 'real-provider canonical slot claim was skipped'
  clean_head=$(git -C "$POOL_DIR" rev-parse HEAD)
  before=$(cksum "$claim/owner")
  # No worker process is left in the clean, landed slot. Its durable lease, not process
  # liveness or our Git-admin claim, must keep a stopped task out of allocation.
  second=$(fixture_treehouse "$provider" "$canonical" "$CASE_DIR" get --lease --json --no-fetch --lease-holder next-task) \
    || fail 'isolated next-task acquire failed'
  second_path=$(printf '%s\n' "$second" | python3 -c 'import json,sys; print(json.load(sys.stdin)["path"])') \
    || fail 'provider did not return the second JSON lease path'
  case "$second_path" in "$CASE_DIR/provider-root/"*) ;; *) fail 'second allocation escaped fixture root' ;; esac
  [ "$first_path" != "$second_path" ] || fail 'provider reused a durably leased stopped slot'
  [ "$(git -C "$POOL_DIR" rev-parse HEAD)" = "$clean_head" ] || fail 'provider moved a clean kept-original slot'
  assert_grep 'must survive a newly spawned branch' "$POOL_DIR/advanced-main.txt" 'provider changed kept-original bytes'
  commit_sentinel
  third=$(fixture_treehouse "$provider" "$canonical" "$CASE_DIR" get --lease --json --no-fetch --lease-holder third-task) \
    || fail 'isolated third-task acquire failed'
  third_path=$(printf '%s\n' "$third" | python3 -c 'import json,sys; print(json.load(sys.stdin)["path"])') \
    || fail 'provider did not return the third JSON lease path'
  case "$third_path" in "$CASE_DIR/provider-root/"*) ;; *) fail 'third allocation escaped fixture root' ;; esac
  [ "$third_path" != "$first_path" ] && [ "$third_path" != "$second_path" ] || fail 'provider reused a stopped leased slot'
  assert_sentinel
  [ "$(cksum "$claim/owner")" = "$before" ] || fail 'next allocation changed the retained task claim'
  [ "$("$provider" --version)" = "$version" ] && [ "$(cksum "$provider")" = "$provider_bytes" ] \
    || fail 'installed provider changed during probe; rerun after the external update completes'
  pass 'installed provider explicit-root durable lease retains stopped work and canonical claim publication succeeds'
}

test_installed_treehouse_lease_and_canonical_claim
test_treehouse_not_returned_preserves_claim
test_invalid_mapping_refuses_before_allocation
test_explicit_canonical_mapping_publishes_and_releases
test_canonical_mapping_rejects_wrong_store_and_missing_claim
test_claimed_unlanded_head_refuses
test_separately_seeded_same_origin_refuses
test_missing_and_incorrect_claim_refuse
test_stale_same_store_path_cannot_claim_another_slot
test_teardown_requires_exact_custody
test_stale_pool_base_refreshes_before_branching
test_non_main_default_branch_refreshes_before_branching
test_direct_pr_and_scout_refresh_before_launch
test_dirty_pool_refuses_without_discarding_work
test_unresolved_remote_default_refuses_pool
test_unreachable_origin_refuses_stale_pool_base
test_stale_submodule_pin_explains_itself
test_unpushed_submodule_commit_is_still_uncommitted_work
test_work_inside_submodule_is_still_uncommitted_work
test_stale_pin_carrying_real_work_is_not_called_stale
test_stale_pin_beside_other_dirt_reports_one_verdict

echo "# all fm-spawn-pool-base-freshen tests passed"
