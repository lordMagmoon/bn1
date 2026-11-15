/* CyberWarrior 3DS — functional C for parts of source/main.S */
#if FUNCTIONAL
#include "cw/cw.h"

/* Initializes the main state (r10 = &MainState) and every subsystem. Called at boot and on soft reset. */
void Main_Init(void)
{
    __asm__ volatile("mov r10, %0" : : "r"(MainState));
    gDisplaySettings.dispcnt = 0x40;
    cw_asm_Video_InitClearColor();
    cw_asm_Video_ApplySettings();
    cw_asm_Sound_Init();
    cw_asm_BgUpdate_Init();
    cw_asm_Video_Init();
    cw_asm_Oam_Init();
    cw_asm_InitMainMenu();
    cw_asm_Oam_InitTransferData();
    Dma_TransferListClear();
    Rng_Init();
    cw_asm_Text_Init();
    cw_asm_Oam_InitAffineData();
    cw_asm_InitWorld_LoadGame();
    cw_asm_InitWorld_NewGame();
    cw_asm_Scene_UnloadAndResetStepCounter();
    cw_asm_Scene_UnloadIfMarked();
    cw_asm_InitBgTask();
    cw_asm_Video_InitBlendSettings();
    cw_asm_InitFadeSettings();
    cw_asm_Sio_SetReady();
    gFrameWaitValue = 1;
    cw_asm_memset0_32(&gManager, 8);
}

/* Waits until the VBlank interrupt has counted gFrameWaitValue frames, then resets the count. */
void Main_WaitFrames(void)
{
    while ((s32)gVBlankFrameCounter < (s32)gFrameWaitValue)
        ;
    gVBlankFrameCounter = 0;
}

/* Busy-waits until the display is in VBlank. */
void Main_WaitForVBlank(void)
{
    while (!(REG_DISPSTAT & DISPSTAT_VBLANK))
        ;
}

/*
 * Reads the keypad.
 *  curKeyState    keys down now
 *  lastKeyState   keys down last frame
 *  toggleKeyState keys pressed this frame (down now, up last frame)
 *  heldKeyState   auto-repeat: a key held across frames reports on its first held frame,
 *                 then, after 16 held frames, once every 4 frames (when frameCounter wraps to 0)
 */
void Main_ReadInput(void)
{
    struct Input *in = &gInput;
    u8 phase = in->frameCounter + 1;
    u16 keys, last, held;
    int i;

    if (phase > 3)
        phase = 0;
    in->frameCounter = phase;

    keys = (u16)~REG_KEYINPUT;
    last = in->curKeyState;
    in->lastKeyState = last;
    in->curKeyState = keys;
    held = keys & last;

    for (i = 0; i < 10; i++) {
        u8 *frames = &in->framesHeldA + i;
        u16 bit = 1 << i;

        if (!(held & bit)) {
            *frames = 0;
            continue;
        }
        if (*frames < 16) {
            *frames += 1;
            if (*frames == 1)
                continue;
        } else if (in->frameCounter == 0) {
            continue;
        }
        held &= ~bit;
    }

    in->heldKeyState = held;
    in->toggleKeyState = keys & (u16)~last;
}

/*
 * Soft reset (A+B+Select+Start, with at least one of them newly pressed), ignored while a
 * fade is running and for a few frames after the previous reset.
 */
void Main_SoftResetCheck(void)
{
    s32 timer;

    if (gFadeSettings.isFadeActive == 1)
        return;

    timer = (s32)gManager.m_softResetDelayTimer - 1;
    if (timer <= 0) {
        timer = 0;
        if ((gInput.curKeyState & 0xF) == 0xF && (gInput.toggleKeyState & 0xF) != 0) {
            cw_asm_InitializeInterruptVectors();
            cw_asm_Main_Init();
            timer = 10;
        }
    }
    gManager.m_softResetDelayTimer = timer;
}
#endif
