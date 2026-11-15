#!/usr/bin/env python3
"""
abi_scan — register-convention analysis for the hand-written BN1 assembly.

The game does not follow the ARM C calling convention (AAPCS): functions take inputs in
r4-r7, return values in r1-r3, clobber callee-saved registers and leave results in the
flags. Before an assembly function is replaced by C (which receives r0-r3, returns r0,
preserves r4-r11 and clobbers r0-r3, r12 and the flags) we need to know:

  * inputs:  registers the function reads before writing them (on some path)
  * writes:  registers the function may change when it returns (after push/pop restores)
  * callers: for each `bl F` site, which registers/flags the caller reads after the call
             before overwriting them (= what the caller expects F to produce or keep)

A C replacement is safe as-is when:
  inputs  ⊆ {r0..r3}            (otherwise an asm entry shim must move them)
  for every call site: live_after ∩ {r1,r2,r3,r12,flags} = ∅, and live_after ∩ {r0}
  only when F really returns a value in r0.

usage:
  abi_scan.py ELF FUNC [FUNC...]       detailed report for some functions
  abi_scan.py ELF --all [--csv out]    summary for every function
"""
import argparse
import bisect
import csv
import sys
from collections import defaultdict

from capstone import CS_ARCH_ARM, CS_MODE_THUMB, Cs
from capstone import arm as A
from elftools.elf.elffile import ELFFile

REGS = [f"r{i}" for i in range(13)] + ["sp", "lr", "pc"]
CREG = {A.ARM_REG_R0 + i: f"r{i}" for i in range(13)}
CREG.update({A.ARM_REG_SB: "r9", A.ARM_REG_SL: "r10", A.ARM_REG_FP: "r11", A.ARM_REG_IP: "r12",
             A.ARM_REG_SP: "sp", A.ARM_REG_LR: "lr", A.ARM_REG_PC: "pc", A.ARM_REG_CPSR: "flags"})
TRACKED = [f"r{i}" for i in range(13)] + ["flags"]
C_CLOBBER = {"r1", "r2", "r3", "r12", "flags"}
# r10 always holds &MainState in this game. C code is built with -ffixed-r10, so it never
# changes r10 and can treat it as an invariant rather than an input.
GLOBAL_REGS = {"r10"}


class Image:
    def __init__(self, path):
        f = open(path, "rb")
        self.elf = ELFFile(f)
        self.segs = []
        for s in self.elf.iter_sections():
            if s["sh_type"] == "SHT_PROGBITS" and s["sh_flags"] & 2 and s["sh_size"]:
                self.segs.append((s["sh_addr"], s.data()))
        syms = self.elf.get_section_by_name(".symtab")
        self.funcs = {}   # name -> start
        self.labels = []  # (addr, name) all text symbols, for function bounds
        for sym in syms.iter_symbols():
            if sym["st_shndx"] == "SHN_UNDEF" or not sym.name or sym.name.startswith("$"):
                continue
            addr = sym["st_value"]
            if sym["st_info"]["type"] == "STT_FUNC":
                self.funcs[sym.name] = addr & ~1
            if 0x08000000 <= addr < 0x0A000000 or 0x03000000 <= addr < 0x03008000:
                self.labels.append((addr & ~1, sym.name, sym["st_info"]["type"] == "STT_FUNC"))
        self.labels.sort()
        self.func_starts = sorted(set(a for a, _, isf in self.labels if isf))
        # any symbol that is not an intra-function code label ends the previous function
        self.bounds = sorted(set(a for a, n, isf in self.labels
                                 if isf or not (n.startswith("LAB_") or n.startswith("."))))
        self.by_addr = defaultdict(list)
        for n, a in self.funcs.items():
            self.by_addr[a].append(n)
        self.md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
        self.md.detail = True
        self._cache = {}

    def read(self, addr, n):
        for base, data in self.segs:
            if base <= addr < base + len(data):
                return data[addr - base: addr - base + n]
        return b""

    def func_end(self, start):
        i = bisect.bisect_right(self.bounds, start)
        return self.bounds[i] if i < len(self.bounds) else start + 0x400

    def insns(self, start):
        if start in self._cache:
            return self._cache[start]
        end = self.func_end(start)
        code = self.read(start, end - start)
        out = {}
        for ins in self.md.disasm(code, start):
            out[ins.address] = ins
        self._cache[start] = out
        return out


