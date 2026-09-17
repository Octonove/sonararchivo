# SonarArchivo

**Encuentra lo que TIENES, no dónde lo guardaste.** 100% local. Apuntas SonarArchivo a una carpeta o disco caótico (Descargas, un disco duro viejo, un pendrive) y "emite un ping" que lee el **contenido** de tus archivos para devolverte un mapa buscable de lo que hay dentro.

<!-- invokard-coffee -->
**&#9749; Si esto te ahorra tiempo, inv&iacute;tame a un caf&eacute;.** [![Inv&iacute;tame a un caf&eacute; con PayPal](https://img.shields.io/badge/PayPal-Inv%C3%ADtame%20a%20un%20caf%C3%A9-00457C?logo=paypal&logoColor=white)](https://www.paypal.com/donate/?business=stradoxx%40gmail.com&no_recurring=0&currency_code=EUR&item_name=Support%20sonararchivo)

**USDC** &middot; Solana `5n6Gfosk7SdwbvdtE9xiLWpcGPBBBGDZYRfAkWyCk86g` &middot; Ethereum (ERC-20) `0xe176866f9d7fdb498e0d4a983d3e34d84dcd6bfc`

## ⬇️ Descargar (Windows 10/11)

### ➡️ [**Descargar SonarArchivo (instalador .exe)**](https://github.com/Octonove/sonararchivo/releases/latest/download/SonarArchivo-Setup.exe)

Descarga **directa** del instalador, sin registro. También puedes ver la [última versión y notas](https://github.com/Octonove/sonararchivo/releases/latest).

> Si Windows muestra *"Windows protegió tu PC"*: pulsa **Más información → Ejecutar de todas formas**. Se instala sin permisos de administrador.

## Qué hace

- **Busca por contenido, no por nombre**: el buscador de Windows no mira dentro de los archivos; SonarArchivo sí. Escribe *"presupuesto reforma"* y encuentra el PDF, el Word o la nota donde aparece, aunque no recuerdes cómo se llama.
- **Lee muchos formatos**: texto de **PDF** (PyMuPDF), **Word/PowerPoint/Excel** (.docx/.pptx/.xlsx), páginas **HTML**, código y ficheros de texto. Y, si lo activas, **transcribe audios y vídeos** con Whisper local para buscar por lo que se dice en ellos.
- **Mapa de lo que tienes**: cuántos archivos y cuánto ocupa cada tipo (documentos, imágenes, vídeo…).
- **Duplicados y espacio recuperable**: detecta archivos idénticos por su firma (SHA-1) y te dice cuánto liberarías borrando las copias sobrantes.
- **Informe PDF** del mapa para archivar o compartir.
- **Reescaneo incremental**: la segunda vez solo lee lo que cambió, así que es rápido.

> **Privacidad**: el índice (con el texto extraído) se guarda **solo en tu equipo** (`%APPDATA%\SonarArchivo`), nunca sale de tu PC, y puedes vaciarlo con un clic. SonarArchivo solo **lee** tus archivos; nunca los modifica, mueve ni borra.

## Stack

Python 3 + Tkinter (ttk) · SQLite FTS5 (índice y búsqueda) · PyMuPDF (PDF) · stdlib (zip/docx/pptx/xlsx/html) · FFmpeg + Whisper opcional para audio/vídeo.

Depende del paquete compartido [`octonove-core`](https://github.com/Octonove/octonove-core) (tema, config, FFmpeg): debe estar en el `sys.path` del entorno.

## Compilar

```powershell
.\build\build.ps1              # ejecutable (PyInstaller onedir)
.\build\build-installer.ps1    # instalador (Inno Setup)
```

## Tests

```powershell
python -m pytest tests/ -q
```

## Licencia

[MIT](LICENSE) — © 2026 Octonove.
