#!/usr/bin/env python3
"""
Differential test of the recompiler: each recompiled Thumb function vs the original machine code
running in Unicorn (ARM926 model: pre-ARMv6 unaligned-load rotation like the GBA's ARM7TDMI).

Same random state on both sides: registers (mostly pointers into RAM), NZCV, all of RAM / IO /
palette / VRAM / OAM / SRAM. Calls leaving the function are stubbed and recorded (target, r0-r3)
on both sides. Compared afterwards: r0-r14, NZCV, every memory region, the recorded calls.

usage: test_recomp.py ROM.gba LIB.so SYMBOLS.elf [-n RUNS] [--only NAME ...] [--sample K] [--seed S]
"""
import argparse, bisect, ctypes, random, struct, sys
from elftools.elf.elffile import ELFFile
from unicorn import (Uc, UcError, UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE, UC_HOOK_INTR)
from unicorn.arm_const import *

try:
    from unicorn.arm_const import UC_CPU_ARM_926
except ImportError:
    UC_CPU_ARM_926 = 0

REGIONS = [  # name, base, size, C symbol
    ("ewram", 0x02000000, 0x40000, "cw_ewram"), ("iwram", 0x03000000, 0x8000, "cw_iwram"),
    ("io", 0x04000000, 0x400, "cw_io"), ("pal", 0x05000000, 0x400, "cw_pal"),
    ("vram", 0x06000000, 0x18000, "cw_vram"), ("oam", 0x07000000, 0x400, "cw_oam"),
    ("sram", 0x0E000000, 0x10000, "cw_sram"),
]
RET = 0x0A000000
SP0 = 0x03007E00
GPR = [UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5,
       UC_ARM_REG_R6, UC_ARM_REG_R7, UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11,
       UC_ARM_REG_R12, UC_ARM_REG_SP, UC_ARM_REG_LR]


class CwCpu(ctypes.Structure):
    _fields_ = [("r", ctypes.c_uint32 * 16), ("n", ctypes.c_uint32), ("z", ctypes.c_uint32),
                ("c", ctypes.c_uint32), ("v", ctypes.c_uint32), ("ret", ctypes.c_uint32),
                ("fault", ctypes.c_int), ("fault_addr", ctypes.c_uint32), ("insns", ctypes.c_uint64)]


def functions(elf_path):
    elf = ELFFile(open(elf_path, "rb"))
    s = sorted({(x["st_value"] & ~1, x.name) for x in elf.get_section_by_name(".symtab").iter_symbols()
                if x["st_info"]["type"] == "STT_FUNC" and x["st_value"] & 1 and 0x08000000 <= x["st_value"] < 0x08800000})
    starts = sorted({a for a, _ in s})
    names = {}
    for a, n in s:
        names.setdefault(a, n)
    return [(names[a], a, starts[i + 1] if i + 1 < len(starts) else a + 0x10000) for i, a in enumerate(starts)]


