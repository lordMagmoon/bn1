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

from unicorn import UC_ARCH_ARM, UC_MODE_THUMB, UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_INTR, Uc, UcError
from unicorn.arm_const import (UC_ARM_REG_CPSR, UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1,
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

    def run(self, func, ram, regs, keys, stubs, read_hooks, record_args=(), stack_args=(), max_insns=400000):
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
        sp = STACK_TOP - 4 * len(stack_args)
        for k, v in enumerate(stack_args):
            uc.mem_write(sp + 4 * k, (v & 0xFFFFFFFF).to_bytes(4, "little"))
        uc.reg_write(UC_ARM_REG_SP, sp)
        uc.reg_write(UC_ARM_REG_LR, RET_ADDR | 1)

        calls = []
        stub_addrs = {self.syms[n] & ~1: n for n in stubs}

        def on_code(uc_, addr, size, _):
            if addr in stub_addrs:
                name = stub_addrs[addr]
                if name in record_args:
                    calls.append((name,) + tuple(uc_.reg_read(r) for r in GPRS[:5]))
                else:
                    calls.append(name)
                uc_.reg_write(UC_ARM_REG_PC, uc_.reg_read(UC_ARM_REG_LR))

        uc.hook_add(UC_HOOK_CODE, on_code)

        def on_swi(uc_, intno, _):
            # BIOS division: swi 6 (Div: r0/r1) and swi 7 (DivArm: r1/r0). Thumb: pc is past the swi.
            pc = uc_.reg_read(UC_ARM_REG_PC)
            num = uc_.mem_read(pc - 2, 1)[0]
            r0, r1 = uc_.reg_read(UC_ARM_REG_R0), uc_.reg_read(UC_ARM_REG_R1)
            if num == 7:
                r0, r1 = r1, r0
            if num in (6, 7):
                a = r0 - (1 << 32) if r0 & 0x80000000 else r0
                b = r1 - (1 << 32) if r1 & 0x80000000 else r1
                if b == 0:
                    q, m = 0, a           # real BIOS hangs/returns garbage; same value for both images
                else:
                    q = abs(a) // abs(b) * (1 if (a < 0) == (b < 0) else -1)
                    m = a - q * b
                uc_.reg_write(UC_ARM_REG_R0, q & 0xFFFFFFFF)
                uc_.reg_write(UC_ARM_REG_R1, m & 0xFFFFFFFF)
                uc_.reg_write(UC_ARM_REG_R3, abs(q) & 0xFFFFFFFF)
            else:
                uc_.emu_stop()

        uc.hook_add(UC_HOOK_INTR, on_swi)
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


def dma_busy(n):
    """read hook on DMA CNT registers: busy (enable bit set) for the first n reads."""
    state = {"reads": 0}

    def fn(uc, a):
        state["reads"] += 1
        busy = state["reads"] <= n
        for off in (0x08, 0x14, 0x20, 0x2C):
            v = int.from_bytes(uc.mem_read(0x040000B0 + off, 4), "little")
            v = (v | 0x80000000) if busy else (v & 0x7FFFFFFF)
            uc.mem_write(0x040000B0 + off, v.to_bytes(4, "little"))
    return fn


RETURNS_R0 = {"Rng_RandomUint", "Rng_RandomInt", "ConvertNumToBCD", "GetWidthOfBcdNumber",
              "GetRandomElementOfArray"}


def scenario(func, rng, syms_asm):
    """One random run: RAM tweaks, keys, stubbed callees, read hooks, arguments."""
    g = syms_asm
    sc = {"keys": rng.getrandbits(10) ^ 0x3FF, "stubs": [], "hooks": [], "tweaks": {}, "args": {},
          "record_args": (), "stack_args": ()}
    tw, args = sc["tweaks"], sc["args"]
    buf = lambda: 0x02030000 + rng.randrange(0, 0x1000, 4)
    if func == "Main_WaitFrames":
        tw[g["gFrameWaitValue"]] = rng.randint(0, 6).to_bytes(2, "little")
        tw[g["gVBlankFrameCounter"]] = rng.randint(0, 8).to_bytes(2, "little")
        sc["hooks"] = [(g["gVBlankFrameCounter"], lambda: counter_increments(g["gVBlankFrameCounter"]))]
    elif func == "Main_WaitForVBlank":
        n = rng.randint(0, 5)
        sc["hooks"] = [(REG_DISPSTAT, lambda n=n: vblank_after(n))]
    elif func == "Main_ReadInput":
        base = g["gInput"]
        tw[base + 19] = bytes([rng.randint(0, 4)])
        tw[base + 8] = bytes(rng.choice([0, 1, 15, 16, 17, 200]) for _ in range(10))
        if rng.random() < 0.5:
            tw[base] = ((~sc["keys"]) & 0x3FF | rng.getrandbits(1)).to_bytes(2, "little")
    elif func == "Main_SoftResetCheck":
        sc["stubs"] = ["InitializeInterruptVectors", "Main_Init"]
        tw[g["gFadeSettings"] + 3] = bytes([rng.choice([0, 1, 1, 2])])
        tw[g["gManager"] + 4] = bytes([rng.choice([0, 0, 1, 2, 10, 255])])
        tw[g["gInput"]] = rng.choice([0xF, 0xF, 0x7, rng.getrandbits(10)]).to_bytes(2, "little")
        tw[g["gInput"] + 2] = rng.choice([0, 1, 8, rng.getrandbits(10)]).to_bytes(2, "little")
    elif func == "Main_Init":
        sc["stubs"] = ["Video_InitClearColor", "Video_ApplySettings", "Sound_Init", "BgUpdate_Init",
                       "Video_Init", "Oam_Init", "InitMainMenu", "Oam_InitTransferData", "Text_Init",
                       "Oam_InitAffineData", "InitWorld_LoadGame", "InitWorld_NewGame",
                       "Scene_UnloadAndResetStepCounter", "Scene_UnloadIfMarked", "InitBgTask",
                       "Video_InitBlendSettings", "InitFadeSettings", "Sio_SetReady"]
    elif func.startswith("Rng_"):
        if rng.random() < 0.2:
            tw[g["gRngState"]] = rng.choice([0, 0xFFFFFFFF, 0x80000000]).to_bytes(4, "little")
    elif func == "memset_16":
        args.update(r0=buf(), r1=2 * rng.randint(1, 40), r2=rng.getrandbits(32))
    elif func == "memcpy_8":
        args.update(r0=buf(), r1=buf() + 0x2000, r2=rng.randint(1, 80))
    elif func == "ConvertNumToBCD":
        args.update(r0=rng.choice([0, 1, 9, 10, 99, 12345678, 99999998, 99999999, 100000000,
                                   0x7FFFFFFF, 0x80000000, 0xFFFFFFFF, rng.getrandbits(32),
                                   rng.randint(0, 99999999)]))
    elif func == "GetWidthOfBcdNumber":
        args.update(r0=rng.choice([0, 1, 0x10, 0x99999999, rng.getrandbits(32), rng.getrandbits(12)]))
    elif func == "ArrayShuffle":
        args.update(r0=buf(), r1=rng.randint(1, 30), r2=rng.randint(1, 12))
    elif func == "GetRandomElementOfArray":
        args.update(r0=buf(), r1=rng.randint(1, 30))
    elif func == "IncrementGameTimer":
        tw[g["gGameStats"] + 24] = rng.choice([0, 1, 5999 * 3600 - 1, 5999 * 3600, 5999 * 3600 + 7,
                                               0x7FFFFFFF, 0xFFFFFFFF, rng.getrandbits(32)]).to_bytes(4, "little")
    elif func == "IncrementMPCounters":
        args.update(r0=rng.choice([0, 1, 2, 998, 999, 1000, 0xFFFFFFFF, rng.getrandbits(32)]))
        tw[g["gGameStats"] + 20] = rng.choice([0, 998, 999, 1000, 0xFFFF]).to_bytes(2, "little")
        tw[g["gGameStats"] + 22] = rng.choice([0, 998, 999, 1000, 0xFFFF]).to_bytes(2, "little")
    elif func == "Dma_WaitForEnd":
        args.update(r0=rng.getrandbits(4))
        n = rng.randint(0, 6)
        sc["hooks"] = [(0x040000B0 + o, lambda n=n: dma_busy(n)) for o in (0x08, 0x14, 0x20, 0x2C)]
    elif func == "Dma_TransferListStartAll":
        sc["stubs"] = ["Dma_SetDirect"]
        sc["record_args"] = ("Dma_SetDirect",)
        tw[g["gDmaParamListSize"]] = rng.randint(0, 6).to_bytes(4, "little")
    return sc


DEFAULT_FUNCS = ["Main_WaitFrames", "Main_WaitForVBlank", "Main_ReadInput", "Main_SoftResetCheck",
                 "Main_Init", "Rng_Init", "Rng_RandomUint", "Rng_RandomInt",
                 "memset_16", "memcpy_8", "ConvertNumToBCD", "GetWidthOfBcdNumber", "ArrayShuffle",
                 "GetRandomElementOfArray", "IncrementGameTimer", "IncrementMPCounters", "SetSortDefault",
                 "Dma_WaitForEnd", "Dma_TransferListClear", "Dma_TransferListStartAll"]


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
            sc = scenario(func, rng, sa)
            for addr, val in sc["tweaks"].items():
                buf, base = (ew, EWRAM) if addr < IWRAM else (iw, IWRAM)
                buf[addr - base: addr - base + len(val)] = val
            regs = [rng.getrandbits(32) for _ in GPRS]
            for k, v in sc["args"].items():
                regs[int(k[1:])] = v & 0xFFFFFFFF
            run = lambda m: m.run(func, (bytes(ew), bytes(iw)), regs, sc["keys"], sc["stubs"],
                                  [(h[0], h[1]()) for h in sc["hooks"]], sc["record_args"], sc["stack_args"])
            ra, rc = run(ma), run(mc)
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
                if func in RETURNS_R0 and ra["r0"] != rc["r0"]:
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
