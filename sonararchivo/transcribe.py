"""Transcripcion opcional de audio/video con el filtro whisper de FFmpeg (local).
Reutiliza el enfoque de la suite (CapturaStudio/CajaNegra). Best-effort."""

from __future__ import annotations

import logging
import os
import re
import subprocess
from pathlib import Path

from octonove_core.ffmpeg import find_ffmpeg as _find_ffmpeg
from octonove_core.ffmpeg import has_whisper
from octonove_core.procutil import subprocess_kwargs

from .config import get_data_dir

logger = logging.getLogger(__name__)


def find_ffmpeg(override: str = "") -> str | None:
    return _find_ffmpeg(override, package_file=__file__)


def find_whisper_model() -> str | None:
    """Modelo ggml de Whisper si alguna app de la suite ya lo descargo."""
    from octonove_core.config import models_dir
    # candidatos construidos a mano, NO con get_data_dir: los candidatos solo
    # se miran y get_data_dir crearia carpetas %APPDATA% vacias de otras apps
    base = Path(os.environ.get("APPDATA") or Path.home())
    d = models_dir("SonarArchivo", shared_candidates=[
        base / app / "models"
        for app in ("CapturaStudio", "ActaLocal", "TranscriptorIA", "CajaNegra")])
    try:
        modelos = sorted(d.glob("ggml-*.bin"), key=lambda p: p.stat().st_size)
        return str(modelos[0]) if modelos else None
    except OSError:
        return None


def whisper_disponible(ffmpeg: str) -> bool:
    return bool(ffmpeg and has_whisper(ffmpeg) and find_whisper_model())


def _srt_a_texto(srt: str) -> str:
    lineas = [ln.strip() for ln in srt.splitlines()
              if ln.strip() and not ln.strip().isdigit()
              and not re.match(r"^\d{2}:\d{2}:\d{2}", ln.strip())]
    return " ".join(lineas).strip()


def transcribir(ffmpeg: str, modelo: str, media_path: str, stop_check=None) -> str:
    """Transcribe con FFmpeg. Si `stop_check()` devuelve True, mata el proceso y
    aborta (para que cancelar/cerrar la app no espere hasta 10 min por archivo)."""
    if not re.fullmatch(r"[A-Za-z0-9._-]+", Path(modelo).name):
        return ""
    model_dir = str(Path(modelo).parent)
    tmp = Path(model_dir) / f".sa_tx_{os.getpid()}.srt"
    try:
        tmp.unlink(missing_ok=True)
    except OSError:
        pass
    filt = (f"aresample=16000,whisper=model={Path(modelo).name}:language=auto"
            f":use_gpu=false:destination={tmp.name}:format=srt")
    proc = None
    try:
        proc = subprocess.Popen([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                                 "-i", str(Path(media_path).resolve()), "-af", filt,
                                 "-f", "null", "-"],
                                cwd=model_dir, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, **subprocess_kwargs())
        esperado = 0.0
        while esperado < 600:
            try:
                proc.wait(timeout=0.5)
                break
            except subprocess.TimeoutExpired:
                esperado += 0.5
                if stop_check and stop_check():
                    proc.terminate()
                    return ""
        else:
            proc.terminate()
            return ""
        if proc.returncode != 0 or not tmp.is_file():
            return ""
        return _srt_a_texto(tmp.read_text(encoding="utf-8", errors="replace"))
    except (OSError, subprocess.SubprocessError):
        return ""
    finally:
        if proc and proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
