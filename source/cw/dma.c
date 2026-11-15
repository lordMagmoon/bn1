/* CyberWarrior 3DS — functional C for parts of source/dma.S */
#if FUNCTIONAL
#include "cw/cw.h"

/* Waits until every DMA channel selected in `flags` (bit n = channel n) is idle. */
void Dma_WaitForEnd(u32 flags)
{
    u32 busy;
    do {
        busy = 0;
        if (flags & 1) busy |= CW_REG32(REG_DMA0 + 0x08);
        if (flags & 2) busy |= CW_REG32(REG_DMA0 + 0x14);
        if (flags & 4) busy |= CW_REG32(REG_DMA0 + 0x20);
        if (flags & 8) busy |= CW_REG32(REG_DMA0 + 0x2C);
    } while (busy & DMA_CNT_ENABLE);
}

void Dma_TransferListClear(void)
{
    gDmaParamListSize = 0;
}

/* Runs every queued channel-3 transfer, one at a time, then empties the queue. */
void Dma_TransferListStartAll(void)
{
    u32 n = gDmaParamListSize;
    struct CwDmaParam *p = gDmaParamList;

    while (n != 0) {
        cw_asm_Dma_SetDirect(p->src, p->dst, p->count, 3, p->control);
        Dma_WaitForEnd(8);
        n--;
        p++;
    }
    Dma_TransferListClear();
}
#endif
