#!/usr/bin/env bash
# Run the regolith-module verification cases (Moon equator, Mars Jezero) in generator and PWF modes and compare
# each with the Python reference.  Usage: planetary/tools/run_regolith_cases.sh <out_dir> [python]
set -e
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="$1"
PY="${2:-python}"
EXE="$ROOT/build/Products/energyplus.exe"
for c in moon_equator mars_jezero; do
  CASE="$ROOT/planetary/cases/$c"
  rm -rf "$OUT/${c}_gen" "$OUT/${c}_pwf"
  mkdir -p "$OUT/${c}_gen" "$OUT/${c}_pwf"
  (cd "$OUT/${c}_gen" && "$EXE" -w "$(cygpath -w "$CASE/placeholder.epw")" -d . "$(cygpath -w "$CASE/$c.idf")" > run.log 2>&1) &
  cp "$CASE/$c.pwf" "$CASE/${c}_pwf.idf" "$OUT/${c}_pwf/"
  (cd "$OUT/${c}_pwf" && "$EXE" -d . "${c}_pwf.idf" > run.log 2>&1) &
done
wait
for c in moon_equator mars_jezero; do
  for m in gen pwf; do
    tail -1 "$OUT/${c}_$m/eplusout.err"
    "$PY" "$ROOT/planetary/cases/compare.py" "$c" "$OUT/${c}_$m" > "$OUT/${c}_$m/compare.log" 2>&1
  done
done
echo ALL-DONE
