@ CyberWarrior 3DS — thunks for calling hand-written assembly from C.
@ The game's assembly freely clobbers r4-r11, which C code expects to be preserved.
@ cw_asm_<name> saves r4-r11, calls <name> and restores them; r0-r2 are passed through
@ (arguments in, return values out).
#if FUNCTIONAL
    .syntax divided
    .thumb
    .text
    .align 2, 0

    .macro CW_ASM_THUNK name
    .global cw_asm_\name
    .thumb_func
cw_asm_\name:
    push    {r4-r7,lr}
    mov     r4,r8
    mov     r5,r9
    mov     r6,r10
    mov     r7,r11
    push    {r4-r7}
    bl      \name
    pop     {r4-r7}
    mov     r8,r4
    mov     r9,r5
    mov     r10,r6
    mov     r11,r7
    pop     {r4-r7}
    pop     {r3}
    bx      r3
    .endm

    CW_ASM_THUNK InitializeInterruptVectors
    CW_ASM_THUNK Main_Init
    CW_ASM_THUNK Video_InitClearColor
    CW_ASM_THUNK Video_ApplySettings
    CW_ASM_THUNK Sound_Init
    CW_ASM_THUNK BgUpdate_Init
    CW_ASM_THUNK Video_Init
    CW_ASM_THUNK Oam_Init
    CW_ASM_THUNK InitMainMenu
    CW_ASM_THUNK Oam_InitTransferData
    CW_ASM_THUNK Text_Init
    CW_ASM_THUNK Oam_InitAffineData
    CW_ASM_THUNK InitWorld_LoadGame
    CW_ASM_THUNK InitWorld_NewGame
    CW_ASM_THUNK Scene_UnloadAndResetStepCounter
    CW_ASM_THUNK Scene_UnloadIfMarked
    CW_ASM_THUNK InitBgTask
    CW_ASM_THUNK Video_InitBlendSettings
    CW_ASM_THUNK InitFadeSettings
    CW_ASM_THUNK Sio_SetReady
    CW_ASM_THUNK memset0_32

@ Dma_SetDirect(src r0, dst r1, count r2, channel r3, control r4): the 5th C argument is on
@ the stack. Dma_SetDirect only uses r0-r7, so r8-r11 need no saving here.
    .global cw_asm_Dma_SetDirect
    .thumb_func
cw_asm_Dma_SetDirect:
    push    {r4-r7,lr}
    ldr     r4,[sp,#20]
    bl      Dma_SetDirect
    pop     {r4-r7}
    pop     {r3}
    bx      r3

    .align 2, 0
#endif
