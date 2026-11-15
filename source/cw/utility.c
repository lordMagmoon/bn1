/* CyberWarrior 3DS — functional C for parts of source/utility.S */
#if FUNCTIONAL
#include "cw/cw.h"

/* Counters below are unsigned on purpose: the assembly wraps around on overflow, which is
 * undefined behaviour for signed ints in C. */

/* Sets `num` bytes at `ptr` to the 16-bit `val`, last halfword first (num must be even, >0). */
void memset_16(void *ptr, u32 num, u16 val)
{
    do {
        num -= 2;
        *(u16 *)((u8 *)ptr + num) = val;
    } while (num != 0);
}

/* Copies `num` bytes from `src` to `dst`, last byte first (num > 0). */
void memcpy_8(const void *src, void *dst, u32 num)
{
    do {
        num--;
        ((u8 *)dst)[num] = ((const u8 *)src)[num];
    } while (num != 0);
}

/* "a < b" as the assembly tests it: cmp + bmi, i.e. the sign of the 32-bit difference. */
static inline int cw_mi(u32 a, u32 b) { return (s32)(a - b) < 0; }

static const u32 sPowersOf10[8] = { 10000000, 1000000, 100000, 10000, 1000, 100, 10, 1 };

/* 10 -> 0x10, 64 -> 0x64; values from 99999999 up (by the asm's sign test) -> 0x99999999. */
u32 ConvertNumToBCD(u32 num)
{
    u32 bcd = 0;
    int i;

    if (!cw_mi(num, 99999999))
        return 0x99999999;
    for (i = 0; i < 8; i++) {
        u32 digit = 0;
        bcd <<= 4;
        while (!cw_mi(num, sPowersOf10[i])) {
            num -= sPowersOf10[i];
            digit++;
        }
        bcd |= digit;
    }
    return bcd;
}

/* Number of BCD digits (at least 1). */
s32 GetWidthOfBcdNumber(u32 bcd)
{
    s32 width;

    if (bcd == 0)
        return 1;
    for (width = 0; bcd != 0; bcd >>= 4)
        width++;
    return width;
}

/* Swaps two random elements, `count` times (count > 0). */
void ArrayShuffle(u8 *array, s32 size, u32 count)
{
    do {
        s32 a = Mod(Rng_RandomInt(), size);
        s32 b = Mod(Rng_RandomInt(), size);
        u8 t = array[a];
        array[a] = array[b];
        array[b] = t;
    } while (--count != 0);
}

u8 GetRandomElementOfArray(const u8 *array, s32 size)
{
    return array[Mod(Rng_RandomInt(), size)];
}

#define GAME_TIMER_MAX (5999 * 60 * 60)   /* 99:59 in frames */

void IncrementGameTimer(void)
{
    s32 t = (s32)((u32)gGameStats.gameTimer + 1);   /* wraps like the asm */
    if (t > GAME_TIMER_MAX)
        t = GAME_TIMER_MAX;
    gGameStats.gameTimer = t;
}

/* Adds `wins` multiplayer wins and one battle, both capped at 999. */
void IncrementMPCounters(s32 wins)
{
    s32 v = (s32)((u32)gGameStats.multiBattleWins + (u32)wins);
    if (v > 999)
        v = 999;
    gGameStats.multiBattleWins = v;
    v = gGameStats.multiBattleTotal + 1;
    if (v > 999)
        v = 999;
    gGameStats.multiBattleTotal = v;
}

void SetSortDefault(void)
{
    gGameStats.sortDirectionFolder = 4;
    gGameStats.sortDirectionSack = 4;
}
#endif
