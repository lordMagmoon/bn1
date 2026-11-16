/* CyberWarrior recompiler runtime: memory map, call dispatch, BIOS calls. */
#include "cw_rt.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

u8 cw_ewram[0x40000], cw_iwram[0x8000], cw_io[0x400], cw_pal[0x400], cw_vram[0x18000],
    cw_oam[0x400], cw_sram[0x10000];
const u8 *cw_rom;
u64 cw_loop_limit = ~0ull;
u32 cw_rom_size;

static void fault(CwCpu *c, u32 addr) {
    if (!c->fault) { c->fault = 1; c->fault_addr = addr; }
}

/* Tests: no mirroring, only the exact region sizes are mapped (like the Unicorn reference). */
int cw_strict_map;
static const u32 strict_size[16] = { 0, 0, 0x40000, 0x8000, 0x400, 0x400, 0x18000, 0x400,
                                     0x2000000, 0, 0, 0, 0, 0, 0x10000, 0 };

u8 *cw_mem_ptr(CwCpu *c, u32 a, u32 size, int write) {
    if (cw_strict_map) {
        u32 region = a >> 24, off = a & 0xFFFFFF;
        if (region > 15 || off + size > strict_size[region] || (region == 8 && off + size > cw_rom_size)) {
            fault(c, a);
            return NULL;
        }
    }
    switch (a >> 24) {
    case 0x02: return &cw_ewram[a & 0x3FFFF];
    case 0x03: return &cw_iwram[a & 0x7FFF];
    case 0x04: if ((a & 0xFFFFFF) < 0x400) return &cw_io[a & 0x3FF]; break;
    case 0x05: return &cw_pal[a & 0x3FF];
    case 0x06: { u32 o = a & 0x1FFFF; if (o >= 0x18000) o -= 0x8000; return &cw_vram[o]; }
    case 0x07: return &cw_oam[a & 0x3FF];
    case 0x08: case 0x09: case 0x0A: case 0x0B: case 0x0C: case 0x0D: {
        u32 o = a & 0x1FFFFFF;
        if (write) { fault(c, a); return NULL; }
        if (o < cw_rom_size) return (u8 *)&cw_rom[o];
        break;
    }
    case 0x0E: case 0x0F: return &cw_sram[a & 0xFFFF];
    }
    fault(c, a);
    return NULL;
}

void cw_io_write(CwCpu *c, u32 addr, u32 value, u32 size) {
    (void)c;
    u32 o = addr & 0x3FF;
    for (u32 i = 0; i < size; ++i) cw_io[(o + i) & 0x3FF] = (u8)(value >> (8 * i));
}

void wr8(CwCpu *c, u32 a, u32 v) {
    if ((a >> 24) == 0x04) { cw_io_write(c, a, v, 1); return; }
    u8 *p = cw_mem_ptr(c, a, 1, 1); if (p) *p = (u8)v;
}
void wr16(CwCpu *c, u32 a, u32 v) {
    a &= ~1u;
    if ((a >> 24) == 0x04) { cw_io_write(c, a, v, 2); return; }
    u8 *p = cw_mem_ptr(c, a, 2, 1); if (p) { p[0] = (u8)v; p[1] = (u8)(v >> 8); }
}
void wr32(CwCpu *c, u32 a, u32 v) {
    a &= ~3u;
    if ((a >> 24) == 0x04) { cw_io_write(c, a, v, 4); return; }
    u8 *p = cw_mem_ptr(c, a, 4, 1); if (p) { p[0] = (u8)v; p[1] = (u8)(v >> 8); p[2] = (u8)(v >> 16); p[3] = (u8)(v >> 24); }
}

/* ---- dispatch ----------------------------------------------------------------------- */
static const CwEntry *find_entry(u32 a) {
    u32 lo = 0, hi = cw_entry_count;
    while (lo < hi) {
        u32 mid = (lo + hi) / 2;
        if (cw_entries[mid].addr < a) lo = mid + 1; else hi = mid;
    }
    return (lo < cw_entry_count && cw_entries[lo].addr == a) ? &cw_entries[lo] : NULL;
}

/* test mode: every call is recorded and returns immediately to lr */
int cw_test_mode;
u32 cw_test_calls[64][5];
int cw_test_ncalls;

void cw_call(CwCpu *c, u32 target) {
    if (cw_test_mode) {
        if (cw_test_ncalls < 64) {
            u32 *rec = cw_test_calls[cw_test_ncalls];
            rec[0] = target & ~1u;
            for (int i = 0; i < 4; ++i) rec[i + 1] = c->r[i];
        }
        ++cw_test_ncalls;
        c->ret = c->r[14];
        return;
    }
    const CwEntry *e = find_entry(target & ~1u);
    if (!e) { fault(c, target); c->ret = 0xFFFFFFFF; return; }
    e->fn(c, target & ~1u);
}

/* ---- BIOS (HLE) --------------------------------------------------------------------- */
void cw_swi(CwCpu *c, u32 num) {
    switch (num) {
    case 6: case 7: {                                   /* Div (r0/r1), DivArm (r1/r0) */
        s32 a = (s32)c->r[0], b = (s32)c->r[1];
        if (num == 7) { s32 t = a; a = b; b = t; }
        if (b == 0) { c->r[0] = 0; c->r[1] = (u32)a; c->r[3] = 0; break; }
        s64 q = (s64)a / b, m = (s64)a - q * b;
        c->r[0] = (u32)q; c->r[1] = (u32)m; c->r[3] = (u32)(q < 0 ? -q : q);
        break;
    }
    default:
        fault(c, 0xDEAD0000 | num);
    }
}

void cw_undefined(CwCpu *c, u32 addr, u32 insn) {
    (void)insn;
    fault(c, addr);
}

/* ---- test harness entry (used by cw/recomp/test_recomp.py through ctypes) ---------------- */
static const CwEntry *find_entry_pub(u32 a) { return find_entry(a); }
int cw_test_run(CwCpu *c, u32 addr) {
    const CwEntry *e = find_entry_pub(addr & ~1u);
    if (!e) return -1;
    cw_test_mode = 1;
    cw_test_ncalls = 0;
    e->fn(c, addr & ~1u);
    return 0;
}
void cw_set_rom(const u8 *rom, u32 size) { cw_rom = rom; cw_rom_size = size; }
