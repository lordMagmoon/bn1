#!/usr/bin/env python3
"""Wrap the code of assembly functions in `#if !FUNCTIONAL ... #endif` (their C version is used
in FUNCTIONAL builds). Only the instructions are guarded: from the `_ts NAME` line up to the
first line that starts data or another function (@@ comment, _ts/_nt, .align, .pool, data
label). Shared tables and literal pools stay in both builds.
usage: guard_asm.py FILE.S C_FILE FUNC [FUNC ...]"""
import re, sys
path, cfile, funcs = sys.argv[1], sys.argv[2], sys.argv[3:]
lines = open(path).read().split("\n")
stop = re.compile(r"^(@@|\s*_(ts|nt|fts|fnt)\s|\s*\.(align|pool|word|byte|hword|2byte|4byte)\b|[A-Za-z_]\w*:\s*(\.word|$))")
for f in funcs:
    start = next((i for i, l in enumerate(lines) if re.match(rf"^\s*_(ts|nt)\s+{f}\s*$", l)), None)
    if start is None:
        sys.exit(f"{f}: not found in {path}")
    if start > 0 and lines[start - 1].startswith("#if !FUNCTIONAL"):
        continue
    end = start + 1
    while end < len(lines):
        l = lines[end]
        is_local_label = ":" in l and re.match(r"^\s*(LAB_|\.|\d)", l.split(":")[0])
        if stop.match(l) and not is_local_label:
            break
        end += 1
    while end > start + 1 and lines[end - 1].strip() == "":
        end -= 1
    lines[end:end] = ["#endif"]
    lines[start:start] = [f"#if !FUNCTIONAL /* CyberWarrior: C version in {cfile} */"]
    print(f"{f}: guarded lines {start + 1}..{end + 1}")
open(path, "w").write("\n".join(lines))
