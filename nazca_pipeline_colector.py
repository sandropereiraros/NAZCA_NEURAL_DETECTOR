"""Recolectores USGS + CSN (xor.cl) — solo para PIPELINE LAB."""
from __future__ import annotations

import calendar
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

import nazca_catalogo_db as catalogo

CHILE_TZ = ZoneInfo("America/Santiago")
CHILE_BOUNDS = {
    "min_lat": -56.0,
    "max_lat": -17.0,
    "min_lon": -76.5,
    "max_lon": -66.0,
}
USGS_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
CSN_RECENT_URL = "https://api.xor.cl/sismo/recent"
CSN_HISTORIC_URL = "https://api.xor.cl/sismo/historic/{yyyymmdd}"


def _mes_siguiente(anio: int, mes: int) -> tuple[int, int]:
    if mes == 12:
        return anio + 1, 1
    return anio, mes + 1


def fetch_usgs_rango(
    inicio: datetime,
    fin: datetime,
    mag_min: float = 2.5,
    timeout: int = 30,
) -> list[dict]:
    params = {
        "format": "geojson",
        "starttime": inicio.strftime("%Y-%m-%d"),
        "endtime": fin.strftime("%Y-%m-%d"),
        "minlatitude": CHILE_BOUNDS["min_lat"],
        "maxlatitude": CHILE_BOUNDS["max_lat"],
        "minlongitude": CHILE_BOUNDS["min_lon"],
        "maxlongitude": CHILE_BOUNDS["max_lon"],
        "minmagnitude": mag_min,
        "orderby": "time",
        "limit": 20000,
    }
    try:
        res = requests.get(USGS_URL, params=params, timeout=timeout)
        if res.status_code != 200:
            return []
        filas = []
        for feat in res.json().get("features", []):
            p = feat["properties"]
            c = feat["geometry"]["coordinates"]
            t_ms = p.get("time")
            if not t_ms:
                continue
            fecha_utc = datetime.fromtimestamp(t_ms / 1000, tz=CHILE_TZ)
            usgs_id = str(p.get("id") or p.get("code") or feat.get("id") or t_ms)
            filas.append({
                "id": usgs_id,
                "fuente": "USGS",
                "fecha_utc": fecha_utc.strftime("%Y-%m-%d %H:%M:%S"),
                "fecha_local": fecha_utc.astimezone(CHILE_TZ).strftime("%Y-%m-%d %H:%M:%S"),
                "lat": float(c[1]),
                "lon": float(c[0]),
                "profundidad_km": float(c[2]) if len(c) > 2 else None,
                "magnitud": float(p.get("mag") or 0),
                "mag_type": p.get("magType"),
                "lugar": p.get("place", ""),
                "url": p.get("url"),
            })
        return filas
    except requests.RequestException:
        return []


def sync_usgs_ultimos_dias(dias: int = 30, mag_min: float = 2.5) -> dict:
    fin = datetime.now(CHILE_TZ)
    inicio = fin - timedelta(days=max(1, dias))
    filas = fetch_usgs_rango(inicio, fin, mag_min=mag_min)
    n = catalogo.upsert_sismos(filas)
    catalogo.guardar_meta("ultimo_sync_usgs", ahora_iso())
    return {"fuente": "USGS", "dias": dias, "recibidos": len(filas), "guardados": n}


def sync_usgs_mes(anio: int, mes: int, mag_min: float = 2.5) -> dict:
    inicio = datetime(anio, mes, 1, tzinfo=CHILE_TZ)
    ny, nm = _mes_siguiente(anio, mes)
    fin = datetime(ny, nm, 1, tzinfo=CHILE_TZ) - timedelta(seconds=1)
    filas = fetch_usgs_rango(inicio, fin, mag_min=mag_min)
    n = catalogo.upsert_sismos(filas)
    catalogo.guardar_meta("ultimo_sync_usgs", ahora_iso())
    return {
        "fuente": "USGS",
        "periodo": f"{anio}-{mes:02d}",
        "recibidos": len(filas),
        "guardados": n,
    }


def _parse_evento_csn(ev: dict) -> dict | None:
    try:
        mag = ev.get("magnitude") or {}
        val = float(mag.get("value") or 0)
        if val <= 0:
            return None
        return {
            "id": str(ev.get("id", "")),
            "fuente": "CSN",
            "fecha_utc": ev.get("utc_date", "").replace("T", " ")[:19],
            "fecha_local": ev.get("local_date", "").replace("T", " ")[:19],
            "lat": float(ev["latitude"]),
            "lon": float(ev["longitude"]),
            "profundidad_km": float(ev.get("depth") or 0),
            "magnitud": val,
            "mag_type": mag.get("measure_unit", "Ml"),
            "lugar": (
                ev.get("geo_reference")
                or ev.get("georeference")
                or ev.get("referencia_geografica")
                or ev.get("reference")
                or ""
            ),
            "url": ev.get("url"),
        }
    except (KeyError, TypeError, ValueError):
        return None


