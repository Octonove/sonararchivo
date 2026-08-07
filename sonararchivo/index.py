"""Indice local (SQLite + FTS5) de SonarArchivo.

Guarda por archivo: ruta, nombre, extension, categoria, tamano, fecha, firma
(sha1 para duplicados) y el TEXTO extraido. La busqueda usa FTS5 sobre nombre +
contenido. El indice vive solo en la carpeta de datos del usuario (%APPDATA%),
nunca sale del equipo; se puede borrar con un clic.

TODO acceso a la conexion pasa por un RLock: el hilo del escaner escribe mientras
el hilo de la UI consulta sobre la MISMA conexion (check_same_thread=False), y sin
serializar podrian chocar ('database is locked' / uso recursivo de cursores).

Reescaneo INCREMENTAL: si un archivo no cambio (misma ruta, tamano y fecha) se
reutiliza su fila y no se vuelve a leer/hashear.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class Registro:
    path: str
    nombre: str
    ext: str
    categoria: str
    size: int
    mtime: float
    sha1: str
    texto: str


class Index:
    def __init__(self, db_path: str):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(self.db_path, check_same_thread=False)
        try:
            self._con.execute("PRAGMA journal_mode=WAL")
            self._lock = threading.RLock()
            self._init()
        except sqlite3.Error:
            # cerrar la conexion antes de propagar: si el fichero esta corrupto
            # hay que poder apartarlo (Windows no deja renombrar un fichero que
            # sigue abierto por esta misma conexion)
            self._con.close()
            raise

    def close(self) -> None:
        with self._lock:
            try:
                self._con.close()
            except sqlite3.Error:
                pass

    def _init(self) -> None:
        with self._lock:
            self._con.executescript("""
            CREATE TABLE IF NOT EXISTS archivos(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL UNIQUE,
                nombre TEXT NOT NULL, ext TEXT NOT NULL, categoria TEXT NOT NULL,
                size INTEGER NOT NULL, mtime REAL NOT NULL, sha1 TEXT NOT NULL,
                raiz TEXT NOT NULL, visto INTEGER NOT NULL DEFAULT 1);
            CREATE INDEX IF NOT EXISTS ix_sha1 ON archivos(sha1);
            CREATE INDEX IF NOT EXISTS ix_cat ON archivos(categoria);
            CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(nombre, contenido);
            """)
            self._con.commit()

    # ------------------------------------------------------------- escaneo
    @staticmethod
    def _prefijo(raiz: str) -> str:
        """Prefijo de ruta 'raiz + separador' para detectar archivos fisicamente
        DENTRO de raiz (raices anidadas: un archivo pudo quedar con la raiz de un
        escaneo previo mas profundo). Se compara con substr, no con LIKE: las
        rutas de Windows llevan '\\' por todas partes y el ESCAPE de LIKE las
        malinterpretaria (tanto el separador como la propia ruta)."""
        return raiz.rstrip("\\/") + os.sep

    def existente(self, path: str) -> tuple[int, float] | None:
        with self._lock:
            r = self._con.execute("SELECT size, mtime FROM archivos WHERE path=?",
                                  (path,)).fetchone()
            return (int(r[0]), float(r[1])) if r else None

    def marcar_visto(self, path: str) -> None:
        with self._lock:
            self._con.execute("UPDATE archivos SET visto=1 WHERE path=?", (path,))

    def upsert(self, reg: Registro, raiz: str) -> None:
        with self._lock:
            cur = self._con.execute("SELECT id FROM archivos WHERE path=?", (reg.path,)).fetchone()
            if cur:
                fid = cur[0]
                self._con.execute(
                    "UPDATE archivos SET nombre=?, ext=?, categoria=?, size=?, mtime=?, "
                    "sha1=?, raiz=?, visto=1 WHERE id=?",
                    (reg.nombre, reg.ext, reg.categoria, reg.size, reg.mtime, reg.sha1, raiz, fid))
                self._con.execute("DELETE FROM fts WHERE rowid=?", (fid,))
            else:
                cur2 = self._con.execute(
                    "INSERT INTO archivos(path, nombre, ext, categoria, size, mtime, sha1, raiz) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (reg.path, reg.nombre, reg.ext, reg.categoria, reg.size, reg.mtime, reg.sha1, raiz))
                fid = int(cur2.lastrowid)
            self._con.execute("INSERT INTO fts(rowid, nombre, contenido) VALUES(?,?,?)",
                              (fid, reg.nombre, reg.texto))

    def comenzar_escaneo(self, raiz: str) -> None:
        with self._lock:
            pre = self._prefijo(raiz)
            self._con.execute(
                "UPDATE archivos SET visto=0 WHERE raiz=? OR substr(path,1,?)=?",
                (raiz, len(pre), pre))

    def purgar_no_vistos(self, raiz: str) -> int:
        """Elimina del indice los archivos de esa raiz marcados como no vistos.
        SOLO debe llamarse tras un escaneo COMPLETO (no cancelado): si no, muchos
        archivos quedarian con visto=0 sin haberse visitado y se perderian."""
        with self._lock:
            pre = self._prefijo(raiz)
            ids = [r[0] for r in self._con.execute(
                "SELECT id FROM archivos WHERE (raiz=? OR substr(path,1,?)=?) AND visto=0",
                (raiz, len(pre), pre))]
            for fid in ids:
                self._con.execute("DELETE FROM fts WHERE rowid=?", (fid,))
            self._con.execute(
                "DELETE FROM archivos WHERE (raiz=? OR substr(path,1,?)=?) AND visto=0",
                (raiz, len(pre), pre))
            self._con.commit()
            return len(ids)

    def commit(self) -> None:
        with self._lock:
            self._con.commit()

    # ------------------------------------------------------------- consultas
    @staticmethod
    def _fts_query(texto: str) -> str:
        palabras = [p for p in "".join(
            c if c.isalnum() else " " for c in texto).split() if p]
        return " ".join(f'"{p}"*' for p in palabras)

    def buscar(self, texto: str, limite: int = 300) -> list[dict]:
        q = self._fts_query(texto)
        if not q:
            return []
        with self._lock:
            try:
                filas = self._con.execute(
                    "SELECT a.path, a.nombre, a.categoria, a.size, a.mtime, "
                    "snippet(fts, 1, '[', ']', ' … ', 12) "
                    "FROM fts JOIN archivos a ON a.id = fts.rowid "
                    "WHERE fts MATCH ? ORDER BY rank LIMIT ?", (q, limite)).fetchall()
            except sqlite3.Error as exc:      # no romper el callback de Tk pase lo que pase
                logger.warning("busqueda fallo: %s", exc)
                return []
        return [{"path": p, "nombre": n, "categoria": c, "size": s, "mtime": m,
                 "fragmento": frag} for p, n, c, s, m, frag in filas]

    def resumen_categorias(self) -> list[tuple[str, int, int]]:
        with self._lock:
            return [(c, int(n), int(b or 0)) for c, n, b in self._con.execute(
                "SELECT categoria, COUNT(*), SUM(size) FROM archivos "
                "GROUP BY categoria ORDER BY SUM(size) DESC")]

    def duplicados(self) -> list[list[dict]]:
        with self._lock:
            grupos = self._con.execute(
                "SELECT sha1 FROM archivos WHERE size>0 AND sha1!='' "
                "GROUP BY sha1 HAVING COUNT(*)>1 ORDER BY SUM(size) DESC LIMIT 500").fetchall()
            salida = []
            for (h,) in grupos:
                filas = self._con.execute(
                    "SELECT path, nombre, size, mtime FROM archivos WHERE sha1=? ORDER BY mtime",
                    (h,)).fetchall()
                salida.append([{"path": p, "nombre": n, "size": int(s), "mtime": m}
                               for p, n, s, m in filas])
            return salida

    def totales(self) -> tuple[int, int]:
        with self._lock:
            r = self._con.execute("SELECT COUNT(*), SUM(size) FROM archivos").fetchone()
            return int(r[0] or 0), int(r[1] or 0)

    def espacio_recuperable(self) -> int:
        total = 0
        for grupo in self.duplicados():
            if grupo:
                total += grupo[0]["size"] * (len(grupo) - 1)
        return total

    def vaciar(self) -> None:
        with self._lock:
            self._con.executescript("DELETE FROM archivos; DELETE FROM fts;")
            self._con.commit()


def abrir_recuperando(db_path: str) -> tuple[Index, bool]:
    """Abre el indice; si el fichero esta danado (corte de luz durante un
    checkpoint WAL, disco lleno, sector defectuoso) lo aparta a .bak y crea uno
    vacio. Sin esto un indice.db corrupto impide arrancar la app PARA SIEMPRE:
    el exe es windowed y el usuario solo ve que 'no abre'. Devuelve
    (indice, se_recupero) para que la UI pueda avisar y pedir un reescaneo."""
    try:
        return Index(db_path), False
    except sqlite3.DatabaseError:
        logger.exception("indice corrupto en %s; se aparta y se recrea", db_path)
        for suf in ("", "-wal", "-shm"):     # los ficheros WAL tambien: SQLite
            p = Path(db_path + suf)          # los aplicaria sobre la BD nueva
            try:
                if p.exists():
                    p.replace(p.with_name(p.name + ".bak"))
            except OSError:
                # si ni apartarlo se puede, borrarlo es la unica via de arranque
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass
        return Index(db_path), True
