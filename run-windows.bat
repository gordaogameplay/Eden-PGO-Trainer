@echo off
REM Lichii PGO Trainer - arranque no Windows (MSYS2 / MinGW-w64 com Python + tkinter).
cd /d "%~dp0"
python pgo_trainer.py %*
if errorlevel 1 (
  echo.
  echo Se der erro de tkinter, instala o Python com a opcao "tcl/tk and IDLE" marcada.
  echoPara compilar com GCC: instala MSYS2 (ucrt64) e adiciona C:\msys64\ucrt64\bin ao PATH.
  pause
)
