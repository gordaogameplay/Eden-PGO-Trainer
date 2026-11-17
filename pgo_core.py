"""
pgo_core.py - Nucleo PGO do Lichii PGO Trainer (sem IA, sem downloads de jogo).
Contem: deteccao de ferramentas, configuracao/build CMake, lancamento do jogo,
treino com paragem limpa (SIGTERM / CTRL_BREAK), juncao de perfis e build final.
Funciona em Linux (GCC/Clang) e Windows (MinGW-w64 / Clang via MSYS2).
"""

import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

IS_WINDOWS = platform.system() == "Windows"
IS_LINUX = platform.system() == "Linux"
IS_MAC = platform.system() == "Darwin"

# ---------------------------------------------------------------------------
# Ferramentas
# ---------------------------------------------------------------------------

def which(name):
    return shutil.which(name)


def exe_name(base):
    return base + (".exe" if IS_WINDOWS else "")


def detect_tools():
    """Deteta CMake, Ninja e compilador GCC/Clang com suporte a PGO.
    Retorna (info: dict, errors: list[str])."""
    info = {"system": platform.system(), "python": sys.version.split()[0]}
    errors = []

    cmake = which("cmake") or which("cmake3")
    if cmake:
        info["cmake"] = cmake
    else:
        errors.append("cmake nao encontrado (instala o CMake).")

    ninja = which("ninja") or which("ninja-build")
    info["ninja"] = ninja
    if not ninja and not which("make"):
        errors.append("Nem Ninja nem make encontrados (instala um dos dois).")

    comp = None
    for cxx, cc in (("g++", "gcc"), ("clang++", "clang")):
        cxxp, ccp = which(cxx), which(cc)
        if cxxp and ccp:
            comp = {"cxx": cxxp, "cc": ccp, "family": "gcc" if cxx == "g++" else "clang"}
            break
    if comp:
        info["compiler"] = comp
        # Teste rapido: o compilador aceita as flags PGO?
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "t.cpp"
            src.write_text("int main(){return 0;}\n")
            for flag in ("-fprofile-generate", "-fprofile-update=atomic", "-fprofile-use"):
                try:
                    r = subprocess.run([comp["cxx"], flag, "-c", str(src), "-o", str(Path(td) / "t.o")],
                                       capture_output=True, timeout=30)
                    if r.returncode != 0:
                        errors.append(f"Compilador {Path(comp['cxx']).name} nao aceita {flag}.")
                        comp = None
                        break
                except Exception as e:
                    errors.append(f"Falha ao testar {flag}: {e}")
                    comp = None
                    break
        if comp:
            info["compiler"] = comp
    else:
        errors.append("Compilador GCC ou Clang nao encontrado (instala o compilador).")

    # Numeros de nucleos / memoria
    try:
        info["cores"] = os.cpu_count() or 4
    except Exception:
        info["cores"] = 4

    return info, errors


# ---------------------------------------------------------------------------
# Constantes do metodo PGO (o que aprendemos na maratona)
# ---------------------------------------------------------------------------

# Limite do overflow: contador mais quente estoura 2^31 a ~4.9M/s => 438s.
# 240s (4 min) e seguro e o valor que usamos nos 3 treinos.
MAX_SESSION_SEC = 438
DEFAULT_SESSION_SEC = 240

# Flags partilhadas entre a build de treino e a build final (o CODIGO tem de ser identico).
BASE_FLAGS = ["-march=native", "-mtune=native", "-DPGO_TRAINING"]
TRAIN_FLAGS = BASE_FLAGS + ["-fprofile-generate", "-fprofile-update=atomic"]
USE_FLAGS = BASE_FLAGS + [
    "-fprofile-use", "-fprofile-correction", "-Wno-missing-profile",
    "-Wno-error=missing-noreturn",  # so aparece com -fprofile-use no GCC
]


# ---------------------------------------------------------------------------
# Gestor do processo de treino
# ---------------------------------------------------------------------------

class TrainingProcess:
    """Lanca o emulador com o jogo, espera o tempo pedido e fecha de forma limpa."""

    def __init__(self, exe, game, env, workdir, logfile, on_tick=None, stop_check=None):
        self.exe = Path(exe)
        self.game = str(game)
        self.env = dict(os.environ)
        self.env.update(env or {})
        self.workdir = Path(workdir)
        self.logfile = Path(logfile)
        self.on_tick = on_tick
        self.stop_check = stop_check
        self.proc = None
        self._lh = None

    def start(self):
        self._lh = open(self.logfile, "ab")
        args = [str(self.exe), "-g", self.game]
        kw = {}
        if IS_WINDOWS:
            # CREATE_NEW_PROCESS_GROUP permite enviar CTRL_BREAK_EVENT ao jogo.
            kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        self.proc = subprocess.Popen(
            args, cwd=str(self.workdir), env=self.env,
            stdout=self._lh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **kw)
        return self.proc.pid

    def is_alive(self):
        return self.proc is not None and self.proc.poll() is None

    def stop(self, grace=120):
        """Pedido de fecho limpo. No Linux SIGTERM; no Windows CTRL_BREAK_EVENT."""
        if not self.is_alive():
            return True
        try:
            if IS_WINDOWS:
                self.proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                self.proc.send_signal(signal.SIGTERM)
        except Exception:
            try:
                self.proc.terminate()
            except Exception:
                pass
        try:
            self.proc.wait(timeout=grace)
            return True
        except subprocess.TimeoutExpired:
            # Ultimo recurso: matar (o perfil pode nao ser escrito).
            try:
                self.proc.kill()
                self.proc.wait(timeout=10)
            except Exception:
                pass
            return False

    def close_log(self):
        if self._lh:
            try:
                self._lh.flush()
                self._lh.close()
            except Exception:
                pass
            self._lh = None

    def wait(self, seconds, stop_check=None):
        """Espera 'seconds' ou ate stop_check() devolver True. Retorna 'stopped'/'timeout'."""
        t0 = time.time()
        check = stop_check or self.stop_check
        last_tick = -1
        while time.time() - t0 < seconds:
            if not self.is_alive():
                return "game_closed"
            if check and check():
                return "stopped"
            elapsed = int(time.time() - t0)
            if elapsed != last_tick:
                last_tick = elapsed
                if self.on_tick:
                    self.on_tick(elapsed, seconds)
            time.sleep(0.5)
        return "timeout"


