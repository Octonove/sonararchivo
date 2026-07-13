"""Tests de logica pura de SonarArchivo (extraccion, indice, escaneo, informe).
Ejecutar:  python -m pytest tests/ -q   (desde la carpeta SonarArchivo)"""

import io
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sonararchivo import extract, report, scanner  # noqa: E402
from sonararchivo.index import Index, Registro  # noqa: E402


# ---------------------------------------------------------------- extract
def test_categoria():
    assert extract.categoria(".PDF") == "Documentos"
    assert extract.categoria(".mp3") == "Audio"
    assert extract.categoria(".py") == "Codigo"
    assert extract.categoria(".xyz") == "Otros"


def test_strip_html():
    h = "<html><body><h1>Hola</h1><script>alert(1)</script><p>mundo &amp; más</p></body></html>"
    t = extract.strip_html(h)
    assert "Hola" in t and "mundo & más" in t
    assert "alert" not in t and "<" not in t


def test_docx_text(tmp_path):
    p = tmp_path / "d.docx"
    doc = ('<?xml version="1.0"?><w:document xmlns:w="x"><w:body>'
           '<w:p><w:r><w:t>Factura</w:t></w:r> <w:r><w:t>Acme</w:t></w:r></w:p>'
           '<w:p><w:r><w:t>Total 1200 euros</w:t></w:r></w:p></w:body></w:document>')
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml", doc)
    t = extract.docx_text(p)
    assert "Factura" in t and "Acme" in t and "1200" in t


def test_extraer_texto_txt(tmp_path):
    p = tmp_path / "n.txt"
    p.write_text("presupuesto reforma cocina 2026", encoding="utf-8")
    assert "presupuesto" in extract.extraer_texto(p)


def test_extraer_texto_desconocido_no_lanza(tmp_path):
    p = tmp_path / "x.bin"
    p.write_bytes(b"\x00\x01\x02")
    assert extract.extraer_texto(p) == ""


# ------------------------------------------------------------------ scanner
def test_human_size():
    assert scanner.human_size(0) == "0 B"
    assert scanner.human_size(1536) == "1,5 KB"
    assert scanner.human_size(5 * 1024**3).endswith("GB")


def test_firma_distingue_y_coincide(tmp_path):
    a = tmp_path / "a.txt"; a.write_text("hola mundo")
    b = tmp_path / "b.txt"; b.write_text("hola mundo")   # mismo contenido
    c = tmp_path / "c.txt"; c.write_text("otro")
    fa = scanner.firma_archivo(a, a.stat().st_size)
    fb = scanner.firma_archivo(b, b.stat().st_size)
    fc = scanner.firma_archivo(c, c.stat().st_size)
    assert fa == fb and fa != fc and len(fa) == 40


def test_escaneo_e_indice(tmp_path):
    # el indice vive FUERA del arbol escaneado (como en produccion: %APPDATA%)
    raiz = tmp_path / "data"; raiz.mkdir()
    (raiz / "docs").mkdir()
    (raiz / "docs" / "informe.txt").write_text("informe anual de ventas 2026", encoding="utf-8")
    (raiz / "copia.txt").write_text("informe anual de ventas 2026", encoding="utf-8")  # dup
    (raiz / "notas.md").write_text("comprar leche y pan", encoding="utf-8")
    idx = Index(str(tmp_path / "idx" / "idx.db"))
    try:
        sc = scanner.Scanner(idx)
        stats = sc.escanear(str(raiz))
        assert stats["archivos"] == 3 and stats["nuevos"] == 3
        # busqueda por CONTENIDO
        r = idx.buscar("ventas")
        assert any("informe.txt" == x["nombre"] for x in r)
        assert idx.buscar("leche")[0]["nombre"] == "notas.md"
        # duplicados detectados por firma
        dups = idx.duplicados()
        assert len(dups) == 1 and len(dups[0]) == 2
        assert idx.espacio_recuperable() > 0
        # reescaneo incremental: nada nuevo
        stats2 = sc.escanear(str(raiz))
        assert stats2["nuevos"] == 0 and stats2["reutilizados"] == 3
    finally:
        idx.close()


def test_indice_purga_borrados(tmp_path):
    raiz = tmp_path / "data"; raiz.mkdir()
    f = raiz / "temp.txt"; f.write_text("dato", encoding="utf-8")
    idx = Index(str(tmp_path / "idx" / "i.db"))
    try:
        sc = scanner.Scanner(idx)
        sc.escanear(str(raiz))
        assert idx.totales()[0] == 1
        f.unlink()
        stats = sc.escanear(str(raiz))
        assert stats["eliminados"] == 1 and idx.totales()[0] == 0
    finally:
        idx.close()


