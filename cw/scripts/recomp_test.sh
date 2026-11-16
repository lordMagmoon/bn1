#!/bin/sh
# Recompile every Thumb function of the built ROM to C and check a random sample of them against
# the original machine code in Unicorn (cw/recomp/test_recomp.py). The ROM comes from the matching
# build, which is byte-identical to the original; nothing derived from it is uploaded.
set -eu
SAMPLE=${1:-400}
SEED=${2:-$(date +%j)}
python3 build.py
python3 cw/recomp/thumb2c.py build/mmbn.gba build/mmbn.elf /tmp/rc_all.c --report
gcc -O1 -w -c -fPIC -Icw/recomp /tmp/rc_all.c -o /tmp/rc_all.o
gcc -O1 -w -c -fPIC -Icw/recomp cw/recomp/cw_rt.c -o /tmp/cw_rt.o
gcc -shared /tmp/rc_all.o /tmp/cw_rt.o -o /tmp/librc.so
python3 cw/recomp/test_recomp.py build/mmbn.gba /tmp/librc.so build/mmbn.elf -n 6 --sample "$SAMPLE" --seed "$SEED"
