#!/usr/bin/env python3
"""
difftest — differential test of decompiled C functions against the original assembly.

Runs each function in two images under the Unicorn ARM emulator, starting from the same
random RAM / register / key state, and compares everything observable afterwards:
RAM (EWRAM + IWRAM outside the stack), the return value in r0, and the sequence of calls
made to other assembly functions (which are stubbed out and recorded, not executed).

usage: difftest.py ASM_ROM ASM_SYMS C_ROM C_SYMS [-n ITER] [-f FUNC ...]
  *_SYMS: output of `arm-none-eabi-nm` for the image (matching build / FUNCTIONAL build).
"""
import argparse
import random
import sys

from unicorn import UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE, UC_HOOK_MEM_READ, Uc, UcError
from unicorn.arm_const import (UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1,
                               UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5,
                               UC_ARM_REG_R6, UC_ARM_REG_R7, UC_ARM_REG_R8, UC_ARM_REG_R9,
                               UC_ARM_REG_R10, UC_ARM_REG_R11, UC_ARM_REG_R12, UC_ARM_REG_SP)

GPRS = [UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5,
        UC_ARM_REG_R6, UC_ARM_REG_R7, UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11,
        UC_ARM_REG_R12]
EWRAM, EWRAM_SIZE = 0x02000000, 0x40000
IWRAM, IWRAM_SIZE = 0x03000000, 0x8000
IO, IO_SIZE = 0x04000000, 0x1000
ROM = 0x08000000
STACK_TOP = 0x03007E00
STACK_LOW = 0x03007000          # [STACK_LOW, end of IWRAM) is excluded from the RAM comparison
RET_ADDR = 0x0A000000           # unmapped-in-GBA magic return page
REG_KEYINPUT = 0x04000130
REG_DISPSTAT = 0x04000004


def load_syms(path):
    syms = {}
    for line in open(path):
        p = line.split()
        if len(p) >= 3:
            syms[p[2]] = int(p[0], 16)
        elif len(p) == 2:
            syms[p[1]] = int(p[0], 16)
    return syms


class Machine:
    def __init__(self, rom_path, syms):
        self.rom = open(rom_path, "rb").read()
        self.syms = syms
        self.addr_to_name = {}
        for n, a in syms.items():
            if ROM <= a < ROM + len(self.rom):
                self.addr_to_name.setdefault(a & ~1, n)

    def run(self, func, ram, regs, keys, stubs, read_hooks, max_insns=200000):
        uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        uc.mem_map(EWRAM, EWRAM_SIZE)
        uc.mem_map(IWRAM, IWRAM_SIZE)
        uc.mem_map(IO, IO_SIZE)
        rom_size = (len(self.rom) + 0xFFF) & ~0xFFF
        uc.mem_map(ROM, rom_size)
        uc.mem_map(RET_ADDR, 0x1000)
        uc.mem_write(ROM, self.rom)
        uc.mem_write(EWRAM, ram[0])
        uc.mem_write(IWRAM, ram[1])
        uc.mem_write(REG_KEYINPUT, keys.to_bytes(2, "little"))
        uc.mem_write(RET_ADDR, b"\x00\xbf" * 8)  # nops (never executed: we stop on arrival)
        for r, v in zip(GPRS, regs):
            uc.reg_write(r, v)
        uc.reg_write(UC_ARM_REG_R10, self.syms["MainState"])
        uc.reg_write(UC_ARM_REG_SP, STACK_TOP)
        uc.reg_write(UC_ARM_REG_LR, RET_ADDR | 1)

        calls = []
        stub_addrs = {self.syms[n] & ~1: n for n in stubs}

        def on_code(uc_, addr, size, _):
            if addr in stub_addrs:
                calls.append(stub_addrs[addr])
                uc_.reg_write(UC_ARM_REG_PC, uc_.reg_read(UC_ARM_REG_LR))

        uc.hook_add(UC_HOOK_CODE, on_code)
        for addr, fn in read_hooks:
            uc.hook_add(UC_HOOK_MEM_READ, lambda uc_, acc, a, sz, v, ud, fn=fn: fn(uc_, a), begin=addr, end=addr + 3)
        start = self.syms[func] & ~1
        try:
            uc.emu_start(start | 1, RET_ADDR, count=max_insns)
        except UcError as e:
            return {"error": f"{e} at pc={uc.reg_read(UC_ARM_REG_PC):#x}"}
        pc = uc.reg_read(UC_ARM_REG_PC)
        if pc & ~1 != RET_ADDR:
            return {"error": f"did not return (pc={pc:#x}, instruction budget exhausted?)"}
        return {
            "r0": uc.reg_read(UC_ARM_REG_R0),
            "sp": uc.reg_read(UC_ARM_REG_SP),
            "ewram": bytes(uc.mem_read(EWRAM, EWRAM_SIZE)),
            "iwram": bytes(uc.mem_read(IWRAM, STACK_LOW - IWRAM)),
            "calls": calls,
        }


def diff_bytes(a, b, base):
    out = []
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            out.append(f"{base + i:#010x}: asm={x:02x} c={y:02x}")
            if len(out) >= 8:
                break
    return out


# ---- per-function scenarios -------------------------------------------------------------

def counter_increments(addr):
    """read hook: every read of a u16 counter at `addr` bumps it (simulates VBlank IRQs)."""
    def fn(uc, a):
        if a == addr:
            v = int.from_bytes(uc.mem_read(addr, 2), "little")
            uc.mem_write(addr, ((v + 1) & 0xFFFF).to_bytes(2, "little"))
    return fn


