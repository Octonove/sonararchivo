"""SonarArchivo — encuentra lo que TIENES, no donde lo guardaste. 100% local.

Apuntas a una carpeta o disco caotico (Descargas, un disco viejo, un pendrive)
y SonarArchivo 'emite un ping' que lee el CONTENIDO de tus archivos —texto de
PDFs, documentos de Office, paginas web, y opcionalmente lo que se dice en
audios y videos (Whisper)— para construir un mapa buscable de lo que hay:
buscas por lo que dice el archivo, no por su nombre. Detecta duplicados y el
espacio que recuperarias. Nada sale de tu equipo.
"""

from __future__ import annotations

APP_NAME = "SonarArchivo"
APP_VERSION = "1.0.1"   # fuente unica de version: build-installer.ps1 la inyecta al .iss
