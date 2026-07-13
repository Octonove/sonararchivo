"""Escaneo de una carpeta: recorre, calcula la firma para duplicados, extrae el
texto y alimenta el indice. Reescaneo incremental (salta lo que no cambio).

Best-effort: los errores de permisos o de lectura de un archivo se registran y
NO detienen el escaneo. Nada se modifica en disco; solo se LEE."""

from __future__ import annotations

import hashlib
import logging
import os
import time
from pathlib import Path

from . import extract
from .index import Index, Registro

logger = logging.getLogger(__name__)

# carpetas que no aportan y solo ralentizan (se saltan siempre)
_SALTAR = {"$recycle.bin", "system volume information", "windows", "$windows.~bs",
           "node_modules", ".git", "__pycache__", ".venv", "venv", "appdata"}
MAX_HASH_BYTES = 200 * 1024**2      # no hashear (para duplicados) archivos enormes
BLOQUE = 1024 * 1024


def human_size(n: int) -> str:
    """Tamano legible en espanol (coma decimal). Puro."""
    n = float(n)
    for unidad in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unidad == "TB":
            if unidad == "B":
                return f"{int(n)} B"
            return f"{n:.1f}".replace(".", ",") + f" {unidad}"
        n /= 1024
    return f"{n:.1f} TB"


def firma_archivo(path: Path, size: int) -> str:
    """sha1 del contenido (para detectar duplicados de verdad). Se omite en
    archivos gigantes por rendimiento (devuelve '' -> no participan en dupes)."""
    if size == 0 or size > MAX_HASH_BYTES:
        return ""
    h = hashlib.sha1()
    try:
        with open(_ext(str(path)), "rb") as f:
            while True:
                b = f.read(BLOQUE)
                if not b:
                    break
                h.update(b)
    except OSError:
        return ""
    return h.hexdigest()


def _saltar_dir(nombre: str) -> bool:
    n = nombre.lower()
    return n in _SALTAR or n.startswith("$")


def _ext(path: str) -> str:
    r"""Ruta con prefijo de longitud extendida (\\?\) para poder stat/abrir
    archivos con rutas > 260 caracteres aunque el sistema no tenga habilitado
    el soporte de rutas largas. UNC -> \\?\UNC\server\share..."""
    p = os.path.abspath(path)
    if p.startswith("\\\\?\\"):
        return p
    if p.startswith("\\\\"):
        return "\\\\?\\UNC\\" + p[2:]
    return "\\\\?\\" + p


class Scanner:
    def __init__(self, index: Index, *, incluir_av: bool = False,
                 ffmpeg: str = "", modelo_whisper: str = ""):
        self.index = index
        self.incluir_av = incluir_av
        self.ffmpeg = ffmpeg
        self.modelo_whisper = modelo_whisper
        self._stop = False

    def cancelar(self) -> None:
        self._stop = True

    def escanear(self, raiz: str, on_progreso=None) -> dict:
        """Recorre `raiz`. on_progreso(n_archivos, ruta_actual) se llama cada
        cierto numero de archivos. Devuelve estadisticas del escaneo."""
        raiz = str(Path(raiz).resolve())
        self._stop = False
        self.index.comenzar_escaneo(raiz)
        n = nuevos = reutilizados = errores = 0
        t0 = time.time()
        for dirpath, dirnames, filenames in os.walk(raiz):
            if self._stop:
                break
            dirnames[:] = [d for d in dirnames if not _saltar_dir(d)]
            for nombre in filenames:
                if self._stop:
                    break
                n += 1
                p = Path(dirpath) / nombre
                path_s = str(p)
                try:
                    st = os.stat(_ext(path_s))
                except OSError:
                    errores += 1
                    # un fallo transitorio (fichero bloqueado/permiso) NO debe
                    # expulsar del indice un archivo que existe: si ya estaba, se
                    # conserva marcandolo visto
                    if self.index.existente(path_s):
                        self.index.marcar_visto(path_s)
                    continue
                prev = self.index.existente(path_s)
                # 'sin cambios' = mismo tamano y misma fecha (tolerancia minima por
                # sistemas de baja resolucion tipo FAT, no una ventana ciega amplia)
                if prev and prev[0] == st.st_size and abs(prev[1] - st.st_mtime) <= 2.0:
                    self.index.marcar_visto(path_s)
                    reutilizados += 1
                else:
                    try:
                        self._indexar(p, st, raiz)
                        nuevos += 1
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("indexar %s fallo: %s", p, exc)
                        errores += 1
                        if prev:
                            self.index.marcar_visto(path_s)   # conservar la fila previa
                if on_progreso and n % 40 == 0:
                    self.index.commit()
                    on_progreso(n, str(p))
        self.index.commit()
        # solo se purga (borra lo que ya no existe) si el escaneo se COMPLETO:
        # cancelar a media ejecucion dejaria muchos archivos con visto=0.
        eliminados = 0 if self._stop else self.index.purgar_no_vistos(raiz)
        return {"archivos": n, "nuevos": nuevos, "reutilizados": reutilizados,
                "eliminados": eliminados, "errores": errores,
                "segundos": round(time.time() - t0, 1), "cancelado": self._stop}

    def _indexar(self, p: Path, st, raiz: str) -> None:
        ext = p.suffix.lower()
        cat = extract.categoria(ext)
        texto = extract.extraer_texto(p)
        if not texto and self.incluir_av and cat in ("Audio", "Video"):
            texto = self._transcribir(p)
        reg = Registro(path=str(p), nombre=p.name, ext=ext, categoria=cat,
                       size=st.st_size, mtime=st.st_mtime,
                       sha1=firma_archivo(p, st.st_size), texto=texto)
        self.index.upsert(reg, raiz)

    def _transcribir(self, p: Path) -> str:
        """Transcribe audio/video con el filtro whisper de FFmpeg (opt-in, lento)."""
        if not self.ffmpeg or not self.modelo_whisper:
            return ""
        try:
            from .transcribe import transcribir
            return transcribir(self.ffmpeg, self.modelo_whisper, str(p),
                               stop_check=lambda: self._stop)
        except Exception as exc:  # noqa: BLE001
            logger.debug("transcripcion %s fallo: %s", p, exc)
            return ""
