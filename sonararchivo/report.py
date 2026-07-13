"""Informe/mapa del escaneo (PDF con PyMuPDF): resumen por categoria, mayores
grupos de duplicados y espacio recuperable. Texto con insert_htmlbox medido."""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

from .scanner import human_size

PW, PH, M = 595, 842, 42
TW = PW - 2 * M
NAVY = "#1e3a5f"


class ReportError(Exception):
    pass


def _measure(html_str: str, width: float) -> float:
    import fitz
    d = fitz.open()
    try:
        pg = d.new_page(width=width + 80, height=4000)
        spare, _ = pg.insert_htmlbox(fitz.Rect(0, 0, width, 4000), html_str)
        return max(1.0, 4000 - spare)
    finally:
        d.close()


def _rgb(hx: str):
    c = hx.lstrip("#")
    return int(c[0:2], 16) / 255, int(c[2:4], 16) / 255, int(c[4:6], 16) / 255


def exportar_pdf(out_path: str, *, raiz: str, total_archivos: int, total_bytes: int,
                 categorias: list, duplicados: list, recuperable: int,
                 fecha: datetime | None = None) -> str:
    import fitz
    fecha = fecha or datetime.now()
    doc = fitz.open()
    try:
        page = doc.new_page(width=PW, height=PH)
        y = M

        def put(h: str, gap: float = 6.0):
            nonlocal y, page
            alto = _measure(h, TW)
            if y + alto > PH - M:
                page = doc.new_page(width=PW, height=PH)
                y = M
            page.insert_htmlbox(fitz.Rect(M, y, PW - M, min(y + alto + 2, PH - M)), h)
            y += alto + gap

        page.draw_rect(fitz.Rect(0, 0, PW, 86), color=_rgb(NAVY), fill=_rgb(NAVY))
        page.insert_htmlbox(fitz.Rect(M, 16, PW - M, 56),
                            '<div style="font-family:sans-serif;font-size:21px;font-weight:bold;'
                            'color:#ffffff">Mapa de tus archivos</div>')
        page.insert_htmlbox(fitz.Rect(M, 52, PW - M, 82),
                            '<div style="font-family:sans-serif;font-size:10px;color:#b7c7da">'
                            'SonarArchivo · escaneado 100% en tu equipo</div>')
        y = 100

        # separador de miles al estilo espanol SOLO en el numero (no en toda la
        # cadena: un replace global corrompia rutas con coma y descuadraba el
        # separador decimal de human_size)
        n_arch = f"{total_archivos:,}".replace(",", ".")
        put(f'<div style="font-family:sans-serif;font-size:11px;color:#334155">'
            f'<b>Carpeta:</b> {html.escape(raiz)}<br>'
            f'<b>Fecha:</b> {fecha.strftime("%d/%m/%Y %H:%M")} &nbsp;·&nbsp; '
            f'<b>Archivos:</b> {n_arch} &nbsp;·&nbsp; '
            f'<b>Tamano total:</b> {human_size(total_bytes)}</div>', 10)

        put(f'<div style="font-family:sans-serif;font-size:14px;font-weight:bold;color:{NAVY}">'
            f'Que tienes (por tipo)</div>', 4)
        filas = []
        for cat, num, bs in categorias:
            filas.append(
                f'<tr><td style="padding:3px 6px"><b>{html.escape(cat)}</b></td>'
                f'<td style="padding:3px 6px;text-align:right;color:#64748b">{num:,}'.replace(",", ".")
                + ' archivos</td>'
                f'<td style="padding:3px 6px;text-align:right"><b>{human_size(bs)}</b></td></tr>')
        put('<table style="font-family:sans-serif;font-size:10px;border-collapse:collapse;'
            'width:100%">' + "".join(filas) + "</table>", 12)

        put(f'<div style="font-family:sans-serif;font-size:14px;font-weight:bold;color:{NAVY}">'
            f'Duplicados &nbsp;·&nbsp; recuperarias {human_size(recuperable)}</div>', 4)
        if duplicados:
            for grupo in duplicados[:20]:
                if not grupo:
                    continue
                copias = len(grupo)
                nombre = html.escape(grupo[0]["nombre"])
                rutas = "<br>".join(html.escape(g["path"]) for g in grupo[:6])
                put(f'<div style="font-family:sans-serif;font-size:9px;color:#334155;'
                    f'line-height:1.4;margin-bottom:3px"><b>{nombre}</b> — {copias} copias '
                    f'de {human_size(grupo[0]["size"])} c/u:<br>'
                    f'<span style="color:#64748b">{rutas}</span></div>', 3)
        else:
            put('<div style="font-family:sans-serif;font-size:10px;color:#64748b">'
                'No se detectaron duplicados. ¡Bien ordenado!</div>', 8)

        pie = ('<div style="font-family:sans-serif;font-size:8px;color:#94a3b8">'
               'Generado con SonarArchivo (gratis y open source) · simplificaconia.com · '
               'El indice y este informe se generan en tu equipo; nada se sube a internet.</div>')
        ph = _measure(pie, TW)
        if y + ph > PH - 20:
            page = doc.new_page(width=PW, height=PH)
        page.insert_htmlbox(fitz.Rect(M, PH - 20 - ph, PW - M, PH - 16), pie)

        try:
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            doc.save(out_path, garbage=3, deflate=True)
        except Exception as exc:  # noqa: BLE001
            raise ReportError("No se pudo guardar el informe. Si lo tienes abierto en un "
                              "visor de PDF, cierralo y reintenta.") from exc
    finally:
        doc.close()
    return out_path
