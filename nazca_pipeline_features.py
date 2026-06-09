"""Feature engineering para PIPELINE LAB (ventanas pasadas → etiqueta futura)."""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

CHILE_TZ = ZoneInfo("America/Santiago")
RADIO_KM = 350
MAG_ETIQUETA = 5.0
HORIZONTE_DIAS = 5
VENTANA_DIAS = 30

ESTACIONES = {
    "Arica / Iquique (85400)": {"lat": -18.47, "lon": -70.31},
    "Antofagasta / Taltal (85442)": {"lat": -23.65, "lon": -70.40},
    "Coquimbo / Illapel (85540)": {"lat": -29.95, "lon": -71.34},
    "Valparaíso / San Antonio (85574)": {"lat": -33.04, "lon": -71.61},
    "Concepción / Lebu (85680)": {"lat": -36.82, "lon": -73.03},
    "Valdivia / Puerto Montt (85799)": {"lat": -39.81, "lon": -73.24},
    "Pto. Aysén / Taitao (85850)": {"lat": -45.40, "lon": -72.69},
}

FEATURE_COLS = [
    "n_7d",
    "n_14d",
    "n_30d",
    "mag_max_30d",
    "mag_media_30d",
    "prof_media_30d",
    "b_value",
    "mc",
    "esperado_m5_7d",
    "tasa_sube",
    "bath_delta",
    "omori_activo",
]


def _cargar_forecast():
    try:
        import nazca_forecast_sismico as fc
        return fc
    except ImportError:
        return None


def distancia_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    lat1r, lon1r, lat2r, lon2r = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2r - lat1r
    dlon = lon2r - lon1r
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1r) * math.cos(lat2r) * math.sin(dlon / 2) ** 2
    return float(2 * r * math.asin(math.sqrt(a)))


def preparar_eventos(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    out["fecha_dt"] = pd.to_datetime(out["fecha_local"], errors="coerce")
    out = out.dropna(subset=["fecha_dt", "lat", "lon", "magnitud"])
    return out.sort_values("fecha_dt")


def eventos_en_zona(df: pd.DataFrame, lat: float, lon: float, radio_km: float = RADIO_KM) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    out["dist_km"] = out.apply(lambda r: distancia_km(lat, lon, r["lat"], r["lon"]), axis=1)
    return out[out["dist_km"] <= radio_km]


def _df_forecast(window: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "Magnitud": window["magnitud"].values,
        "Fecha": window["fecha_local"].astype(str).values,
        "Lugar": window.get("lugar", pd.Series([""] * len(window))).fillna("").values,
    })


def calcular_bath(window: pd.DataFrame, mag_principal_min: float = 4.5) -> float:
    if window.empty:
        return 0.0
    principales = window[window["magnitud"] >= mag_principal_min]
    if principales.empty:
        return 0.0
    t_main = principales.iloc[-1]["magnitud"]
    replicas = window[window["magnitud"] < mag_principal_min]
    if replicas.empty:
        return float(t_main)
    return float(t_main - replicas["magnitud"].max())


def _b_value_rapido(mags: np.ndarray) -> tuple[float, float]:
    if len(mags) < 5:
        return 1.0, float(mags.min()) if len(mags) else 2.5
    mc = float(np.min(mags))
    fil = mags[mags >= mc]
    media = float(np.mean(fil))
    if media <= mc:
        return 1.0, mc
    b = min(2.0, max(0.4, 0.4343 / (media - mc)))
    return round(b, 3), mc


