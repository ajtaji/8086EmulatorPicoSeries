#!/bin/sh
# Builds the desktop 8086 emulator on Linux, from the same source as build.ps1 on Windows:
# cpu86_desktop (the window), cpu86_pc and cpu86_console (the same program for the console
# modes), cpu86_run (the console modes without the engine) and cpu86_console_proctable.
# PureBasic 6.41 for Linux, the C back end (pbcompilerc: the core's dispatch is inline C).
#   PUREBASIC_HOME  the PureBasic folder (its compilers/pbcompilerc is used)
#   NEON_ENGINE     the Neon Arcade Display Engine (github.com/ajtaji/Neon-Arcade-Dispay-Engine),
#                   else a clone beside this repository
set -e
here=$(cd "$(dirname "$0")" && pwd)
: "${PUREBASIC_HOME:?set PUREBASIC_HOME to the PureBasic folder}"
export PUREBASIC_HOME
compiler="$PUREBASIC_HOME/compilers/pbcompilerc"
engine="${NEON_ENGINE:-$here/../../Neon-Arcade-Dispay-Engine}"
engine="${engine%/}/"
[ -f "${engine}GlUI.pbi" ] || { echo "Neon Arcade Display Engine not found at $engine - set NEON_ENGINE"; exit 1; }
python3 "$here/../tools/gen_cpu.py"
python3 "$here/../tools/make_examples.py" > /dev/null
python3 "$here/../tools/desktop_proc_variant.py" > /dev/null
python3 "$here/../tools/make_cgafont.py" > /dev/null
cd "$here"
build() {
  out=$1; shift
  "$compiler" cpu86_desktop.pb -o "$out" -t -z -q --constant "GL_ENGINE_DIR\$=$engine" "$@"
}
build cpu86_desktop --constant CPU_TIMING=1
build cpu86_pc -cl --constant CPU_TIMING=1
build cpu86_console -cl
build cpu86_run -cl --constant CPU86_LEAN=1
build cpu86_console_proctable -cl --constant CPU86_PROCTABLE=1
sha256sum cpu86_desktop cpu86_console
