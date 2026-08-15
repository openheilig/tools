#!/bin/bash
# Run a headless Ghidra script against a program in the sacred-re project.
#   run.sh <program> <Script.java> [args...]
# Programs: sacred_orig (THE CITATION STANDARD), sacred-1.0.02-final.
# Scripts write to /tmp/gh/out.txt unless they take an output path.
set -e
cd "$(dirname "$0")/../../../.."
mkdir -p /tmp/gh
P=$1; S=$2; shift 2
exec analysis/vendor/ghidra_12.1.2_PUBLIC/support/analyzeHeadless \
  analysis/ghidra sacred-re -process "$P" -noanalysis \
  -scriptPath "$(pwd)/analysis/tools/binary/ghidra" -postScript "$S" "$@"
