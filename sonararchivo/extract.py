"""Extraccion de CONTENIDO por tipo de archivo. Funciones puras/best-effort:
reciben una ruta y devuelven texto plano (o '' si no aplica o falla). Nunca
lanzan: un archivo ilegible no debe abortar el escaneo."""

from __future__ import annotations

import html as _html
import logging
import os
import re
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Categorias por extension (para el mapa y los filtros).
CATEGORIAS = {
    "Documentos": {".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt", ".md", ".tex"},
    "Hojas de calculo": {".xls", ".xlsx", ".ods", ".csv", ".tsv"},
    "Presentaciones": {".ppt", ".pptx", ".odp"},
    "Imagenes": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif",
                 ".heic", ".svg"},
    "Audio": {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac", ".wma"},
    "Video": {".mp4", ".mkv", ".mov", ".avi", ".wmv", ".webm", ".flv"},
    "Codigo": {".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".cs", ".go",
               ".rs", ".rb", ".php", ".sql", ".css", ".html", ".htm", ".json",
               ".xml", ".yml", ".yaml", ".ini", ".cfg", ".sh", ".ps1", ".bat"},
    "Comprimidos": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2"},
    "Ejecutables": {".exe", ".msi", ".dll", ".apk"},
}
_EXT2CAT = {ext: cat for cat, exts in CATEGORIAS.items() for ext in exts}

# Extensiones de texto plano legibles directamente.
_TEXTO = (CATEGORIAS["Codigo"] | {".txt", ".md", ".csv", ".tsv", ".log", ".tex", ".rtf"})

MAX_TEXT = 200_000        # tope de texto indexado por archivo (evita RAM/BD enormes)
MAX_LEER = MAX_TEXT * 4   # tope de BYTES que se leen del disco/zip (anti zip-bomb/OOM)


def categoria(ext: str) -> str:
    return _EXT2CAT.get(ext.lower(), "Otros")


def _ext_path(path: Path) -> str:
    r"""Ruta con prefijo \\?\ para poder abrir archivos con rutas > 260."""
    p = os.path.abspath(str(path))
    if p.startswith("\\\\?\\"):
        return p
    if p.startswith("\\\\"):
        return "\\\\?\\UNC\\" + p[2:]
    return "\\\\?\\" + p


def _decode(data: bytes) -> str:
    """Decodifica de forma tolerante: UTF-8 con reemplazo (asi un byte multibyte
    cortado por el tope NO convierte todo el texto en mojibake cayendo a cp1252)."""
    if data[:3] == b"\xef\xbb\xbf":
        data = data[3:]
    return data.decode("utf-8", "replace")


def _leer_bytes(path: Path, limite: int = MAX_LEER) -> bytes:
    try:
        with open(_ext_path(path), "rb") as f:
            return f.read(limite)
    except OSError:
        return b""


def _leer_texto_plano(path: Path) -> str:
    return _decode(_leer_bytes(path))


def strip_html(texto: str) -> str:
    """Quita etiquetas (y el contenido de script/style) y colapsa espacios. Puro.
    Se acota la entrada para que el patron de script/style no pueda degradar a
    coste cuadratico con muchos <script> abiertos y sin cerrar."""
    if len(texto) > MAX_LEER:
        texto = texto[:MAX_LEER]
    sin_script = re.sub(r"(?is)<(script|style)\b[^>]*>.*?</\s*\1\s*>", " ", texto)
    sin_tags = re.sub(r"(?s)<[^>]+>", " ", sin_script)
    return re.sub(r"\s+", " ", _html.unescape(sin_tags)).strip()


def _leer_miembro(z: zipfile.ZipFile, nombre: str, limite: int = MAX_LEER) -> str:
    """Lee como maximo `limite` bytes de un miembro del zip (con z.open, no
    z.read: no descomprime el miembro entero en RAM -> a prueba de zip-bombs)."""
    try:
        with z.open(nombre) as f:
            return _decode(f.read(limite))
    except Exception:  # noqa: BLE001
        return ""


def docx_text(path: Path) -> str:
    """Texto de un .docx (zip con word/document.xml). Sin dependencias externas."""
    try:
        with zipfile.ZipFile(_ext_path(path)) as z:
            xml = _leer_miembro(z, "word/document.xml")
    except Exception:  # noqa: BLE001
        return ""
    xml = re.sub(r"</w:p>", "\n", xml)
    return re.sub(r"\s*\n\s*", "\n", re.sub(r"(?s)<[^>]+>", "", xml)).strip()


def pptx_text(path: Path) -> str:
    """Texto de un .pptx (todas las diapositivas)."""
    trozos = []
    total = 0
    try:
        with zipfile.ZipFile(_ext_path(path)) as z:
            for nombre in sorted(z.namelist()):
                if total >= MAX_LEER:
                    break
                if re.match(r"ppt/slides/slide\d+\.xml$", nombre):
                    xml = _leer_miembro(z, nombre, MAX_LEER - total)
                    total += len(xml)
                    trozos.append(re.sub(r"(?s)<[^>]+>", " ", xml))
    except Exception:  # noqa: BLE001
        return ""
    return re.sub(r"\s+", " ", " ".join(trozos)).strip()


def xlsx_text(path: Path) -> str:
    """Cadenas compartidas de un .xlsx (sharedStrings.xml): da idea del contenido."""
    try:
        with zipfile.ZipFile(_ext_path(path)) as z:
            if "xl/sharedStrings.xml" not in z.namelist():
                return ""
            xml = _leer_miembro(z, "xl/sharedStrings.xml")
    except Exception:  # noqa: BLE001
        return ""
    return re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]+>", " ", xml)).strip()


def pdf_text(path: Path, max_pages: int = 30) -> str:
    try:
        import fitz
    except ImportError:
        return ""
    try:
        doc = fitz.open(_ext_path(path))
    except Exception:  # noqa: BLE001
        return ""
    try:
        partes = []
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            partes.append(page.get_text("text"))
        return "\n".join(partes).strip()
    except Exception:  # noqa: BLE001
        return ""
    finally:
        doc.close()


def extraer_texto(path: Path) -> str:
    """Devuelve el contenido textual del archivo segun su tipo (o '')."""
    ext = path.suffix.lower()
    try:
        if ext == ".pdf":
            txt = pdf_text(path)
        elif ext == ".docx":
            txt = docx_text(path)
        elif ext == ".pptx":
            txt = pptx_text(path)
        elif ext == ".xlsx":
            txt = xlsx_text(path)
        elif ext in (".html", ".htm"):
            txt = strip_html(_leer_texto_plano(path))
        elif ext in _TEXTO:
            txt = _leer_texto_plano(path)
        else:
            txt = ""
    except Exception as exc:  # noqa: BLE001
        logger.debug("extraccion fallo en %s: %s", path, exc)
        txt = ""
    return txt[:MAX_TEXT]
