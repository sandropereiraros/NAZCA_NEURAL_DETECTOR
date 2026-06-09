"""Motor de vigilancia Chile sin Streamlit (USGS + riesgo + alertas)."""
from __future__ import annotations

import json
import os
import random
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

import nazca_alertas as alertas
import nazca_atmosfera as atmosfera
import nazca_conductividad as conductividad
import nazca_gnss as gnss
import nazca_shoa as shoa_ioc

try:
    import nazca_auditoria_semaforo as auditoria
except ImportError:
    auditoria = None

BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = BASE_DIR / ".nazca_cache"
COOLDOWN_FILE = CACHE_DIR / "telegram_cooldown_vigilancia.json"

PESOS = {"SISMO_BVAL": 0.62, "INSAR": 0.18, "CONDUCT": 0.10, "SHOA": 0.06, "ATMOS": 0.01}
RADIO_ESTACION_KM = 350
CHILE_BOUNDS = {"min_lat": -56.0, "max_lat": -17.0, "min_lon": -76.5, "max_lon": -66.0}
CHILE_TZ = ZoneInfo("America/Santiago")
TTL_SEG_DEFAULT = 21600

ESTACIONES_CONFIG = {
    "Arica / Iquique (85400)": {"id": "85400", "baseline_cond": 3.9, "sigma_cond": 0.2, "baseline_pres": 1012.1, "lat": -18.47, "lon": -70.31},
    "Antofagasta / Taltal (85442)": {"id": "85442", "baseline_cond": 3.8, "sigma_cond": 0.2, "baseline_pres": 1011.5, "lat": -23.65, "lon": -70.40},
    "Coquimbo / Illapel (85540)": {"id": "85540", "baseline_cond": 4.0, "sigma_cond": 0.18, "baseline_pres": 1012.8, "lat": -29.95, "lon": -71.34},
    "Valparaíso / San Antonio (85574)": {"id": "85574", "baseline_cond": 4.1, "sigma_cond": 0.15, "baseline_pres": 1013.25, "lat": -33.04, "lon": -71.61},
    "Concepción / Lebu (85680)": {"id": "85680", "baseline_cond": 3.7, "sigma_cond": 0.25, "baseline_pres": 1010.4, "lat": -36.82, "lon": -73.03},
    "Valdivia / Puerto Montt (85799)": {"id": "85799", "baseline_cond": 3.5, "sigma_cond": 0.3, "baseline_pres": 1008.0, "lat": -39.81, "lon": -73.24},
    "Pto. Aysén / Taitao (85850)": {"id": "85850", "baseline_cond": 3.2, "sigma_cond": 0.35, "baseline_pres": 1005.2, "lat": -45.40, "lon": -72.69},
}

EVENTOS_M7 = [
    {"evento": "Terremoto Maule 2010", "mag": "M8.8", "b_14d": 0.62, "sismos_14d": 52, "insar": 96.2, "cond": 4.8, "shoa": 150.0},
    {"evento": "Sismo Constitución 2012", "mag": "M7.1", "b_14d": 0.88, "sismos_14d": 28, "insar": 70.5, "cond": 4.1, "shoa": 4.0},
    {"evento": "Terremoto Iquique 2014", "mag": "M8.2", "b_14d": 0.58, "sismos_14d": 61, "insar": 91.8, "cond": 4.5, "shoa": 8.0},
    {"evento": "Terremoto Illapel 2015", "mag": "M8.3", "b_14d": 0.64, "sismos_14d": 44, "insar": 94.0, "cond": 4.2, "shoa": 5.0},
    {"evento": "Terremoto Melinka 2016", "mag": "M7.6", "b_14d": 0.71, "sismos_14d": 35, "insar": 85.5, "cond": 3.9, "shoa": 6.5},
]


def ahora_chile():
    return datetime.now(CHILE_TZ).replace(tzinfo=None)


def timestamp_usgs_a_chile(timestamp_ms):
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=CHILE_TZ).strftime("%Y-%m-%d %H:%M")


def distancia_km(lat1, lon1, lat2, lon2):
    radio = 6371.0
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return float(2 * radio * np.arcsin(np.sqrt(a)))


def _ruta_cache(clave):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{clave}.json"


