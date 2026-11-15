/* CyberWarrior 3DS — functional C for source/rng.S */
#if FUNCTIONAL
#include "cw/cw.h"

#define RNG_INIT_SEED 0xA338244Fu
#define RNG_CONSTANT  0x873CA9E5u

void Rng_Init(void)
{
    gRngState = RNG_INIT_SEED;
}

static u32 Rng_Next(void)
{
    u32 s = gRngState;
    s = ((s << 1) + (s >> 31) + 1) ^ RNG_CONSTANT;
    gRngState = s;
    return s;
}

/* Returns a random number in 0..0xFFFFFFFF. */
u32 Rng_RandomUint(void)
{
    return Rng_Next();
}

/* Returns a random number in 0..0x7FFFFFFF. */
u32 Rng_RandomInt(void)
{
    return Rng_Next() >> 1;
}
#endif
