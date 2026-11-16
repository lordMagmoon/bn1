# CyberWarrior 3DS

Projeto para levar Mega Man Battle Network (USA) a um port nativo de 3DS, no estilo do Emerald 3DS
(duas telas; possivelmente outros jogos da série depois). Este fork de
[Silenthal/bn1](https://github.com/Silenthal/bn1) é a base da decompilação.

## Branches

- `develop` — espelho do upstream. Branches de PR para o Silenthal saem daqui, sem os arquivos do CyberWarrior.
- `cyberwarrior` — branch principal do projeto: CI, ferramentas, decompilação em andamento.

## Base ROM

A ROM nunca entra neste repositório nem em artifacts do Actions. A comparação byte a byte roda
**dentro do repositório privado** `lordMagmoon/cyberwarrior-3ds-rom` (workflow `matching-check`): ele
baixa este fork (público), compila e compara com a ROM que está lá. Não precisa de token.
O job `matching` deste fork só compila (o `BASE_ROM_TOKEN` é opcional e não está configurado).

## Estratégia

O código do jogo foi escrito à mão em assembly (r10 como registrador global com `&MainState`,
convenção de chamada própria, ~36% das funções sujam r4–r7 sem salvar), então decompilação
*matching* não é viável fora das bibliotecas do SDK (m4a, sram). O caminho é decompilação
**funcional**:

- cada função decompilada ganha versão em C em `source/cw/`;
- o assembly original fica no `.S` dentro de `#if !FUNCTIONAL`, então o build padrão continua
  **idêntico à ROM**;
- `python3 build.py functional` (ou `make FUNCTIONAL=1`) usa o C no lugar do assembly.

### Convenção de chamada C ↔ asm

- O C é compilado com `-ffixed-r10`: o compilador nunca toca no r10, que o assembly usa como `&MainState`.
- O C acessa as globais direto (`gInput`, `gManager`…): a `MainState` é uma tabela fixa na ROM.
- **C chamando asm**: sempre pelos thunks `cw_asm_<nome>` de `source/cw/thunks.S`, que salvam e
  restauram r4–r11 (o assembly não preserva esses registradores).
- **asm chamando C**: antes de decompilar uma função, rodar
  `python3 cw/tools/abi_scan.py build/mmbn.elf <Função>`. Ele lista entradas, registradores
  escritos e, para cada chamador, o que ele lê depois da chamada. Se algum chamador depender de
  r1–r3, r12 ou flags, ou se a função receber entrada em r4+, precisa de um shim em asm.

### Código do SDK vindo da ROM (build byte a byte)

A ROM original foi montada com o **agbcc** e revisões antigas do SDK da Nintendo (driver de som m4a,
rotinas de SRAM) e com uma `libgcc` antiga (`__divsi3` em Thumb, `_call_via_rX`). Compilar os `.c`
equivalentes com o GCC moderno nunca reproduz a ROM. Por isso:

- `source/m4a_rom.S` e `source/sdk_rom.S` são **gerados da ROM** por `cw/tools/gen_rom_asm.py`
  (código em `.2byte`, todo ponteiro e `bl` externo simbólico, então continuam funcionando quando o
  código se desloca). Os `.c` (`m4a.c`, `agb_sram.c`) ficam como referência atrás de `M4A_C`/`SDK_C`.
- As cópias da `libgcc` antiga se chamam `rom_divsi3`/`rom_call_via_*`, para o C moderno poder usar a
  `libgcc` atual ao mesmo tempo.
- Correções de dados: tabelas de som com alinhamento natural (`m4a_tables.c`), byte 3 das 10 vozes de
  ruído que guardam `0xC0`, tabelas de keysplit que tinham sido lidas como vozes, a tabela de ponteiros
  do `agb_sram_ptr.S` e o preenchimento com zeros no fim do `m4a_1.S`.

### Validação

| Job do CI | O que garante |
|---|---|
| `matching` | build padrão byte a byte igual à ROM base (precisa do `BASE_ROM_TOKEN`) |
| `shift` | o código empurrado 0x100 bytes joga igual: o código vivo não tem ponteiros fixos |
| `functional` | build C x build asm: teste diferencial no Unicorn por função + as duas ROMs lado a lado no mGBA (`framecmp2`: tolera só quadros isolados com ≤ 2 linhas diferentes, efeito de tempo; falha em diferença maior ou quadros diferentes seguidos) |
| `matching-check` (repo privado) | build padrão byte a byte igual à ROM base |

Ferramentas:
- `cw/framecmp/framecmp.c` — roda a ROM na libmgba sem tela, com um roteiro de entradas, e imprime o CRC32 de cada quadro.
- `cw/movies/*.txt` — roteiros de entradas (`início duração TECLAS`). `intro_room.txt`: boot, New Game,
  diálogos, andar pelo quarto, soft reset (4.300 quadros).
- `cw/tests/difftest.py` — teste diferencial asm x C no Unicorn com RAM/registradores/teclas aleatórios.
  Validado com mutações (alterar a constante do RNG ou um limite do `ReadInput` faz o teste falhar).
- `cw/tools/abi_scan.py` — análise de convenção de chamada (ver acima).
- `cw/tools/cw_progress.py` — funções já em C / total.

### Ambiente local (sem devkitARM)

O `gcc-arm-none-eabi` do Ubuntu compila o projeto, mas o `m4a.c` sai diferente e o som trava o jogo
(a ROM local não é jogável). Serve para iterar e para rodar o `difftest` nas funções em C; a
validação oficial é sempre o CI com a imagem `devkitpro/devkitarm`. `gbafix` local: script Python mínimo.

## Marco 1 — fundação

- [x] Fork + repositório privado da ROM
- [x] CI: build asm + comparação byte a byte com a ROM base *(falta o secret `BASE_ROM_TOKEN` chegar ao CI)*
- [x] Ponteiros de ROM fixos: os 5 (`extra_far.S`, `build_chip_sack_far.S`) estão em código morto,
      provavelmente sobra da versão JP; o shift test prova que o código vivo é deslocável
- [x] Build duplo asm/C (`FUNCTIONAL=1`)
- [x] `cw/tools/abi_scan.py` + thunks C→asm
- [x] Primeiro lote em C: `Main_WaitFrames`, `Main_WaitForVBlank`, `Main_ReadInput`,
      `Main_SoftResetCheck`, `Rng_Init`, `Rng_RandomUint`, `Rng_RandomInt`
- [x] CI `functional` verde com o roteiro `intro_room` (4.300 quadros idênticos; difftest 300/300 por função)
- [x] Métrica de progresso: `python3 cw/tools/cw_progress.py .` → **7/9485 funções em C (0,07%)**

## Registro

- **2026-11-15** — fork, repositório privado da ROM, CI (`matching`, `shift`), `framecmp`.
  Descoberta: código escrito à mão em assembly → decompilação funcional.
- **2026-11-15** — build duplo asm/C, primeiras 7 funções em C (loop principal, entrada, RNG),
  `abi_scan`, `difftest` (200/200 execuções idênticas por função), job `functional`, roteiro `intro_room`.
- **2026-11-15** — CI `functional` verde. O difftest pegou uma armadilha real: o GCC do devkitARM usa
  C23 por padrão, onde `bool` vira `_Bool` e `isFadeActive == 1` virava `!= 0` (o jogo guarda 2 ali).
  Correção: C compilado com `-std=gnu17`. **Marco 1 concluído** (falta só o `BASE_ROM_TOKEN` no CI).

## Marco 3 — recompilação estática (em andamento)

Objetivo: ver o jogo rodando fora do GBA cedo (PC primeiro, depois 3DS), sem esperar a decompilação manual.

- [x] `cw/recomp/thumb2c.py`: traduz **todo o código Thumb da ROM** (9.552 funções, ~183 mil instruções)
      para C que mantém o estado completo do ARM7TDMI (registradores, NZCV, mapa de memória do GBA).
      Desvios viram `goto`; `bl` vira chamada com retorno verificado; saltos calculados (`bx`, `pop {pc}`,
      `mov pc`) voltam, vão para um rótulo local ou viram chamada de cauda; retorno para outro lugar
      "desenrola" a pilha de C até o dono. Literais da ROM viram constantes. `mov lr, pc` marca o ponto
      de retorno de chamadas `mov lr,pc; bx rX`.
- [x] `cw/recomp/cw_rt.{h,c}`: memória com espelhamento do GBA (modo estrito nos testes), flags exatas
      (deslocamentos por registrador, ADC/SBC), **leituras desalinhadas do ARM7** (rotação; `ldrsh` ímpar =
      `ldrsb`, que o jogo usa de propósito), divisão da BIOS, despachante de chamadas.
- [x] `cw/recomp/test_recomp.py`: cada função recompilada x código original no Unicorn, mesmo estado aleatório;
      compara r0–r14, NZCV, toda a memória e as chamadas. Amostra de 1.500 funções: **990 idênticas**,
      6 diferem só pelo comportamento de leitura desalinhada do ARM7 (o recompilador segue o GBA; o Unicorn
      é ARMv5), as restantes são tabelas de salto com índice aleatório caindo em dados.
- [x] Job `recomp` no CI (amostra de 400 funções por execução, semente muda por dia).
- [ ] Código ARM (rotina de interrupção, `SoundMain` do m4a, código copiado para a IWRAM).
- [ ] Interpretador de reserva para endereços não descobertos estaticamente.
- [ ] Camada de hardware no PC: vídeo (modos 0–2, sprites, blending), DMA, timers, IRQ/VBlank, teclado,
      som; laço principal com eventos de hardware nos pontos de `CW_LOOP`.
- [ ] Primeiro boot no PC, comparado quadro a quadro com o mGBA; depois a camada do 3DS.

## Marco 2 — loop principal e subsistemas básicos (em andamento)

- [x] `Main_Init` em C (21 chamadas a asm por thunks; r10 definido por `asm`)
- [x] `utility.S`: `memset_16`, `memcpy_8`, `ConvertNumToBCD`, `GetWidthOfBcdNumber`, `ArrayShuffle`,
      `GetRandomElementOfArray`, `IncrementGameTimer`, `IncrementMPCounters`, `SetSortDefault`
- [x] `dma.S`: `Dma_WaitForEnd`, `Dma_TransferListClear`, `Dma_TransferListStartAll` (thunk com 5º argumento em r4)
- [x] `cw/tools/guard_asm.py` (guardas automáticas), difftest com divisão da BIOS e argumentos/retornos
- [ ] Funções com convenção especial (`memset0_16`, `memcpy_16`, `memset_32`, `Dma_TransferListAdd`…): shims
- [ ] `AgbMain`, vídeo (`Video_ApplySettings`, `Video_BlitScreens`, `BgUpdate_*`)
- [ ] Roteiro até a primeira batalha

### Proposta original do Marco 2

1. `AgbMain` + `Main_Init` em C (o loop vira C chamando asm pelos thunks; tabela `jumpTableMain`).
2. `dma.S`, `utility.S` (cópias/limpezas de memória — muito chamadas, boas para validar o `abi_scan`).
3. Vídeo: `Video_ApplySettings`, `Video_BlitScreens`, `BgUpdate_*`.
4. Roteiros novos: primeira batalha (para cobrir RNG em batalha e a Custom Screen depois).
5. Gerar thunks automaticamente a partir de uma lista (hoje são escritos à mão em `thunks.S`).
- **2026-11-15** — Comparação byte a byte movida para o repositório privado (sem token).
  **Achado: o projeto upstream não casa com a ROM em nenhum devkitARM testado** (2025-07 a 2026-02:
  ~768 mil bytes diferentes). A causa é o `m4a.c` (driver de som do SDK): a ROM original foi
  compilada com o **agbcc** (a `MidiKeyToFreq` da ROM é idêntica à saída do `agbcc -O2`), e o
  upstream compila com o GCC moderno, que gera outro tamanho e desloca tudo depois dele.
  Com o agbcc do pret, ~27 das 54 funções do `m4a.c` já batem byte a byte; as outras diferem
  porque o `m4a.c` do pret é de outra versão do SDK. O `make check` do upstream não acusa isso
  porque o `|| quick_comp` engole o erro.
- **2026-11-15** — **Build byte a byte com qualquer devkitARM**: m4a, SRAM e libgcc antigos gerados da
  ROM; correções de dados de som. Localmente a ROM inteira bate (fora o logotipo do cabeçalho, que o
  `gbafix` oficial escreve). Marco 2: 13 funções novas em C (total 20/9485), `framecmp2` tolerante a
  diferenças de tempo de uma linha. `abi_scan` agora avisa funções sem chamadores diretos
  (`GetVcountPlusVal`, `ArraySort`, `FrameTimeToRealTime_Reg` não são referenciadas: código morto).
- **2026-11-16** — PR #1 sem resposta ainda. **Marco 3 iniciado**: recompilador estático Thumb→C para a ROM
  inteira, runtime e teste diferencial contra o Unicorn (990/1.500 funções idênticas na amostra; nenhuma
  diferença atribuível ao recompilador). Achado: o jogo usa de propósito `ldrsh` em endereço ímpar
  (no ARM7 lê um byte com sinal) para ler tabelas de coordenadas.
