# Lichii PGO Trainer

[Português (Brasil)](README.md) · **English**

A graphical tool (no AI, no game downloads) that lets anyone run **Profile-Guided Optimization (PGO)** on the Lichii/Eden emulator (used with *The Legend of Zelda: Ocarina of Time* on Switch 2) **on their own machine**, on **Linux or Windows**.

It automates the exact method we used during the PGO marathon:

1. **Builds** an instrumented binary (`-fprofile-generate -fprofile-update=atomic -DPGO_TRAINING`).
2. **Launches the game** with your dump and lets you play for N sessions of 4 minutes.
3. **Closes the game cleanly** (SIGTERM on Linux / CTRL_BREAK on Windows) so counters are flushed.
4. **Merges all profiles** (`.gcda` files add up automatically) and **builds the final binary** (`-fprofile-use`).

> The binary and the profile are **specific to your machine** (CPU + GPU). Don't share them. What is shareable is **the method** — which is exactly what this repository provides.

---

## What's included

| file / folder | what it is |
|---|---|
| `pgo_trainer.py` | GUI (Tkinter) — asks for the dump, the number of sessions, drives everything |
| `pgo_core.py` | Core: tool detection, builds, training process, profiles |
| `emulator-source/` | **Clean copy of the emulator source** (60 MB), already patched with clean-shutdown handlers for Linux and Windows in `yuzu.cpp` |
| `run-linux.sh` / `run-windows.bat` | Quick launchers |
| `licenses/` | Emulator and dependency licenses |

---

## Requirements

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
1. Install **Python** (tick the *tcl/tk and IDLE* option).
2. Install **MSYS2** (https://www.msys2.org) and, in the **UCRT64** terminal:
   ```bash
   pacman -S mingw-w64-ucrt-x86_64-gcc mingw-w64-ucrt-x86_64-cmake mingw-w64-ucrt-x86_64-ninja git
   ```
3. Add `C:\msys64\ucrt64\bin` to the Windows **PATH**.
4. Install the emulator dependencies (SDL3, FFmpeg, Vulkan, etc.) — CMake fetches the main ones through CPM (internet needed on first configure).

---

## How to use (step by step)

### 1. Launch
```bash
# Linux
./run-linux.sh

# Windows
run-windows.bat
```

### 2. Fill in the interface
- **Game dump**: pick your `.nup` (or `exefs/main`) of Zelda OoT.
- **Source folder**: defaults to the bundled `emulator-source/`. You can point to your own checkout.
- **How many sessions**: `3` (recommended). Up to 10.
- **Seconds per session**: `240` (4 minutes). **Never exceed 438s** — the hottest counter overflows `2^31` and corrupts the profile.
- **Build threads**: core count (lower to 4-6 if you run out of RAM).

### 3. Click **Check tools**
Confirm CMake, Ninja and GCC/Clang were detected.

### 4. Click **START**
The app does everything:
1. `cmake ... -DCMAKE_CXX_FLAGS="-march=native -mtune=native -DPGO_TRAINING -fprofile-generate -fprofile-update=atomic" -DENABLE_WERROR=OFF`
2. `ninja -j N eden-cli`
3. For each session: launch the game → **you play normally** → at 4 min it closes cleanly → `.gcda` written.
4. Merge profiles (automatic summation).
5. `cmake ... -fprofile-use -fprofile-correction -Wno-missing-profile` (same `-DPGO_TRAINING`!) → `ninja eden-cli`.
6. Copy the final binary to `work/final/eden-cli`.

> **Tip:** during each session, play in **different areas** (e.g. one in the Kokiri forest, one in the village, one in combat). The more varied, the better the gain.

### 5. Use the final binary
Copy `work/final/eden-cli` (or `eden-cli.exe`) into your game folder, replacing the old one. **Keep a backup of the old binary.**

---

## Why 4 minutes? (the math)

The hottest branch counter increments ~4.9 million times/second.
`2^31 / 4.9M ≈ 438 seconds`. Beyond that the counter goes negative and GCC rejects the profile (`corrupted profile info`). Hence 240 s is safe.

Multiple 240 s sessions **add up** — you don't need to delete profiles between them. `-fprofile-update=atomic` is mandatory: without it, the emulator's 12+ host threads corrupt each other's counters.

---

## Linux vs Windows differences

| | Linux | Windows |
|---|---|---|
| Stop signal | `SIGTERM` | `CTRL_BREAK_EVENT` (handler added in `yuzu.cpp`) |
| Compiler | GCC / Clang | GCC / Clang via MSYS2 UCRT64 |
| Generator | Ninja | Ninja |
| Binary | `eden-cli` | `eden-cli.exe` |

The emulator code is **identical** on both platforms; only the clean-shutdown request differs (already handled).

---

## Folder layout after a run

```
PGO-Trainer/
├── emulator-source/        # source code (unchanged)
├── work/
│   ├── build-train/        # instrumented build + .gcda (the profiles)
│   │   └── .../*.gcda      # ← sessions accumulate here
│   ├── run/                # run folder + treino-1.log, treino-2.log...
│   └── final/eden-cli      # ← optimized final binary
└── pgo_trainer.py
```

---

## Troubleshooting

| problem | fix |
|---|---|
| `Tkinter not installed` | Linux: `sudo pacman -S tk` / `sudo apt install python3-tk`. Windows: reinstall Python with *tcl/tk* ticked. |
| `Compiler does not accept -fprofile-generate` | Use GCC/Clang (MSYS2 on Windows). MSVC does not support these flags. |
| `Could not find eden-cli binary` | The target may have another name in your fork — change `target` in `build_cmd()` in `pgo_core.py`. |
| `Build failed out of RAM` | Lower build threads to 4-6. |
| `Game won't close / profile not written` | Make sure you're using **this** copy of `emulator-source/` (it has the clean-shutdown handler). |
| `corrupted profile info` | A session exceeded 438s or had a dirty exit. Click **Delete profiles and restart**. |

---

## What is NOT shareable

- ❌ The final binary (compiled for your CPU with `-march=native`).
- ❌ The `.gcda` files (they measure your branch predictor, caches and timings).

## What IS shareable

- ✅ This method, the scripts and the flags.
- ✅ The code fixes (clean shutdown in `yuzu.cpp`) — worth upstreaming.

---

## License

The emulator source in `emulator-source/` is GPL-3.0 (Eden Emulator Project / yuzu). The tools in this repository are MIT. Full licenses are in `licenses/`.

---

**Made on CachyOS, Ryzen 5 4600G + RTX 3060, with the 3×4-minute sessions that produced the stable 60 FPS Zelda build.** 🎮
