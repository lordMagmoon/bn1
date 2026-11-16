#!/usr/bin/env python3
"""
thumb2c — static recompiler: GBA Thumb (ARMv4T) machine code -> C.

Every recompiled function keeps the ARM7TDMI architectural state in a CwCpu (registers, NZCV,
memory through the GBA map in cw_rt.c), so behaviour does not depend on calling conventions:
the game's hand-written assembly passes values in any register, and that is preserved.

Control flow:
  * branches inside a function           -> goto
  * bl X                                 -> lr = next|1; cw_call(X); resume at c->ret
  * bx / mov pc / add pc / pop {pc} -> T -> if T is this call's return address: return
                                          if T is a label here:  goto it
                                          else: cw_call(T) (tail call), then resume at c->ret
  * a return to an address that is not ours unwinds (returns) until a frame owns it.
Literal-pool loads from ROM are folded to constants.

usage: thumb2c.py ROM.gba SYMBOLS.elf OUT.c [--only NAME ...] [--report]
"""
import argparse, struct, sys
from elftools.elf.elffile import ELFFile

ROM_BASE = 0x08000000
COND = ["c->z", "!c->z", "c->c", "!c->c", "c->n", "!c->n", "c->v", "!c->v",
        "(c->c && !c->z)", "(!c->c || c->z)", "(c->n == c->v)", "(c->n != c->v)",
        "(!c->z && c->n == c->v)", "(c->z || c->n != c->v)"]
R = lambda i: f"c->r[{i}]"


class Rom:
    def __init__(self, path):
        self.b = open(path, "rb").read()
    def h(self, a):
        o = a - ROM_BASE
        return struct.unpack_from("<H", self.b, o)[0] if 0 <= o < len(self.b) - 1 else None
    def w(self, a):
        o = a - ROM_BASE
        return struct.unpack_from("<I", self.b, o)[0] if 0 <= o < len(self.b) - 3 else None


def bl_target(a, h1, h2):
    off = ((h1 & 0x7FF) << 12) | ((h2 & 0x7FF) << 1)
    if off & 0x400000:
        off -= 0x800000
    return a + 4 + off


def successors(rom, a, h):
    """(next_addr or None, [branch targets], is_bl, literal address or None)"""
    top5 = h >> 11
    if (h & 0xF800) == 0x4800:                          # ldr rd,[pc,#imm]
        return a + 2, [], None, ((a + 4) & ~3) + (h & 0xFF) * 4
    if (h & 0xF000) == 0xD000:
        cond = (h >> 8) & 0xF
        if cond < 0xE:
            off = h & 0xFF
            if off & 0x80:
                off -= 0x100
            return a + 2, [a + 4 + off * 2], None, None
        if cond == 0xF:                                  # swi
            return a + 2, [], None, None
        return None, [], None, None                      # undefined
    if top5 == 0x1C:                                     # b
        off = h & 0x7FF
        if off & 0x400:
            off -= 0x800
        return None, [a + 4 + off * 2], None, None
    if top5 == 0x1E:                                     # bl (first half)
        h2 = rom.h(a + 2)
        if h2 is not None and (h2 & 0xF800) == 0xF800:
            return a + 4, [], bl_target(a, h, h2), None
        return None, [], None, None
    if top5 == 0x1F:                                     # stray second half
        return None, [], None, None
    if (h & 0xFF00) == 0x4700:                           # bx
        return None, [], None, None
    if (h & 0xFC00) == 0x4400:                           # hi-register add/mov to pc ends the block
        op = (h >> 8) & 3
        rd = (h & 7) | ((h >> 4) & 8)
        if op in (0, 2) and rd == 15:
            return None, [], None, None
    if (h & 0xFF00) == 0xBD00:                           # pop {..., pc}
        return None, [], None, None
    return a + 2, [], None, None


