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

    .align 2, 0
#endif