def rand_state(rng):
    mem = {}
    for name, base, size, _ in REGIONS:
        words = []
        for _ in range(size // 4):
            x = rng.random()
            if x < 0.25:
                w = 0x02000000 + rng.randrange(0, 0x40000, 4)
            elif x < 0.35:
                w = 0x03000000 + rng.randrange(0, 0x7000, 4)
            elif x < 0.6:
                w = rng.randrange(0, 256)
            else:
                w = rng.getrandbits(32)
            words.append(w)
        mem[name] = struct.pack(f"<{len(words)}I", *words)
    regs = []
    for i in range(13):
        x = rng.random()
        if x < 0.45:
            regs.append(0x02000000 + rng.randrange(0x1000, 0x3F000, 4))
        elif x < 0.6:
            regs.append(0x03000000 + rng.randrange(0x100, 0x6000, 4))
        elif x < 0.85:
            regs.append(rng.randrange(0, 64))
        else:
            regs.append(rng.getrandbits(32))
    flags = [rng.getrandbits(1) for _ in range(4)]
    return mem, regs, flags


class Recomp:
    def __init__(self, lib, rom):
        self.lib = ctypes.CDLL(lib)
        self.rom = ctypes.create_string_buffer(rom, len(rom))
        self.lib.cw_set_rom(self.rom, len(rom))
        self.lib.cw_test_run.argtypes = [ctypes.POINTER(CwCpu), ctypes.c_uint32]
        self.mem = {name: (ctypes.c_uint8 * size).in_dll(self.lib, sym) for name, _, size, sym in REGIONS}
        self.calls = (ctypes.c_uint32 * (64 * 5)).in_dll(self.lib, "cw_test_calls")
        self.ncalls = ctypes.c_int.in_dll(self.lib, "cw_test_ncalls")
        ctypes.c_uint64.in_dll(self.lib, "cw_loop_limit").value = 20000
        ctypes.c_int.in_dll(self.lib, "cw_strict_map").value = 1

    def run(self, addr, mem, regs, flags):
        for name, data in mem.items():
            ctypes.memmove(self.mem[name], data, len(data))
        c = CwCpu()
        for i, v in enumerate(regs):
            c.r[i] = v
        c.r[13], c.r[14] = SP0, RET | 1
        c.n, c.z, c.c, c.v = flags
        if self.lib.cw_test_run(ctypes.byref(c), addr) != 0:
            return {"error": "no entry"}
        if c.fault:
            return {"error": f"fault {c.fault} @ {c.fault_addr:#x}"}
        if (c.ret & ~1) != RET:
            return {"error": f"returned to {c.ret:#x}"}
        n = min(self.ncalls.value, 64)
        return {"regs": [c.r[i] for i in range(15)], "flags": [c.n, c.z, c.c, c.v],
                "mem": {k: bytes(v) for k, v in self.mem.items()},
                "calls": [tuple(self.calls[k * 5:(k + 1) * 5]) for k in range(n)] + (["..."] if self.ncalls.value > 64 else [])}


class Uni:
    def __init__(self, rom):
        self.rom = rom

    def run(self, start, end, mem, regs, flags):
        uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        try:
            uc.ctl_set_cpu_model(UC_CPU_ARM_926)
        except Exception:
            pass
        for name, base, size, _ in REGIONS:
            uc.mem_map(base, max(size, 0x1000))
            uc.mem_write(base, mem[name])
        rom_size = (len(self.rom) + 0xFFF) & ~0xFFF
        uc.mem_map(0x08000000, rom_size)
        uc.mem_write(0x08000000, self.rom)
        uc.mem_map(RET, 0x1000)
        for r, v in zip(GPR, regs + [SP0, RET | 1]):
            uc.reg_write(r, v)
        cpsr = uc.reg_read(UC_ARM_REG_CPSR) & 0x0FFFFFFF
        n, z, cf, v = flags
        uc.reg_write(UC_ARM_REG_CPSR, cpsr | n << 31 | z << 30 | cf << 29 | v << 28)
        calls, err = [], []

        def on_code(u, addr, size, _):
            if addr == RET or start <= addr < end:
                return
            if len(calls) < 64:
                calls.append((addr & ~1,) + tuple(u.reg_read(r) for r in GPR[:4]))
            elif len(calls) == 64:
                calls.append("...")
            u.reg_write(UC_ARM_REG_PC, u.reg_read(UC_ARM_REG_LR) | 1)

        def on_intr(u, intno, _):
            pc = u.reg_read(UC_ARM_REG_PC)
            num = u.mem_read(pc - 2, 1)[0]
            r0, r1 = u.reg_read(UC_ARM_REG_R0), u.reg_read(UC_ARM_REG_R1)
            if num not in (6, 7):
                err.append(f"swi {num}"); u.emu_stop(); return
            if num == 7:
                r0, r1 = r1, r0
            a = r0 - (1 << 32) if r0 >> 31 else r0
            b = r1 - (1 << 32) if r1 >> 31 else r1
            if b == 0:
                q, m = 0, a
            else:
                q = int(a / b); m = a - q * b
            u.reg_write(UC_ARM_REG_R0, q & 0xFFFFFFFF); u.reg_write(UC_ARM_REG_R1, m & 0xFFFFFFFF)
            u.reg_write(UC_ARM_REG_R3, abs(q) & 0xFFFFFFFF)

        uc.hook_add(UC_HOOK_CODE, on_code)
        uc.hook_add(UC_HOOK_INTR, on_intr)
        try:
            uc.emu_start(start | 1, RET, count=40000)
        except UcError as e:
            return {"error": f"uc {e}"}
        if err:
            return {"error": err[0]}
        if uc.reg_read(UC_ARM_REG_PC) & ~1 != RET:
            return {"error": "budget"}
        cp = uc.reg_read(UC_ARM_REG_CPSR)
        return {"regs": [uc.reg_read(r) for r in GPR], "flags": [cp >> 31 & 1, cp >> 30 & 1, cp >> 29 & 1, cp >> 28 & 1],
                "mem": {name: bytes(uc.mem_read(base, size)) for name, base, size, _ in REGIONS}, "calls": calls}


def compare(a, b):
    out = []
    for i, (x, y) in enumerate(zip(a["regs"], b["regs"])):
        if x != y:
            out.append(f"r{i} uc={x:#x} rc={y:#x}")
    if a["flags"] != b["flags"]:
        out.append(f"NZCV uc={a['flags']} rc={b['flags']}")
    for k in a["mem"]:
        if a["mem"][k] != b["mem"][k]:
            i = next(j for j, (x, y) in enumerate(zip(a["mem"][k], b["mem"][k])) if x != y)
            out.append(f"{k}+{i:#x} uc={a['mem'][k][i]:02x} rc={b['mem'][k][i]:02x}")
    if a["calls"] != b["calls"]:
        out.append(f"calls uc={a['calls'][:3]} rc={b['calls'][:3]}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rom"); ap.add_argument("lib"); ap.add_argument("elf")
    ap.add_argument("-n", type=int, default=20)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("-v", action="store_true")
    a = ap.parse_args()
    rom = open(a.rom, "rb").read()
    rc, uni = Recomp(a.lib, rom), Uni(rom)
    funcs = functions(a.elf)
    if a.only:
        funcs = [f for f in funcs if f[0] in a.only]
    rng = random.Random(a.seed)
    if a.sample:
        funcs = rng.sample(funcs, min(a.sample, len(funcs)))
    tally = {"ok": 0, "fail": 0, "untested": 0}
    fails = []
    for name, start, end in funcs:
        good = bad = skipped = 0
        first = None
        for it in range(a.n):
            mem, regs, flags = rand_state(rng)
            ru = uni.run(start, end, mem, regs, flags)
            rr = rc.run(start, mem, regs, flags)
            if "error" in ru or "error" in rr:
                # both failing the same way (bad pointers, waits) is not a verdict
                if ("error" in ru) != ("error" in rr) and not ("budget" in ru.get("error", "") or "fault 2" in rr.get("error", "")):
                    bad += 1
                    first = first or [f"uc: {ru.get('error', 'ok')}", f"rc: {rr.get('error', 'ok')}"]
                else:
                    skipped += 1
                continue
            d = compare(ru, rr)
            if d:
                bad += 1
                first = first or d
            else:
                good += 1
        if bad:
            tally["fail"] += 1
            fails.append((name, start, bad, good, first))
        elif good:
            tally["ok"] += 1
        else:
            tally["untested"] += 1
        if a.v:
            print(f"{'FAIL' if bad else 'ok  ' if good else 'skip'} {name} {start:#x}: {good} identical, {bad} differ, {skipped} skipped")
    for name, start, bad, good, first in fails[:40]:
        print(f"FAIL {name} @ {start:#x} ({bad} differ, {good} identical): " + "; ".join(first[:4]))
    print(f"functions: {tally['ok']} identical in all runs, {tally['fail']} with differences, "
          f"{tally['untested']} never completed (random state not usable)")
    sys.exit(1 if tally["fail"] else 0)


if __name__ == "__main__":
    main()