class Func:
    def __init__(self, name, start, end):
        self.name, self.start, self.end = name, start, end
        self.roots = {start}
        self.insns = {}          # addr -> halfword (bl: first half)
        self.literals = set()
        self.calls = set()       # bl targets
        self.ptrs = set()        # ROM pointers found in literal pools

    def explore(self, rom):
        work = sorted(self.roots - set(self.insns))
        while work:
            a = work.pop()
            while self.start <= a < self.end and a not in self.insns and a not in self.literals:
                h = rom.h(a)
                if h is None:
                    break
                self.insns[a] = h
                nxt, targets, bl, lit = successors(rom, a, h)
                if lit is not None:
                    self.literals.add(lit)
                    v = rom.w(lit)
                    if v is not None and ROM_BASE <= v < ROM_BASE + len(rom.b):
                        self.ptrs.add(v)
                if bl is not None:
                    self.calls.add(bl)
                if h == 0x46FE:                          # mov lr, pc: a call returns to a+4
                    self.roots.add(a + 4)
                    work.append(a + 4)
                for t in targets:
                    if self.start <= t < self.end and t not in self.insns:
                        work.append(t)
                if nxt is None:
                    break
                a = nxt


def load_functions(elf_path, rom):
    elf = ELFFile(open(elf_path, "rb"))
    syms = []
    for s in elf.get_section_by_name(".symtab").iter_symbols():
        if s["st_info"]["type"] == "STT_FUNC" and (s["st_value"] & 1) and ROM_BASE <= s["st_value"] < 0x08800000:
            syms.append((s["st_value"] & ~1, s.name))
    syms = sorted(set(syms))
    starts = sorted({a for a, _ in syms})
    names = {}
    for a, n in syms:
        names.setdefault(a, n)
    funcs = []
    for i, a in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else a + 0x10000
        funcs.append(Func(names[a], a, end))
    return funcs


def owner(funcs_by_start, starts, a):
    import bisect
    i = bisect.bisect_right(starts, a) - 1
    if i >= 0:
        f = funcs_by_start[starts[i]]
        if f.start <= a < f.end:
            return f
    return None


def discover(funcs, rom):
    by_start = {f.start: f for f in funcs}
    starts = sorted(by_start)
    for _ in range(10):
        for f in funcs:
            f.explore(rom)
        changed = False
        for f in funcs:
            for t in list(f.calls) + [p & ~1 for p in f.ptrs if p & 1]:
                g = owner(by_start, starts, t)
                if g and t not in g.roots and t not in g.literals:
                    g.roots.add(t)
                    changed = True
        if not changed:
            break


