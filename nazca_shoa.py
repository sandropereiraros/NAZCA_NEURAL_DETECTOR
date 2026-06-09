"""Marea Chile — mareógrafos IOC UNESCO (API pública, sin key)."""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import requests

BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = BASE_DIR / ".nazca_cache"
CHILE_TZ = ZoneInfo("America/Santiago")

IOC_DATA_URL = "https://www.ioc-sealevelmonitoring.org/service.php?query=data&code={codigo}"
IOC_STATION_URL = "https://www.ioc-sealevelmonitoring.org/service.php?query=station&code={codigo}"

PERIODO_MAREA_PTS = 360
VENTANA_RESIDUAL_PTS = 15
SIGMA_GATE = 1.2
SPIKE_SIGMA_MULT = 3.0
SENSOR_PREFERIDO = "rad"
TTL_SEG_DEFAULT = 1800

NODOS_IOC = {
    "Arica / Iquique (85400)": "aric",
    "Antofagasta / Taltal (85442)": "anto",
    "Coquimbo / Illapel (85540)": "coqu",
    "Valparaíso / San Antonio (85574)": "sano",
    "Concepción / Lebu (85680)": "lebu",
    "Valdivia / Puerto Montt (85799)": "pmon",
    "Pto. Aysén / Taitao (85850)": "cstr",
}

COORDS_IOC = {
    "aric": (-18.4758, -70.3232),
    "anto": (-23.6542, -70.4046),
    "coqu": (-29.9501, -71.3353),
    "sano": (-33.5816, -71.6182),
    "lebu": (-37.5941, -73.6641),
    "pmon": (-41.4849, -72.9609),
    "cstr": (-42.4809, -73.7582),
}


def ahora_chile() -> datetime:
    return datetime.now(CHILE_TZ).replace(tzinfo=None)


