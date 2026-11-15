#!/bin/sh
# Compile source/m4a.c with pret's agbcc (the compiler the original ROM's sound driver was built with).
# usage: m4a_agbcc.sh AGBCC_DIR OUT.o
set -eu
A=$1; OUT=$2; T=$(mktemp -d)
arm-none-eabi-cpp -std=gnu89 -nostdinc -undef -I "$A/ginclude" -iquote include -iquote libagbsyscall -iquote build \
  source/m4a.c -o "$T/m4a.i"
# agbcc is a C89-era GCC: it rejects C11 repeated typedefs used by the shared headers.
sed -E 's/^typedef struct (\w+) \1, \*P\1;/struct \1; typedef struct \1 *P\1;/' "$T/m4a.i" > "$T/m4a2.i"
"$A/agbcc" -mthumb-interwork -O2 -fhex-asm "$T/m4a2.i" -o "$T/m4a.s"
arm-none-eabi-as -mcpu=arm7tdmi "$T/m4a.s" -o "$OUT"
rm -rf "$T"
