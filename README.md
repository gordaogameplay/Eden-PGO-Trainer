# Lichii PGO Trainer

[English](README.en.md) · **Português (Brasil)**

Ferramenta gráfica (sem IA, sem downloads de jogo) para qualquer pessoa fazer **Profile-Guided Optimization (PGO)** do emulador Lichii/Eden (usado com *The Legend of Zelda: Ocarina of Time* emSwitch 2) **na própria máquina**, em **Linux ou Windows**.

Ela automatiza o mesmo método que usamos na maratona de PGO:

1. **Compila** uma build instrumentada (`-fprofile-generate -fprofile-update=atomic -DPGO_TRAINING`).
2. **Abre o jogo** com o teu dump e deixa você jogar por N sessões de 4 minutos.
3. **Fecha o jogo de forma limpa** (SIGTERM no Linux / CTRL_BREAK no Windows) para gravar os contadores.
4. **Junta todos os perfis** (os `.gcda` somam-se sozinhos) e **compila a build final** (`-fprofile-use`).

> O binário e o perfil são **específicos da tua máquina** (CPU + GPU). Não se partilham. O que é partilhável é **este método** — e é exatamente o que este repositório faz.

---

## O que está incluído

| ficheiro / pasta | o que é |
|---|---|
| `pgo_trainer.py` | Interface gráfica (Tkinter) — pede o dump, o nº de treinos, gere tudo |
| `pgo_core.py` | Núcleo: deteção de ferramentas, builds, processo de treino, perfis |
| `emulator-source/` | **Cópia limpa do código-fonte do emulador** (60 MB), já com os handlers de fecho limpo para Linux e Windows no `yuzu.cpp` |
| `run-linux.sh` / `run-windows.bat` | Arranque rápido |
| `licenses/` | Licenças do emulador e dependências |

---

## Requisitos

### Linux (Arch / CachyOS, Debian / Ubuntu, Fedora…)
```bash
# Arch / CachyOS
sudo pacman -S --noconfirm base-devel cmake ninja git tk \
    libx11 libxext libxrandr libxcursor libxi libxss libxfixes libxtst \
    libxkbcommon wayland wayland-protocols libdecor libegl libdrm libgbm \
    libpulse alsa-lib libpipewire libdbus libudev libibus libvulkan

# Debian / Ubuntu
sudo apt install -y build-essential cmake ninja-build git python3-tk \
    libx11-dev libxext-dev libxrandr-dev libxcursor-dev libxi-dev libxss-dev libxfixes-dev libxtst-dev \
    libxkbcommon-dev libwayland-dev wayland-protocols libdecor-0-dev libegl-dev libdrm-dev libgbm-dev \
    libpulse-dev libasound2-dev libpipewire-0.3-dev libdbus-1-dev libudev-dev libibus-1.0-dev libvulkan-dev
```