def extraer_features_ventana(
    window: pd.DataFrame,
    corte: datetime,
    modo_rapido: bool = False,
) -> dict:
    n7 = int((window["fecha_dt"] >= corte - timedelta(days=7)).sum())
    n14 = int((window["fecha_dt"] >= corte - timedelta(days=14)).sum())
    n30 = len(window)
    mags = window["magnitud"].to_numpy() if n30 else np.array([])

    feats = {
        "n_7d": n7,
        "n_14d": n14,
        "n_30d": n30,
        "mag_max_30d": float(window["magnitud"].max()) if n30 else 0.0,
        "mag_media_30d": float(window["magnitud"].mean()) if n30 else 0.0,
        "prof_media_30d": float(window["profundidad_km"].dropna().mean()) if window["profundidad_km"].notna().any() else 0.0,
        "b_value": 1.0,
        "mc": 2.5,
        "esperado_m5_7d": 0.0,
        "tasa_sube": 1 if n7 > n14 else 0,
        "bath_delta": calcular_bath(window),
        "omori_activo": 0,
    }

    if n30 >= 5:
        b, mc = _b_value_rapido(mags)
        feats["b_value"] = b
        feats["mc"] = mc
        lam = max(0.0, n30 / 30.0) * max(0.0, 10 ** (math.log10(max(n30, 1)) + b * mc - b * 5.0) / 365.25)
        feats["esperado_m5_7d"] = round(lam * 7.0, 4)

    if not modo_rapido:
        fc_mod = _cargar_forecast()
        if fc_mod and n30 >= 5:
            df_fc = _df_forecast(window)
            resumen = fc_mod.resumen_forecast_sismico(df_fc)
            feats["b_value"] = float(resumen.get("b_value", feats["b_value"]))
            feats["mc"] = float(resumen.get("mc", feats["mc"]))
            feats["esperado_m5_7d"] = float(resumen.get("esperado_m5_7d") or feats["esperado_m5_7d"])
            dir_t = (resumen.get("tendencia") or {}).get("direccion", "ESTABLE")
            feats["tasa_sube"] = 1 if dir_t == "SUBE" else 0
            om = resumen.get("omori") or {}
            feats["omori_activo"] = 1 if om.get("direccion") == "SUBE" else 0

    return feats


def etiqueta_futuro(futuro: pd.DataFrame, mag_min: float = MAG_ETIQUETA) -> int:
    if futuro.empty:
        return 0
    return int((futuro["magnitud"] >= mag_min).any())


def construir_dataset(
    df_raw: pd.DataFrame,
    estaciones: dict | None = None,
    paso_dias: int = 3,
    modo_rapido: bool = True,
) -> pd.DataFrame:
    """Filas históricas: features en t → etiqueta M≥5 en (t, t+5d]."""
    estaciones = estaciones or ESTACIONES
    ev = preparar_eventos(df_raw)
    if ev.empty:
        return pd.DataFrame()

    t_min = ev["fecha_dt"].min() + timedelta(days=VENTANA_DIAS)
    t_max = ev["fecha_dt"].max() - timedelta(days=HORIZONTE_DIAS)
    if t_min >= t_max:
        return pd.DataFrame()

    filas = []
    cursor = t_min
    while cursor <= t_max:
        for nombre, cfg in estaciones.items():
            zona = eventos_en_zona(ev, cfg["lat"], cfg["lon"])
            pasado = zona[(zona["fecha_dt"] > cursor - timedelta(days=VENTANA_DIAS)) & (zona["fecha_dt"] <= cursor)]
            futuro = zona[(zona["fecha_dt"] > cursor) & (zona["fecha_dt"] <= cursor + timedelta(days=HORIZONTE_DIAS))]
            feats = extraer_features_ventana(pasado, cursor, modo_rapido=modo_rapido)
            fila = {
                "estacion": nombre,
                "fecha_corte": cursor.strftime("%Y-%m-%d"),
                "etiqueta_m5_5d": etiqueta_futuro(futuro),
            }
            fila.update(feats)
            filas.append(fila)
        cursor += timedelta(days=max(1, paso_dias))

    return pd.DataFrame(filas)


def features_vivo(df_raw: pd.DataFrame, estacion: str, config: dict) -> dict | None:
    ev = preparar_eventos(df_raw)
    if ev.empty:
        return None
    corte = ev["fecha_dt"].max()
    zona = eventos_en_zona(ev, config["lat"], config["lon"])
    pasado = zona[zona["fecha_dt"] > corte - timedelta(days=VENTANA_DIAS)]
    corte_dt = pd.Timestamp(corte)
    if getattr(corte_dt, "tz", None) is not None:
        corte_dt = corte_dt.tz_localize(None)
    feats = extraer_features_ventana(pasado, corte_dt.to_pydatetime())
    feats["estacion"] = estacion
    feats["fecha_corte"] = corte.strftime("%Y-%m-%d %H:%M:%S")
    return feats