def rw(ins):
    try:
        r, w = ins.regs_access()
    except Exception:
        return set(), set()
    rd = {CREG.get(x) for x in r} - {None}
    wr = {CREG.get(x) for x in w} - {None}
    # push/pop/ldm/stm register lists
    if ins.mnemonic in ("push", "stm", "stmia", "stmdb"):
        rd |= {CREG.get(op.reg) for op in ins.operands if op.type == A.ARM_OP_REG} - {None}
    if ins.mnemonic in ("pop", "ldm", "ldmia"):
        wr |= {CREG.get(op.reg) for op in ins.operands if op.type == A.ARM_OP_REG} - {None}
    if ins.mnemonic in ("bl", "blx"):
        rd -= {"r0", "r1", "r2", "r3"}
    return rd, wr


def is_return(ins):
    m, s = ins.mnemonic, ins.op_str.replace(" ", "")
    return (m == "bx" and s == "lr") or (m == "mov" and s == "pc,lr") or \
           (m == "pop" and "pc" in s) or (m == "bx" and ins.address and False)


def successors(ins, start, end):
    m = ins.mnemonic
    nxt = ins.address + ins.size
    if is_return(ins):
        return []
    if m == "bx" or (m == "mov" and ins.op_str.startswith("pc")):
        return []  # indirect jump: unknown, end of path
    if m == "b" or m.startswith("b") and m not in ("bl", "blx", "bic", "bics") and len(m) in (3, 4) and \
            ins.operands and ins.operands[0].type == A.ARM_OP_IMM:
        tgt = ins.operands[0].imm
        cond = m != "b"
        out = [tgt] if start <= tgt < end else []
        return out + ([nxt] if cond else [])
    if m in ("cbz", "cbnz"):
        tgt = ins.operands[1].imm
        return ([tgt] if start <= tgt < end else []) + [nxt]
    return [nxt]


def read_before_write(img, start, entry, stop_at_call=True):
    """Forward dataflow from `entry` inside function [start,end): registers (and flags)
    read on some path before being written on that path."""
    insns = img.insns(start)
    end = img.func_end(start)
    reads = set()
    best = {}  # addr -> frozenset(defined) already explored (we explore if new state not superset)
    work = [(entry, frozenset())]
    steps = 0
    while work and steps < 20000:
        steps += 1
        addr, defined = work.pop()
        if addr in best and best[addr] <= defined:
            continue
        best[addr] = defined if addr not in best else best[addr] & defined
        defined = best[addr]
        ins = insns.get(addr)
        if ins is None:
            continue
        r, w = rw(ins)
        if ins.mnemonic in ("push",):  # saving a reg is not a use of its value
            r = set()
        if ins.mnemonic in ("pop",) and "pc" in ins.op_str:
            w = w | set()
        reads |= (r & set(TRACKED)) - defined
        if ins.mnemonic in ("bl", "blx") and stop_at_call:
            # the callee consumes its own inputs; after it returns we stop (unknown clobbers)
            if ins.operands and ins.operands[0].type == A.ARM_OP_IMM:
                reads |= callee_inputs(img, ins.operands[0].imm) - defined
            else:
                reads |= {"r0", "r1", "r2", "r3"} - defined
            continue
        nd = defined | (w & set(TRACKED))
        for s in successors(ins, start, end):
            work.append((s, frozenset(nd)))
    return reads


_inputs_memo = {}


def callee_inputs(img, target):
    if target in _inputs_memo:
        return _inputs_memo[target]
    _inputs_memo[target] = {"r0", "r1", "r2", "r3"}  # recursion guard: assume AAPCS args
    if target not in img.by_addr:
        return _inputs_memo[target]
    res = read_before_write(img, target, target) - GLOBAL_REGS
    _inputs_memo[target] = res
    return res


