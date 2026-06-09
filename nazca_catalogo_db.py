"""Almacén SQLite aislado para PIPELINE LAB — no toca caché ni CSV del núcleo NAZCA."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

CHILE_TZ = ZoneInfo("America/Santiago")
BASE_DIR = Path(__file__).resolve().parent
PIPELINE_DATA_DIR = BASE_DIR / "data" / "pipeline_lab"
DB_PATH = PIPELINE_DATA_DIR / "nazca_pipeline.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sismos_raw (
    id TEXT NOT NULL,
    fuente TEXT NOT NULL,
    fecha_utc TEXT,
    fecha_local TEXT NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    profundidad_km REAL,
    magnitud REAL NOT NULL,
    mag_type TEXT,
    lugar TEXT,
    url TEXT,
    insertado_at TEXT NOT NULL,
    PRIMARY KEY (id, fuente)
);
CREATE TABLE IF NOT EXISTS pipeline_meta (
    clave TEXT PRIMARY KEY,
    valor TEXT,
    actualizado_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sismos_fecha ON sismos_raw(fecha_local);
CREATE INDEX IF NOT EXISTS idx_sismos_mag ON sismos_raw(magnitud);
"""


def ahora_iso() -> str:
    return datetime.now(CHILE_TZ).strftime("%Y-%m-%d %H:%M:%S")


def asegurar_db() -> Path:
    PIPELINE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(SCHEMA)
    return DB_PATH


def guardar_meta(clave: str, valor: str) -> None:
    asegurar_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO pipeline_meta (clave, valor, actualizado_at) VALUES (?, ?, ?)",
            (clave, valor, ahora_iso()),
        )


def leer_meta(clave: str, default: str = "") -> str:
    asegurar_db()
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT valor FROM pipeline_meta WHERE clave = ?", (clave,)
        ).fetchone()
    return row[0] if row else default


def upsert_sismos(filas: list[dict]) -> int:
    if not filas:
        return 0
    asegurar_db()
    insertados = 0
    ts = ahora_iso()
    with sqlite3.connect(DB_PATH) as conn:
        for f in filas:
            conn.execute(
                """
                INSERT OR REPLACE INTO sismos_raw
                (id, fuente, fecha_utc, fecha_local, lat, lon, profundidad_km,
                 magnitud, mag_type, lugar, url, insertado_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(f["id"]),
                    str(f["fuente"]),
                    f.get("fecha_utc"),
                    f["fecha_local"],
                    float(f["lat"]),
                    float(f["lon"]),
                    f.get("profundidad_km"),
                    float(f["magnitud"]),
                    f.get("mag_type"),
                    f.get("lugar"),
                    f.get("url"),
                    ts,
                ),
            )
            insertados += 1
    return insertados


def leer_sismos(
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    mag_min: float = 0.0,
    fuente: str | None = None,
) -> pd.DataFrame:
    asegurar_db()
    q = "SELECT * FROM sismos_raw WHERE magnitud >= ?"
    params: list = [mag_min]
    if fecha_desde:
        q += " AND fecha_local >= ?"
        params.append(fecha_desde)
    if fecha_hasta:
        q += " AND fecha_local <= ?"
        params.append(fecha_hasta)
    if fuente:
        q += " AND fuente = ?"
        params.append(fuente)
    q += " ORDER BY fecha_local DESC"
    with sqlite3.connect(DB_PATH) as conn:
        df = pd.read_sql_query(q, conn, params=params)
    return df


def resumen_db() -> dict:
    asegurar_db()
    with sqlite3.connect(DB_PATH) as conn:
        total = conn.execute("SELECT COUNT(*) FROM sismos_raw").fetchone()[0]
        por_fuente = conn.execute(
            "SELECT fuente, COUNT(*) FROM sismos_raw GROUP BY fuente"
        ).fetchall()
        rango = conn.execute(
            "SELECT MIN(fecha_local), MAX(fecha_local) FROM sismos_raw"
        ).fetchone()
    return {
        "ruta": str(DB_PATH),
        "total": int(total),
        "por_fuente": {f: int(n) for f, n in por_fuente},
        "fecha_min": rango[0],
        "fecha_max": rango[1],
        "ultimo_usgs": leer_meta("ultimo_sync_usgs"),
        "ultimo_csn": leer_meta("ultimo_sync_csn"),
    }


def df_a_formato_nazca(df: pd.DataFrame) -> pd.DataFrame:
    """Adapta catálogo pipeline al esquema del monitor principal (solo lectura)."""
    if df is None or df.empty:
        return pd.DataFrame(columns=["Magnitud", "Lugar", "Fecha", "Latitud", "Longitud", "Fuente"])
    out = pd.DataFrame({
        "Magnitud": df["magnitud"],
        "Lugar": df["lugar"].fillna(""),
        "Fecha": df["fecha_local"],
        "Latitud": df["lat"],
        "Longitud": df["lon"],
        "Fuente": df["fuente"],
    })
    if "profundidad_km" in df.columns:
        out["Profundidad_km"] = df["profundidad_km"]
    return out.sort_values("Fecha", ascending=False)