# ---- code generation --------------------------------------------------------------------
class Gen:
    def __init__(self, rom, f):
        self.rom, self.f, self.out = rom, f, []

    def emit(self, s):
        self.out.append("    " + s)

    def jump(self, expr):
        self.emit(f"{{ t = {expr}; goto jump; }}")

    def insn(self, a, h):
        e, r = self.emit, R
        op5 = h >> 11
        if op5 <= 2:                                     # 1: shift by immediate
            rd, rs, n = h & 7, (h >> 3) & 7, (h >> 6) & 31
            fn = ["lsl_i", "lsr_i", "asr_i"][op5]
            e(f"{r(rd)} = {fn}(c, {r(rs)}, {n});")
        elif op5 == 3:                                   # 2: add/sub
            rd, rs, imm, rn = h & 7, (h >> 3) & 7, (h >> 6) & 7, (h >> 6) & 7
            operand = str(imm) if h & 0x400 else r(rn)
            fn = "sub_f" if h & 0x200 else "add_f"
            e(f"{r(rd)} = {fn}(c, {r(rs)}, {operand});")
        elif op5 >> 2 == 1:                              # 3: mov/cmp/add/sub imm8
            op, rd, imm = (h >> 11) & 3, (h >> 8) & 7, h & 0xFF
            if op == 0:
                e(f"{r(rd)} = nz(c, {imm});")
            elif op == 1:
                e(f"sub_f(c, {r(rd)}, {imm});")
            elif op == 2:
                e(f"{r(rd)} = add_f(c, {r(rd)}, {imm});")
            else:
                e(f"{r(rd)} = sub_f(c, {r(rd)}, {imm});")
        elif (h & 0xFC00) == 0x4000:                     # 4: ALU
            op, rs, rd = (h >> 6) & 15, (h >> 3) & 7, h & 7
            D, S = r(rd), r(rs)
            code = {
                0: f"{D} = nz(c, {D} & {S});", 1: f"{D} = nz(c, {D} ^ {S});",
                2: f"{D} = lsl_r(c, {D}, {S});", 3: f"{D} = lsr_r(c, {D}, {S});",
                4: f"{D} = asr_r(c, {D}, {S});", 5: f"{D} = adc_f(c, {D}, {S});",
                6: f"{D} = sbc_f(c, {D}, {S});", 7: f"{D} = ror_r(c, {D}, {S});",
                8: f"nz(c, {D} & {S});", 9: f"{D} = sub_f(c, 0, {S});",
                10: f"sub_f(c, {D}, {S});", 11: f"add_f(c, {D}, {S});",
                12: f"{D} = nz(c, {D} | {S});", 13: f"{D} = nz(c, {D} * {S});",
                14: f"{D} = nz(c, {D} & ~{S});", 15: f"{D} = nz(c, ~{S});",
            }[op]
            e(code)
        elif (h & 0xFC00) == 0x4400:                     # 5: hi-register ops / bx
            op = (h >> 8) & 3
            rs = (h >> 3) & 15
            rd = (h & 7) | ((h >> 4) & 8)
            src = f"0x{a + 4:08X}u" if rs == 15 else r(rs)
            dst_val = f"0x{a + 4:08X}u" if rd == 15 else r(rd)
            if op == 0:
                if rd == 15:
                    self.jump(f"{dst_val} + {src}")
                else:
                    e(f"{r(rd)} = {dst_val} + {src};")
            elif op == 1:
                e(f"sub_f(c, {dst_val}, {src});")
            elif op == 2:
                if rd == 15:
                    self.jump(src)
                else:
                    e(f"{r(rd)} = {src};")
            else:
                self.jump(src)
        elif (h & 0xF800) == 0x4800:                     # 6: pc-relative load
            rd = (h >> 8) & 7
            lit = ((a + 4) & ~3) + (h & 0xFF) * 4
            v = self.rom.w(lit)
            e(f"{r(rd)} = 0x{v:08X}u;" if v is not None else f"{r(rd)} = rd32(c, 0x{lit:08X}u);")
        elif (h & 0xF000) == 0x5000:                     # 7/8: register offset
            ro, rb, rd = (h >> 6) & 7, (h >> 3) & 7, h & 7
            ad = f"{r(rb)} + {r(ro)}"
            op = (h >> 9) & 7
            e([f"wr32(c, {ad}, {r(rd)});", f"wr16(c, {ad}, {r(rd)});", f"wr8(c, {ad}, {r(rd)});",
               f"{r(rd)} = rds8(c, {ad});", f"{r(rd)} = rd32(c, {ad});", f"{r(rd)} = rd16(c, {ad});",
               f"{r(rd)} = rd8(c, {ad});", f"{r(rd)} = rds16(c, {ad});"][op])
        elif (h & 0xE000) == 0x6000:                     # 9: imm offset word/byte
            off, rb, rd = (h >> 6) & 31, (h >> 3) & 7, h & 7
            byte, load = h & 0x1000, h & 0x800
            ad = f"{r(rb)} + {off if byte else off * 4}"
            if load:
                e(f"{r(rd)} = {'rd8' if byte else 'rd32'}(c, {ad});")
            else:
                e(f"{'wr8' if byte else 'wr32'}(c, {ad}, {r(rd)});")
        elif (h & 0xF000) == 0x8000:                     # 10: halfword imm
            off, rb, rd = ((h >> 6) & 31) * 2, (h >> 3) & 7, h & 7
            e(f"{r(rd)} = rd16(c, {r(rb)} + {off});" if h & 0x800 else f"wr16(c, {r(rb)} + {off}, {r(rd)});")
        elif (h & 0xF000) == 0x9000:                     # 11: sp-relative
            rd, off = (h >> 8) & 7, (h & 0xFF) * 4
            e(f"{r(rd)} = rd32(c, c->r[13] + {off});" if h & 0x800 else f"wr32(c, c->r[13] + {off}, {r(rd)});")
        elif (h & 0xF000) == 0xA000:                     # 12: load address
            rd, off = (h >> 8) & 7, (h & 0xFF) * 4
            if h & 0x800:
                e(f"{r(rd)} = c->r[13] + {off};")
            else:
                e(f"{r(rd)} = 0x{((a + 4) & ~3) + off:08X}u;")
        elif (h & 0xFF00) == 0xB000:                     # 13: add sp
            off = (h & 0x7F) * 4
            e(f"c->r[13] {'-' if h & 0x80 else '+'}= {off};")
        elif (h & 0xF600) == 0xB400:                     # 14: push/pop
            rl = [i for i in range(8) if h & (1 << i)]
            extra = h & 0x100
            if not h & 0x800:                            # push
                regs = rl + ([14] if extra else [])
                e(f"c->r[13] -= {4 * len(regs)};")
                for k, i in enumerate(regs):
                    e(f"wr32(c, c->r[13] + {4 * k}, {r(i)});")
            else:                                        # pop
                for k, i in enumerate(rl):
                    e(f"{r(i)} = rd32(c, c->r[13] + {4 * k});")
                if extra:
                    e(f"t = rd32(c, c->r[13] + {4 * len(rl)});")
                    e(f"c->r[13] += {4 * (len(rl) + 1)};")
                    e("goto jump;")
                else:
                    e(f"c->r[13] += {4 * len(rl)};")
        elif (h & 0xF000) == 0xC000:                     # 15: ldmia/stmia
            rb, rl = (h >> 8) & 7, [i for i in range(8) if h & (1 << i)]
            if not rl:
                e(f"cw_undefined(c, 0x{a:08X}u, 0x{h:04X}u); return;")
                return
            e(f"a = {r(rb)};")
            if h & 0x800:
                for k, i in enumerate(rl):
                    e(f"{r(i)} = rd32(c, a + {4 * k});")
                if rb not in rl:
                    e(f"{r(rb)} = a + {4 * len(rl)};")
            else:
                for k, i in enumerate(rl):
                    val = "a" if (i == rb and k == 0) else (f"a + {4 * len(rl)}" if i == rb else r(i))
                    e(f"wr32(c, a + {4 * k}, {val});")
                e(f"{r(rb)} = a + {4 * len(rl)};")
        elif (h & 0xF000) == 0xD000:                     # 16/17: conditional branch, swi
            cond = (h >> 8) & 15
            if cond == 15:
                e(f"cw_swi(c, {h & 0xFF});")
            elif cond == 14:
                e(f"cw_undefined(c, 0x{a:08X}u, 0x{h:04X}u); return;")
            else:
                off = h & 0xFF
                if off & 0x80:
                    off -= 0x100
                tgt = a + 4 + off * 2
                e(f"if ({COND[cond]}) {self.goto_or_jump(tgt, a)}")
        elif (h >> 11) == 0x1C:                          # 18: b
            off = h & 0x7FF
            if off & 0x400:
                off -= 0x800
            e(self.goto_or_jump(a + 4 + off * 2, a))
        elif (h >> 11) == 0x1E:                          # 19: bl
            h2 = self.rom.h(a + 2)
            if h2 is None or (h2 & 0xF800) != 0xF800:
                e(f"cw_undefined(c, 0x{a:08X}u, 0x{h:04X}u); return;")
                return
            tgt = bl_target(a, h, h2)
            nxt = a + 4
            e(f"c->r[14] = 0x{nxt | 1:08X}u; cw_call(c, 0x{tgt | 1:08X}u);")
            e(f"if ((c->ret & ~1u) != 0x{nxt:08X}u) {{ t = c->ret; goto resume; }}")
        else:
            e(f"cw_undefined(c, 0x{a:08X}u, 0x{h:04X}u); return;")

    def goto_or_jump(self, tgt, here=None):
        if tgt in self.f.insns:
            if here is not None and tgt <= here:          # backward branch: loop guard
                return f"{{ CW_LOOP(c); goto L_{tgt:08X}; }}"
            return f"goto L_{tgt:08X};"
        return f"{{ t = 0x{tgt | 1:08X}u; goto jump; }}"

    def generate(self):
        f = self.f
        addrs = sorted(f.insns)
        out = [f"void F_{f.start:08X}(CwCpu *c, u32 entry)  /* {f.name} */", "{",
               "    u32 ret_expect = c->r[14] & ~1u, t, a;", "    (void)a;",
               "    t = entry; goto dispatch;"]
        self.out = out
        prev_end = None
        for ad in addrs:
            if prev_end is not None and ad != prev_end:
                # previous instruction falls through into a gap (data / unexplored): treat as jump
                pass
            out.append(f"L_{ad:08X}: __attribute__((unused));")
            self.insn(ad, f.insns[ad])
            nxt, _, bl, _ = successors(self.rom, ad, f.insns[ad])
            if nxt is not None and nxt not in f.insns:
                self.emit(f"{{ t = 0x{nxt | 1:08X}u; goto jump; }}  /* falls out of known code */")
            prev_end = None
        out += [
            "jump:",                                     # t = target (may carry the Thumb bit)
            "    CW_LOOP(c);",
            "    if ((t & ~1u) == ret_expect) { c->ret = t; return; }",
            "    switch (t & ~1u) {",
        ]
        out += [f"    case 0x{ad:08X}u: goto L_{ad:08X};" for ad in addrs]
        out += ["    }",
                "    cw_call(c, t);",                    # tail call; resume where it returned
                "    t = c->ret;",
                "resume:",
                "    if ((t & ~1u) == ret_expect) { c->ret = t; return; }",
                "dispatch:",
                "    switch (t & ~1u) {"]
        out += [f"    case 0x{ad:08X}u: goto L_{ad:08X};" for ad in addrs]
        out += ["    }",
                "    c->ret = t; return;",                # not ours: unwind
                "}", ""]
        return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rom"); ap.add_argument("elf"); ap.add_argument("out")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()
    rom = Rom(a.rom)
    funcs = load_functions(a.elf, rom)
    discover(funcs, rom)
    sel = [f for f in funcs if f.insns and (not a.only or f.name in a.only)]
    parts = ['#include "cw_rt.h"', ""]
    parts += [f"void F_{f.start:08X}(CwCpu *c, u32 entry);" for f in sel]
    parts.append("")
    for f in sel:
        parts.append(Gen(rom, f).generate())
    entries = sorted({(ad, f.start) for f in sel for ad in f.insns})
    parts.append("const CwEntry cw_entries[] = {")
    parts += [f"    {{ 0x{ad:08X}u, F_{fs:08X} }}," for ad, fs in entries]
    parts.append("};")
    parts.append(f"const u32 cw_entry_count = {len(entries)};")
    open(a.out, "w").write("\n".join(parts) + "\n")
    n_ins = sum(len(f.insns) for f in sel)
    print(f"{len(sel)} functions, {n_ins} instructions, {len(entries)} entry points -> {a.out}")
    if a.report:
        undef = sum(1 for f in sel for ad, h in f.insns.items() if ((h >> 11) == 0x1F) or ((h & 0xFF00) == 0xDE00))
        print(f"  undefined/stray encodings reached: {undef}")


if __name__ == "__main__":
    main()
