"""GNSS Chile — velocidades MIDAS (NGL) en marco Sudamérica (SA)."""
from __future__ import annotations

import json
import math
import re
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

import nazca_alertas as alertas

BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = BASE_DIR / ".nazca_cache"
CATALOGO_FILE = CACHE_DIR / "gnss_catalogo_chile.json"
VELOCIDADES_FILE = CACHE_DIR / "gnss_velocidades_sa.json"
SERIES_CACHE_DIR = CACHE_DIR / "gnss_series_sa"
CHILE_TZ = ZoneInfo("America/Santiago")

CHILE_BOUNDS = {"min_lat": -56.0, "max_lat": -17.0, "min_lon": -76.5, "max_lon": -66.0}
NGL_MIDAS_SA_URL = "https://geodesy.unr.edu/velocities/midas.SA.txt"
NGL_TENV3_SA_URL = "https://geodesy.unr.edu/gps_timeseries/IGS20/tenv3/SA/{sid}.SA.tenv3"
NGL_STATION_URL = "https://geodesy.unr.edu/NGLStationPages/stations/{sid}.sta"

VENTANA_RECENTE_ANIOS = 1.0
MIN_PUNTOS_SERIE = 30
UMBRAL_RATIO_ACELERACION = 1.35
UMBRAL_SUBSIDENCIA_EXTRA_MM_ANIO = 3.0

# Semillas verificadas (NGL station pages) — aceleran el primer arranque.
ESTACIONES_SEMILLA_CHILE = {
    "ANTF": {"lat": -23.70, "lon": -70.42},
    "IQQE": {"lat": -20.27, "lon": -70.13},
    "VALP": {"lat": -33.03, "lon": -71.63},
    "SANT": {"lat": -33.15, "lon": -70.67},
    "CONZ": {"lat": -36.84, "lon": -73.03},
    "PCMU": {"lat": -34.50, "lon": -71.96},
    "NAVI": {"lat": -33.95, "lon": -71.83},
    "RCSD": {"lat": -33.65, "lon": -71.61},
    "ILOC": {"lat": -34.95, "lon": -72.18},
    "MAUL": {"lat": -35.81, "lon": -70.82},
    "OSOR": {"lat": -40.60, "lon": -73.10},
    "SNJV": {"lat": -45.15, "lon": -72.06},
    "AEDA": {"lat": -20.55, "lon": -70.18},
    "ARCO": {"lat": -37.21, "lon": -73.23},
    "LSCH": {"lat": -29.91, "lon": -71.25},
    "BTO1": {"lat": -30.26, "lon": -71.49},
    "BN17": {"lat": -30.60, "lon": -71.20},
}

# Candidatos extra para ampliar catálogo (norte / centro).
CANDIDATOS_CATALOGO_CHILE = [
    "ATJN", "CALD", "LSCG", "LSCH", "COQU", "LAFL", "LAFS", "SERG", "OVAL",
    "MEJI", "PTLO", "CHLB", "CHAI", "B914", "ALT1", "ANG8", "ANTC",
]

# Preferencia GNSS por nodo CORE NAZCA (4 letras IGS/NGL).
NODOS_GNSS_PREFERIDOS = {
    "Arica / Iquique (85400)": ["IQQE"],
    "Antofagasta / Taltal (85442)": ["ANTF", "IQQE"],
    "Coquimbo / Illapel (85540)": ["LSCH", "BTO1", "BN17", "CMPN", "RCSD"],
    "Valparaíso / San Antonio (85574)": ["VALP", "RCSD", "SANT"],
    "Concepción / Lebu (85680)": ["CONZ", "ILOC", "PCMU"],
    "Valdivia / Puerto Montt (85799)": ["OSOR", "CONZ"],
    "Pto. Aysén / Taitao (85850)": ["SNJV", "OSOR"],
}


def ahora_chile() -> datetime:
    return datetime.now(CHILE_TZ).replace(tzinfo=None)


def _ssl_context():
    return ssl.create_default_context()


