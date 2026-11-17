#!/usr/bin/env python3
"""
Lichii PGO Trainer - interface grafica (Tkinter, sem dependencias externas).
Pedir o dump do jogo, escolher quantos treinos (1-10, 4 min cada), gerar a build
instrumentada, treinar, juntar os perfis e compilar a build final otimizada.
Funciona em Linux e Windows. Sem IA. Sem downloads de jogo.
"""

import os
import platform
import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pgo_core as core

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
except ImportError:
    print("Erro: Tkinter nao instalado. No Linux: sudo apt install python3-tk / sudo pacman -S tk")
    sys.exit(1)

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "emulator-source"
WORK = ROOT / "work"
DEFAULT_GAME = "The Legend of Zelda Ocarina of Time [0400486024DEC000][v131072].nup"
GAME_ENV = {
    "EDEN_NX2_AUTO_STUB": "1",
    "EDEN_NX2_DMA_SNAPSHOT": "0",
    "EDEN_NX2_VDEC_EOS_RELEASE_NOW": "1",
}


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Lichii PGO Trainer - treino e compilacao PGO para o emulador OoT")
        self.root.geometry("960x780")
        self.root.minsize(860, 700)
        self.q = queue.Queue()
        self.build_dir = WORK / "build-train"
        self.run_dir = WORK / "run"
        self.tools = None
        self.tool_errors = []
        self.worker = None
        self.current_proc = None
        self.stop_requested = threading.Event()
        self._build_gui()
        self._poll()
        self._check_tools_async()

    # ---------------------------------------------------------------- GUI
    def _build_gui(self):
        s = ttk.Style()
        try:
            s.theme_use("clam")
        except Exception:
            pass

        top = ttk.Frame(self.root, padding=12)
        top.pack(fill="x")
        ttk.Label(top, text="Lichii PGO Trainer", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(top, text="Treino PGO local para o emulador do Zelda Ocarina of Time (sem IA, sem downloads de jogo).",
                  foreground="#666").pack(anchor="w")
        self.lbl_sys = ttk.Label(top, text="", foreground="#666")
        self.lbl_sys.pack(anchor="w")

        box = ttk.LabelFrame(self.root, text="Configuracao", padding=10)
        box.pack(fill="x", padx=12, pady=6)

        r = ttk.Frame(box); r.pack(fill="x", pady=3)
        ttk.Label(r, text="Dump do jogo (.nup / exefs/main):", width=32).pack(side="left")
        self.game_var = tk.StringVar()
        ttk.Entry(r, textvariable=self.game_var, width=62).pack(side="left", fill="x", expand=True)
        ttk.Button(r, text="Procurar...", command=self._pick_game).pack(side="left", padx=4)

        r = ttk.Frame(box); r.pack(fill="x", pady=3)
        ttk.Label(r, text="Pasta do codigo-fonte:", width=32).pack(side="left")
        self.source_var = tk.StringVar(value=str(SOURCE))
        ttk.Entry(r, textvariable=self.source_var, width=62).pack(side="left", fill="x", expand=True)
        ttk.Button(r, text="Procurar...", command=self._pick_source).pack(side="left", padx=4)

        r = ttk.Frame(box); r.pack(fill="x", pady=3)
        ttk.Label(r, text="Quantos treinos (1-10):", width=32).pack(side="left")
        self.sessions_var = tk.StringVar(value="3")
        ttk.Spinbox(r, from_=1, to=10, textvariable=self.sessions_var, width=6).pack(side="left")
        ttk.Label(r, text="(recomendado: 3 x 4 min; max seguro 438s/treino)", foreground="#666").pack(side="left", padx=8)

        r = ttk.Frame(box); r.pack(fill="x", pady=3)
        ttk.Label(r, text="Segundos por treino:", width=32).pack(side="left")
        self.sec_var = tk.StringVar(value=str(core.DEFAULT_SESSION_SEC))
        ttk.Spinbox(r, from_=30, to=core.MAX_SESSION_SEC, textvariable=self.sec_var, width=8).pack(side="left")
        ttk.Label(r, text="(240 = 4 min; >438 corre risco de overflow do contador)", foreground="#a11").pack(side="left", padx=8)

        r = ttk.Frame(box); r.pack(fill="x", pady=3)
        ttk.Label(r, text="Threads de compilacao:", width=32).pack(side="left")
        self.jobs_var = tk.StringVar(value=str(os.cpu_count() or 4))
        ttk.Spinbox(r, from_=1, to=64, textvariable=self.jobs_var, width=6).pack(side="left")
        ttk.Label(r, text="(se ficar sem RAM, baixa para 4-6)", foreground="#666").pack(side="left", padx=8)

        ctl = ttk.Frame(self.root, padding=(12, 6))
        ctl.pack(fill="x")
        self.btn_tools = ttk.Button(ctl, text="Verificar ferramentas", command=self._check_tools_async)
        self.btn_tools.pack(side="left")
        self.btn_start = ttk.Button(ctl, text="INICIAR (compilar treino -> treinar -> compilar final)",
                                    command=self._start, style="Accent.TButton")
        self.btn_start.pack(side="left", padx=8)
        self.btn_stop = ttk.Button(ctl, text="Terminar treino agora", command=self._stop_session, state="disabled")
        self.btn_stop.pack(side="left")
        self.btn_reset = ttk.Button(ctl, text="Apagar perfis e recomecar", command=self._reset_profiles)
        self.btn_reset.pack(side="left", padx=8)

        pf = ttk.LabelFrame(self.root, text="Progresso", padding=10)
        pf.pack(fill="x", padx=12, pady=6)
        self.lbl_status = ttk.Label(pf, text="Pronto.", font=("Segoe UI", 10, "bold"))
        self.lbl_status.pack(anchor="w")
        self.pb = ttk.Progressbar(pf, orient="horizontal", length=100, mode="determinate")
        self.pb.pack(fill="x", pady=4)

        lf = ttk.LabelFrame(self.root, text="Registo", padding=6)
        lf.pack(fill="both", expand=True, padx=12, pady=6)
        self.text = tk.Text(lf, height=18, wrap="word", font=("Consolas", 9))
        self.text.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(lf, orient="vertical", command=self.text.yview)
        sb.pack(side="right", fill="y")
        self.text.config(yscrollcommand=sb.set)
        self.text.tag_configure("ok", foreground="#1a7f37")
        self.text.tag_configure("err", foreground="#c00")
        self.text.tag_configure("hl", foreground="#06c", font=("Consolas", 9, "bold"))

    # ------------------------------------------------------------ util GUI
    def log(self, msg, tag=None):
        self.q.put(("log", (str(msg), tag)))

    def status(self, msg, progress=None):
        self.q.put(("status", (str(msg), progress)))

    def _poll(self):
        try:
            while True:
                kind, data = self.q.get_nowait()
                if kind == "log":
                    msg, tag = data
                    self.text.insert("end", msg + "\n", tag or ())
                    self.text.see("end")
                elif kind == "status":
                    msg, progress = data
                    self.lbl_status.config(text=msg)
                    if progress is not None:
                        self.pb["value"] = progress
        except queue.Empty:
            pass
        self.root.after(120, self._poll)

    def _pick_game(self):
        p = filedialog.askopenfilename(
            title="Escolhe o dump do jogo",
            filetypes=[("Jogo Switch", "*.nup *.nsp *.xci *.nca"), ("Todos", "*.*")])
        if p:
            self.game_var.set(p)

    def _pick_source(self):
        p = filedialog.askdirectory(title="Escolhe a pasta do codigo-fonte (com CMakeLists.txt)")
        if p:
            self.source_var.set(p)

    def _check_tools_async(self):
        self.btn_tools.config(state="disabled")
        def run():
            self.tools, self.tool_errors = core.detect_tools()
            sysinfo = self.tools.get("system", "?")
            comp = self.tools.get("compiler")
            cn = f"{Path(comp['cxx']).name} ({comp['family']})" if comp else "FALTANDO"
            self.q.put(("log", (f"Sistema: {sysinfo} | Python {self.tools.get('python', '?')} | "
                                f"Nucleos: {self.tools.get('cores', '?')} | Compilador: {cn}",
                                "ok" if comp and not self.tool_errors else "err")))
            self.q.put(("log", (f"CMake: {self.tools.get('cmake', 'FALTANDO')} | "
                                f"Ninja: {self.tools.get('ninja') or 'nao (usa make)'}", None)))
            for e in self.tool_errors:
                self.q.put(("log", ("ERRO: " + e, "err")))
            self.lbl_sys.config(text=f"{sysinfo} | {cn} | {self.tools.get('cores', '?')} nucleos")
            self.q.put(("ctl-tools", None))
        threading.Thread(target=run, daemon=True).start()

    def _stop_session(self):
        self.stop_requested.set()
        self.btn_stop.config(state="disabled")
        self.status("A terminar o treino (fecho limpo)...")
        if self.current_proc and self.current_proc.is_alive():
            self.current_proc.stop()

    def _reset_profiles(self):
        if not messagebox.askyesno("Apagar perfis", "Apagar TODOS os .gcda e comecar do zero?"):
            return
        n = core.reset_profiles(self.build_dir)
        self.log(f"Apagados {n} ficheiros .gcda.", "ok")

    # -------------------------------------------------------------- fluxo
    def _start(self):
        game = self.game_var.get().strip()
        if not game or not Path(game).exists():
            messagebox.showerror("Erro", "Escolhe um dump de jogo valido (.nup / exefs/main).")
            return
        source = Path(self.source_var.get().strip())
        if not (source / "CMakeLists.txt").is_file():
            messagebox.showerror("Erro", "A pasta do codigo-fonte nao tem CMakeLists.txt.")
            return
        try:
            sessions = int(self.sessions_var.get())
            secs = int(self.sec_var.get())
            jobs = int(self.jobs_var.get())
        except ValueError:
            messagebox.showerror("Erro", "Numeros invalidos.")
            return
        if not (1 <= sessions <= 10):
            messagebox.showerror("Erro", "Escolhe entre 1 e 10 treinos.")
            return
        if not (30 <= secs <= core.MAX_SESSION_SEC):
            messagebox.showerror("Erro", f"Segundos por treino: 30 a {core.MAX_SESSION_SEC}.")
            return
        if not self.tools:
            self.tools, self.tool_errors = core.detect_tools()
        if self.tool_errors:
            messagebox.showerror("Ferramentas em falta", "\n".join(self.tool_errors))
            return

        self.btn_start.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.btn_reset.config(state="disabled")
        self.stop_requested.clear()
        self.worker = threading.Thread(target=self._run_all, args=(source, game, sessions, secs, jobs), daemon=True)
        self.worker.start()

    def _run_all(self, source, game, sessions, secs, jobs):
        try:
            info = self.tools
            WORK.mkdir(parents=True, exist_ok=True)
            self.run_dir.mkdir(parents=True, exist_ok=True)
            generator = "Ninja" if info.get("ninja") else None
            total_steps = 2 + sessions + 1  # config+build treino, N treinos, build final
            step = 0

            # ---- 1. Build instrumentada
            step += 1
            self.status(f"[{step}/{total_steps}] A configurar a build de treino...", 5)
            self.log("=== PASSO 1: build de treino (-fprofile-generate -fprofile-update=atomic -DPGO_TRAINING)", "hl")
            cmd = core.cmake_configure_cmd(source, self.build_dir, generator, info, "train")
            self.log("$ " + " ".join(cmd))
            code, _ = core.run_streamed(cmd, on_line=self.log)
            if code != 0:
                raise RuntimeError("cmake (treino) falhou.")

            self.status(f"[{step}/{total_steps}] A compilar a build instrumentada...", 12)
            cmd = core.build_cmd(self.build_dir, generator, jobs)
            self.log("$ " + " ".join(cmd))
            code, _ = core.run_streamed(cmd, on_line=self.log)
            if code != 0:
                raise RuntimeError("Build de treino falhou.")

            exe = core.find_binary(self.build_dir)
            if not exe:
                raise RuntimeError("Nao encontrei o binario eden-cli na build de treino.")
            self.log(f"Binario de treino: {exe}", "ok")

            # Copiar binario instrumentado para a pasta de corrida (o jogo corre la, mas os .gcda
            # vao para a build dir porque os caminhos sao absolute no elemento de compilacao).
            run_exe = self.run_dir / exe.name
            shutil.copy2(exe, run_exe)

            # ---- 2. Treinos
            for i in range(1, sessions + 1):
                step += 1
                pct = 12 + int((i - 1) * 60 / sessions)
                self.status(f"[{step}/{total_steps}] Treino {i}/{sessions} - a correr ({secs}s)", pct)
                self.log(f"=== TREINO {i}/{sessions}: abre o jogo, jogate normalmente. Vai fechar sozinho aos {secs}s.", "hl")

                logf = self.run_dir / f"treino-{i}.log"
                tp = core.TrainingProcess(
                    run_exe, game, GAME_ENV, self.run_dir, logf,
                    on_tick=lambda el, tot: self.q.put(("tick", (el, tot))))
                self.current_proc = tp
                pid = tp.start()
                self.log(f"Jogo lancado (PID {pid}). Log: {logf.name}")
                reason = tp.wait(secs, stop_check=self.stop_requested.is_set)
                closed = tp.stop()
                tp.close_log()
                self.current_proc = None

                n, sz = core.gcda_stats(self.build_dir)
                self.log(f"Treino {i} terminado ({reason}). Fecho limpo: {closed}. "
                         f"Perfis: {n} ficheiros, {sz/1048576:.1f} MB.", "ok" if closed else "err")
                if not closed:
                    self.log("AVISO: o jogo nao fechou limpo — os contadores podem ter ficado por gravar.", "err")
                self.stop_requested.clear()

            # ---- 3. Build final com os perfis juntos
            step += 1
            n, sz = core.gcda_stats(self.build_dir)
            self.status(f"[{step}/{total_steps}] A compilar a build final com {n} perfis...", 78)
            self.log(f"=== PASSO FINAL: {n} ficheiros .gcda ({sz/1048576:.1f} MB) -> -fprofile-use", "hl")
            cmd = core.cmake_configure_cmd(source, self.build_dir, generator, info, "use")
            self.log("$ " + " ".join(cmd))
            code, _ = core.run_streamed(cmd, on_line=self.log)
            if code != 0:
                raise RuntimeError("cmake (final) falhou.")

            cmd = core.build_cmd(self.build_dir, generator, jobs)
            self.log("$ " + " ".join(cmd))
            code, _ = core.run_streamed(cmd, on_line=self.log)
            if code != 0:
                raise RuntimeError("Build final falhou.")

            exe = core.find_binary(self.build_dir)
            if not exe:
                raise RuntimeError("Nao encontrei o binario final.")
            final_dir = WORK / "final"
            final_dir.mkdir(parents=True, exist_ok=True)
            final_exe = final_dir / exe.name
            shutil.copy2(exe, final_exe)
            size_mb = final_exe.stat().st_size / 1048576

            self.status("CONCLUIDO!", 100)
            self.log(f"SUCESSO: {final_exe} ({size_mb:.1f} MB)", "ok")
            self.log("Copia esse binario para a tua pasta de jogo. O codigo e O MESMO do treino "
                     "(so as flags mudaram de -fprofile-generate para -fprofile-use).", "ok")

        except Exception as e:
            self.log(f"ERRO: {e}", "err")
            self.status("Falhou. Ve o registo.", 0)
        finally:
            self.q.put(("ctl-done", None))

    # ------------------------------------------------------------ eventos
    def _on_qctl(self, kind):
        if kind == "ctl-tools":
            self.btn_tools.config(state="normal")
        elif kind == "ctl-done":
            self.btn_start.config(state="normal")
            self.btn_stop.config(state="disabled")
            self.btn_reset.config(state="normal")
        elif kind and kind.startswith("tick:"):
            _, el, tot = kind.split(":")
            self.status(f"A treinar... {int(el)//60:02d}:{int(el)%60:02d} / {int(tot)//60:02d}:{int(tot)%60:02d}",
                        12 + int(int(el) / max(int(tot), 1) * 60))

    def _poll(self):
        try:
            while True:
                kind, data = self.q.get_nowait()
                if kind == "log":
                    msg, tag = data
                    self.text.insert("end", msg + "\n", tag or ())
                    self.text.see("end")
                elif kind == "status":
                    msg, progress = data
                    self.lbl_status.config(text=msg)
                    if progress is not None:
                        self.pb["value"] = progress
                elif kind.startswith("ctl-"):
                    self._on_qctl(kind)
                elif kind == "tick":
                    el, tot = data
                    self.status(f"A treinar... {el//60:02d}:{el%60:02d} / {tot//60:02d}:{tot%60:02d}",
                                12 + int(el / max(tot, 1) * 60))
        except queue.Empty:
            pass
        self.root.after(120, self._poll)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
