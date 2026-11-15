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

## Estratégia (resumo)

O código do jogo foi escrito à mão em assembly (r10 como registrador global, convenção de chamada própria),
então decompilação *matching* não é viável fora das bibliotecas do SDK. O caminho é decompilação
**funcional**: cada função ganha versão em C, a versão em assembly continua sendo o padrão (ROM idêntica),
e o build `FUNCTIONAL=1` usa o C, validado por testes diferenciais (Unicorn por função; mGBA por quadros).

## Marco 1 — fundação

- [x] Fork + repositório privado da ROM
- [ ] CI: build asm + comparação byte a byte com a ROM base
- [ ] Ponteiros de ROM fixos viram símbolos (`extra_far.S`, `build_chip_sack_far.S`) + shift test
- [ ] Build duplo asm/C (`FUNCTIONAL=1`)
- [ ] `tools/abi_scan.py`: entradas/saídas/registradores sujos por função; thunks C↔asm
- [ ] Primeiro lote em C: `main.S`, `rng.S`, parte de `dma.S`, com testes diferenciais