def _descargar_texto(url: str, timeout: int = 45) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "NAZCA-GNSS/1.0"})
    with urllib.request.urlopen(req, context=_ssl_context(), timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _parsear_midas_sa(texto: str) -> dict[str, dict]:
    estaciones: dict[str, dict] = {}
    for line in texto.splitlines():
        if not line.strip():
            continue
        partes = line.split()
        if len(partes) < 17 or partes[1] != "MIDAS5":
            continue
        sid = partes[0].upper()
        vn = float(partes[8]) * 1000.0
        ve = float(partes[9]) * 1000.0
        vu = float(partes[10]) * 1000.0
        estaciones[sid] = {
            "vn_mm_anio": round(vn, 2),
            "ve_mm_anio": round(ve, 2),
            "vu_mm_anio": round(vu, 2),
            "horiz_mm_anio": round(math.hypot(vn, ve), 2),
            "total_mm_anio": round(math.hypot(vn, ve, vu), 2),
            "t_inicio": float(partes[2]),
            "t_fin": float(partes[3]),
        }
    return estaciones


def _coordenadas_estacion(sid: str) -> tuple[float, float] | None:
    sid = sid.upper()
    if sid in ESTACIONES_SEMILLA_CHILE:
        s = ESTACIONES_SEMILLA_CHILE[sid]
        return s["lat"], s["lon"]
    try:
        html = _descargar_texto(NGL_STATION_URL.format(sid=sid), timeout=12)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        return None
    lat = re.search(r"Latitude:\s*(-?[\d.]+)", html)
    lon = re.search(r"Longitude:\s*(-?[\d.]+)", html)
    if not lat or not lon:
        return None
    return float(lat.group(1)), float(lon.group(1))


def _en_chile(lat: float, lon: float) -> bool:
    b = CHILE_BOUNDS
    return b["min_lat"] <= lat <= b["max_lat"] and b["min_lon"] <= lon <= b["max_lon"]


def _leer_json_cache(ruta: Path) -> dict | None:
    if not ruta.exists():
        return None
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _guardar_json_cache(ruta: Path, payload: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def obtener_velocidades_sa(ttl_seg: int = 86400, forzar: bool = False) -> tuple[dict[str, dict], str]:
    cache = _leer_json_cache(VELOCIDADES_FILE)
    if cache and not forzar:
        expira = datetime.fromisoformat(cache["expira"])
        if ahora_chile() <= expira:
            return cache["estaciones"], cache.get("consultado", "")

    texto = _descargar_texto(NGL_MIDAS_SA_URL)
    estaciones = _parsear_midas_sa(texto)
    consultado = ahora_chile().isoformat(timespec="seconds")
    _guardar_json_cache(
        VELOCIDADES_FILE,
        {
            "expira": (ahora_chile() + timedelta(seconds=ttl_seg)).isoformat(timespec="seconds"),
            "consultado": consultado,
            "fuente": NGL_MIDAS_SA_URL,
            "estaciones": estaciones,
        },
    )
    return estaciones, consultado


def actualizar_catalogo_chile(
    ttl_seg: int = 604800,
    forzar: bool = False,
    max_nuevas: int = 120,
) -> tuple[list[dict], dict]:
    cache = _leer_json_cache(CATALOGO_FILE)
    catalogo_map: dict[str, dict] = {}
    if cache and not forzar:
        expira = datetime.fromisoformat(cache["expira"])
        if ahora_chile() <= expira:
            return cache["estaciones"], cache

    if cache:
        for est in cache.get("estaciones", []):
            catalogo_map[est["id"]] = est

    velocidades, vel_consultado = obtener_velocidades_sa(ttl_seg=min(ttl_seg, 86400), forzar=forzar)
    consultadas = 0

    for sid in CANDIDATOS_CATALOGO_CHILE:
        if sid in catalogo_map or sid not in velocidades:
            continue
        if consultadas >= max_nuevas:
            break
        coords = _coordenadas_estacion(sid)
        consultadas += 1
        if coords is None:
            time.sleep(0.12)
            continue
        lat, lon = coords
        if not _en_chile(lat, lon):
            time.sleep(0.12)
            continue
        v = velocidades[sid]
        catalogo_map[sid] = {"id": sid, "lat": round(lat, 4), "lon": round(lon, 4), **v}
        time.sleep(0.12)

    for sid in sorted(velocidades):
        if sid in catalogo_map:
            v = velocidades[sid]
            catalogo_map[sid].update(
                {
                    "vn_mm_anio": v["vn_mm_anio"],
                    "ve_mm_anio": v["ve_mm_anio"],
                    "vu_mm_anio": v["vu_mm_anio"],
                    "horiz_mm_anio": v["horiz_mm_anio"],
                    "total_mm_anio": v["total_mm_anio"],
                }
            )
            continue
        if consultadas >= max_nuevas:
            continue
        coords = _coordenadas_estacion(sid)
        consultadas += 1
        if coords is None:
            time.sleep(0.15)
            continue
        lat, lon = coords
        if not _en_chile(lat, lon):
            time.sleep(0.15)
            continue
        v = velocidades[sid]
        catalogo_map[sid] = {
            "id": sid,
            "lat": round(lat, 4),
            "lon": round(lon, 4),
            **v,
        }
        time.sleep(0.15)

    catalogo = list(catalogo_map.values())
    meta = {
        "expira": (ahora_chile() + timedelta(seconds=ttl_seg)).isoformat(timespec="seconds"),
        "consultado": ahora_chile().isoformat(timespec="seconds"),
        "velocidades_consultado": vel_consultado,
        "fuente": NGL_MIDAS_SA_URL,
        "consultadas": consultadas,
        "total": len(catalogo),
    }
    _guardar_json_cache(CATALOGO_FILE, {"estaciones": catalogo, **meta})
    return catalogo, meta


def _fusionar_catalogo(catalogo: list[dict]) -> list[dict]:
    por_id = {e["id"]: e for e in catalogo}
    for semilla in _catalogo_semilla_con_velocidades():
        por_id[semilla["id"]] = semilla
    return list(por_id.values())


def cargar_catalogo_chile() -> list[dict]:
    cache = _leer_json_cache(CATALOGO_FILE)
    if cache and cache.get("estaciones"):
        expira = datetime.fromisoformat(cache["expira"])
        if ahora_chile() <= expira:
            return _fusionar_catalogo(cache["estaciones"])

    catalogo, _ = actualizar_catalogo_chile(max_nuevas=80)
    return _fusionar_catalogo(catalogo if len(catalogo) >= 5 else _catalogo_semilla_con_velocidades())


def _catalogo_semilla_con_velocidades() -> list[dict]:
    velocidades, _ = obtener_velocidades_sa()
    salida = []
    for sid, coords in ESTACIONES_SEMILLA_CHILE.items():
        if sid not in velocidades:
            continue
        v = velocidades[sid]
        salida.append({"id": sid, "lat": coords["lat"], "lon": coords["lon"], **v})
    return salida


def distancia_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radio = 6371.0
    lat1r, lon1r, lat2r, lon2r = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2r - lat1r
    dlon = lon2r - lon1r
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1r) * np.cos(lat2r) * np.sin(dlon / 2) ** 2
    return float(2 * radio * np.arcsin(np.sqrt(a)))


def estacion_mas_cercana(
    lat: float,
    lon: float,
    catalogo: list[dict],
    preferidas: list[str] | None = None,
    max_dist_preferida_km: float = 280.0,
) -> dict | None:
    if not catalogo:
        return None
    if preferidas:
        by_id = {e["id"]: e for e in catalogo}
        for sid in preferidas:
            if sid not in by_id:
                continue
            est = dict(by_id[sid])
            dist = distancia_km(lat, lon, est["lat"], est["lon"])
            if dist <= max_dist_preferida_km:
                est["dist_km"] = round(dist, 1)
                est["match"] = "preferida"
                return est
    mejor = None
    mejor_dist = float("inf")
    for est in catalogo:
        d = distancia_km(lat, lon, est["lat"], est["lon"])
        if d < mejor_dist:
            mejor_dist = d
            mejor = est
    if mejor is None:
        return None
    out = dict(mejor)
    out["dist_km"] = round(mejor_dist, 1)
    out["match"] = "cercana"
    return out


def _parsear_tenv3_sa(texto: str) -> list[tuple[float, float, float, float]]:
    filas: list[tuple[float, float, float, float]] = []
    for line in texto.splitlines():
        if line.startswith("site") or not line.strip():
            continue
        partes = line.split()
        if len(partes) < 13:
            continue
        try:
            dec_yr = float(partes[2])
            east = float(partes[7]) + float(partes[8])
            north = float(partes[9]) + float(partes[10])
            up = float(partes[11]) + float(partes[12])
        except ValueError:
            continue
        filas.append((dec_yr, east, north, up))
    filas.sort(key=lambda x: x[0])
    return filas


def _pendiente_mm_anio(valores_t: np.ndarray, valores_y: np.ndarray) -> float:
    if len(valores_t) < 5:
        return 0.0
    coef = np.polyfit(valores_t, valores_y, 1)
    return float(coef[0] * 1000.0)


def _ruta_cache_serie(sid: str) -> Path:
    SERIES_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return SERIES_CACHE_DIR / f"{sid.upper()}.json"


def obtener_serie_sa(sid: str, ttl_seg: int = 86400, forzar: bool = False) -> list[tuple[float, float, float, float]]:
    sid = sid.upper()
    ruta = _ruta_cache_serie(sid)
    if ruta.exists() and not forzar:
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
            expira = datetime.fromisoformat(datos["expira"])
            if ahora_chile() <= expira:
                return [tuple(x) for x in datos["filas"]]
        except (json.JSONDecodeError, KeyError, ValueError, TypeError):
            pass
    try:
        texto = _descargar_texto(NGL_TENV3_SA_URL.format(sid=sid), timeout=60)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        return []
    filas = _parsear_tenv3_sa(texto)
    if filas:
        ruta.write_text(
            json.dumps(
                {
                    "expira": (ahora_chile() + timedelta(seconds=ttl_seg)).isoformat(timespec="seconds"),
                    "consultado": ahora_chile().isoformat(timespec="seconds"),
                    "fuente": NGL_TENV3_SA_URL.format(sid=sid),
                    "filas": filas,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    return filas


def analizar_aceleracion_reciente(
    sid: str,
    horiz_base: float,
    vert_base: float,
    ttl_seg: int = 86400,
) -> dict | None:
    filas = obtener_serie_sa(sid, ttl_seg=ttl_seg)
    if len(filas) < MIN_PUNTOS_SERIE:
        return None
    t_max = filas[-1][0]
    t_min = t_max - VENTANA_RECENTE_ANIOS
    recientes = [f for f in filas if f[0] >= t_min]
    if len(recientes) < MIN_PUNTOS_SERIE:
        return None

    t = np.array([f[0] for f in recientes], dtype=float)
    e = np.array([f[1] for f in recientes], dtype=float)
    n = np.array([f[2] for f in recientes], dtype=float)
    u = np.array([f[3] for f in recientes], dtype=float)
    ve = _pendiente_mm_anio(t, e)
    vn = _pendiente_mm_anio(t, n)
    vu = _pendiente_mm_anio(t, u)
    horiz_rec = math.hypot(vn, ve)

    base_h = max(horiz_base, 3.0)
    ratio_h = horiz_rec / base_h
    extra_subsidencia = vert_base - vu
    acelerando_h = ratio_h >= UMBRAL_RATIO_ACELERACION
    acelerando_v = extra_subsidencia >= UMBRAL_SUBSIDENCIA_EXTRA_MM_ANIO
    acelerando = acelerando_h or acelerando_v

    return {
        "ventana_anios": VENTANA_RECENTE_ANIOS,
        "puntos": len(recientes),
        "horiz_reciente_mm_anio": round(horiz_rec, 2),
        "vert_reciente_mm_anio": round(vu, 2),
        "ratio_horizontal": round(ratio_h, 2),
        "extra_subsidencia_mm_anio": round(extra_subsidencia, 2),
        "acelerando": acelerando,
        "acelerando_horizontal": acelerando_h,
        "acelerando_vertical": acelerando_v,
    }


def deformacion_a_indice(
    horiz_mm_anio: float,
    vert_mm_anio: float,
    aceleracion: dict | None = None,
) -> float:
    """Mapea deformación GNSS (mm/año, marco SA) a índice 0–100 tipo InSAR NAZCA."""
    if aceleracion and aceleracion.get("acelerando"):
        horiz_mm_anio = max(horiz_mm_anio, aceleracion.get("horiz_reciente_mm_anio", horiz_mm_anio))
        vert_mm_anio = min(vert_mm_anio, aceleracion.get("vert_reciente_mm_anio", vert_mm_anio))

    hacia_fosa = max(0.0, horiz_mm_anio)
    subsidencia = max(0.0, -vert_mm_anio)
    carga = hacia_fosa * 0.55 + subsidencia * 1.15 + abs(vert_mm_anio) * 0.25
    indice = min(98.0, max(12.0, (carga / 32.0) * 85.0))

    if aceleracion and aceleracion.get("acelerando"):
        ratio = float(aceleracion.get("ratio_horizontal", 1.0))
        boost = min(18.0, max(0.0, (ratio - 1.0) * 22.0))
        if aceleracion.get("acelerando_vertical"):
            boost = min(18.0, boost + 6.0)
        indice = min(98.0, indice + boost)

    return round(indice, 1)


def lectura_gnss_nodo(
    nombre_nodo: str,
    lat: float,
    lon: float,
    ttl_seg: int = 86400,
) -> dict | None:
    catalogo = cargar_catalogo_chile()
    preferidas = NODOS_GNSS_PREFERIDOS.get(nombre_nodo, [])
    est = estacion_mas_cercana(lat, lon, catalogo, preferidas=preferidas)
    if est is None:
        return None

    aceleracion = None
    try:
        aceleracion = analizar_aceleracion_reciente(
            est["id"], est["horiz_mm_anio"], est["vu_mm_anio"], ttl_seg=ttl_seg
        )
    except Exception:
        aceleracion = None

    indice = deformacion_a_indice(est["horiz_mm_anio"], est["vu_mm_anio"], aceleracion)
    subsidencia = est["vu_mm_anio"] < -2.0
    if aceleracion and aceleracion.get("vert_reciente_mm_anio", 0) < -2.0:
        subsidencia = True
    carga_alta = est["horiz_mm_anio"] >= 18.0 or subsidencia
    if aceleracion and aceleracion.get("acelerando"):
        carga_alta = True

    dist_km = est.get("dist_km")
    gnss_confiable = alertas.gnss_es_confiable({"dist_km": dist_km})
    origen = f"GNSS {est['id']} ({est.get('match', 'cercana')})"
    if aceleracion and aceleracion.get("acelerando"):
        origen += " · aceleración reciente"

    return {
        "estacion_gnss": est["id"],
        "lat_gnss": est["lat"],
        "lon_gnss": est["lon"],
        "dist_km": dist_km,
        "match": est.get("match", "cercana"),
        "gnss_confiable": gnss_confiable,
        "vn_mm_anio": est["vn_mm_anio"],
        "ve_mm_anio": est["ve_mm_anio"],
        "vu_mm_anio": est["vu_mm_anio"],
        "horiz_mm_anio": est["horiz_mm_anio"],
        "total_mm_anio": est["total_mm_anio"],
        "insar_pct": indice,
        "carga_tectonica": carga_alta,
        "subsidencia": subsidencia,
        "aceleracion": aceleracion,
        "marco": "SA (Sudamérica, NGL MIDAS + serie 1A)",
        "fuente": "GNSS NGL",
        "origen": origen,
    }


def resumen_nodos_core(estaciones_config: dict, ttl_seg: int = 86400) -> list[dict]:
    filas = []
    for nombre, cfg in estaciones_config.items():
        lectura = lectura_gnss_nodo(nombre, cfg["lat"], cfg["lon"], ttl_seg=ttl_seg)
        filas.append({"nodo": nombre, "lectura": lectura})
    return filas
