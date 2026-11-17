#!/usr/bin/env bash
# Arranque do Lichii PGO Trainer no Linux.
set -e
cd "$(dirname "$0")"
if ! python3 -c 'import tkinter' 2>/dev/null; then
    echo "Tkinter em falta. Instala: sudo pacman -S tk  (Arch)  ou  sudo apt install python3-tk  (Debian/Ubuntu)"
    exit 1
fi
exec python3 pgo_trainer.py "$@"