def _cache_path(codigo: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"shoa_ioc_{codigo}.json"


def _leer_cache(codigo: str) -> dict | None:
    ruta = _cache_path(codigo)
    if not ruta.exists():
        return None
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        if ahora_chile() <= datetime.fromisoformat(datos["expira"]):
            return datos["payload"]
    except (json.JSONDecodeError, KeyError, ValueError, OSError):
        pass
    return None


def _guardar_cache(codigo: str, payload: dict, ttl_seg: int) -> None:
    _cache_path(codigo).write_text(
        json.dumps(
            {
                "expira": (ahora_chile() + timedelta(seconds=ttl_seg)).isoformat(timespec="seconds"),
                "consultado": ahora_chile().strftime("%Y-%m-%d %H:%M:%S"),
                "payload": payload,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def distancia_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radio = 6371.0
    lat1r, lon1r, lat2r, lon2r = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2r - lat1r
    dlon = lon2r - lon1r
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1r) * math.cos(lat2r) * math.sin(dlon / 2) ** 2
    return float(2 * radio * math.asin(math.sqrt(a)))


def _parse_stime(texto: str) -> datetime | None:
    try:
        return datetime.strptime(texto, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _filtrar_sensor(puntos: list[dict], preferido: str = SENSOR_PREFERIDO) -> list[dict]:
    if not puntos:
        return []
    sensores = {p.get("sensor") for p in puntos if p.get("sensor")}
    sensor = preferido if preferido in sensores else sorted(sensores)[0] if sensores else ""
    filtrados = [p for p in puntos if p.get("sensor") == sensor and p.get("slevel") is not None]
    filtrados.sort(key=lambda p: p.get("stime", ""))
    return filtrados


def _fetch_ioc_datos(codigo: str) -> list[dict] | None:
    try:
        res = requests.get(IOC_DATA_URL.format(codigo=codigo), timeout=20)
        if res.status_code != 200:
            return None
        datos = res.json()
        if not isinstance(datos, list) or len(datos) < 30:
            return None
        return datos
    except (requests.RequestException, ValueError, TypeError):
        return None


def _media_movil(niveles: np.ndarray, periodo: int) -> np.ndarray:
    if len(niveles) < periodo:
        return niveles.copy()
    kernel = np.ones(periodo) / periodo
    pad = periodo // 2
    yp = np.pad(niveles, (pad, pad), mode="edge")
    ma = np.convolve(yp, kernel, mode="valid")
    return ma[: len(niveles)]


def _calcular_metricas(puntos: list[dict]) -> dict | None:
    serie = _filtrar_sensor(puntos)
    if len(serie) < 40:
        return None

    niveles_m = np.array([float(p["slevel"]) for p in serie], dtype=float)
    periodo = min(PERIODO_MAREA_PTS, max(60, len(niveles_m) // 3))
    media_marea = _media_movil(niveles_m, periodo)
    residual_cm = (niveles_m - media_marea) * 100.0

    ventana_std = residual_cm[-min(len(residual_cm), PERIODO_MAREA_PTS * 2) :]
    sigma = float(np.std(ventana_std)) if len(ventana_std) > 10 else 5.0
    sigma = max(sigma, 2.0)

    suave = float(np.mean(np.abs(residual_cm[-VENTANA_RESIDUAL_PTS:])))
    anomalia_cm = float(residual_cm[-1])
    exceso = max(0.0, suave - SIGMA_GATE * sigma)

    idx_tasa = max(0, len(niveles_m) - VENTANA_RESIDUAL_PTS)
    t0 = _parse_stime(serie[idx_tasa].get("stime", ""))
    t1 = _parse_stime(serie[-1].get("stime", ""))
    delta_h = max((t1 - t0).total_seconds() / 3600.0, 0.25) if t0 and t1 else 0.5
    tasa_cm_h = float(((niveles_m[-1] - niveles_m[idx_tasa]) / delta_h) * 100.0)

    spike = abs(float(residual_cm[-1] - residual_cm[idx_tasa]))
    if spike > SPIKE_SIGMA_MULT * sigma:
        exceso = max(exceso, min(150.0, spike - SIGMA_GATE * sigma))

    shoa_cm = round(min(150.0, exceso), 2)
    actual_m = float(niveles_m[-1])
    media_ref_m = float(media_marea[-1])

    return {
        "shoa_cm": shoa_cm,
        "anomalia_cm": round(anomalia_cm, 2),
        "tasa_cm_h": round(tasa_cm_h, 2),
        "nivel_m": round(actual_m, 3),
        "media_6h_m": round(media_ref_m, 3),
        "sigma_residual_cm": round(sigma, 2),
        "sensor": serie[-1].get("sensor", ""),
        "ultima_lectura": serie[-1].get("stime", ""),
        "puntos": len(serie),
    }


def _payload_shoa(
    estacion: str,
    codigo: str,
    lat: float,
    lon: float,
    metricas: dict,
    consultado: str,
) -> dict:
    ioc_lat, ioc_lon = COORDS_IOC.get(codigo, (lat, lon))
    dist = round(distancia_km(lat, lon, ioc_lat, ioc_lon), 1)
    return {
        "shoa_real": True,
        "shoa_cm": metricas["shoa_cm"],
        "anomalia_cm": metricas["anomalia_cm"],
        "tasa_cm_h": metricas["tasa_cm_h"],
        "nivel_m": metricas["nivel_m"],
        "media_6h_m": metricas["media_6h_m"],
        "codigo_ioc": codigo,
        "estacion_ioc": codigo.upper(),
        "dist_km": dist,
        "sensor": metricas["sensor"],
        "ultima_lectura": metricas["ultima_lectura"],
        "puntos": metricas["puntos"],
        "origen": f"IOC UNESCO ({codigo})",
        "consultado": consultado,
        "nodo": estacion,
    }


def lectura_marea_nodo(
    estacion: str,
    lat: float,
    lon: float,
    ttl_seg: int = TTL_SEG_DEFAULT,
) -> dict | None:
    codigo = NODOS_IOC.get(estacion)
    if not codigo:
        return None

    cache = _leer_cache(codigo)
    if cache:
        return cache

    puntos = _fetch_ioc_datos(codigo)
    if not puntos:
        return None

    metricas = _calcular_metricas(puntos)
    if not metricas:
        return None

    consultado = ahora_chile().strftime("%Y-%m-%d %H:%M:%S")
    payload = _payload_shoa(estacion, codigo, lat, lon, metricas, consultado)
    _guardar_cache(codigo, payload, ttl_seg)
    return payload
