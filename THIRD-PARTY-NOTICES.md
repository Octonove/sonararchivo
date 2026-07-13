# Avisos de terceros (Third-Party Notices)

SonarArchivo empaqueta y/o utiliza los siguientes componentes de terceros:

## PyMuPDF (fitz) — GNU AGPL v3
SonarArchivo incluye **PyMuPDF** (https://pymupdf.io) para extraer texto de PDF
y generar el informe. PyMuPDF se distribuye bajo la **GNU Affero General Public
License v3 (AGPL-3.0)**, con opción de licencia comercial de Artifex Software.

- Proyecto: https://github.com/pymupdf/PyMuPDF
- Licencia comercial (Artifex): https://artifex.com/licensing
- Texto de la licencia AGPL: https://www.gnu.org/licenses/agpl-3.0.html

**Nota sobre la AGPL:** dado que SonarArchivo empaqueta PyMuPDF (AGPL-3.0), el
código fuente completo está disponible en este repositorio, lo que satisface los
requisitos de la AGPL para esta distribución.

## Otras dependencias
- **Pillow** (PIL) — licencia HPND/MIT-CMU — https://python-pillow.org (solo para el icono en build)

## FFmpeg (no empaquetado)
La transcripción opcional de audio/vídeo usa **FFmpeg** (con el filtro whisper)
si ya está instalado en el sistema. FFmpeg se distribuye bajo LGPL/GPL según la
build — https://ffmpeg.org/legal.html

El resto del código de SonarArchivo se distribuye bajo licencia MIT (ver `LICENSE`).
