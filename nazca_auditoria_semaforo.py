"""Bitácora de alertas del semáforo — seguimiento aciertos / falsos positivos por zona."""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

CHILE_TZ = ZoneInfo("America/Santiago")
BASE_DIR = Path(__file__).resolve().parent
AUDITORIA_FILE = BASE_DIR / "nazca_auditoria_semaforo.csv"

NIVELES_REGISTRO = {"AMARILLO", "NARANJO", "ROJO"}
VENTANA_EVAL_DIAS = 30
MAG_MIN_EVENTO = 5.0
RADIO_EVAL_KM = 350


def ahora_chile() -> datetime:
    return datetime.now(CHILE_TZ).replace(tzinfo=None)


def distancia_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radio = 6371.0
    lat1r, lon1r, lat2r, lon2r = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2r - lat1r
    dlon = lon2r - lon1r
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1r) * math.cos(lat2r) * math.sin(dlon / 2) ** 2
    return float(2 * radio * math.asin(math.sqrt(a)))


def _parse_fecha(texto: str) -> datetime | None:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(str(texto), fmt)
        except ValueError:
            continue
    return None


def leer_auditoria() -> pd.DataFrame:
    if not AUDITORIA_FILE.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(AUDITORIA_FILE, encoding="utf-8-sig")
    except (OSError, pd.errors.EmptyDataError, ValueError):
        return pd.DataFrame()
    if "fecha_alerta" in df.columns:
        df["fecha_alerta_dt"] = pd.to_datetime(df["fecha_alerta"], errors="coerce")
    return df


def _guardar_auditoria(df: pd.DataFrame) -> None:
    out = df.drop(columns=["fecha_alerta_dt"], errors="ignore")
    out.to_csv(AUDITORIA_FILE, index=False, encoding="utf-8-sig")


def registrar_alerta_semaforo(
    estacion: str,
    config: dict,
    nivel_alerta: dict,
    puntaje: float,
    mejor_match: float,
    mejor_ev: str,
    total_sismos: int,
    motivos: list[str] | None = None,
    clave_bloque: str = "",
) -> str | None:
    nivel = str(nivel_alerta.get("nivel", "VERDE")).upper()
    if nivel not in NIVELES_REGISTRO:
        return None

    df = leer_auditoria()
    ahora = ahora_chile()
    clave = clave_bloque or ahora.strftime("%Y-%m-%d %H")
    if not df.empty:
        dup = df[
            (df["estacion"] == estacion)
            & (df["nivel"] == nivel)
            & (df.get("clave_bloque", pd.Series(dtype=str)) == clave)
        ]
        if not dup.empty:
            return None

    fila = {
        "fecha_alerta": ahora.strftime("%Y-%m-%d %H:%M:%S"),
        "estacion": estacion,
        "lat": config.get("lat"),
        "lon": config.get("lon"),
        "nivel": nivel,
        "puntaje": round(float(puntaje), 2),
        "match_m7": round(float(mejor_match), 2),
        "patron_m7": mejor_ev,
        "sismos_locales_14d": int(total_sismos),
        "motivos": " | ".join(motivos or []),
        "ventana_eval_dias": VENTANA_EVAL_DIAS,
        "resultado": "PENDIENTE",
        "fecha_evento": "",
        "mag_evento": "",
        "lugar_evento": "",
        "dias_anticipacion": "",
        "clave_bloque": clave,
    }
    df = pd.concat([df, pd.DataFrame([fila])], ignore_index=True)
    _guardar_auditoria(df)
    return clave


def _eventos_posteriores(df_sismos: pd.DataFrame, desde: datetime, lat: float, lon: float) -> pd.DataFrame:
    if df_sismos is None or df_sismos.empty:
        return pd.DataFrame()
    cols = {"Magnitud", "Latitud", "Longitud", "Fecha"}
    if not cols.issubset(df_sismos.columns):
        return pd.DataFrame()

    filas = []
    for _, row in df_sismos.iterrows():
        mag = float(row.get("Magnitud") or 0)
        if mag < MAG_MIN_EVENTO:
            continue
        fecha = _parse_fecha(str(row.get("Fecha", "")))
        if not fecha or fecha < desde:
            continue
        dist = distancia_km(lat, lon, float(row["Latitud"]), float(row["Longitud"]))
        if dist > RADIO_EVAL_KM:
            continue
        filas.append({
            "Magnitud": mag,
            "Lugar": row.get("Lugar", ""),
            "Fecha": row.get("Fecha", ""),
            "fecha_dt": fecha,
            "dist_km": round(dist, 1),
        })
    if not filas:
        return pd.DataFrame()
    return pd.DataFrame(filas).sort_values("fecha_dt")


def actualizar_resultados_auditoria(df_sismos: pd.DataFrame) -> int:
    df = leer_auditoria()
    if df.empty:
        return 0
    ahora = ahora_chile()
    actualizados = 0

    for idx, row in df.iterrows():
        if str(row.get("resultado", "")).upper() != "PENDIENTE":
            continue
        fecha_alerta = row.get("fecha_alerta_dt")
        if pd.isna(fecha_alerta):
            fecha_alerta = _parse_fecha(str(row.get("fecha_alerta", "")))
        if not fecha_alerta:
            continue

        limite = fecha_alerta + timedelta(days=int(row.get("ventana_eval_dias", VENTANA_EVAL_DIAS)))
        eventos = _eventos_posteriores(
            df_sismos,
            fecha_alerta,
            float(row.get("lat", 0)),
            float(row.get("lon", 0)),
        )
        if not eventos.empty:
            ev = eventos.iloc[0]
            dias = (ev["fecha_dt"] - fecha_alerta).total_seconds() / 86400.0
            df.at[idx, "resultado"] = "ACIERTO"
            df.at[idx, "fecha_evento"] = ev["Fecha"]
            df.at[idx, "mag_evento"] = ev["Magnitud"]
            df.at[idx, "lugar_evento"] = ev["Lugar"]
            df.at[idx, "dias_anticipacion"] = round(dias, 2)
            actualizados += 1
        elif ahora >= limite:
            df.at[idx, "resultado"] = "FALSO_POSITIVO"
            actualizados += 1

    if actualizados:
        _guardar_auditoria(df)
    return actualizados


def resumen_auditoria_estacion(estacion: str) -> dict:
    df = leer_auditoria()
    if df.empty:
        return {"total": 0, "pendiente": 0, "acierto": 0, "falso_positivo": 0}
    local = df[df["estacion"] == estacion]
    if local.empty:
        return {"total": 0, "pendiente": 0, "acierto": 0, "falso_positivo": 0}
    res = local["resultado"].astype(str).str.upper().value_counts().to_dict()
    return {
        "total": len(local),
        "pendiente": int(res.get("PENDIENTE", 0)),
        "acierto": int(res.get("ACIERTO", 0)),
        "falso_positivo": int(res.get("FALSO_POSITIVO", 0)),
    }


def tabla_auditoria_estacion(estacion: str, limite: int = 12) -> pd.DataFrame:
    df = leer_auditoria()
    if df.empty:
        return pd.DataFrame()
    local = df[df["estacion"] == estacion].copy()
    if local.empty:
        return pd.DataFrame()
    cols = [
        "fecha_alerta", "nivel", "puntaje", "match_m7", "patron_m7",
        "sismos_locales_14d", "resultado", "fecha_evento", "mag_evento", "dias_anticipacion",
    ]
    cols = [c for c in cols if c in local.columns]
    if "fecha_alerta_dt" in local.columns:
        local = local.sort_values("fecha_alerta_dt", ascending=False)
    return local[cols].head(limite)