### Windows (MSYS2 / MinGW-w64)
1. Instala o **Python** (marca a opção *tcl/tk and IDLE*).
2. Instala o **MSYS2** (https://www.msys2.org) e, no terminal **UCRT64**:
   ```bash
   pacman -S mingw-w64-ucrt-x86_64-gcc mingw-w64-ucrt-x86_64-cmake mingw-w64-ucrt-x86_64-ninja git
   ```
3. Adiciona `C:\msys64\ucrt64\bin` ao **PATH** do Windows.
4. Instala as dependências do emulador (SDL3, FFmpeg, Vulkan, etc.) — o CMake vai buscar as principais via CPM (precisa de internet na primeira configuração).

---

## Como usar (passo a passo)

### 1. Arranque
```bash
# Linux
./run-linux.sh

# Windows
run-windows.bat
```

### 2. Preenche a interface
- **Dump do jogo**: escolhe o teu `.nup` (ou `exefs/main`) do Zelda OoT.
- **Pasta do código-fonte**: por omissão é `emulator-source/` (incluída). Podes apontar para o teu próprio checkout.
- **Quantos treinos**: `3` (recomendado). Podes pôr até 10.
- **Segundos por treino**: `240` (4 minutos). **Nunca passes de 438s** — o contador mais quente estoura `2^31` e corrompe o perfil.
- **Threads de compilação`: nº de núcleos (baixa para 4-6 se ficar sem RAM).

### 3. Clica em **Verificar ferramentas**
Confirma que CMake, Ninja e GCC/Clang foram detetados.

### 4. Clica em **INICIAR**
A aplicação faz tudo sozinha:
1. `cmake ... -DCMAKE_CXX_FLAGS="-march=native -mtune=native -DPGO_TRAINING -fprofile-generate -fprofile-update=atomic" -DENABLE_WERROR=OFF`
2. `ninja -j N eden-cli`
3. Para cada treino: abre o jogo → **você joga normalmente** → ao fim dos 4 min fecha limpo → grava `.gcda`.
4. Junta os perfis (soma automática).
5. `cmake ... -fprofile-use -fprofile-correction -Wno-missing-profile` (mesmo `-DPGO_TRAINING`!) → `ninja eden-cli`.
6. Copia o binário final para `work/final/eden-cli`.

> **Dica importante:** durante cada treino, joga em **zonas diferentes** (ex.: um na floresta Kokiri, outro na vila, outro em batalha). Quanto mais variado, melhor o ganho.

### 5. Usa o binário final
Copia `work/final/eden-cli` (ou `eden-cli.exe`) para a tua pasta de jogo, no lugar do antigo. **Guarda um backup do antigo.**

---

## Por que 4 minutos? (a matemática)

O contador de ramos mais quente incrementa ~4,9 milhões de vezes/segundo.
`2^31 / 4,9M ≈ 438 segundos`. Passar disso faz o contador virar negativo e o GCC rejeita o perfil (`corrupted profile info`). Daí 240 s ser seguro.

Vários treinos de 240 s **somam** — não precisas de apagar os perfis entre eles. O `-fprofile-update=atomic` é obrigatório: sem ele, as 12+ threads do emulador rasgam os contadores umas das outras.

---

## Diferenças Linux vs Windows

| | Linux | Windows |
|---|---|---|
| Sinal de paragem | `SIGTERM` | `CTRL_BREAK_EVENT` (handler added no `yuzu.cpp`) |
| Compilador | GCC / Clang | GCC / Clang via MSYS2 UCRT64 |
| Gerador | Ninja | Ninja |
| Binário | `eden-cli` | `eden-cli.exe` |

O código do emulador é **idêntico** nas duas plataformas; só muda a forma de pedir o fecho limpo (já tratada).

---

## Estrutura de pastas após a execução

```
PGO-Trainer/
├── emulator-source/        # código-fonte (inalterado)
├── work/
│   ├── build-train/        # build instrumentada + .gcda (os perfis)
│   │   └── .../*.gcda      # ← é aqui que os treinos acumulam
│   ├── run/                # pasta de corrida + logs treino-1.log, treino-2.log...
│   └── final/eden-cli      # ← binário otimizado final
└── pgo_trainer.py
```

---

## Resolução de problemas

| problema | solução |
|---|---|
| `Tkinter nao instalado` | Linux: `sudo pacman -S tk` / `sudo apt install python3-tk`. Windows: reinstala Python com *tcl/tk* marcado. |
| `Compilador nao aceita -fprofile-generate` | Usa GCC/Clang (MSYS2 no Windows). MSVC não suporta estas flags. |
| `Nao encontrei o binario eden-cli` | O target pode chamar-se outro noutro fork — muda `target` em `build_cmd()` no `pgo_core.py`. |
| `Build falhou por falta de RAM` | Baixa as threads de compilação para 4-6. |
| `Jogo nao fecha / perfil nao gravado` | Confirma que usaste **esta** cópia do `emulator-source/` (tem o handler de fecho limpo). |
| `corrupted profile info` | Um treino passou de 438s ou houve fecho sujo. Clica em **Apagar perfis e recomeçar**. |

---

## O que NÃO é partilhável

- ❌ O binário final (compilado para a tua CPU com `-march=native`).
- ❌ Os `.gcda` (medem o teu preditor de ramos, caches e temporizações).

## O que É partilhável

- ✅ Este método, os scripts e as flags.
- ✅ Os consertos de código (fecho limpo no `yuzu.cpp`) — aportam para o upstream.

---

## Licença

O código-fonte do emulador em `emulator-source/` é GPL-3.0 (Eden Emulator Project / yuzu). As ferramentas deste repositório são MIT. As licenças completas estão em `licenses/`.

---

**Feito na CachyOS, Ryzen 5 4600G + RTX 3060, com os 3 treinos de 4 min que resultaram no Zelda estável a 60 FPS.** 🎮
