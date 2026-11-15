#!/usr/bin/env python3
"""CyberWarrior progress: functions decompiled to C (inside #if !FUNCTIONAL guards) vs total."""
import pathlib
import re
import sys

root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
func_re = re.compile(r"^\s*_(?:ts|fts|nt|fnt)\s+(\w+)", re.M)
total, done, per_file = 0, 0, []
for f in sorted((root / "source").rglob("*.S")):
    text = f.read_text(errors="ignore")
    n = len(func_re.findall(text))
    guarded = 0
    for block in re.findall(r"#if !FUNCTIONAL[^\n]*\n(.*?)#endif", text, re.S):
        guarded += len(func_re.findall(block))
    total += n
    done += guarded
    if guarded:
        per_file.append((f.relative_to(root), guarded, n))
print(f"CyberWarrior: {done}/{total} functions in C ({100 * done / max(total, 1):.2f}%)")
for path, g, n in per_file:
    print(f"  {path}: {g}/{n}")
