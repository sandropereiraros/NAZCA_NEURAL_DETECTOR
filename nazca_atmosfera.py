"""Atmósfera Chile — Open-Meteo (gratis), OpenWeatherMap y MeteoChile (opcional)."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

import nazca_alertas as alertas

BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = BASE_DIR / ".nazca_cache"
EMA_CACHE_FILE = CACHE_DIR / "meteochile_ema_estaciones.json"
CHILE_TZ = ZoneInfo("America/Santiago")

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
OPENWEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"
METEOCHILE_EMA_URL = "https://climatologia.meteochile.gob.cl/application/servicios/getEstacionesRedEma"
METEOCHILE_DATOS_URL = (
    "https://climatologia.meteochile.gob.cl/application/servicios/getDatosRecientesEma/{codigo}"
)


def ahora_chile() -> datetime:
    return datetime.now(CHILE_TZ).replace(tzinfo=None)


def _cache_path(clave: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"atmos_{clave}.json"


def _leer_cache(clave: str) -> dict | None:
    ruta = _cache_path(clave)
    if not ruta.exists():
        return None
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        if ahora_chile() <= datetime.fromisoformat(datos["expira"]):
            return datos["payload"]
    except (json.JSONDecodeError, KeyError, ValueError, OSError):
        pass
    return None


def _guardar_cache(clave: str, payload: dict, ttl_seg: int) -> None:
    _cache_path(clave).write_text(
        json.dumps(
            {
                "expira": (ahora_chile() + timedelta(seconds=ttl_seg)).isoformat(timespec="seconds"),
                "payload": payload,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _parse_num(texto) -> float | None:
    if texto is None:
        return None
    limpio = re.sub(r"[^\d.\-]", "", str(texto))
    try:
        return float(limpio)
    except ValueError:
        return None


def _indice_termico(temp_c: float, humedad: float, presion: float, baseline_pres: float) -> float:
    delta_t = abs(temp_c - 18.0) / 12.0
    delta_p = abs(presion - baseline_pres) / 8.0
    hum = max(0.0, (humedad - 55.0) / 45.0)
    return round(min(5.0, delta_t * 1.6 + delta_p * 1.2 + hum * 0.8), 2)


def _payload_atmos(
    presion: float,
    temp_c: float,
    humedad: float,
    precip: float,
    baseline_pres: float,
    origen: str,
    fuente: str,
    extra: dict | None = None,
) -> dict:
    payload = {
        "presion_hpa": round(presion, 1),
        "temp_c": round(temp_c, 1),
        "humedad_pct": round(humedad, 1),
        "precip_mm": round(precip, 2),
        "termico": _indice_termico(temp_c, humedad, presion, baseline_pres),
        "atmos_real": True,
        "origen": origen,
        "fuente": fuente,
    }
    if extra:
        payload.update(extra)
    return payload


def _open_meteo(lat: float, lon: float, baseline_pres: float) -> dict | None:
    try:
        resp = requests.get(
            OPEN_METEO_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,surface_pressure,precipitation",
                "timezone": "America/Santiago",
            },
            timeout=20,
        )
        resp.raise_for_status()
        cur = resp.json().get("current") or {}
        presion = float(cur.get("surface_pressure", 0))
        if presion <= 800:
            return None
        return _payload_atmos(
            presion=presion,
            temp_c=float(cur.get("temperature_2m", 15.0)),
            humedad=float(cur.get("relative_humidity_2m", 50.0)),
            precip=float(cur.get("precipitation", 0.0)),
            baseline_pres=baseline_pres,
            origen="Open-Meteo",
            fuente=OPEN_METEO_URL,
        )
    except (requests.RequestException, ValueError, TypeError, KeyError):
        return None


def _openweather(lat: float, lon: float, api_key: str, baseline_pres: float) -> dict | None:
    if not api_key:
        return None
    try:
        resp = requests.get(
            OPENWEATHER_URL,
            params={"lat": lat, "lon": lon, "appid": api_key, "units": "metric"},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        main = data.get("main") or {}
        presion = float(main.get("pressure", 0))
        if presion <= 800:
            return None
        rain = data.get("rain") or {}
        return _payload_atmos(
            presion=presion,
            temp_c=float(main.get("temp", 15.0)),
            humedad=float(main.get("humidity", 50.0)),
            precip=float(rain.get("1h", 0.0) or 0.0),
            baseline_pres=baseline_pres,
            origen="OpenWeatherMap",
            fuente=OPENWEATHER_URL,
        )
    except (requests.RequestException, ValueError, TypeError, KeyError):
        return None


def _cargar_ema_meteochile(usuario: str, token: str, ttl_seg: int = 604800) -> list[dict]:
    cache = _leer_cache("ema_lista") if EMA_CACHE_FILE.exists() else None
    if cache:
        return cache.get("estaciones", [])
    try:
        resp = requests.get(
            METEOCHILE_EMA_URL,
            params={"usuario": usuario, "token": token},
            timeout=30,
            verify=False,
        )
        resp.raise_for_status()
        estaciones = resp.json().get("datosEstacion") or []
        payload = {"estaciones": estaciones, "consultado": ahora_chile().isoformat(timespec="seconds")}
        EMA_CACHE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        _guardar_cache("ema_lista", payload, ttl_seg)
        return estaciones
    except (requests.RequestException, ValueError, TypeError, KeyError, json.JSONDecodeError):
        if EMA_CACHE_FILE.exists():
            try:
                return json.loads(EMA_CACHE_FILE.read_text(encoding="utf-8")).get("estaciones", [])
            except json.JSONDecodeError:
                pass
        return []


def _ema_por_omm(estaciones: list[dict], codigo_omm: str) -> dict | None:
    codigo_omm = str(codigo_omm).strip()
    for est in estaciones:
        if str(est.get("codigoOMM", "")).strip() == codigo_omm:
            return est
    return None


def _meteochile_reciente(
    codigo_nacional: str,
    usuario: str,
    token: str,
    baseline_pres: float,
) -> dict | None:
    try:
        url = METEOCHILE_DATOS_URL.format(codigo=codigo_nacional)
        resp = requests.get(url, params={"usuario": usuario, "token": token}, timeout=25, verify=False)
        resp.raise_for_status()
        data = resp.json()
        datos = (data.get("datosEstaciones") or {}).get("datos") or []
        if not datos:
            return None
        ultimo = datos[-1]
        presion = _parse_num(ultimo.get("presionNivelDelMar")) or _parse_num(ultimo.get("presionEstacion"))
        temp = _parse_num(ultimo.get("temperatura"))
        hum = _parse_num(ultimo.get("humedadRelativa"))
        if presion is None or temp is None:
            return None
        precip = _parse_num(ultimo.get("aguaCaidaDelDia")) or 0.0
        est = (data.get("datosEstaciones") or {}).get("estacion") or {}
        return _payload_atmos(
            presion=presion,
            temp_c=temp,
            humedad=hum or 50.0,
            precip=precip or 0.0,
            baseline_pres=baseline_pres,
            origen=f"MeteoChile {est.get('nombreEstacion', codigo_nacional)}",
            fuente=url,
            extra={
                "codigo_meteochile": codigo_nacional,
                "codigo_omm": est.get("codigoOMM"),
                "estacion_meteochile": est.get("nombreEstacion"),
            },
        )
    except (requests.RequestException, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def lectura_atmosfera(
    lat: float,
    lon: float,
    baseline_pres: float = 1012.0,
    codigo_omm: str | None = None,
    secrets: dict | None = None,
    ttl_seg: int = 3600,
) -> dict | None:
    clave = f"{round(lat, 2)}_{round(lon, 2)}_{ttl_seg}"
    cache = _leer_cache(clave)
    if cache:
        return cache

    secrets = secrets or alertas.leer_secrets_toml()
    usuario = alertas.obtener_secret("METEOCHILE_USUARIO", secrets) or os.environ.get("METEOCHILE_USUARIO", "")
    token = alertas.obtener_secret("METEOCHILE_TOKEN", secrets) or os.environ.get("METEOCHILE_TOKEN", "")
    owm_key = alertas.obtener_secret("OPENWEATHER_API_KEY", secrets) or os.environ.get("OPENWEATHER_API_KEY", "")

    lectura = None
    if usuario and token and codigo_omm:
        estaciones = _cargar_ema_meteochile(usuario, token)
        ema = _ema_por_omm(estaciones, codigo_omm)
        if ema:
            lectura = _meteochile_reciente(str(ema.get("codigoNacional")), usuario, token, baseline_pres)

    if lectura is None and owm_key:
        lectura = _openweather(lat, lon, owm_key, baseline_pres)

    if lectura is None:
        lectura = _open_meteo(lat, lon, baseline_pres)

    if lectura:
        _guardar_cache(clave, lectura, ttl_seg)
    return lectura
