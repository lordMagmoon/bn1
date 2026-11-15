#!/usr/bin/env python3
"""Explain a frame-CRC divergence: real difference or the same frames delayed (lag)?
usage: crc_lag.py A.crc B.crc"""
import sys
a = [l.split()[1] for l in open(sys.argv[1])]
b = [l.split()[1] for l in open(sys.argv[2])]
first = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), None)
if first is None:
    print("identical"); sys.exit(0)
print(f"first differing frame: {first}")
for lag in range(-4, 5):
    if lag == 0:
        continue
    n = ok = 0
    for i in range(first, min(len(a), len(b))):
        j = i + lag
        if 0 <= j < len(b):
            n += 1; ok += a[i] == b[j]
    print(f"  B delayed by {lag:+d} frames: {ok}/{n} frames after divergence match ({100*ok/max(n,1):.1f}%)")
# unique-frame view: compare sequences of distinct consecutive CRCs (timing-insensitive)
def dedup(s):
    out = []
    for x in s:
        if not out or out[-1] != x: out.append(x)
    return out
da, db = dedup(a), dedup(b)
same = sum(1 for x, y in zip(da, db) if x == y)
print(f"distinct-frame sequences: A {len(da)}, B {len(db)}, positionally equal {same}")
import difflib
sm = difflib.SequenceMatcher(None, da, db, autojunk=False)
print(f"distinct-frame similarity (timing-insensitive): {sm.ratio():.4f}")
