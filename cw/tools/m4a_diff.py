#!/usr/bin/env python3
"""Diff an agbcc-compiled m4a.o against the base ROM's sound-driver region (instruction level).
usage: m4a_diff.py M4A.o BASE.gba [--show FUNC ...] [--all]
Prints, per function of the .o, whether its instructions appear unchanged in the ROM, and with
--show/--all the instruction-level differences."""
import argparse, difflib, re
from elftools.elf.elffile import ELFFile
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB

START, SIZE = 0x0809CAEC, 0x1464
ap = argparse.ArgumentParser(); ap.add_argument('obj'); ap.add_argument('rom')
ap.add_argument('--show', nargs='*', default=[]); ap.add_argument('--all', action='store_true')
a = ap.parse_args()
base = open(a.rom, 'rb').read()[START - 0x08000000:START - 0x08000000 + SIZE]
e = ELFFile(open(a.obj, 'rb'))
text = e.get_section_by_name('.text').data()
funcs = sorted((s['st_value'] & ~1, s.name) for s in e.get_section_by_name('.symtab').iter_symbols()
               if s['st_info']['type'] == 'STT_FUNC')
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

def norm(i):
    s = f"{i.mnemonic} {i.op_str}"
    if i.mnemonic.startswith('b') and i.mnemonic not in ('bic', 'bics'):
        s = re.sub(r"#0x[0-9a-f]+", "#T", s)          # branch targets
    s = re.sub(r"\[pc, #0x[0-9a-f]+\]", "[pc, #P]", s)  # literal-pool offsets
    return s

def listing(buf):
    out, off = [], 0
    while off < len(buf):
        got = False
        for i in md.disasm(buf[off:], off):
            out.append((i.address, norm(i))); got = True
        last = out[-1][0] + 2 if got else off
        if last <= off: last = off
        off = max(last, off + 2) if not got else out[-1][0] + 2
        if got and out[-1][0] + 2 >= len(buf): break
        if not got:
            out.append((off - 2, '.data')); 
    return out

B = listing(base); T = listing(text)
def fname(addr):
    n = None
    for fa, fn in funcs:
        if fa <= addr: n = fn
    return n
sm = difflib.SequenceMatcher(None, [x[1] for x in B], [x[1] for x in T], autojunk=False)
bad = {}
for tag, i1, i2, j1, j2 in sm.get_opcodes():
    if tag == 'equal': continue
    names = {fname(T[j][0]) for j in range(j1, max(j2, j1 + 1)) if j < len(T)}
    for n in names:
        bad.setdefault(n, []).append((tag, i1, i2, j1, j2))
for fa, fn in funcs:
    status = 'DIFF' if fn in bad else 'ok  '
    print(f"{status} {fn}")
for fa, fn in funcs:
    if fn in bad and (a.all or fn in a.show):
        print(f"\n===== {fn}")
        for tag, i1, i2, j1, j2 in bad[fn]:
            print(f"  [{tag}] base+{B[i1][0] if i1 < len(B) else 0:#06x}")
            for k in range(i1, i2): print(f"    - {B[k][1]}")
            for k in range(j1, j2): print(f"    + {T[k][1]}")
print(f"\nsimilarity {sm.ratio():.4f}  diff functions: {len(bad)}/{len(funcs)}")
