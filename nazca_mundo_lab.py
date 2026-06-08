"""
NAZCA MUNDO LAB — módulo desmontable de calibración multi-placa (solo admin).
Poner MODULO_MUNDO_ACTIVO = False o eliminar este archivo para desactivar sin afectar Chile.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
import streamlit as st

try:
    import nazca_mapa_tectonico as mapa_tect
except ImportError:
    mapa_tect = None

# ==============================================================================
# INTERRUPTOR GLOBAL — False = Chile sigue igual, pestaña MUNDO no aparece
# ==============================================================================
MODULO_MUNDO_ACTIVO = True
MUNDO_LAB_VERSION = "v4.0-sin-chile"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE_DIR, ".nazca_cache")
EVIDENCIA_MUNDO_CSV = os.path.join(BASE_DIR, "nazca_evidencia_mundo.csv")
CHILE_TZ = ZoneInfo("America/Santiago")
CHILE_TZ_LABEL = "Chile continental (UTC-4)"
MAG_MIN_GLOBAL = 4.5
VENTANA_DIAS = 14

PESOS_POR_TIPO = {
    "subduccion": {"SISMO_BVAL": 0.62, "INSAR": 0.18, "CONDUCT": 0.10, "SHOA": 0.06, "ATMOS": 0.01},
    "transformante": {"SISMO_BVAL": 0.58, "INSAR": 0.12, "CONDUCT": 0.12, "SHOA": 0.05, "ATMOS": 0.13},
    "divergente": {"SISMO_BVAL": 0.55, "INSAR": 0.20, "CONDUCT": 0.15, "SHOA": 0.02, "ATMOS": 0.08},
    "colision": {"SISMO_BVAL": 0.50, "INSAR": 0.25, "CONDUCT": 0.12, "SHOA": 0.03, "ATMOS": 0.10},
    "complejo": {"SISMO_BVAL": 0.60, "INSAR": 0.15, "CONDUCT": 0.12, "SHOA": 0.08, "ATMOS": 0.05},
}

TIPO_FALLA_INFO = {
    "subduccion": "Enjambres, coupling interplaca, potencial tsunamigenico.",
    "transformante": "Secuencias repetitivas, tramos locked vs creeping.",
    "divergente": "Sismicidad superficial, enjambres y actividad volcánica.",
    "colision": "Sismos profundos, acumulación lenta de esfuerzo.",
    "complejo": "Múltiples placas; patrones locales, no transferir desde Chile.",
}

TELEMETRIA_POR_TIPO = {
    "subduccion": {"insar_base": 40.0, "insar_gain": 3.8, "shoa_scale": 1.4, "cond_amp": 0.75, "mag_enjambre": 4.8},
    "transformante": {"insar_base": 34.0, "insar_gain": 2.6, "shoa_scale": 0.4, "cond_amp": 0.55, "mag_enjambre": 4.2},
    "divergente": {"insar_base": 30.0, "insar_gain": 2.2, "shoa_scale": 0.2, "cond_amp": 0.45, "mag_enjambre": 3.8},
    "colision": {"insar_base": 38.0, "insar_gain": 3.2, "shoa_scale": 0.3, "cond_amp": 0.65, "mag_enjambre": 4.0},
    "complejo": {"insar_base": 36.0, "insar_gain": 3.0, "shoa_scale": 0.9, "cond_amp": 0.60, "mag_enjambre": 4.5},
}

# Sin Chile — el módulo nacional ya cubre Nazca/Sudamérica.
NODOS_MUNDO_CONFIG = {
    "Perú · Lima-Nazca (subducción)": {
        "tipo_falla": "subduccion", "pais": "Perú", "lat": -12.05, "lon": -77.05,
        "radio_km": 400, "umbral_critico": 74.0, "mag_min_local": 4.0,
        "baseline_cond": 3.9, "sigma_cond": 0.18, "baseline_pres": 1011.0,
    },
    "Japón · Tohoku (subducción)": {
        "tipo_falla": "subduccion", "pais": "Japón", "lat": 38.25, "lon": 142.35,
        "radio_km": 450, "umbral_critico": 76.0, "mag_min_local": 4.0,
        "baseline_cond": 4.2, "sigma_cond": 0.14, "baseline_pres": 1012.5,
    },
    "Indonesia · Sumatra (subducción)": {
        "tipo_falla": "subduccion", "pais": "Indonesia", "lat": 3.30, "lon": 95.85,
        "radio_km": 480, "umbral_critico": 77.0, "mag_min_local": 4.2,
        "baseline_cond": 4.1, "sigma_cond": 0.16, "baseline_pres": 1010.5,
    },
    "Alaska · Aleutianas (subducción)": {
        "tipo_falla": "subduccion", "pais": "EE.UU.", "lat": 61.50, "lon": -150.00,
        "radio_km": 500, "umbral_critico": 75.0, "mag_min_local": 4.0,
        "baseline_cond": 3.7, "sigma_cond": 0.20, "baseline_pres": 1008.0,
    },
    "México · Guerrero (subducción)": {
        "tipo_falla": "subduccion", "pais": "México", "lat": 17.50, "lon": -101.50,
        "radio_km": 420, "umbral_critico": 74.0, "mag_min_local": 4.0,
        "baseline_cond": 4.0, "sigma_cond": 0.17, "baseline_pres": 1011.8,
    },
    "Filipinas · Mindanao (complejo)": {
        "tipo_falla": "complejo", "pais": "Filipinas", "lat": 6.20, "lon": 125.10,
        "radio_km": 380, "umbral_critico": 73.0, "mag_min_local": 4.2,
        "baseline_cond": 4.0, "sigma_cond": 0.20, "baseline_pres": 1010.8,
    },
    "Taiwán · Ryukyu (complejo)": {
        "tipo_falla": "complejo", "pais": "Taiwán", "lat": 23.80, "lon": 121.20,
        "radio_km": 360, "umbral_critico": 73.0, "mag_min_local": 4.0,
        "baseline_cond": 4.1, "sigma_cond": 0.19, "baseline_pres": 1011.5,
    },
    "Grecia · Egeo (complejo)": {
        "tipo_falla": "complejo", "pais": "Grecia", "lat": 37.50, "lon": 25.20,
        "radio_km": 320, "umbral_critico": 71.0, "mag_min_local": 4.0,
        "baseline_cond": 3.9, "sigma_cond": 0.21, "baseline_pres": 1012.0,
    },
    "California · San Andreas (transformante)": {
        "tipo_falla": "transformante", "pais": "EE.UU.", "lat": 36.10, "lon": -120.30,
        "radio_km": 320, "umbral_critico": 72.0, "mag_min_local": 3.8,
        "baseline_cond": 3.6, "sigma_cond": 0.22, "baseline_pres": 1014.0,
    },
    "Turquía · Anatolia (transformante)": {
        "tipo_falla": "transformante", "pais": "Turquía", "lat": 37.20, "lon": 37.00,
        "radio_km": 350, "umbral_critico": 72.0, "mag_min_local": 4.0,
        "baseline_cond": 3.8, "sigma_cond": 0.20, "baseline_pres": 1011.2,
    },
    "Nueva Zelanda · Kaikoura (transformante)": {
        "tipo_falla": "transformante", "pais": "Nueva Zelanda", "lat": -42.40, "lon": 173.70,
        "radio_km": 340, "umbral_critico": 72.0, "mag_min_local": 4.0,
        "baseline_cond": 3.7, "sigma_cond": 0.21, "baseline_pres": 1010.5,
    },
    "Islandia · Reykjanes (divergente)": {
        "tipo_falla": "divergente", "pais": "Islandia", "lat": 63.90, "lon": -22.50,
        "radio_km": 280, "umbral_critico": 70.0, "mag_min_local": 3.5,
        "baseline_cond": 3.4, "sigma_cond": 0.28, "baseline_pres": 1008.5,
    },
    "Rift Africano · Afar (divergente)": {
        "tipo_falla": "divergente", "pais": "Etiopía", "lat": 11.60, "lon": 41.00,
        "radio_km": 300, "umbral_critico": 68.0, "mag_min_local": 3.5,
        "baseline_cond": 3.5, "sigma_cond": 0.25, "baseline_pres": 1009.0,
    },
    "Himalaya · Nepal (colisión)": {
        "tipo_falla": "colision", "pais": "Nepal", "lat": 28.15, "lon": 84.00,
        "radio_km": 500, "umbral_critico": 74.0, "mag_min_local": 4.2,
        "baseline_cond": 4.3, "sigma_cond": 0.16, "baseline_pres": 1010.0,
    },
}

EVENTOS_REF_MUNDO = {
    "Perú · Lima-Nazca (subducción)": [
        {"evento": "Pisco 2007", "mag": "M8.0", "b_14d": 0.66, "sismos_14d": 38, "insar": 88.0, "cond": 4.3, "shoa": 12.0},
        {"evento": "Lima 1974", "mag": "M8.1", "b_14d": 0.60, "sismos_14d": 45, "insar": 90.5, "cond": 4.6, "shoa": 9.0},
        {"evento": "Chimbote 1970", "mag": "M7.9", "b_14d": 0.63, "sismos_14d": 41, "insar": 87.0, "cond": 4.4, "shoa": 10.0},
    ],
    "Japón · Tohoku (subducción)": [
        {"evento": "Tohoku 2011", "mag": "M9.0", "b_14d": 0.55, "sismos_14d": 72, "insar": 98.0, "cond": 5.1, "shoa": 180.0},
        {"evento": "Kumamoto 2016", "mag": "M7.3", "b_14d": 0.72, "sismos_14d": 34, "insar": 78.0, "cond": 4.0, "shoa": 3.0},
        {"evento": "Hokkaido 2018", "mag": "M6.7", "b_14d": 0.69, "sismos_14d": 29, "insar": 74.0, "cond": 3.9, "shoa": 2.5},
    ],
    "Indonesia · Sumatra (subducción)": [
        {"evento": "Aceh 2004", "mag": "M9.1", "b_14d": 0.54, "sismos_14d": 78, "insar": 97.0, "cond": 5.0, "shoa": 220.0},
        {"evento": "Nias 2005", "mag": "M8.6", "b_14d": 0.57, "sismos_14d": 65, "insar": 93.0, "cond": 4.7, "shoa": 45.0},
        {"evento": "Padang 2009", "mag": "M7.6", "b_14d": 0.65, "sismos_14d": 36, "insar": 84.0, "cond": 4.2, "shoa": 8.0},
    ],
    "Alaska · Aleutianas (subducción)": [
        {"evento": "Alaska 1964", "mag": "M9.2", "b_14d": 0.52, "sismos_14d": 58, "insar": 95.0, "cond": 4.9, "shoa": 160.0},
        {"evento": "Rat Islands 1965", "mag": "M8.7", "b_14d": 0.58, "sismos_14d": 42, "insar": 89.0, "cond": 4.4, "shoa": 22.0},
    ],
    "México · Guerrero (subducción)": [
        {"evento": "Michoacán 1985", "mag": "M8.0", "b_14d": 0.61, "sismos_14d": 47, "insar": 91.0, "cond": 4.5, "shoa": 6.0},
        {"evento": "Puebla 2017", "mag": "M7.1", "b_14d": 0.70, "sismos_14d": 33, "insar": 79.0, "cond": 4.1, "shoa": 3.5},
        {"evento": "Guerrero 2014", "mag": "M7.2", "b_14d": 0.68, "sismos_14d": 30, "insar": 76.0, "cond": 4.0, "shoa": 4.0},
    ],
    "Filipinas · Mindanao (complejo)": [
        {"evento": "Mindanao 2026", "mag": "M7.8", "b_14d": 0.67, "sismos_14d": 31, "insar": 82.0, "cond": 4.1, "shoa": 14.0},
        {"evento": "Bohol 2013", "mag": "M7.2", "b_14d": 0.74, "sismos_14d": 22, "insar": 71.0, "cond": 3.9, "shoa": 5.0},
        {"evento": "Leyte 2017", "mag": "M6.5", "b_14d": 0.76, "sismos_14d": 27, "insar": 68.0, "cond": 3.8, "shoa": 4.5},
    ],
    "Taiwán · Ryukyu (complejo)": [
        {"evento": "Hualien 2018", "mag": "M6.4", "b_14d": 0.73, "sismos_14d": 25, "insar": 70.0, "cond": 4.0, "shoa": 6.0},
        {"evento": "Ji-Ji 1999", "mag": "M7.7", "b_14d": 0.64, "sismos_14d": 39, "insar": 85.0, "cond": 4.3, "shoa": 7.0},
    ],
    "Grecia · Egeo (complejo)": [
        {"evento": "Santorini 1956", "mag": "M7.7", "b_14d": 0.71, "sismos_14d": 28, "insar": 73.0, "cond": 3.9, "shoa": 5.0},
        {"evento": "Kos 2017", "mag": "M6.6", "b_14d": 0.77, "sismos_14d": 24, "insar": 66.0, "cond": 3.7, "shoa": 3.0},
    ],
    "California · San Andreas (transformante)": [
        {"evento": "Ridgecrest 2019", "mag": "M7.1", "b_14d": 0.78, "sismos_14d": 48, "insar": 65.0, "cond": 3.8, "shoa": 2.0},
        {"evento": "Loma Prieta 1989", "mag": "M6.9", "b_14d": 0.82, "sismos_14d": 26, "insar": 58.0, "cond": 3.5, "shoa": 1.5},
        {"evento": "San Fernando 1971", "mag": "M6.6", "b_14d": 0.80, "sismos_14d": 22, "insar": 55.0, "cond": 3.4, "shoa": 1.2},
    ],
    "Turquía · Anatolia (transformante)": [
        {"evento": "Kahramanmaras 2023", "mag": "M7.8", "b_14d": 0.70, "sismos_14d": 40, "insar": 72.0, "cond": 4.0, "shoa": 2.5},
        {"evento": "Izmit 1999", "mag": "M7.6", "b_14d": 0.68, "sismos_14d": 35, "insar": 75.0, "cond": 4.2, "shoa": 3.0},
        {"evento": "Van 2011", "mag": "M7.1", "b_14d": 0.72, "sismos_14d": 28, "insar": 68.0, "cond": 3.9, "shoa": 2.0},
    ],
    "Nueva Zelanda · Kaikoura (transformante)": [
        {"evento": "Kaikoura 2016", "mag": "M7.8", "b_14d": 0.69, "sismos_14d": 44, "insar": 74.0, "cond": 3.9, "shoa": 2.8},
        {"evento": "Christchurch 2011", "mag": "M6.2", "b_14d": 0.81, "sismos_14d": 36, "insar": 60.0, "cond": 3.6, "shoa": 1.0},
    ],
    "Islandia · Reykjanes (divergente)": [
        {"evento": "Reykjanes 2024", "mag": "M6.8", "b_14d": 0.85, "sismos_14d": 55, "insar": 55.0, "cond": 3.2, "shoa": 0.8},
        {"evento": "Grindavik enjambre", "mag": "M5.6", "b_14d": 0.90, "sismos_14d": 68, "insar": 48.0, "cond": 3.0, "shoa": 0.5},
        {"evento": "Bárðarbunga 2014", "mag": "M5.4", "b_14d": 0.93, "sismos_14d": 72, "insar": 42.0, "cond": 2.9, "shoa": 0.3},
    ],
    "Rift Africano · Afar (divergente)": [
        {"evento": "Afar 2005", "mag": "M6.2", "b_14d": 0.88, "sismos_14d": 42, "insar": 52.0, "cond": 3.3, "shoa": 0.3},
        {"evento": "Dallol enjambre", "mag": "M5.5", "b_14d": 0.92, "sismos_14d": 58, "insar": 45.0, "cond": 3.1, "shoa": 0.2},
    ],
    "Himalaya · Nepal (colisión)": [
        {"evento": "Nepal 2015", "mag": "M7.8", "b_14d": 0.59, "sismos_14d": 18, "insar": 92.0, "cond": 4.5, "shoa": 1.0},
        {"evento": "Sikkim 2011", "mag": "M6.9", "b_14d": 0.63, "sismos_14d": 14, "insar": 86.0, "cond": 4.3, "shoa": 0.8},
        {"evento": "Kashmir 2005", "mag": "M7.6", "b_14d": 0.61, "sismos_14d": 16, "insar": 89.0, "cond": 4.4, "shoa": 0.9},
    ],
}

COMPUERTA_POR_TIPO = {
    "subduccion": {"insar_min": 50.0, "sismos_min": 2, "b_critico": 0.65},
    "transformante": {"insar_min": 40.0, "sismos_min": 3, "b_critico": 0.70},
    "divergente": {"insar_min": 35.0, "sismos_min": 4, "b_critico": 0.75},
    "colision": {"insar_min": 45.0, "sismos_min": 1, "b_critico": 0.60},
    "complejo": {"insar_min": 45.0, "sismos_min": 2, "b_critico": 0.68},
}


def listar_nodos_mundo():
    return list(NODOS_MUNDO_CONFIG.keys())


def nodo_por_defecto():
    return "Filipinas · Mindanao (complejo)"


def catalogo_referencia_mundial(nodo_activo=None):
    filas = []
    for nodo, eventos in EVENTOS_REF_MUNDO.items():
        cfg = NODOS_MUNDO_CONFIG.get(nodo, {})
        for ev in eventos:
            filas.append({
                "Región nodal": nodo,
                "País": cfg.get("pais", ""),
                "Tipo falla": cfg.get("tipo_falla", ""),
                "Evento": ev["evento"],
                "Magnitud": ev["mag"],
                "b-value 14D": ev["b_14d"],
                "Sismos 14D": ev["sismos_14d"],
                "InSAR %": ev["insar"],
                "EM ref.": ev["cond"],
                "Marea/SHOA": ev["shoa"],
                "Nodo activo": "◉" if nodo == nodo_activo else "",
            })
    df = pd.DataFrame(filas)
    if nodo_activo and not df.empty:
        df = df.sort_values(
            by=["Nodo activo", "Región nodal", "Magnitud"],
            ascending=[False, True, False],
        )
    return df


def referencia_nodo_activo(nodo):
    eventos = EVENTOS_REF_MUNDO.get(nodo, [])
    cfg = NODOS_MUNDO_CONFIG.get(nodo, {})
    if not eventos:
        return pd.DataFrame()
    return pd.DataFrame([{
        "País": cfg.get("pais", ""),
        "Evento": e["evento"],
        "Magnitud": e["mag"],
        "b-value 14D": e["b_14d"],
        "Sismos 14D": e["sismos_14d"],
        "InSAR %": e["insar"],
        "EM ref.": e["cond"],
        "Marea/SHOA": e["shoa"],
    } for e in eventos])


def filtrar_eventos_fuera_chile(df_sismos):
    if df_sismos.empty:
        return df_sismos.copy()
    df = df_sismos.copy()
    en_chile = (
        (df["Latitud"] >= -56.0) & (df["Latitud"] <= -17.0)
        & (df["Longitud"] >= -76.5) & (df["Longitud"] <= -66.0)
    )
    return df[~en_chile].copy()


# ==============================================================================
# UTILIDADES
# ==============================================================================
def ahora_chile():
    return datetime.now(CHILE_TZ).replace(tzinfo=None)


def timestamp_usgs_a_chile(timestamp_ms):
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=CHILE_TZ).strftime("%Y-%m-%d %H:%M")


def distancia_km(lat1, lon1, lat2, lon2):
    radio = 6371.0
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return float(2 * radio * np.arcsin(np.sqrt(a)))


def calcular_b_value(df):
    if df.empty or len(df) < 10:
        return 1.0
    mags = df["Magnitud"].to_numpy()
    mc = mags.min()
    filtrado = mags[mags >= mc]
    if len(filtrado) == 0:
        return 1.0
    b = (1.0 / (np.mean(filtrado) - mc)) * 0.4343
    return round(max(0.4, min(b, 2.0)), 2)


def similitud(a, r, escala):
    return max(0.0, 100.0 - abs(a - r) / escala * 100.0)


def _ruta_cache(clave):
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"mundo_{clave}.json")


def leer_cache(clave, ttl_seg):
    ruta = _ruta_cache(clave)
    if not os.path.exists(ruta):
        return None, None, False
    try:
        with open(ruta, encoding="utf-8") as f:
            data = json.load(f)
        expira = datetime.fromisoformat(data["expira"])
        ahora = ahora_chile()
        vigente = ahora <= expira
        return data.get("payload"), data.get("consultado"), vigente
    except (OSError, json.JSONDecodeError, KeyError, ValueError):
        return None, None, False


def guardar_cache(clave, payload, ttl_seg):
    ahora = ahora_chile()
    with open(_ruta_cache(clave), "w", encoding="utf-8") as f:
        json.dump({
            "payload": payload,
            "consultado": ahora.strftime("%Y-%m-%d %H:%M:%S"),
            "expira": (ahora + timedelta(seconds=ttl_seg)).isoformat(),
            "zona_horaria": CHILE_TZ_LABEL,
        }, f, ensure_ascii=False)


def borrar_cache_mundo(clave):
    ruta = _ruta_cache(clave)
    if os.path.exists(ruta):
        os.remove(ruta)


def clave_sismos_global(ttl_seg):
    return f"sismos_global_{MAG_MIN_GLOBAL}_{VENTANA_DIAS}_{ttl_seg}"


def _fetch_sismos_global(dias=VENTANA_DIAS, mag_min=MAG_MIN_GLOBAL):
    inicio = (ahora_chile() - timedelta(days=dias)).strftime("%Y-%m-%d")
    url = (
        "https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson"
        f"&starttime={inicio}"
        f"&minmagnitude={mag_min}&orderby=time&limit=500"
    )
    try:
        res = requests.get(url, timeout=15)
        if res.status_code == 200:
            filas = []
            for f in res.json().get("features", []):
                p, c = f["properties"], f["geometry"]["coordinates"]
                filas.append({
                    "Magnitud": float(p.get("mag") or 0),
                    "Lugar": p.get("place", ""),
                    "Latitud": c[1], "Longitud": c[0],
                    "Fecha": timestamp_usgs_a_chile(p["time"]),
                })
            return filas
    except requests.RequestException:
        pass
    return None


def sismos_global_cacheados(ttl_seg, forzar=False):
    clave = clave_sismos_global(ttl_seg)
    payload, consultado, vigente = leer_cache(clave, ttl_seg)
    if payload is not None and vigente and not forzar:
        return pd.DataFrame(payload), consultado, False
    nuevo = _fetch_sismos_global()
    if nuevo is not None:
        guardar_cache(clave, nuevo, ttl_seg)
        return pd.DataFrame(nuevo), ahora_chile().strftime("%Y-%m-%d %H:%M:%S"), True
    if payload is not None:
        return pd.DataFrame(payload), f"{consultado} (caché anterior)", False
    return pd.DataFrame(), None, False


def filtrar_sismos_nodo(df_sismos, lat, lon, radio_km):
    if df_sismos.empty:
        return df_sismos.copy()
    df = df_sismos.copy()
    df["Distancia_km"] = df.apply(
        lambda r: distancia_km(lat, lon, r["Latitud"], r["Longitud"]), axis=1,
    )
    return df[df["Distancia_km"] <= radio_km].sort_values("Fecha", ascending=False)


def telemetria_nodo(nodo, config, total_sismos, ttl_seg, modo_sat, modo_demo=False):
    tipo = config.get("tipo_falla", "subduccion")
    perfil = TELEMETRIA_POR_TIPO.get(tipo, TELEMETRIA_POR_TIPO["subduccion"])
    bloque = int(ahora_chile().timestamp() // ttl_seg)
    rng = random.Random(hash((nodo, bloque, modo_sat, modo_demo, tipo)))

    ganancia = perfil["insar_gain"] * (1.35 if modo_demo else 1.0)
    base = perfil["insar_base"] + (18.0 if modo_demo else 0.0)
    insar = round(base + min(total_sismos * ganancia, 52.0) + rng.uniform(-2.5, 2.5), 1)

    cond_amp = perfil["cond_amp"] * (1.4 if modo_demo else 1.0)
    cond = round(config["baseline_cond"] + rng.uniform(-0.15, cond_amp), 2)
    shoa_max = 18.0 * perfil["shoa_scale"] * (1.5 if modo_demo else 1.0)
    shoa = round(rng.uniform(0.1, max(0.5, shoa_max)), 2)
    pres = round(config["baseline_pres"] + rng.uniform(-1.2, 1.2), 2)
    termico = round(rng.uniform(0.3, 2.8 if modo_demo else 2.2), 2)

    if modo_sat:
        insar = round(min(insar + 8.0, 98.0), 1)
        cond = round(cond + 0.25, 2)
        origen = "SAT MUNDO LAB"
    elif modo_demo:
        origen = "DEMO MUNDO LAB"
    else:
        origen = f"LAB {tipo.upper()}"
    return shoa, cond, pres, termico, insar, origen


def calcular_riesgo_regional(insar, total_sismos, b_val, cond, shoa, config, kp, termico, presion, tipo_falla):
    pesos = PESOS_POR_TIPO.get(tipo_falla, PESOS_POR_TIPO["subduccion"])
    gate = COMPUERTA_POR_TIPO.get(tipo_falla, COMPUERTA_POR_TIPO["subduccion"])
    compuerta = (insar >= gate["insar_min"]) or (total_sismos >= gate["sismos_min"])
    z = (cond - config["baseline_cond"]) / config["sigma_cond"]
    cond_val = cond if z > 1.2 else config["baseline_cond"]

    if not compuerta:
        score = 15.0 + min(insar * 0.1, 10.0)
        return "ESTABLE", "🟢", score, f"LAB {tipo_falla}: compuerta cerrada."

    if b_val <= gate["b_critico"]:
        score_sismo = 100.0 * pesos["SISMO_BVAL"]
        filtro = f"LAB {tipo_falla}: b-value crítico ({b_val})."
    else:
        mult = max(0, (gate["b_critico"] + 0.55 - b_val) / 0.55)
        score_sismo = min((total_sismos / 40.0) * 100 * mult, 100.0) * pesos["SISMO_BVAL"]
        filtro = f"LAB {tipo_falla}: b-value {b_val}, sismos {total_sismos}."

    factor_kp = 1.10 if kp <= 2 else 0.90
    score = (
        score_sismo
        + min((insar / 85.0) * 100, 100.0) * pesos["INSAR"]
        + min((abs(cond_val - config["baseline_cond"]) / 2.0) * 100 * factor_kp, 100.0) * pesos["CONDUCT"]
        + min((abs(shoa) / 15.0) * 100, 100.0) * pesos["SHOA"]
        + min(termico * 2, 5.0)
        + min(abs(config["baseline_pres"] - presion) * 0.5, 5.0)
        + 100.0 * pesos["ATMOS"]
    )
    score = min(score, 100.0)
    umbral = config.get("umbral_critico", 75.0)

    if score >= 90:
        return "CRÍTICO", "🔴", score, filtro
    if score >= umbral:
        return "ADVERTENCIA", "🟠", score, filtro
    if score >= 40:
        return "ATENCIÓN", "🟡", score, filtro
    return "ESTABLE", "🟢", score, filtro


def comparar_referencia_regional(nodo, insar, total_sismos, b_val, cond, shoa):
    eventos = EVENTOS_REF_MUNDO.get(nodo, [])
    filas = []
    for ev in eventos:
        match = round(
            similitud(b_val, ev["b_14d"], 0.6) * 0.30
            + similitud(insar, ev["insar"], 85) * 0.25
            + similitud(total_sismos, ev["sismos_14d"], max(ev["sismos_14d"], 15)) * 0.20
            + similitud(cond, ev["cond"], 2.0) * 0.15
            + similitud(abs(shoa), abs(ev["shoa"]), 15.0) * 0.10,
            1,
        )
        filas.append({
            "Evento ref.": ev["evento"],
            "Magnitud": ev["mag"],
            "Match %": match,
            "Estado": "🔴 ALTO" if match >= 75 else ("🟠 MEDIO" if match >= 60 else "🟢 BAJO"),
        })
    if not filas:
        return pd.DataFrame(), "Sin referencia", 0.0
    df = pd.DataFrame(filas)
    mejor = df.loc[df["Match %"].idxmax()]
    return df, mejor["Evento ref."], float(mejor["Match %"])


def clasificar_nivel_lab(puntaje, mejor_match, b_val, total_sismos, umbral_critico):
    if puntaje >= umbral_critico + 10 and mejor_match >= 80 and b_val <= 0.70:
        return {"nivel": "ROJO", "color": "🔴", "ventana": "6-24 h", "mensaje": "Vigilancia máxima LAB."}
    if puntaje >= umbral_critico and mejor_match >= 75:
        return {"nivel": "NARANJO", "color": "🟠", "ventana": "12-24 h", "mensaje": "Vigilancia alta LAB."}
    if puntaje >= 55 or mejor_match >= 65 or total_sismos >= 10:
        return {"nivel": "AMARILLO", "color": "🟡", "ventana": "24-36 h", "mensaje": "Observación reforzada LAB."}
    return {"nivel": "VERDE", "color": "🟢", "ventana": "Sin ventana", "mensaje": "Estable en modelo regional."}


def hash_evidencia(payload):
    base = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]


def registrar_evidencia_mundo(nodo, config, estado, puntaje, nivel, mejor_ev, mejor_match,
                              total_local, total_global, b_val, insar, cond, shoa, log_filtro):
    ahora = ahora_chile()
    payload = {
        "fecha_hora": ahora.strftime("%Y-%m-%d %H:%M:%S"),
        "zona_horaria": CHILE_TZ_LABEL,
        "nodo": nodo,
        "pais": config.get("pais", ""),
        "tipo_falla": config.get("tipo_falla", ""),
        "lat": config["lat"], "lon": config["lon"],
        "estado": estado, "nivel": nivel["nivel"],
        "puntaje": round(float(puntaje), 2),
        "match_ref": round(float(mejor_match), 2),
        "patron_ref": mejor_ev,
        "sismos_locales_14d": int(total_local),
        "sismos_global_14d": int(total_global),
        "b_value": b_val, "insar": round(float(insar), 2),
        "em": round(float(cond), 2), "shoa": round(float(shoa), 2),
        "log_modelo": log_filtro,
        "modelo": "NAZCA_MUNDO_LAB_v1",
    }
    payload["hash_evidencia"] = hash_evidencia(payload)
    reg = pd.DataFrame([payload])
    reg.to_csv(EVIDENCIA_MUNDO_CSV, index=False, mode="a", header=not os.path.exists(EVIDENCIA_MUNDO_CSV))
    return payload["hash_evidencia"]


def leer_evidencia_mundo():
    if not os.path.exists(EVIDENCIA_MUNDO_CSV):
        return pd.DataFrame()
    try:
        df = pd.read_csv(EVIDENCIA_MUNDO_CSV)
        if "fecha_hora" in df.columns:
            df["fecha_hora_dt"] = pd.to_datetime(df["fecha_hora"], errors="coerce")
        return df
    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError):
        return pd.DataFrame()


def evaluar_coincidencias_mundo(df_evidencia, df_eventos, radio_km=400, horas_previas=336):
    if df_evidencia.empty or df_eventos.empty:
        return pd.DataFrame()
    filas = []
    for _, ev in df_eventos.iterrows():
        for _, snap in df_evidencia.dropna(subset=["fecha_hora_dt"]).iterrows():
            delta_h = (ev["fecha_dt"] - snap["fecha_hora_dt"]).total_seconds() / 3600
            if delta_h < 0 or delta_h > horas_previas:
                continue
            dist = distancia_km(float(snap["lat"]), float(snap["lon"]), float(ev["Latitud"]), float(ev["Longitud"]))
            if dist > radio_km:
                continue
            nivel = str(snap.get("nivel", "VERDE"))
            match = float(snap.get("match_ref", 0) or 0)
            puntaje = float(snap.get("puntaje", 0) or 0)
            if nivel not in ("AMARILLO", "NARANJO", "ROJO") and match < 65 and puntaje < 55:
                continue
            filas.append({
                "Evento real": ev["Lugar"],
                "Magnitud": ev["Magnitud"],
                "Fecha evento": ev["Fecha"],
                "Nodo LAB": snap["nodo"],
                "Tipo falla": snap.get("tipo_falla", ""),
                "Fecha evidencia": snap["fecha_hora"],
                "Anticipación h": round(delta_h, 1),
                "Distancia km": round(dist, 1),
                "Nivel previo": nivel,
                "Índice %": puntaje,
                "Match ref. %": match,
                "Hash": snap.get("hash_evidencia"),
            })
    return pd.DataFrame(filas).sort_values(["Fecha evento", "Anticipación h"], ascending=[False, True]) if filas else pd.DataFrame()


def construir_calibracion_mundo(df_global, ttl_seg, modo_sat, kp, consultado_usgs, modo_demo=False):
    filas = []
    for nodo, cfg in NODOS_MUNDO_CONFIG.items():
        df_local = filtrar_sismos_nodo(df_global, cfg["lat"], cfg["lon"], cfg["radio_km"])
        total = len(df_local)
        b_val = calcular_b_value(df_local)
        shoa, cond, pres, termico, insar, origen = telemetria_nodo(
            nodo, cfg, total, ttl_seg, modo_sat, modo_demo=modo_demo,
        )
        tipo = cfg["tipo_falla"]
        estado, icono, puntaje, log = calcular_riesgo_regional(
            insar, total, b_val, cond, shoa, cfg, kp, termico, pres, tipo,
        )
        _, patron, match = comparar_referencia_regional(nodo, insar, total, b_val, cond, shoa)
        nivel = clasificar_nivel_lab(puntaje, match, b_val, total, cfg["umbral_critico"])
        filas.append({
            "Nodo": nodo,
            "País": cfg["pais"],
            "Tipo falla": tipo,
            "Señal clave": TIPO_FALLA_INFO.get(tipo, ""),
            "Estado": f"{icono} {estado}",
            "Índice %": round(puntaje, 1),
            "Nivel LAB": f"{nivel['color']} {nivel['nivel']}",
            "Match ref.": f"{match:.1f}%",
            "Patrón ref.": patron,
            "b-value": b_val,
            "Sismos local 14D": total,
            "InSAR est.": f"{insar:.1f}%",
            "Umbral crítico": cfg["umbral_critico"],
        })
    return pd.DataFrame(filas)


def procesar_nodo(nodo, config, df_global, ttl_seg, modo_sat, kp, modo_demo=False):
    mag_min = config.get("mag_min_local", MAG_MIN_GLOBAL)
    df_zona = df_global[df_global["Magnitud"] >= mag_min] if not df_global.empty else df_global
    df_local = filtrar_sismos_nodo(df_zona, config["lat"], config["lon"], config["radio_km"])
    total_local = len(df_local)
    total_global = len(df_global)
    b_val = calcular_b_value(df_local)
    shoa, cond, pres, termico, insar, origen = telemetria_nodo(
        nodo, config, total_local, ttl_seg, modo_sat, modo_demo=modo_demo,
    )
    tipo = config["tipo_falla"]
    estado, icono, puntaje, log_filtro = calcular_riesgo_regional(
        insar, total_local, b_val, cond, shoa, config, kp, termico, pres, tipo,
    )
    df_match, mejor_ev, mejor_match = comparar_referencia_regional(nodo, insar, total_local, b_val, cond, shoa)
    nivel = clasificar_nivel_lab(puntaje, mejor_match, b_val, total_local, config["umbral_critico"])
    return {
        "df_local": df_local,
        "total_local": total_local,
        "total_global": total_global,
        "b_val": b_val,
        "shoa": shoa, "cond": cond, "pres": pres, "termico": termico,
        "insar": insar, "origen": origen,
        "estado": estado, "icono": icono, "puntaje": puntaje, "log_filtro": log_filtro,
        "df_match": df_match, "mejor_ev": mejor_ev, "mejor_match": mejor_match,
        "nivel": nivel, "tipo": tipo,
    }


# ==============================================================================
# UI — solo admin
# ==============================================================================
def render_mundo_lab(
    admin_activo, ttl_seg, ttl_horas, nodo_sel=None,
    forzar=False, modo_sat=False, modo_demo=False, kp=0,
):
    if not MODULO_MUNDO_ACTIVO:
        return

    if not admin_activo:
        st.info("NAZCA MUNDO LAB es privado. Ingresa PIN admin para acceder al laboratorio multi-placa.")
        return

    st.markdown("### 🌍 NAZCA MUNDO LAB — Calibración multi-placa")
    st.caption(
        f"Build **{MUNDO_LAB_VERSION}** · Hora: **{ahora_chile().strftime('%Y-%m-%d %H:%M:%S')}** ({CHILE_TZ_LABEL}) · "
        "Solo terremotos mundiales · Chile está en pestañas nacionales"
    )
    st.success(
        "Esta pestaña NO usa Maule, Iquique ni Illapel. "
        "Referencias: Japón, Filipinas, Indonesia, Alaska, Turquía, Nepal y más."
    )
    if modo_demo:
        st.error("MODO DEMO MUNDO — telemetría amplificada para prueba de respuesta LAB.")

    df_global, consultado_usgs, api_nueva = sismos_global_cacheados(ttl_seg, forzar=forzar)
    df_global = filtrar_eventos_fuera_chile(df_global)
    if api_nueva:
        st.success(f"USGS global M{MAG_MIN_GLOBAL}+ actualizado.")
    else:
        st.info(f"📦 Caché MUNDO — USGS global: {consultado_usgs} | ventana {VENTANA_DIAS}D")

    m1, m2, m3 = st.columns(3)
    m1.metric("Sismos mundiales M4.5+ (sin Chile)", len(df_global))
    m2.metric("Nodos CORE NETWORK", len(NODOS_MUNDO_CONFIG))
    m3.metric("Caché APIs", f"{ttl_horas} h")

    nodo_sel = nodo_sel or nodo_por_defecto()
    if nodo_sel not in NODOS_MUNDO_CONFIG:
        nodo_sel = nodo_por_defecto()
    config = NODOS_MUNDO_CONFIG[nodo_sel]
    tipo = config["tipo_falla"]
    st.info(
        f"**Nodo activo:** {nodo_sel} · **País:** {config['pais']} · "
        f"**Tipo falla:** {tipo} · {TIPO_FALLA_INFO.get(tipo, '')}"
    )

    st.markdown("#### Terremotos históricos mundiales (todas las regiones, sin Chile)")
    st.caption(
        "Catálogo de referencia donde ocurrieron los grandes sismos del planeta. "
        "La columna ◉ marca el nodo seleccionado en CORE NETWORK."
    )
    st.dataframe(
        catalogo_referencia_mundial(nodo_activo=nodo_sel),
        use_container_width=True,
        hide_index=True,
        height=280,
    )

    res = procesar_nodo(nodo_sel, config, df_global, ttl_seg, modo_sat, kp, modo_demo=modo_demo)
    bloque = int(ahora_chile().timestamp() // ttl_seg)

    clave_ev = (
        f"mundo_{nodo_sel}_{bloque}_{res['nivel']['nivel']}_"
        f"{round(res['puntaje'], 1)}_{round(res['mejor_match'], 1)}"
    )
    if st.session_state.get("ultima_evidencia_mundo") != clave_ev:
        registrar_evidencia_mundo(
            nodo_sel, config, res["estado"], res["puntaje"], res["nivel"],
            res["mejor_ev"], res["mejor_match"], res["total_local"], res["total_global"],
            res["b_val"], res["insar"], res["cond"], res["shoa"], res["log_filtro"],
        )
        st.session_state["ultima_evidencia_mundo"] = clave_ev

    if res["nivel"]["nivel"] == "ROJO":
        st.error(f"{res['nivel']['color']} ALERTA ROJA LAB — {res['nivel']['mensaje']}")
    elif res["nivel"]["nivel"] == "NARANJO":
        st.warning(f"{res['nivel']['color']} ALERTA NARANJA LAB — {res['nivel']['mensaje']}")
    elif res["nivel"]["nivel"] == "AMARILLO":
        st.warning(f"{res['nivel']['color']} ALERTA AMARILLA LAB — {res['nivel']['mensaje']}")
    else:
        st.success(f"{res['nivel']['color']} {res['nivel']['mensaje']}")

    st.caption(res["log_filtro"])

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Estado", res["icono"])
    c2.metric("Índice LAB", f"{res['puntaje']:.1f}%")
    c3.metric("b-value", res["b_val"])
    c4.metric("Sismos local", res["total_local"])
    c5.metric("Match ref.", f"{res['mejor_match']:.1f}%")

    pesos = PESOS_POR_TIPO.get(tipo, {})
    gate = COMPUERTA_POR_TIPO.get(tipo, {})
    with st.expander("Parámetros regionales activos"):
        st.dataframe(pd.DataFrame([
            {"Parámetro": k, "Peso": v} for k, v in pesos.items()
        ] + [
            {"Parámetro": "umbral_critico", "Peso": config["umbral_critico"]},
            {"Parámetro": "radio_km", "Peso": config["radio_km"]},
            {"Parámetro": "compuerta_insar_min", "Peso": gate.get("insar_min")},
            {"Parámetro": "compuerta_sismos_min", "Peso": gate.get("sismos_min")},
            {"Parámetro": "b_critico", "Peso": gate.get("b_critico")},
        ]), use_container_width=True, hide_index=True)

    col_mapa, col_tabla = st.columns([1.8, 1.2])
    with col_mapa:
        st.markdown("#### Mapa global — Cinturón de Fuego + sismos USGS")
        mapa_renderizado = False
        if mapa_tect:
            try:
                mapa_tect.render_mapa_tectonico(
                    df_sismos=df_global,
                    df_etiquetas=res["df_local"],
                    estacion_lat=config["lat"],
                    estacion_lon=config["lon"],
                    estacion_label=nodo_sel,
                    estacion_color_rgb=[59, 130, 246, 255],
                    lat_center=config["lat"],
                    lon_center=config["lon"],
                    zoom=2,
                    altura=420,
                    mostrar_anillo=True,
                    max_etiquetas=15,
                )
                st.caption(mapa_tect.leyenda_mapa_tectonico())
                mapa_renderizado = True
            except Exception as exc:
                st.warning(f"Mapa pydeck no disponible ({exc}). Mostrando vista simplificada.")
        if not mapa_renderizado:
            mapa_df = pd.DataFrame([{"lat": config["lat"], "lon": config["lon"], "size": 200, "color": "#3b82f6"}])
            if not res["df_local"].empty:
                sm = res["df_local"].rename(columns={"Latitud": "lat", "Longitud": "lon", "Magnitud": "mag"})
                sm["size"] = (sm["mag"].clip(lower=4.0) ** 2) * 14
                sm["color"] = np.where(
                    sm["mag"] >= 6.0, "#ef4444",
                    np.where(sm["mag"] >= 4.5, "#facc15", "#4ade80"),
                )
                mapa_df = pd.concat([mapa_df, sm[["lat", "lon", "size", "color"]]], ignore_index=True)
            st.map(mapa_df, latitude="lat", longitude="lon", size="size", color="color", zoom=3)

    with col_tabla:
        st.caption(
            f"Radio {config['radio_km']} km · Origen telemetría: {res['origen']} · "
            f"Global M{MAG_MIN_GLOBAL}+: {res['total_global']}"
        )
        cols = ["Magnitud", "Lugar", "Fecha", "Distancia_km"]
        st.dataframe(
            res["df_local"][cols] if not res["df_local"].empty else pd.DataFrame(columns=cols),
            height=220, use_container_width=True,
        )

    st.markdown(f"#### Referencia del nodo activo: {config['pais']}")
    df_ref_nodo = referencia_nodo_activo(nodo_sel)
    if not df_ref_nodo.empty:
        st.dataframe(df_ref_nodo, use_container_width=True, hide_index=True)

    st.markdown("##### Match calculado vs referencia del nodo (no Chile)")
    st.dataframe(res["df_match"], use_container_width=True, hide_index=True)
    if res["mejor_ev"] and "Maule" not in res["mejor_ev"] and "Iquique" not in res["mejor_ev"]:
        st.caption(f"Patrón más parecido en este nodo: **{res['mejor_ev']}** ({res['mejor_match']:.1f}%)")

    st.markdown("#### Calibración todos los nodos mundiales")
    df_cal = construir_calibracion_mundo(
        df_global, ttl_seg, modo_sat, kp, consultado_usgs, modo_demo=modo_demo,
    )
    st.dataframe(df_cal, use_container_width=True, hide_index=True)
    st.download_button(
        "Descargar calibración MUNDO CSV",
        df_cal.to_csv(index=False).encode("utf-8-sig"),
        "calibracion_mundo_lab_nazca.csv",
        "text/csv",
        use_container_width=True,
    )

    st.markdown("#### Evidencia LAB mundial")
    df_ev = leer_evidencia_mundo()
    eventos_val = df_global.copy()
    if not eventos_val.empty:
        eventos_val["fecha_dt"] = pd.to_datetime(eventos_val["Fecha"], errors="coerce")
        eventos_val = eventos_val[eventos_val["Magnitud"] >= 5.5].dropna(subset=["fecha_dt"])
    coincidencias = evaluar_coincidencias_mundo(df_ev, eventos_val)

    e1, e2, e3 = st.columns(3)
    e1.metric("Snapshots LAB", len(df_ev))
    e2.metric("Eventos M5.5+ global", len(eventos_val))
    e3.metric("Coincidencias", len(coincidencias))

    if not df_ev.empty:
        st.dataframe(
            df_ev[["fecha_hora", "nodo", "tipo_falla", "nivel", "puntaje", "match_ref", "hash_evidencia"]]
            .tail(20).sort_values("fecha_hora", ascending=False),
            use_container_width=True, hide_index=True,
        )
        st.download_button(
            "Descargar evidencia MUNDO CSV",
            df_ev.drop(columns=["fecha_hora_dt"], errors="ignore").to_csv(index=False).encode("utf-8-sig"),
            "nazca_evidencia_mundo.csv",
            "text/csv",
            use_container_width=True,
        )

    if not coincidencias.empty:
        st.dataframe(coincidencias, use_container_width=True, hide_index=True)
    else:
        st.caption("Sin coincidencias LAB bajo criterios actuales.")

    st.caption(
        "Para desactivar este módulo: `MODULO_MUNDO_ACTIVO = False` en nazca_mundo_lab.py "
        "o eliminar el archivo. Chile no se ve afectado."
    )