def _params_csn_mag(mag_min: float) -> dict:
    """api.xor.cl acepta magnitud entera; 2.5 → sin filtro y filtramos en cliente."""
    if mag_min >= 3.0:
        return {"magnitude": int(mag_min)}
    return {}


def fetch_csn_recientes(mag_min: float = 2.5) -> list[dict]:
    try:
        res = requests.get(CSN_RECENT_URL, params=_params_csn_mag(mag_min), timeout=20)
        if res.status_code != 200:
            return []
        data = res.json()
        filas = []
        for ev in data.get("events", []):
            row = _parse_evento_csn(ev)
            if row and row["magnitud"] >= mag_min:
                filas.append(row)
        return filas
    except requests.RequestException:
        return []


def fetch_csn_dia(fecha: datetime, mag_min: float = 2.5) -> list[dict]:
    yyyymmdd = fecha.strftime("%Y%m%d")
    url = CSN_HISTORIC_URL.format(yyyymmdd=yyyymmdd)
    try:
        res = requests.get(url, params=_params_csn_mag(mag_min), timeout=20)
        if res.status_code != 200:
            return []
        filas = []
        for ev in res.json().get("events", []):
            row = _parse_evento_csn(ev)
            if row and row["magnitud"] >= mag_min:
                filas.append(row)
        return filas
    except requests.RequestException:
        return []


def sync_csn_recientes(mag_min: float = 2.5) -> dict:
    filas = fetch_csn_recientes(mag_min=mag_min)
    n = catalogo.upsert_sismos(filas)
    catalogo.guardar_meta("ultimo_sync_csn", ahora_iso())
    return {"fuente": "CSN", "recibidos": len(filas), "guardados": n}


def sync_csn_ultimos_dias(dias: int = 7, mag_min: float = 2.5) -> dict:
    total_rec = 0
    total_guard = 0
    hoy = datetime.now(CHILE_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    for d in range(max(1, dias)):
        fecha = hoy - timedelta(days=d)
        filas = fetch_csn_dia(fecha, mag_min=mag_min)
        total_rec += len(filas)
        total_guard += catalogo.upsert_sismos(filas)
    catalogo.guardar_meta("ultimo_sync_csn", ahora_iso())
    return {
        "fuente": "CSN",
        "dias": dias,
        "recibidos": total_rec,
        "guardados": total_guard,
    }


def ahora_iso() -> str:
    return datetime.now(CHILE_TZ).strftime("%Y-%m-%d %H:%M:%S")


def sync_operativo(usgs_dias: int = 45, csn_dias: int = 14, mag_min: float = 2.5) -> dict:
    """Ciclo en producción: USGS ventana móvil + CSN recientes + días recientes."""
    r_usgs = sync_usgs_ultimos_dias(usgs_dias, mag_min=mag_min)
    r_csn_r = sync_csn_recientes(mag_min=mag_min)
    r_csn_d = sync_csn_ultimos_dias(csn_dias, mag_min=mag_min)
    catalogo.guardar_meta("ultimo_pipeline_sync", ahora_iso())
    return {
        "usgs": r_usgs,
        "csn_recientes": r_csn_r,
        "csn_dias": r_csn_d,
        "total_db": catalogo.resumen_db()["total"],
    }


def backfill_usgs(
    anio_desde: int = 2015,
    mes_desde: int = 1,
    mag_min: float = 2.5,
) -> dict:
    """Histórico USGS mes a mes hasta hoy."""
    hoy = datetime.now(CHILE_TZ)
    anio, mes = anio_desde, mes_desde
    total_rec = total_guard = meses = 0
    while (anio < hoy.year) or (anio == hoy.year and mes <= hoy.month):
        r = sync_usgs_mes(anio, mes, mag_min=mag_min)
        total_rec += r["recibidos"]
        total_guard += r["guardados"]
        meses += 1
        anio, mes = _mes_siguiente(anio, mes)
    catalogo.guardar_meta("ultimo_backfill_usgs", ahora_iso())
    return {
        "meses": meses,
        "recibidos": total_rec,
        "guardados": total_guard,
        "total_db": catalogo.resumen_db()["total"],
    }


def backfill_csn_dias(
    dias: int = 120,
    mag_min: float = 2.5,
    pausa_seg: float = 0.15,
) -> dict:
    """Histórico CSN día a día (api.xor.cl → sismologia.cl)."""
    import time

    total_rec = total_guard = 0
    hoy = datetime.now(CHILE_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    for d in range(max(1, dias)):
        fecha = hoy - timedelta(days=d)
        filas = fetch_csn_dia(fecha, mag_min=mag_min)
        total_rec += len(filas)
        total_guard += catalogo.upsert_sismos(filas)
        if pausa_seg > 0:
            time.sleep(pausa_seg)
    catalogo.guardar_meta("ultimo_backfill_csn", ahora_iso())
    return {
        "dias": dias,
        "recibidos": total_rec,
        "guardados": total_guard,
        "total_db": catalogo.resumen_db()["total"],
    }