def test_busqueda_fts_query_segura(tmp_path):
    idx = Index(str(tmp_path / "q.db"))
    try:
        # una consulta con comillas/operadores NO debe lanzar
        assert idx.buscar('"' * 5 + " OR AND (") == []
        assert idx.buscar("") == []
    finally:
        idx.close()


def test_cancelar_no_purga_el_indice(tmp_path):
    # regresion: cancelar un reescaneo NO debe borrar los archivos aun no visitados
    raiz = tmp_path / "data"; raiz.mkdir()
    for i in range(45):     # >40 para que on_progreso dispare y podamos cancelar
        (raiz / f"f{i:02d}.txt").write_text(f"contenido {i}", encoding="utf-8")
    idx = Index(str(tmp_path / "idx" / "i.db"))
    try:
        sc = scanner.Scanner(idx)
        sc.escanear(str(raiz))
        assert idx.totales()[0] == 45
        # cancelar a mitad del reescaneo (en el primer callback de progreso)
        stats = sc.escanear(str(raiz), on_progreso=lambda n, p: sc.cancelar())
        assert stats["cancelado"] and stats["eliminados"] == 0
        assert idx.totales()[0] == 45         # NO se perdio nada
    finally:
        idx.close()


def test_raices_anidadas(tmp_path):
    raiz = tmp_path / "data"; raiz.mkdir()
    (raiz / "sub").mkdir()
    (raiz / "sub" / "dentro.txt").write_text("hola", encoding="utf-8")
    (raiz / "fuera.txt").write_text("mundo", encoding="utf-8")
    idx = Index(str(tmp_path / "idx" / "i.db"))
    try:
        sc = scanner.Scanner(idx)
        sc.escanear(str(raiz / "sub"))        # primero la subcarpeta
        sc.escanear(str(raiz))                # luego la carpeta padre (anidada)
        # 'dentro.txt' se quedo con la raiz de la subcarpeta; borrarlo del disco y
        # reescanear el padre debe purgarlo igualmente (path bajo la raiz)
        (raiz / "sub" / "dentro.txt").unlink()
        sc.escanear(str(raiz))
        assert not idx.buscar("hola")         # purgado
        assert idx.buscar("mundo")            # sigue
    finally:
        idx.close()


# ------------------------------------------------------------ decode/topes
def test_decode_utf8_cortado_no_corrompe():
    # 'café' con la 'é' (0xC3 0xA9) cortada en el ultimo byte: no debe volver
    # mojibake TODO el texto (debe usar reemplazo, no caer a latin-1)
    data = ("café " * 100).encode("utf-8")[:-1]   # corta un byte multibyte
    t = extract._decode(data)
    assert "café caf" in t          # el texto previo sigue legible


def test_leer_miembro_acota(tmp_path):
    import zipfile
    p = tmp_path / "big.docx"
    grande = "A" * (extract.MAX_LEER * 3)
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", f"<w:p><w:t>{grande}</w:t></w:p>")
    t = extract.docx_text(p)
    assert 0 < len(t) <= extract.MAX_LEER + 100      # no cargo los 2.4 MB enteros


def test_docx_corrupto_no_lanza(tmp_path):
    p = tmp_path / "roto.docx"
    p.write_bytes(b"no soy un zip")
    assert extract.docx_text(p) == ""      # best-effort: no lanza


# ------------------------------------------------------------------ informe
def test_informe_pdf(tmp_path):
    import fitz
    out = str(tmp_path / "mapa.pdf")
    report.exportar_pdf(out, raiz=r"C:\Users\x\Downloads", total_archivos=1234,
                        total_bytes=5 * 1024**3,
                        categorias=[("Documentos", 400, 2 * 1024**3),
                                    ("Imagenes", 800, 3 * 1024**3)],
                        duplicados=[[{"path": r"C:\a\f.jpg", "nombre": "f.jpg",
                                      "size": 1024**2, "mtime": 0},
                                     {"path": r"C:\b\f.jpg", "nombre": "f.jpg",
                                      "size": 1024**2, "mtime": 0}]],
                        recuperable=1024**2)
    doc = fitz.open(out)
    text = "\n".join(doc[p].get_text("text") for p in range(doc.page_count))
    doc.close()
    assert "Mapa de tus archivos" in text
    assert "Downloads" in text and "Documentos" in text
    assert "Duplicados" in text
