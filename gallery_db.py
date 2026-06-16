"""
gallery_db.py
# ═══════════════════════════════════════════════════════════════════════════════
Capa de persistencia SQLite para la galería musical
# ═══════════════════════════════════════════════════════════════════════════════

Schema:
  tracks (id, job_id, title, prompt, genre, bpm, key, output_path,
          metadata_json, timings_json, created_at, duration_seconds, file_size_bytes)
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("gallery_db")

DB_PATH = Path("gallery.db")


class GalleryDB:
    """Wrapper SQLite thread-safe para la galería de canciones generadas."""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    def _get_conn(self) -> sqlite3.Connection:
        """Retorna una conexión; la crea si no existe (thread-local safe con check_same_thread=False)."""
        if self._conn is None:
            self._conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                detect_types=sqlite3.PARSE_DECLTYPES,
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA foreign_keys=ON;")
        return self._conn

    def init(self) -> None:
        """Crea las tablas si no existen."""
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS tracks (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id            TEXT    NOT NULL UNIQUE,
                title             TEXT    NOT NULL,
                prompt            TEXT    NOT NULL,
                genre             TEXT,
                bpm               INTEGER,
                key_signature     TEXT,
                output_path       TEXT    NOT NULL,
                metadata_json     TEXT    DEFAULT '{}',
                timings_json      TEXT    DEFAULT '{}',
                duration_seconds  REAL,
                file_size_bytes   INTEGER,
                created_at        TEXT    NOT NULL,
                favorite          INTEGER DEFAULT 0,
                play_count        INTEGER DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_tracks_job_id ON tracks(job_id);
            CREATE INDEX IF NOT EXISTS idx_tracks_created_at ON tracks(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_tracks_genre ON tracks(genre);
        """)
        conn.commit()
        log.info(f"[DB] Galería inicializada en: {self.db_path.resolve()}")

    def insert_track(
        self,
        job_id: str,
        title: str,
        prompt: str,
        output_path: str,
        metadata: dict[str, Any],
        timings: dict[str, float],
    ) -> int:
        """Inserta un nuevo track en la galería. Retorna el id asignado."""
        p = Path(output_path)
        file_size = p.stat().st_size if p.exists() else None

        # Intentar obtener duración con wave
        duration = None
        try:
            import wave
            with wave.open(str(p), "r") as wf:
                duration = wf.getnframes() / wf.getframerate()
        except Exception:
            pass

        conn = self._get_conn()
        cursor = conn.execute(
            """
            INSERT INTO tracks
                (job_id, title, prompt, genre, bpm, key_signature,
                 output_path, metadata_json, timings_json,
                 duration_seconds, file_size_bytes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                title,
                prompt,
                metadata.get("genero"),
                metadata.get("tempo_bpm"),
                metadata.get("tonalidad"),
                output_path,
                json.dumps(metadata, ensure_ascii=False),
                json.dumps(timings),
                duration,
                file_size,
                datetime.utcnow().isoformat(),
            ),
        )
        conn.commit()
        inserted_id = cursor.lastrowid
        log.info(f"[DB] Track insertado: id={inserted_id}, título='{title}'")
        return inserted_id

    def list_tracks(self, limit: int = 50, offset: int = 0) -> list[dict]:
        """Retorna tracks ordenados por fecha descendente."""
        conn = self._get_conn()
        rows = conn.execute(
            """
            SELECT id, job_id, title, prompt, genre, bpm, key_signature,
                   output_path, duration_seconds, file_size_bytes,
                   created_at, favorite, play_count, metadata_json
            FROM tracks
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
        import json
        results = []
        for r in rows:
            d = dict(r)
            d["metadata"] = json.loads(d.pop("metadata_json", "{}")) if d.get("metadata_json") else {}
            results.append(d)
        return results

    def get_track(self, track_id: int) -> Optional[dict]:
        """Retorna los metadatos completos de un track por su id."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM tracks WHERE id = ?", (track_id,)
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        # Deserializar JSON embebido
        result["metadata"] = json.loads(result.pop("metadata_json", "{}"))
        result["timings"] = json.loads(result.pop("timings_json", "{}"))
        return result

    def get_track_by_job(self, job_id: str) -> Optional[dict]:
        """Retorna el track por su job_id."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM tracks WHERE job_id = ?", (job_id,)
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["metadata"] = json.loads(result.pop("metadata_json", "{}"))
        result["timings"] = json.loads(result.pop("timings_json", "{}"))
        return result

    def delete_track(self, track_id: int) -> bool:
        """Elimina un track de la BD. No borra el archivo de audio."""
        conn = self._get_conn()
        cursor = conn.execute("DELETE FROM tracks WHERE id = ?", (track_id,))
        conn.commit()
        deleted = cursor.rowcount > 0
        if deleted:
            log.info(f"[DB] Track {track_id} eliminado de la galería.")
        return deleted

    def toggle_favorite(self, track_id: int) -> bool:
        """Alterna el estado de favorito de un track. Retorna el nuevo estado."""
        conn = self._get_conn()
        conn.execute(
            "UPDATE tracks SET favorite = CASE WHEN favorite = 1 THEN 0 ELSE 1 END WHERE id = ?",
            (track_id,),
        )
        conn.commit()
        row = conn.execute("SELECT favorite FROM tracks WHERE id = ?", (track_id,)).fetchone()
        return bool(row["favorite"]) if row else False

    def increment_play_count(self, track_id: int) -> None:
        """Incrementa el contador de reproducciones de un track."""
        conn = self._get_conn()
        conn.execute(
            "UPDATE tracks SET play_count = play_count + 1 WHERE id = ?", (track_id,)
        )
        conn.commit()

    def count_tracks(self) -> int:
        """Retorna el total de tracks en la galería."""
        conn = self._get_conn()
        return conn.execute("SELECT COUNT(*) FROM tracks").fetchone()[0]

    def search_tracks(self, query: str, limit: int = 20) -> list[dict]:
        """Búsqueda full-text básica por título, prompt o género."""
        conn = self._get_conn()
        q = f"%{query}%"
        rows = conn.execute(
            """
            SELECT id, job_id, title, prompt, genre, bpm, key_signature,
                   output_path, duration_seconds, file_size_bytes,
                   created_at, favorite, play_count, metadata_json
            FROM tracks
            WHERE title LIKE ? OR prompt LIKE ? OR genre LIKE ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (q, q, q, limit),
        ).fetchall()
        import json
        results = []
        for r in rows:
            d = dict(r)
            d["metadata"] = json.loads(d.pop("metadata_json", "{}")) if d.get("metadata_json") else {}
            results.append(d)
        return results

    def rename_track(self, track_id: int, new_title: str) -> bool:
        """Cambia el título de una canción."""
        conn = self._get_conn()
        cursor = conn.execute("UPDATE tracks SET title = ? WHERE id = ?", (new_title, track_id))
        conn.commit()
        return cursor.rowcount > 0

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

