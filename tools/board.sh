#!/bin/bash
# Board work on the shared Pico W under its lease (taken and released from
# Bash: the PowerShell tool cannot see the lease file it creates).
#   tools/board.sh <source> <output.uf2> [vectors args...]      stream vectors
#   SECONDS_CAPTURE=20 tools/board.sh <source> <output.uf2>      capture output
LEASE_DIR=/c/PMFBuild/board-leases
LEASE=$LEASE_DIR/COM7.lease
ROOT=$(cd "$(dirname "$0")/.." && pwd)
SRC=$1; OUT=$2; shift 2
mkdir -p "$LEASE_DIR"
TAG="8086-emulator worker $(date -Iseconds) pid $$"
while true; do
  if ( set -o noclobber; echo "$TAG" > "$LEASE" ) 2>/dev/null; then break; fi
  if [ -f "$LEASE" ]; then
    age=$(( $(date +%s) - $(stat -c %Y "$LEASE") ))
    if [ $age -gt 1800 ]; then
      echo "lease is ${age}s old ($(cat "$LEASE")): removing it"; rm -f "$LEASE"; continue
    fi
    echo "lease held: $(cat "$LEASE") - waiting 30 s"
  fi
  sleep 30
done
release() { if [ "$(cat "$LEASE" 2>/dev/null)" = "$TAG" ]; then rm -f "$LEASE"; echo "lease released"; else echo "lease no longer ours - left alone"; fi; }
trap release EXIT
SEC=${SECONDS_CAPTURE:-0}
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(cygpath -w "$ROOT/tools/build.ps1")" -Source "$SRC" -Output "$OUT" -Port COM7 -Seconds $SEC || exit 1
if [ $# -gt 0 ]; then
  py -3 "$ROOT/tools/vectors.py" --port COM7 "$@"
  echo "vectors exit $?"
fi
