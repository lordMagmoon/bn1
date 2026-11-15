#!/bin/sh
# Functional test: the FUNCTIONAL=1 build (decompiled C) must behave exactly like the
# matching build (original assembly).
#   1. per-function differential test in Unicorn (random RAM/register/key states)
#   2. whole-game test in mGBA: same input movie, every frame identical
# Needs: framecmp on PATH (cw/framecmp), python3 with unicorn.
set -eu
MOVIE=${1:-cw/movies/boot_newgame.txt}
FRAMES=${2:-1200}
OUT=${CW_OUT:-/tmp/cw}
mkdir -p "$OUT"

python3 build.py
cp build/mmbn.gba "$OUT/asm.gba"
arm-none-eabi-nm build/mmbn.elf > "$OUT/asm_syms.txt" 2>/dev/null || "$DEVKITARM/bin/arm-none-eabi-nm" build/mmbn.elf > "$OUT/asm_syms.txt"

python3 build.py functional
cp build/mmbn.gba "$OUT/c.gba"
arm-none-eabi-nm build/mmbn.elf > "$OUT/c_syms.txt" 2>/dev/null || "$DEVKITARM/bin/arm-none-eabi-nm" build/mmbn.elf > "$OUT/c_syms.txt"

if cmp -s "$OUT/asm.gba" "$OUT/c.gba"; then echo "::error::FUNCTIONAL build is identical to the matching build"; exit 1; fi

echo "== Differential test (Unicorn)"
python3 cw/tests/difftest.py "$OUT/asm.gba" "$OUT/asm_syms.txt" "$OUT/c.gba" "$OUT/c_syms.txt" -n 300

echo "== Frame test (mGBA, $FRAMES frames, $MOVIE)"
framecmp "$OUT/asm.gba" "$MOVIE" "$FRAMES" > "$OUT/asm.crc"
framecmp "$OUT/c.gba" "$MOVIE" "$FRAMES" > "$OUT/c.crc"
if diff -q "$OUT/asm.crc" "$OUT/c.crc" >/dev/null; then
  echo "FUNCTIONAL OK: $FRAMES frames identical"
else
  echo "::error::FUNCTIONAL build diverges, first differing frame: $(diff "$OUT/asm.crc" "$OUT/c.crc" | grep '^>' | head -1)"
  python3 cw/tools/crc_lag.py "$OUT/asm.crc" "$OUT/c.crc" || true
  exit 1
fi