def vblank_after(n):
    state = {"reads": 0}

    def fn(uc, a):
        if a == REG_DISPSTAT:
            state["reads"] += 1
            v = 1 if state["reads"] > n else 0
            uc.mem_write(REG_DISPSTAT, v.to_bytes(2, "little"))
    return fn


def scenario(func, rng, syms_asm):
    """Return (ram_tweaks, keys, stubs, read_hooks_factory) for one random run."""
    keys = rng.getrandbits(10) ^ 0x3FF  # REG_KEYINPUT is active-low
    stubs, hooks, tweaks = [], [], {}
    g = syms_asm
    if func == "Main_WaitFrames":
        wait = rng.randint(0, 6)
        tweaks[g["gFrameWaitValue"]] = wait.to_bytes(2, "little")
        tweaks[g["gVBlankFrameCounter"]] = rng.randint(0, 8).to_bytes(2, "little")
        hooks = [(g["gVBlankFrameCounter"], lambda: counter_increments(g["gVBlankFrameCounter"]))]
    elif func == "Main_WaitForVBlank":
        n = rng.randint(0, 5)
        hooks = [(REG_DISPSTAT, lambda n=n: vblank_after(n))]
    elif func == "Main_ReadInput":
        base = g["gInput"]
        tweaks[base + 19] = bytes([rng.randint(0, 4)])                       # frameCounter
        tweaks[base + 8] = bytes(rng.choice([0, 1, 15, 16, 17, 200]) for _ in range(10))
        if rng.random() < 0.5:                                                # held keys likely
            tweaks[base] = ((~keys) & 0x3FF | rng.getrandbits(1)).to_bytes(2, "little")
    elif func == "Main_SoftResetCheck":
        stubs = ["InitializeInterruptVectors", "Main_Init"]
        tweaks[g["gFadeSettings"] + 3] = bytes([rng.choice([0, 1, 1, 2])])
        tweaks[g["gManager"] + 4] = bytes([rng.choice([0, 0, 1, 2, 10, 255])])
        cur = rng.choice([0xF, 0xF, 0x7, rng.getrandbits(10)])
        tweaks[g["gInput"]] = cur.to_bytes(2, "little")
        tweaks[g["gInput"] + 2] = rng.choice([0, 1, 8, rng.getrandbits(10)]).to_bytes(2, "little")
    elif func.startswith("Rng_"):
        if rng.random() < 0.2:
            tweaks[g["gRngState"]] = rng.choice([0, 0xFFFFFFFF, 0x80000000]).to_bytes(4, "little")
    return tweaks, keys, stubs, hooks


DEFAULT_FUNCS = ["Main_WaitFrames", "Main_WaitForVBlank", "Main_ReadInput", "Main_SoftResetCheck",
                 "Rng_Init", "Rng_RandomUint", "Rng_RandomInt"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("asm_rom"); ap.add_argument("asm_syms"); ap.add_argument("c_rom"); ap.add_argument("c_syms")
    ap.add_argument("-n", type=int, default=300)
    ap.add_argument("-f", nargs="*", default=DEFAULT_FUNCS)
    ap.add_argument("--seed", type=int, default=1234)
    a = ap.parse_args()
    sa, sc = load_syms(a.asm_syms), load_syms(a.c_syms)
    ma, mc = Machine(a.asm_rom, sa), Machine(a.c_rom, sc)
    rng = random.Random(a.seed)
    failures = 0
    for func in a.f:
        bad = 0
        for it in range(a.n):
            ew = bytearray(rng.randbytes(EWRAM_SIZE))
            iw = bytearray(rng.randbytes(IWRAM_SIZE))
            tweaks, keys, stubs, hooks = scenario(func, rng, sa)
            for addr, val in tweaks.items():
                buf, base = (ew, EWRAM) if addr < IWRAM else (iw, IWRAM)
                buf[addr - base: addr - base + len(val)] = val
            regs = [rng.getrandbits(32) for _ in GPRS]
            ra = ma.run(func, (bytes(ew), bytes(iw)), regs, keys, stubs, [(h[0], h[1]()) for h in hooks])
            rc = mc.run(func, (bytes(ew), bytes(iw)), regs, keys, stubs, [(h[0], h[1]()) for h in hooks])
            problems = []
            for r, tag in ((ra, "asm"), (rc, "c")):
                if "error" in r:
                    problems.append(f"{tag}: {r['error']}")
            if not problems:
                if ra["sp"] != rc["sp"]:
                    problems.append(f"sp asm={ra['sp']:#x} c={rc['sp']:#x}")
                if ra["calls"] != rc["calls"]:
                    problems.append(f"calls asm={ra['calls']} c={rc['calls']}")
                problems += diff_bytes(ra["ewram"], rc["ewram"], EWRAM)
                problems += diff_bytes(ra["iwram"], rc["iwram"], IWRAM)
                if func.startswith("Rng_Random") and ra["r0"] != rc["r0"]:
                    problems.append(f"r0 asm={ra['r0']:#x} c={rc['r0']:#x}")
            if problems:
                bad += 1
                if bad <= 3:
                    print(f"FAIL {func} iter {it}:\n   " + "\n   ".join(problems))
        status = "OK  " if bad == 0 else "FAIL"
        print(f"{status} {func}: {a.n - bad}/{a.n} runs identical")
        failures += bad
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
