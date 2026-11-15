#!/bin/sh
# Shift test: build the ROM, then rebuild with 0x100 bytes of padding inserted at the start of
# main.S (right after crt0) and check that the scripted input movie produces identical frames.
# Proves that live code is position-independent (no hard-coded ROM pointers on the executed path).
set -eu
MOVIE=${1:-cw/movies/boot_newgame.txt}
FRAMES=${2:-1200}
FRAMECMP=${FRAMECMP:-framecmp}

python3 build.py
cp build/mmbn.gba /tmp/ref.gba
$FRAMECMP /tmp/ref.gba "$MOVIE" "$FRAMES" > /tmp/ref.crc

cp source/main.S /tmp/main.S.orig
sed -i '0,/^_ts AgbMain/s//    .space 0x100, 0\n_ts AgbMain/' source/main.S
python3 build.py
mv /tmp/main.S.orig source/main.S
$FRAMECMP build/mmbn.gba "$MOVIE" "$FRAMES" > /tmp/shift.crc

if cmp -s /tmp/ref.gba build/mmbn.gba; then echo "::error::padding did not change the ROM"; exit 1; fi
if diff -q /tmp/ref.crc /tmp/shift.crc >/dev/null; then
  echo "SHIFT OK: $FRAMES frames identical with code shifted by 0x100"
else
  first=$(diff /tmp/ref.crc /tmp/shift.crc | grep '^>' | head -1)
  echo "::error::Shifted build diverges, first differing frame: $first"
  exit 1
fi
