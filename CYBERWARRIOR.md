# CyberWarrior 3DS

Projeto para levar Mega Man Battle Network (USA) a um port nativo de 3DS, no estilo do Emerald 3DS
(duas telas; possivelmente outros jogos da série depois). Este fork de
[Silenthal/bn1](https://github.com/Silenthal/bn1) é a base da decompilação.

## Branches

- `develop` — espelho do upstream. Branches de PR para o Silenthal saem daqui, sem os arquivos do CyberWarrior.
- `cyberwarrior` — branch principal do projeto: CI, ferramentas, decompilação em andamento.

## Base ROM

A ROM nunca entra neste repositório nem em artifacts do Actions. O CI busca `base.gba` no repositório
privado `lordMagmoon/cyberwarrior-3ds-rom` usando o secret `BASE_ROM_TOKEN`
(token fine-grained, somente leitura de *Contents*, só naquele repositório).

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

### Validação

| Job do CI | O que garante |
|---|---|
| `matching` | build padrão byte a byte igual à ROM base (precisa do `BASE_ROM_TOKEN`) |
| `shift` | o código empurrado 0x100 bytes joga igual: o código vivo não tem ponteiros fixos |
| `functional` | build C x build asm: teste diferencial no Unicorn por função + todos os quadros iguais no mGBA |

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

## Próximo marco (proposta) — Marco 2: loop principal e subsistemas básicos

1. `AgbMain` + `Main_Init` em C (o loop vira C chamando asm pelos thunks; tabela `jumpTableMain`).
2. `dma.S`, `utility.S` (cópias/limpezas de memória — muito chamadas, boas para validar o `abi_scan`).
3. Vídeo: `Video_ApplySettings`, `Video_BlitScreens`, `BgUpdate_*`.
4. Roteiros novos: primeira batalha (para cobrir RNG em batalha e a Custom Screen depois).
5. Gerar thunks automaticamente a partir de uma lista (hoje são escritos à mão em `thunks.S`).