def obtener_con_cache(clave, ttl_seg, fetch_fn):
    ruta = _ruta_cache(clave)
    payload_cache = None
    consultado = None
    if ruta.exists():
        try:
            datos = json.loads(ruta.read_text(encoding="utf-8"))
            expira = datetime.fromisoformat(datos["expira"])
            payload_cache = datos["payload"]
            consultado = datos.get("consultado")
            if ahora_chile() <= expira:
                return payload_cache, consultado, False
        except (json.JSONDecodeError, KeyError, ValueError):
            pass
    payload_nuevo = fetch_fn()
    if payload_nuevo is not None:
        ahora = ahora_chile()
        ruta.write_text(
            json.dumps({
                "consultado": ahora.strftime("%Y-%m-%d %H:%M:%S"),
                "expira": (ahora + timedelta(seconds=ttl_seg)).isoformat(),
                "ttl_seg": ttl_seg,
                "payload": payload_nuevo,
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        return payload_nuevo, ahora.strftime("%Y-%m-%d %H:%M:%S"), True
    if payload_cache is not None:
        return payload_cache, f"{consultado} (cache anterior)", False
    return [], None, False


def _fetch_sismos_regionales(dias=14):
    inicio = (ahora_chile() - timedelta(days=dias)).strftime("%Y-%m-%d")
    url = (
        "https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson"
        f"&starttime={inicio}"
        f"&minlatitude={CHILE_BOUNDS['min_lat']}&maxlatitude={CHILE_BOUNDS['max_lat']}"
        f"&minlongitude={CHILE_BOUNDS['min_lon']}&maxlongitude={CHILE_BOUNDS['max_lon']}"
        "&minmagnitude=2.5&orderby=time&limit=300"
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


def _fetch_kp_noaa():
    try:
        res = requests.get("https://services.swpc.noaa.gov/products/noaa-scales.json", timeout=8)
        return int(res.json().get("0", {}).get("GeomagneticStorms", {}).get("Scale", 0))
    except (requests.RequestException, ValueError, TypeError):
        return 0


def filtrar_sismos_estacion(df_sismos, lat, lon, radio_km=RADIO_ESTACION_KM):
    if df_sismos.empty:
        return df_sismos.copy()
    df = df_sismos.copy()
    df["Distancia_km"] = df.apply(lambda r: distancia_km(lat, lon, r["Latitud"], r["Longitud"]), axis=1)
    return df[df["Distancia_km"] <= radio_km].sort_values("Fecha", ascending=False)


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


def telemetria_estable(estacion, config, total_sismos, ttl_seg, secrets=None):
    bloque = int(ahora_chile().timestamp() // ttl_seg)
    rng = random.Random(hash((estacion, bloque, "vigilancia")))
    shoa = round(2.0 + rng.uniform(-1.5, 3.0), 2)
    cond = round(config["baseline_cond"] + rng.uniform(-0.3, 0.7), 2)
    pres = round(config["baseline_pres"] + rng.uniform(-1.5, 1.5), 2)
    termico = round(rng.uniform(0.2, 2.5), 2)
    insar = round(42.0 + min(total_sismos * 4.0, 48.0) + rng.uniform(-1.5, 1.5), 1)
    gnss_info = None
    atmos_info = None
    cond_info = None
    shoa_info = None
    try:
        shoa_info = shoa_ioc.lectura_marea_nodo(
            estacion, config["lat"], config["lon"], ttl_seg=min(ttl_seg, 1800)
        )
        if shoa_info:
            shoa = shoa_info["shoa_cm"]
    except Exception:
        shoa_info = None
    try:
        gnss_info = gnss.lectura_gnss_nodo(estacion, config["lat"], config["lon"], ttl_seg=ttl_seg)
        if gnss_info:
            insar = gnss_info["insar_pct"]
    except Exception:
        gnss_info = None
    try:
        atmos_info = atmosfera.lectura_atmosfera(
            config["lat"],
            config["lon"],
            baseline_pres=config["baseline_pres"],
            codigo_omm=config.get("id"),
            secrets=secrets,
            ttl_seg=min(ttl_seg, 3600),
        )
        if atmos_info:
            pres = atmos_info["presion_hpa"]
            termico = atmos_info["termico"]
    except Exception:
        atmos_info = None
    try:
        cond_info = conductividad.estimar_conductividad(estacion, config, atmos_info)
        if cond_info:
            cond = cond_info["conductividad_ms_m"]
    except Exception:
        cond_info = None
    return shoa, cond, pres, termico, insar, gnss_info, atmos_info, cond_info, shoa_info


def calcular_riesgo_fusion(insar, total_sismos, b_val, cond, shoa, config, kp, termico, presion):
    compuerta = alertas.compuerta_abierta(insar, total_sismos)
    z = (cond - config["baseline_cond"]) / config["sigma_cond"]
    cond_val = cond if z > 1.2 else config["baseline_cond"]
    if not compuerta:
        return "ESTABLE cortical", "🟢", 15.0 + min(insar * 0.1, 10.0), "Sin estres mecanico verificado."
    if b_val <= alertas.UMBRAL_B_RUPTURA_CRITICO:
        score_sismo = 100.0 * PESOS["SISMO_BVAL"]
        filtro = f"COMPUERTA ABIERTA // b-value critico ({b_val})."
    else:
        mult = max(0, (1.2 - b_val) / 0.55)
        score_sismo = min((total_sismos / 40.0) * 100 * mult, 100.0) * PESOS["SISMO_BVAL"]
        filtro = f"COMPUERTA ABIERTA // b-value regional: {b_val}."
    factor_kp = 1.15 if kp <= 2 else 0.85
    score = min(
        score_sismo
        + min((insar / 85.0) * 100, 100.0) * PESOS["INSAR"]
        + min((abs(cond_val - config["baseline_cond"]) / 2.0) * 100 * factor_kp, 100.0) * PESOS["CONDUCT"]
        + min((abs(shoa) / 15.0) * 100, 100.0) * PESOS["SHOA"]
        + min(termico * 2, 5.0)
        + min(abs(config["baseline_pres"] - presion) * 0.5, 5.0)
        + 100.0 * PESOS["ATMOS"],
        100.0,
    )
    if score >= 90:
        return "CRITICO", "🔴", score, filtro
    if score >= alertas.UMBRAL_CRITICO:
        return "ADVERTENCIA CRITICA", "🟠", score, filtro
    if score >= 40:
        return "ATENCION SISMICA", "🟡", score, filtro
    return "ESTABLE", "🟢", score, filtro


def similitud(a, r, escala):
    return max(0.0, 100.0 - abs(a - r) / escala * 100.0)


def comparar_con_historico(insar, total_sismos, b_val, cond, shoa):
    filas = []
    for ev in EVENTOS_M7:
        match = round(
            similitud(b_val, ev["b_14d"], 0.6) * 0.30
            + similitud(insar, ev["insar"], 85) * 0.25
            + similitud(total_sismos, ev["sismos_14d"], max(ev["sismos_14d"], 15)) * 0.20
            + similitud(cond, ev["cond"], 2.0) * 0.15
            + similitud(abs(shoa), abs(ev["shoa"]), 15.0) * 0.10,
            1,
        )
        filas.append({"evento": ev["evento"], "match": match})
    mejor = max(filas, key=lambda x: x["match"])
    return mejor["evento"], mejor["match"]


def evaluar_estacion(estacion, config, df_sismos, kp, consultado_usgs, ttl_seg):
    df_local = filtrar_sismos_estacion(df_sismos, config["lat"], config["lon"])
    total_sismos = len(df_local)
    b_val = calcular_b_value(df_local)
    shoa, cond, pres, termico, insar, gnss_info, atmos_info, cond_info, shoa_info = telemetria_estable(
        estacion, config, total_sismos, ttl_seg, secrets=alertas.leer_secrets_toml()
    )
    estado, icono, puntaje, log_filtro = calcular_riesgo_fusion(
        insar, total_sismos, b_val, cond, shoa, config, kp, termico, pres
    )
    tope = alertas.tope_riesgo_permitido(gnss_info, atmos_info, cond_info, shoa_info)
    if puntaje > tope:
        puntaje = tope
        estado = "VIGILANCIA ALTA HEURISTICA" if not alertas.gnss_es_confiable(gnss_info) else estado
    mejor_ev, mejor_match = comparar_con_historico(insar, total_sismos, b_val, cond, shoa)
    nivel = alertas.clasificar_nivel_alerta(puntaje, mejor_match, b_val, total_sismos, insar)
    resultado = {
        "estacion": estacion,
        "estado": estado,
        "puntaje": puntaje,
        "b_val": b_val,
        "total_sismos": total_sismos,
        "insar": insar,
        "cond": cond,
        "shoa": shoa,
        "mejor_ev": mejor_ev,
        "mejor_match": mejor_match,
        "nivel": nivel,
        "log_filtro": log_filtro,
        "consultado_usgs": consultado_usgs,
        "gnss": gnss_info,
        "atmos": atmos_info,
        "cond_info": cond_info,
        "shoa_info": shoa_info,
    }
    if atmos_info:
        resultado["log_filtro"] = (
            f"{resultado['log_filtro']} // Atmos {atmos_info['origen']}: "
            f"P={atmos_info['presion_hpa']:.1f}hPa T={atmos_info['temp_c']:.1f}C HR={atmos_info['humedad_pct']:.0f}%."
        )
    if cond_info and cond_info.get("cond_proxy_fisico"):
        resultado["log_filtro"] = (
            f"{resultado['log_filtro']} // EM proxy {cond_info['zona_suelo']}: {cond_info['conductividad_ms_m']:.2f} mS/m."
        )
    if shoa_info and shoa_info.get("shoa_real"):
        conf_m = "confiable" if alertas.shoa_es_real(shoa_info) else f"lejana {shoa_info.get('dist_km')}km"
        resultado["log_filtro"] = (
            f"{resultado['log_filtro']} // SHOA IOC {shoa_info['codigo_ioc']} ({conf_m}): "
            f"anom={shoa_info['anomalia_cm']:.1f}cm tasa={shoa_info['tasa_cm_h']:.1f}cm/h."
        )
    if gnss_info:
        extra = ""
        acel = gnss_info.get("aceleracion") or {}
        if acel.get("acelerando"):
            extra = (
                f" | acel. 1A H={acel.get('horiz_reciente_mm_anio', 0):.1f} "
                f"ratio={acel.get('ratio_horizontal', 1):.2f}"
            )
        conf = "confiable" if gnss_info.get("gnss_confiable") else f"lejana {gnss_info.get('dist_km')}km"
        resultado["log_filtro"] = (
            f"{resultado['log_filtro']} // GNSS {gnss_info['estacion_gnss']} ({conf}): "
            f"H={gnss_info['horiz_mm_anio']:.1f} V={gnss_info['vu_mm_anio']:.1f} mm/yr{extra}."
        )
    return resultado


def ejecutar_vigilancia(secrets: dict | None = None, ttl_seg: int = TTL_SEG_DEFAULT, dry_run: bool = False):
    secrets = secrets or alertas.leer_secrets_toml()
    filas, consultado_usgs, _ = obtener_con_cache(
        f"sismos_chile_14d_{ttl_seg}",
        ttl_seg,
        _fetch_sismos_regionales,
    )
    kp, _, _ = obtener_con_cache("kp_noaa_vigilancia", ttl_seg, _fetch_kp_noaa)
    df_sismos = pd.DataFrame(filas)
    cooldown = alertas.CooldownStore(COOLDOWN_FILE)
    resultados = []
    alertas_enviadas = 0

    bloque_aud = int(ahora_chile().timestamp() // ttl_seg)
    for estacion, config in ESTACIONES_CONFIG.items():
        ev = evaluar_estacion(estacion, config, df_sismos, kp, consultado_usgs, ttl_seg)
        if auditoria and not dry_run:
            nivel_nom = (ev.get("nivel") or {}).get("nivel", "VERDE")
            clave_aud = f"{estacion}_{bloque_aud}_{nivel_nom}"
            auditoria.registrar_alerta_semaforo(
                estacion,
                config,
                ev["nivel"],
                ev["puntaje"],
                ev["mejor_match"],
                ev["mejor_ev"],
                ev["total_sismos"],
                clave_bloque=clave_aud,
            )
        disparar, motivo, clave = alertas.evaluar_disparo_telegram(
            estacion,
            ev["mejor_ev"],
            ev["puntaje"],
            ev["mejor_match"],
            ev["b_val"],
            ev["total_sismos"],
            ev["insar"],
            modo_demo=False,
            cooldown=cooldown,
        )
        ev["disparar"] = disparar
        ev["motivo"] = motivo
        resultados.append(ev)

        if not disparar:
            continue

        mensaje = alertas.construir_mensaje_telegram(
            estacion,
            ev["estado"],
            ev["puntaje"],
            ev["b_val"],
            ev["total_sismos"],
            ev["insar"],
            ev["cond"],
            ev["shoa"],
            ev["mejor_ev"],
            ev["mejor_match"],
            consultado_usgs,
            ev["nivel"],
            ev["nivel"]["ventana"],
            motivo_disparo=motivo,
        )
        if dry_run:
            ev["accion"] = "dry-run"
            alertas_enviadas += 1
            continue

        ok_admin, _ = alertas.enviar_telegram(mensaje, secrets=secrets)
        subs_ok, subs_err = alertas.enviar_alerta_suscriptores(
            mensaje, estacion, ev["nivel"], secrets=secrets
        )
        if ok_admin or subs_ok:
            cooldown.set(clave)
            alertas_enviadas += 1
        ev["accion"] = f"admin={ok_admin} subs={subs_ok} err={subs_err}"

    if auditoria and not dry_run:
        auditoria.actualizar_resultados_auditoria(df_sismos)

    return {
        "estaciones": len(resultados),
        "alertas_enviadas": alertas_enviadas,
        "consultado_usgs": consultado_usgs,
        "resultados": resultados,
    }
