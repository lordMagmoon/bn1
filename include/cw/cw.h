/*
 * CyberWarrior 3DS — shared declarations for the functional C decompilation.
 *
 * C files under source/cw/ are compiled only when FUNCTIONAL=1. In the default build they
 * are empty and the matching assembly is used instead, so the ROM stays byte-identical.
 *
 * Calling convention notes (see CYBERWARRIOR.md and cw/tools/abi_scan.py):
 *  - C is compiled with -ffixed-r10: r10 always holds &MainState for the assembly.
 *  - C is compiled with -std=gnu17 so that mmbn.h's "bool" stays a plain byte: the game's
 *    flags are bytes that may hold values other than 0/1 (found by difftest on
 *    FadeSettings.isFadeActive == 2 with the C23 default of newer GCC).
 *  - Assembly functions do NOT preserve r4-r11. C must call them through the
 *    cw_asm_<name> thunks from source/cw/thunks.S, which save and restore r4-r11.
 */
#ifndef CW_H
#define CW_H

#include "mmbn.h"

#define CW_REG16(addr) (*(volatile u16 *)(addr))
#define CW_REG32(addr) (*(volatile u32 *)(addr))
#define REG_DISPSTAT CW_REG16(0x04000004)
#define REG_KEYINPUT CW_REG16(0x04000130)
#define REG_DMA0 0x040000B0
#define DMA_CNT_ENABLE 0x80000000u

#define DISPSTAT_VBLANK 0x1

/* RAM globals (addresses fixed by ld_script.ld). */
extern struct Manager gManager;
extern struct Input gInput;
extern struct FadeSettings gFadeSettings;
extern struct FrameCounter gFrameCounter;
extern volatile u16 gVBlankFrameCounter;   /* incremented by the VBlank interrupt */
extern u16 gFrameWaitValue;
extern u32 gRngState;
extern struct GameStats gGameStats;
extern struct DisplaySettings gDisplaySettings;
extern u32 gDmaParamListSize;

struct CwDmaParam { u32 src, dst, count, control; };
extern struct CwDmaParam gDmaParamList[64];

extern const u32 MainState[];   /* ROM table loaded into r10 (source/main.S) */

/* libagbsyscall (BIOS calls), same routines the assembly uses */
s32 Mod(s32 num, s32 denom);

/* Functions now in C that other C code calls */
u32 Rng_RandomInt(void);
void Rng_Init(void);
void Dma_WaitForEnd(u32 flags);
void Dma_TransferListClear(void);

/* Assembly functions called from C (through register-saving thunks, source/cw/thunks.S). */
void cw_asm_InitializeInterruptVectors(void);
void cw_asm_Main_Init(void);
void cw_asm_Video_InitClearColor(void);
void cw_asm_Video_ApplySettings(void);
void cw_asm_Sound_Init(void);
void cw_asm_BgUpdate_Init(void);
void cw_asm_Video_Init(void);
void cw_asm_Oam_Init(void);
void cw_asm_InitMainMenu(void);
void cw_asm_Oam_InitTransferData(void);
void cw_asm_Text_Init(void);
void cw_asm_Oam_InitAffineData(void);
void cw_asm_InitWorld_LoadGame(void);
void cw_asm_InitWorld_NewGame(void);
void cw_asm_Scene_UnloadAndResetStepCounter(void);
void cw_asm_Scene_UnloadIfMarked(void);
void cw_asm_InitBgTask(void);
void cw_asm_Video_InitBlendSettings(void);
void cw_asm_InitFadeSettings(void);
void cw_asm_Sio_SetReady(void);
void cw_asm_memset0_32(void *ptr, s32 num);
/* Dma_SetDirect takes its 5th argument (control) in r4. */
void cw_asm_Dma_SetDirect(u32 src, u32 dst, u32 count, u32 channel, u32 control);

#endif /* CW_H */
