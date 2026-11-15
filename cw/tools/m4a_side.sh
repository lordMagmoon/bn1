#!/bin/sh
# Side-by-side: base ROM span vs agbcc functions.  usage: m4a_side.sh M4A.o BASE.gba START_OFF END_OFF FUNC...
O=$1; R=$2; S=$3; E=$4; shift 4
B=0x0809CAEC
arm-none-eabi-objdump -D -b binary -marm -Mforce-thumb --adjust-vma=0x08000000 \
  --start-address=$((B + S)) --stop-address=$((B + E)) "$R" | tail -n +8 | awk -F'\t' '{printf "%-10s %s %s\n",$1,$3,$4}' > /tmp/side_base.txt
: > /tmp/side_agb.txt
for f in "$@"; do
  arm-none-eabi-objdump -d "$O" | awk -v f="<$f>:" '$2==f{p=1;next} p&&/^$/{p=0} p' | awk -F'\t' '{printf "%-10s %s %s\n",$1,$3,$4}' >> /tmp/side_agb.txt
done
paste -d'|' /tmp/side_base.txt /tmp/side_agb.txt | awk -F'|' '{printf "%-52s | %s\n",$1,$2}'
