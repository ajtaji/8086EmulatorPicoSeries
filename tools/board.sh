#!/bin/bash
# Board work on the shared Pico W (COM7) under ONE lease for a batch of jobs.
# The lease is taken and released from Bash (the PowerShell tool cannot see
# the lease file it creates), and held only while the batch runs.
#
#   tools/board.sh 'flash Diagnostics/api.picow Diagnostics/build/api.uf2 10' \
#                  'vectors Diagnostics/vectors.picow Diagnostics/build/vectors.uf2 --per-file 100 --log docs/x.log'
#
#   flash   <source> <output.uf2> [seconds]   build, upload, capture output
#   vectors <source> <output.uf2> <vectors.py args...>   build, upload, stream
LEASE_DIR=/c/PMFBuild/board-leases
LEASE=$LEASE_DIR/COM7.lease
ROOT=$(cd "$(dirname "$0")/.." && pwd)
mkdir -p "$LEASE_DIR"
TAG="8086-emulator worker $(date -Iseconds) pid $$ ($# jobs)"
last=""
while true; do
  if ( set -o noclobber; echo "$TAG" > "$LEASE" ) 2>/dev/null; then break; fi
  if [ -f "$LEASE" ]; then
    age=$(( $(date +%s) - $(stat -c %Y "$LEASE" 2>/dev/null || date +%s) ))
    if [ $age -gt 1800 ]; then
      echo "lease is ${age}s old ($(cat "$LEASE")): removing it"; rm -f "$LEASE"; continue
    fi
    now=$(cat "$LEASE" 2>/dev/null)
    [ "$now" != "$last" ] && echo "lease held: $now - waiting"
    last=$now
  fi
  sleep 5
done
echo "lease taken $(date +%T)"
release() { if [ "$(cat "$LEASE" 2>/dev/null)" = "$TAG" ]; then rm -f "$LEASE"; echo "lease released $(date +%T)"; else echo "lease no longer ours - left alone"; fi; }
trap release EXIT
build() {  # source output seconds
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(cygpath -w "$ROOT/tools/build.ps1")" -Source "$1" -Output "$2" -Port COM7 -Seconds "${3:-0}"
}
for job in "$@"; do
  set -- $job
  kind=$1; shift
  case $kind in
    flash) build "$1" "$2" "${3:-0}" || echo "JOB FAILED: $job" ;;
    vectors) src=$1; out=$2; shift 2
             if build "$src" "$out" 0; then py -3 "$ROOT/tools/vectors.py" --port COM7 "$@"; echo "vectors exit $?"; else echo "JOB FAILED: $job"; fi ;;
    *) echo "unknown job: $job" ;;
  esac
done