def written_on_return(img, start):
    """Registers possibly modified when the function returns (push/pop-restored ones excluded,
    callee clobbers from nested calls approximated by AAPCS r0-r3,r12)."""
    insns = img.insns(start)
    end = img.func_end(start)
    written = set()
    saved = set()
    for ins in insns.values():
        if ins.mnemonic == "push":
            saved |= {CREG.get(op.reg) for op in ins.operands if op.type == A.ARM_OP_REG} - {None, "lr"}
    for ins in insns.values():
        r, w = rw(ins)
        if ins.mnemonic in ("push", "pop"):
            continue
        if ins.mnemonic in ("bl", "blx"):
            w = {"r0", "r1", "r2", "r3", "r12", "flags", "lr"}
        written |= w & set(TRACKED)
    return written - saved, saved


def call_sites(img, target):
    sites = []
    for fstart in img.func_starts:
        if not (0x08000000 <= fstart < 0x0A000000 or 0x03000000 <= fstart < 0x03008000):
            continue
        for ins in img.insns(fstart).values():
            if ins.mnemonic == "bl" and ins.operands and ins.operands[0].imm == target:
                sites.append((fstart, ins.address + ins.size))
    return sites


def name_of(img, addr):
    return "/".join(img.by_addr.get(addr, [hex(addr)]))


def report(img, fname):
    if fname not in img.funcs:
        print(f"{fname}: not found")
        return None
    start = img.funcs[fname]
    inputs = read_before_write(img, start, start) - GLOBAL_REGS
    writes, saved = written_on_return(img, start)
    print(f"== {fname} @ {start:#010x}  size {img.func_end(start) - start:#x}")
    print(f"   inputs : {sorted(inputs, key=TRACKED.index)}")
    print(f"   writes : {sorted(writes, key=TRACKED.index)}   (push-saved: {sorted(saved)})")
    risky = set()
    sites = call_sites(img, start)
    for caller, after in sites:
        live = read_before_write(img, caller, after) - GLOBAL_REGS
        bad = live & (C_CLOBBER | (writes - {"r0"}))
        mark = "  <-- relies on " + ",".join(sorted(bad)) if bad else ""
        risky |= bad
        print(f"   caller {name_of(img, caller)} (ret {after:#x}) reads after: {sorted(live, key=TRACKED.index)}{mark}")
    extra_in = inputs - {"r0", "r1", "r2", "r3"}
    verdict = []
    if extra_in:
        verdict.append(f"needs entry shim for inputs {sorted(extra_in)}")
    if risky:
        verdict.append(f"callers rely on {sorted(risky)} after return")
    print("   verdict: " + ("; ".join(verdict) if verdict else "C-safe (AAPCS-compatible at all call sites)"))
    return {"name": fname, "inputs": inputs, "writes": writes, "sites": len(sites), "risky": risky, "extra_in": extra_in}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("elf")
    ap.add_argument("funcs", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--csv")
    a = ap.parse_args()
    img = Image(a.elf)
    names = a.funcs
    if a.all:
        names = sorted(n for n, s in img.funcs.items() if 0x08000000 <= s < 0x08180000)
    rows = []
    import io, contextlib
    for n in names:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            r = report(img, n)
        if not a.all:
            sys.stdout.write(buf.getvalue())
        if r:
            rows.append(r)
    if a.all:
        safe = sum(1 for r in rows if not r["risky"] and not r["extra_in"])
        print(f"functions: {len(rows)}  C-safe as-is: {safe}  need shim/care: {len(rows) - safe}")
    if a.csv:
        with open(a.csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["name", "inputs", "writes", "call_sites", "callers_rely_on", "extra_inputs"])
            for r in rows:
                w.writerow([r["name"], " ".join(sorted(r["inputs"])), " ".join(sorted(r["writes"])), r["sites"],
                            " ".join(sorted(r["risky"])), " ".join(sorted(r["extra_in"]))])


if __name__ == "__main__":
    main()
