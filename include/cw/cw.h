/*
 * CyberWarrior 3DS — shared declarations for the functional C decompilation.
 *
 * C files under source/cw/ are compiled only when FUNCTIONAL=1. In the default build they
 * are empty and the matching assembly is used instead, so the ROM stays byte-identical.
 *
 * Calling convention notes (see CYBERWARRIOR.md and cw/tools/abi_scan.py):
 *  - C is compiled with -ffixed-r10: r10 always holds &MainState for the assembly.
 *  - Assembly functions do NOT preserve r4-r11. C must call them through the
 *    cw_asm_<name> thunks from source/cw/thunks.S, which save and restore r4-r11.
 */
#ifndef CW_H
#define CW_H

#include "mmbn.h"

#define CW_REG16(addr) (*(volatile u16 *)(addr))
#define REG_DISPSTAT CW_REG16(0x04000004)
#define REG_KEYINPUT CW_REG16(0x04000130)

#define DISPSTAT_VBLANK 0x1

/* RAM globals (addresses fixed by ld_script.ld). */
extern struct Manager gManager;
extern struct Input gInput;
extern struct FadeSettings gFadeSettings;
extern struct FrameCounter gFrameCounter;
extern volatile u16 gVBlankFrameCounter;   /* incremented by the VBlank interrupt */
extern u16 gFrameWaitValue;
extern u32 gRngState;

/* Assembly functions called from C (through register-saving thunks). */
void cw_asm_InitializeInterruptVectors(void);
void cw_asm_Main_Init(void);

#endif /* CW_H */
