#!/bin/sh
# Functional test: the FUNCTIONAL=1 build (decompiled C) must behave exactly like the
# matching build (original assembly).
#   1. per-function differential test in Unicorn (random RAM/register/key states)
#   2. whole-game test in mGBA: same input movie, every frame identical
# Needs: framecmp2 on PATH (cw/framecmp), python3 with unicorn.
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

echo "== Frame test (mGBA, both ROMs side by side, $FRAMES frames, $MOVIE)"
# C does the same work in a different number of cycles, which can move a mid-frame video write
# by a scanline. framecmp2 tolerates isolated frames differing in <= 2 rows and fails on
# anything wider or on consecutive differing frames (lag / real divergence).
framecmp2 "$OUT/asm.gba" "$OUT/c.gba" "$MOVIE" "$FRAMES" 2 1
echo "FUNCTIONAL OK"
