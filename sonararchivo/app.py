"""Ventana principal de SonarArchivo: elegir carpeta, escanear (ping en 2o plano),
buscar por contenido y ver el mapa (tipos, duplicados, espacio)."""

from __future__ import annotations

import logging
import os
import subprocess
import threading
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from . import APP_NAME, APP_VERSION, theme
from . import report
from .config import AppConfig, INDEX_PATH, load_config, save_config
from .index import Index
from .scanner import Scanner, human_size

logger = logging.getLogger(__name__)


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_NAME} {APP_VERSION}")
        self.geometry("980x680")
        self.minsize(900, 620)
        theme.apply(self)
        try:
            ico = Path(__file__).resolve().parent.parent / "build" / "icon.ico"
            if ico.is_file():
                self.iconbitmap(str(ico))
        except tk.TclError:
            pass

        self.cfg: AppConfig = load_config()
        self.index = Index(str(INDEX_PATH))
        self.scanner: Scanner | None = None
        self._scan_thread: threading.Thread | None = None
        self._scanning = False
        self._closing = False
        self._resultados: list[dict] = []
        self._buscar_id: str | None = None

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(300, self._first_run)
        self.after(500, self._refrescar_mapa)

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        theme.header(self, APP_NAME, "Encuentra lo que tienes, no donde lo guardaste · 100% local")
        self.status = theme.status_bar(self, "Elige una carpeta y pulsa 'Escanear'.")

        top = ttk.Frame(self, padding=(14, 12))
        top.pack(fill="x")
        ttk.Label(top, text="Carpeta:", style="Muted.TLabel").pack(side="left")
        self.var_carpeta = tk.StringVar(value=self.cfg.ultima_carpeta)
        ttk.Entry(top, textvariable=self.var_carpeta).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(top, text="Elegir…", command=self._elegir).pack(side="left")
        self.btn_scan = ttk.Button(top, text="📡 Escanear", style="Primary.TButton",
                                   command=self._toggle_scan)
        self.btn_scan.pack(side="left", padx=(6, 0))

        opts = ttk.Frame(self, padding=(14, 0))
        opts.pack(fill="x")
        self.var_av = tk.BooleanVar(value=self.cfg.incluir_audio_video)
        ttk.Checkbutton(opts, text="Incluir audio y video (transcribe con Whisper; mas lento)",
                        variable=self.var_av, command=self._on_av).pack(side="left")
        self.lbl_av = ttk.Label(opts, text="", style="Muted.TLabel")
        self.lbl_av.pack(side="left", padx=(10, 0))

        body = ttk.Frame(self, padding=(14, 8))
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(1, weight=1)

        # --- buscador (izquierda) ---
        bar = ttk.Frame(body)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(bar, text="🔎", font=(theme.FONT, 14)).pack(side="left")
        self.var_q = tk.StringVar()
        e = ttk.Entry(bar, textvariable=self.var_q, font=(theme.FONT, 12))
        e.pack(side="left", fill="x", expand=True, padx=6)
        e.bind("<KeyRelease>", self._on_query)
        e.bind("<Return>", lambda _e: self._buscar())

        cols = ("nombre", "categoria", "size", "fragmento")
        self.tree = ttk.Treeview(body, columns=cols, show="headings")
        self.tree.heading("nombre", text="Archivo")
        self.tree.heading("categoria", text="Tipo")
        self.tree.heading("size", text="Tamano")
        self.tree.heading("fragmento", text="Coincidencia")
        self.tree.column("nombre", width=230)
        self.tree.column("categoria", width=90)
        self.tree.column("size", width=70, anchor="e")
        self.tree.column("fragmento", width=260)
        self.tree.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        self.tree.bind("<Double-1>", self._abrir_sel)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: None)

        rowb = ttk.Frame(body)
        rowb.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        ttk.Button(rowb, text="Abrir archivo", command=self._abrir_sel).pack(side="left")
        ttk.Button(rowb, text="Abrir su carpeta", command=self._abrir_carpeta_sel).pack(
            side="left", padx=6)

        # --- mapa (derecha) ---
        mapa = ttk.LabelFrame(body, text="Mapa de lo que tienes", padding=10)
        mapa.grid(row=0, column=1, rowspan=3, sticky="nsew")
        self.lbl_totales = ttk.Label(mapa, text="", style="Big.TLabel")
        self.lbl_totales.pack(anchor="w")
        self.txt_mapa = tk.Text(mapa, width=34, height=18, wrap="word", font=(theme.FONT, 10),
                                bg=theme.CARD, relief="flat", state="disabled")
        self.txt_mapa.pack(fill="both", expand=True, pady=(6, 8))
        b_pdf = ttk.Button(mapa, text="📄 Informe PDF", style="Primary.TButton", command=self._pdf)
        b_pdf.pack(fill="x")
        b_dup = ttk.Button(mapa, text="Ver duplicados", command=self._ver_duplicados)
        b_dup.pack(fill="x", pady=(6, 0))
        b_vac = ttk.Button(mapa, text="Vaciar indice", command=self._vaciar)
        b_vac.pack(fill="x", pady=(6, 0))
        self._acciones = [b_pdf, b_dup, b_vac]   # se deshabilitan durante el escaneo

        self.prog = ttk.Progressbar(self, mode="indeterminate")

    # ------------------------------------------------------------- escaneo
    def _elegir(self) -> None:
        d = filedialog.askdirectory(title="Carpeta a escanear",
                                    initialdir=self.var_carpeta.get() or None, parent=self)
        if d:
            self.var_carpeta.set(d)

    def _on_av(self) -> None:
        self.cfg.incluir_audio_video = bool(self.var_av.get())
        save_config(self.cfg)

    def _toggle_scan(self) -> None:
        if self._scanning and self.scanner:
            self.scanner.cancelar()
            self._set_status("Cancelando…")
            return
        raiz = self.var_carpeta.get().strip()
        if not raiz or not Path(raiz).is_dir():
            messagebox.showinfo(APP_NAME, "Elige una carpeta valida.")
            return
        self.cfg.ultima_carpeta = raiz
        save_config(self.cfg)
        self._scanning = True
        self.btn_scan.config(text="⏹ Detener")
        self._set_acciones_estado("disabled")   # no mutar el indice mientras escanea
        self.prog.pack(fill="x", side="bottom")
        self.prog.start(12)

        ffmpeg = modelo = ""
        if self.var_av.get():
            from .transcribe import find_ffmpeg, find_whisper_model
            ffmpeg = find_ffmpeg() or ""
            modelo = find_whisper_model() or ""
            if not ffmpeg or not modelo:
                self.after(0, lambda: self.lbl_av.config(
                    text="(sin FFmpeg/modelo Whisper: el audio/video se indexa solo por nombre)"))
        self.scanner = Scanner(self.index, incluir_av=self.var_av.get(),
                               ffmpeg=ffmpeg, modelo_whisper=modelo)

        def on_prog(n, ruta):
            if not self._closing:
                try:
                    self.after(0, lambda: self._set_status(
                        f"Escaneando… {n} archivos · {Path(ruta).name[:40]}"))
                except (RuntimeError, tk.TclError):
                    pass

        def runner():
            try:
                stats = self.scanner.escanear(raiz, on_progreso=on_prog)
            except Exception as exc:  # noqa: BLE001
                logger.exception("escaneo fallo")
                stats = {"error": str(exc)}
            if not self._closing:
                try:
                    self.after(0, self._scan_done, stats)
                except (RuntimeError, tk.TclError):
                    pass
        self._scan_thread = threading.Thread(target=runner, daemon=True)
        self._scan_thread.start()

    def _set_acciones_estado(self, estado: str) -> None:
        # acciones que leen/mutan el indice: se bloquean durante el escaneo
        for w in getattr(self, "_acciones", []):
            try:
                w.config(state=estado)
            except tk.TclError:
                pass

    def _scan_done(self, stats: dict) -> None:
        self._scanning = False
        self.scanner = None
        self._scan_thread = None
        try:
            self.prog.stop()
            self.prog.pack_forget()
            self.btn_scan.config(text="📡 Escanear")
            self._set_acciones_estado("normal")
        except tk.TclError:
            return
        if "error" in stats:
            messagebox.showerror(APP_NAME, f"El escaneo fallo:\n{stats['error']}")
            return
        self._refrescar_mapa()
        msg = (f"{stats['archivos']} archivos en {stats['segundos']}s "
               f"({stats['nuevos']} nuevos, {stats['reutilizados']} sin cambios)")
        if stats.get("cancelado"):
            msg = "Escaneo cancelado. " + msg
        self._set_status(msg)

    # -------------------------------------------------------------- buscar
    def _on_query(self, _e=None) -> None:
        if self._buscar_id:
            try:
                self.after_cancel(self._buscar_id)
            except (tk.TclError, ValueError):
                pass
        self._buscar_id = self.after(250, self._buscar)   # debounce

    def _buscar(self) -> None:
        self._buscar_id = None
        q = self.var_q.get().strip()
        self.tree.delete(*self.tree.get_children())
        self._resultados = []
        if len(q) < 2:
            return
        res = self.index.buscar(q)
        self._resultados = res
        for r in res:
            self.tree.insert("", "end",
                             values=(r["nombre"], r["categoria"], human_size(r["size"]),
                                     (r["fragmento"] or "").replace("\n", " ")[:120]))
        self._set_status(f"{len(res)} resultados para «{q}».")

    def _sel_path(self) -> str | None:
        sel = self.tree.selection()
        if not sel:
            return None
        idx = self.tree.index(sel[0])
        if 0 <= idx < len(self._resultados):
            return self._resultados[idx]["path"]
        return None

    def _abrir_sel(self, _e=None) -> None:
        p = self._sel_path()
        if p and Path(p).exists():
            try:
                os.startfile(p)
            except OSError as exc:
                messagebox.showerror(APP_NAME, f"No se pudo abrir:\n{exc}")
        elif p:
            messagebox.showinfo(APP_NAME, "Ese archivo ya no existe (vuelve a escanear).")

    def _abrir_carpeta_sel(self) -> None:
        p = self._sel_path()
        if p:
            try:
                subprocess.run(["explorer", "/select,", str(Path(p))])
            except OSError:
                pass

    # ---------------------------------------------------------------- mapa
    def _refrescar_mapa(self) -> None:
        if self._closing:
            return
        n, bs = self.index.totales()
        self.lbl_totales.config(text=f"{n:,} archivos · {human_size(bs)}".replace(",", "."))
        cats = self.index.resumen_categorias()
        rec = self.index.espacio_recuperable()
        lineas = []
        for cat, num, cbs in cats:
            lineas.append(f"{cat:<18} {num:>6}   {human_size(cbs)}")
        if rec:
            lineas.append("")
            lineas.append(f"♻ Recuperable (duplicados): {human_size(rec)}")
        self.txt_mapa.config(state="normal")
        self.txt_mapa.delete("1.0", "end")
        self.txt_mapa.insert("1.0", "\n".join(lineas) or "Aun no has escaneado nada.")
        self.txt_mapa.config(state="disabled")

    def _ver_duplicados(self) -> None:
        dups = self.index.duplicados()
        if not dups:
            messagebox.showinfo(APP_NAME, "No se detectaron duplicados.")
            return
        win = tk.Toplevel(self)
        theme.center_window(win)
        win.title("Duplicados")
        win.configure(bg=theme.BG)
        frm = ttk.Frame(win, padding=12)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text=f"{len(dups)} grupos de archivos idénticos "
                  f"(recuperarías {human_size(self.index.espacio_recuperable())})",
                  style="H.TLabel").pack(anchor="w", pady=(0, 6))
        txt = tk.Text(frm, width=90, height=26, wrap="none", font=("Consolas", 9),
                      bg=theme.WHITE)
        txt.pack(fill="both", expand=True)
        for g in dups[:200]:
            txt.insert("end", f"● {g[0]['nombre']}  ({len(g)} copias, {human_size(g[0]['size'])} c/u)\n")
            for x in g:
                txt.insert("end", f"    {x['path']}\n")
            txt.insert("end", "\n")
        txt.config(state="disabled")
        ttk.Button(frm, text="Cerrar", command=win.destroy).pack(anchor="e", pady=(8, 0))

    def _pdf(self) -> None:
        n, bs = self.index.totales()
        if n == 0:
            messagebox.showinfo(APP_NAME, "Escanea una carpeta primero.")
            return
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        out = Path(self.cfg.output_dir) / f"Mapa_archivos_{stamp}.pdf"
        try:
            report.exportar_pdf(str(out), raiz=self.var_carpeta.get(), total_archivos=n,
                                total_bytes=bs, categorias=self.index.resumen_categorias(),
                                duplicados=self.index.duplicados(),
                                recuperable=self.index.espacio_recuperable())
        except Exception as exc:  # noqa: BLE001
            logger.exception("pdf fallo")
            messagebox.showerror(APP_NAME, f"No se pudo generar el informe:\n{exc}")
            return
        if messagebox.askyesno(APP_NAME, f"Informe guardado en:\n{out}\n\n¿Abrirlo?"):
            try:
                os.startfile(str(out))
            except OSError:
                pass

    def _vaciar(self) -> None:
        if messagebox.askyesno(APP_NAME, "¿Borrar el indice? (no toca tus archivos, solo "
                               "olvida lo escaneado; tendras que volver a escanear)"):
            self.index.vaciar()
            self.tree.delete(*self.tree.get_children())
            self._resultados = []
            self._refrescar_mapa()
            self._set_status("Indice vaciado.")

    # -------------------------------------------------------------- varios
    def _set_status(self, text: str) -> None:
        try:
            self.status.config(text=text)
        except tk.TclError:
            pass

    def _first_run(self) -> None:
        if self._closing or self.cfg.seen_welcome:
            return
        self.cfg.seen_welcome = True
        save_config(self.cfg)
        messagebox.showinfo(
            APP_NAME, "Bienvenido a SonarArchivo.\n\n"
            "1. Elige una carpeta (Descargas, un disco viejo, un pendrive…) y pulsa 'Escanear'.\n"
            "2. SonarArchivo lee el CONTENIDO de tus archivos (texto de PDFs, Office, webs; "
            "y si lo activas, lo que se dice en audios y videos).\n"
            "3. Busca por lo que DICE el archivo, no por su nombre. Y mira el mapa: qué tienes, "
            "duplicados y espacio recuperable.\n\n"
            "El indice se guarda solo en tu equipo; nada se sube a internet.")

    def _on_close(self) -> None:
        self._closing = True
        if self.scanner:
            self.scanner.cancelar()
        # esperar a que el hilo del escaner termine ANTES de cerrar la BD que
        # comparten (si no, cerrar la conexion mientras el hilo la usa da errores)
        t = self._scan_thread
        if t and t.is_alive():
            t.join(timeout=8)
        try:
            self.index.close()
        except Exception:  # noqa: BLE001
            pass
        self.destroy()


def main() -> None:
    from .config import setup_logging
    setup_logging()
    App().mainloop()