# ---------------------------------------------------------------------------
# Perfis
# ---------------------------------------------------------------------------

def count_gcda(build_dir):
    return len(list(Path(build_dir).rglob("*.gcda")))


def newest_gcda_mtime(build_dir):
    newest = 0.0
    try:
        for p in Path(build_dir).rglob("*.gcda"):
            try:
                m = p.stat().st_mtime
                if m > newest:
                    newest = m
            except OSError:
                pass
    except Exception:
        pass
    return newest


def gcda_stats(build_dir):
    n = 0
    total = 0
    try:
        for p in Path(build_dir).rglob("*.gcda"):
            try:
                n += 1
                total += p.stat().st_size
            except OSError:
                pass
    except Exception:
        pass
    return n, total


def reset_profiles(build_dir):
    """Apaga todos os .gcda (para recomeçar o treino do zero)."""
    n = 0
    try:
        for p in Path(build_dir).rglob("*.gcda"):
            try:
                p.unlink()
                n += 1
            except OSError:
                pass
    except Exception:
        pass
    return n


def merge_profiles(src_dir, dst_dir):
    """Os .gcda ja estao no build dir e somam-se sozinhos (atomic update).
    Esta funcao copia perfis de uma build auxiliar para a build final, se necessario."""
    n = 0
    try:
        for p in Path(src_dir).rglob("*.gcda"):
            rel = p.relative_to(src_dir)
            out = Path(dst_dir) / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, out)
            n += 1
    except Exception:
        pass
    return n


# ---------------------------------------------------------------------------
# Comandos de build
# ---------------------------------------------------------------------------

def cmake_configure_cmd(source, build, generator, info, mode, extra_defines=None):
    """Constroi o comando cmake para a build de treino ou final."""
    comp = info.get("compiler") or {}
    flags = TRAIN_FLAGS if mode == "train" else USE_FLAGS
    cxx_flags = " ".join(flags)
    c_flags = " ".join(f for f in flags if f != "-Wno-error=missing-noreturn")
    cmd = [info["cmake"], "-S", str(source), "-B", str(build)]
    if generator:
        cmd += ["-G", generator]
    cmd += [
        f"-DCMAKE_CXX_COMPILER={comp.get('cxx', '')}",
        f"-DCMAKE_C_COMPILER={comp.get('cc', '')}",
        f"-DCMAKE_CXX_FLAGS={cxx_flags}",
        f"-DCMAKE_C_FLAGS={c_flags}",
        "-DENABLE_WERROR=OFF",
        "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
    ]
    for k, v in (extra_defines or {}).items():
        cmd.append(f"-D{k}={v}")
    return cmd


def build_cmd(build_dir, generator, jobs, target="eden-cli"):
    if generator and "Ninja" in generator:
        return ["ninja", "-C", str(build_dir), "-j", str(jobs), target]
    return ["make", "-C", str(build_dir), "-j", str(jobs), target]


def find_binary(build_dir, names=("eden-cli", "yuzu", "main")):
    """Procura o executavel na arvore da build."""
    for name in names:
        for cand in (Path(build_dir) / "bin" / exe_name(name),
                     Path(build_dir) / exe_name(name)):
            if cand.is_file():
                return cand
    # Procura generica (limitada) por nome
    try:
        for p in Path(build_dir).rglob(exe_name("eden-cli")):
            if p.is_file():
                return p
    except Exception:
        pass
    return None


def run_streamed(cmd, on_line=None, cwd=None, env=None, timeout=None):
    """Corre um comando e envia cada linha para on_line. Retorna (codigo, texto)."""
    proc = subprocess.Popen(
        cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, errors="replace")
    out = []
    try:
        for line in proc.stdout:
            line = line.rstrip("\n")
            out.append(line)
            if on_line:
                on_line(line)
        code = proc.wait(timeout=timeout) if timeout else proc.wait()
    except Exception:
        proc.kill()
        proc.wait()
        code = -1
    return code, "\n".join(out)
