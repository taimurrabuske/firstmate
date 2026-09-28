#!/usr/bin/env bash
# Publish a fresh Treehouse slot claim from the ACQUIRED shell, never from a
# supervisor's possibly stale current-path observation.
# Usage: fm-slot-custody.sh claim <project> <state> <task-id> <token>
# fm-spawn owns the token and checks the published claim before freshen/launch.
# There is intentionally no force, adopt, release, or stale-claim repair command.
set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=bin/fm-slot-custody-lib.sh
. "$SCRIPT_DIR/fm-slot-custody-lib.sh"
if [ "$#" -ne 5 ] || [ "$1" != claim ]; then
  echo 'usage: fm-slot-custody.sh claim <project> <state> <task-id> <token>' >&2
  exit 2
fi
fm_slot_claim "$2" "$PWD" "$3" "$4" "$5"
