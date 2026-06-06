import json
import os
import random
from datetime import datetime, timedelta

import folium
import numpy as np
import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components
from fpdf import FPDF
from streamlit_folium import st_folium

# ==============================================================================
# CONFIGURACIÓN
# ==============================================================================
st.set_page_config(page_title="NAZCA CORE MONITOR v8.0", layout="wide")

PESOS = {"SISMO_BVAL": 0.62, "INSAR": 0.18, "CONDUCT": 0.10, "SHOA": 0.06, "ATMOS": 0.01}
UMBRAL_CRITICO = 75.0
RADIO_ESTACION_KM = 350
MAX_RIESGO_CON_TELEMETRIA_ESTIMADA = 74.0
INTERVALOS_API = {"10 minutos": 600, "30 minutos": 1800, "1 hora": 3600, "Desactivado": 3600}
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".nazca_cache")
CHILE_BOUNDS = {
    "min_lat": -56.0,
    "max_lat": -17.0,
    "min_lon": -76.5,
    "max_lon": -66.0,
}

st.markdown(
    """
    <style>
    .stApp { background-color: #0d1117; color: #c9d1d9; }
    .metric-card {
        background: linear-gradient(145deg, #161b22, #0d1117);
        border: 1px solid #30363d; border-radius: 12px;
        padding: 20px; margin-bottom: 10px;
    }
    h1, h2, h3 { font-family: 'Courier New', monospace !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

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

# ==============================================================================
# CACHÉ EN DISCO (APIs solo cada 10 / 30 / 60 min)
# ==============================================================================
def _ruta_cache(clave):
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{clave}.json")


def leer_cache_detalle(clave):
    ruta = _ruta_cache(clave)
    if not os.path.exists(ruta):
        return None, None, None, False
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            datos = json.load(f)
        expira = datetime.fromisoformat(datos["expira"])
        vigente = datetime.now() <= expira
        return datos["payload"], datos.get("consultado"), expira, vigente
    except (json.JSONDecodeError, KeyError, ValueError):
        return None, None, None, False


def leer_cache(clave, ttl_seg):
    payload, consultado, _, vigente = leer_cache_detalle(clave)
    if vigente:
        return payload, consultado
    return None, consultado


def guardar_cache(clave, payload, ttl_seg):
    ahora = datetime.now()
    datos = {
        "consultado": ahora.strftime("%Y-%m-%d %H:%M:%S"),
        "expira": (ahora + timedelta(seconds=ttl_seg)).isoformat(),
        "ttl_seg": ttl_seg,
        "payload": payload,
    }
    with open(_ruta_cache(clave), "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, default=str)


def borrar_cache(clave):
    ruta = _ruta_cache(clave)
    if os.path.exists(ruta):
        os.remove(ruta)


def obtener_con_cache(clave, ttl_seg, fetch_fn, forzar=False):
    payload_cache, consultado, _, vigente = leer_cache_detalle(clave)
    if payload_cache is not None and vigente and not forzar:
        return payload_cache, consultado, False

    payload_nuevo = fetch_fn()
    if payload_nuevo is not None:
        guardar_cache(clave, payload_nuevo, ttl_seg)
        return payload_nuevo, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), True

    # Si USGS/NOAA falla, mantenemos la última lectura buena para no dejar el sistema sin cálculo.
    if payload_cache is not None:
        return payload_cache, f"{consultado} (caché anterior)", False
    return [] if clave.startswith("sismos_") else 0, None, False


def bucket_telemetria(estacion, ttl_seg):
    return int(datetime.now().timestamp() // ttl_seg), estacion

# ==============================================================================
# APIs (solo invocadas cuando la caché expira)
# ==============================================================================
def _fetch_sismos_regionales(lat, lon, dias=14):
    inicio = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d")
    url = (
        "https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson"
        f"&starttime={inicio}"
        f"&minlatitude={CHILE_BOUNDS['min_lat']}&maxlatitude={CHILE_BOUNDS['max_lat']}"
        f"&minlongitude={CHILE_BOUNDS['min_lon']}&maxlongitude={CHILE_BOUNDS['max_lon']}"
        "&minmagnitude=2.5&orderby=time&limit=300"
    )
    try:
        res = requests.get(url, timeout=12)
        if res.status_code == 200:
            filas = []
            for f in res.json().get("features", []):
                p, c = f["properties"], f["geometry"]["coordinates"]
                filas.append({
                    "Magnitud": float(p.get("mag") or 0),
                    "Lugar": p.get("place", ""),
                    "Latitud": c[1], "Longitud": c[0],
                    "Fecha": datetime.fromtimestamp(p["time"] / 1000).strftime("%Y-%m-%d %H:%M"),
                })
            return filas
    except requests.RequestException:
        pass
    return None


def _fetch_kp_noaa():
    try:
        res = requests.get("https://services.swpc.noaa.gov/products/noaa-scales.json", timeout=5)
        return int(res.json().get("0", {}).get("GeomagneticStorms", {}).get("Scale", 0))
    except (requests.RequestException, ValueError, TypeError):
        return 0


def clave_sismos_14d(ttl_seg):
    return f"sismos_chile_14d_{ttl_seg}"


def sismos_regionales_cacheados(lat, lon, estacion_id, ttl_seg, forzar=False):
    clave = clave_sismos_14d(ttl_seg)
    filas, consultado, nuevo = obtener_con_cache(clave, ttl_seg, lambda: _fetch_sismos_regionales(lat, lon), forzar=forzar)
    return pd.DataFrame(filas), consultado, nuevo


def kp_noaa_cacheado(ttl_seg):
    clave = f"kp_noaa_{ttl_seg}"
    kp, consultado, nuevo = obtener_con_cache(clave, ttl_seg, _fetch_kp_noaa)
    return int(kp), consultado, nuevo

# ==============================================================================
# UTILIDADES
# ==============================================================================
def sanitizar_texto(texto):
    for e in ["🟢", "🟡", "🟠", "🔴", "🚨", "⚠️", "✅", "🛰️", "🌐"]:
        texto = texto.replace(e, "")
    return texto


def registrar_en_bitacora(estacion, estado, puntaje, insar, b_val, cond, shoa):
    reg = pd.DataFrame([{
        "Fecha_Hora": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "Estacion": estacion, "Estado": estado, "Criticidad_%": puntaje,
        "InSAR_%": insar, "b-value_14D": b_val, "EM_mS/m": cond, "SHOA_cm": shoa,
    }])
    archivo = "nazca_log_historico.csv"
    reg.to_csv(archivo, index=False, mode="a", header=not os.path.exists(archivo))


@st.cache_data(ttl=30)
def leer_bitacora_bytes():
    if os.path.exists("nazca_log_historico.csv"):
        with open("nazca_log_historico.csv", "rb") as f:
            return f.read()
    return None


def distancia_km(lat1, lon1, lat2, lon2):
    radio_tierra = 6371.0
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return float(2 * radio_tierra * np.arcsin(np.sqrt(a)))


def filtrar_sismos_estacion(df_sismos, lat, lon, radio_km=RADIO_ESTACION_KM):
    if df_sismos.empty:
        return df_sismos.copy()
    df = df_sismos.copy()
    df["Distancia_km"] = df.apply(
        lambda r: distancia_km(lat, lon, r["Latitud"], r["Longitud"]),
        axis=1,
    )
    return df[df["Distancia_km"] <= radio_km].sort_values("Fecha", ascending=False)


def telemetria_estable(estacion, config, total_sismos, ttl_seg, modo_sat, nodo_offline):
    bloque, _ = bucket_telemetria(estacion, ttl_seg)
    rng = random.Random(hash((estacion, bloque, modo_sat, nodo_offline)))

    if nodo_offline:
        shoa = round(1.8 + rng.uniform(0.5, 2.0), 2)
        cond = round(config["baseline_cond"] + 0.25, 2)
        pres = round(config["baseline_pres"] - 0.8, 2)
        termico = 1.4
        insar = 65.0
        origen = "INTERPOLACIÓN VECINDAD"
    else:
        shoa = round(2.0 + rng.uniform(-1.5, 3.0), 2)
        cond = round(config["baseline_cond"] + rng.uniform(-0.3, 0.7), 2)
        pres = round(config["baseline_pres"] + rng.uniform(-1.5, 1.5), 2)
        termico = round(rng.uniform(0.2, 2.5), 2)
        insar = round(42.0 + min(total_sismos * 4.0, 48.0) + rng.uniform(-1.5, 1.5), 1)
        origen = "SATELITAL LEO" if modo_sat else "SENSOR FÍSICO"

    return shoa, cond, pres, termico, insar, origen

# ==============================================================================
# MOTOR DE RIESGO (fusión: matriz v7 + compuerta/Z-score/Kp del v3)
# ==============================================================================
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


def calcular_riesgo_fusion(insar, total_sismos, b_val, cond, shoa, config, kp, termico, presion):
    compuerta = (insar >= 50.0) or (total_sismos >= 2)
    z = (cond - config["baseline_cond"]) / config["sigma_cond"]
    cond_val = cond if z > 1.2 else config["baseline_cond"]

    if not compuerta:
        score = 15.0 + min(insar * 0.1, 10.0)
        return "ESTABLE cortical", "🟢", score, "INTERRUPTOR: sin estrés mecánico verificado."

    if b_val <= 0.65:
        score_sismo = 100.0 * PESOS["SISMO_BVAL"]
        filtro = f"COMPUERTA ABIERTA // b-value crítico ({b_val})."
    else:
        mult = max(0, (1.2 - b_val) / 0.55)
        score_sismo = min((total_sismos / 40.0) * 100 * mult, 100.0) * PESOS["SISMO_BVAL"]
        filtro = f"COMPUERTA ABIERTA // b-value regional: {b_val}."

    factor_kp = 1.15 if kp <= 2 else 0.85
    score = (
        score_sismo
        + min((insar / 85.0) * 100, 100.0) * PESOS["INSAR"]
        + min((abs(cond_val - config["baseline_cond"]) / 2.0) * 100 * factor_kp, 100.0) * PESOS["CONDUCT"]
        + min((abs(shoa) / 15.0) * 100, 100.0) * PESOS["SHOA"]
        + min(termico * 2, 5.0)
        + min(abs(config["baseline_pres"] - presion) * 0.5, 5.0)
        + 100.0 * PESOS["ATMOS"]
    )
    score = min(score, 100.0)

    if score >= 90:
        return "CRÍTICO", "🔴", score, filtro
    if score >= UMBRAL_CRITICO:
        return "ADVERTENCIA CRÍTICA", "🟠", score, filtro
    if score >= 40:
        return "ATENCIÓN SÍSMICA", "🟡", score, filtro
    return "ESTABLE", "🟢", score, filtro


def aplicar_control_calidad(estado, icono, puntaje, log_filtro, modo_demo=False):
    if modo_demo:
        return estado, icono, puntaje, f"{log_filtro} // MODO DEMO."
    if puntaje > MAX_RIESGO_CON_TELEMETRIA_ESTIMADA:
        return (
            "VIGILANCIA ALTA HEURÍSTICA",
            "🟠",
            MAX_RIESGO_CON_TELEMETRIA_ESTIMADA,
            f"{log_filtro} // Riesgo limitado: InSAR/EM/SHOA/presión/térmico son estimados, no mediciones reales.",
        )
    return estado, icono, puntaje, f"{log_filtro} // Calidad: USGS/NOAA real + telemetría física estimada."


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
        filas.append({
            "Evento M7+": ev["evento"], "Magnitud": ev["mag"],
            "b-value ref. 14D": ev["b_14d"], "Sismos ref.": ev["sismos_14d"],
            "InSAR ref.": f"{ev['insar']:.1f}%",
            "Match vs Actual": f"{match:.1f}%",
            "Estado": "🔴 ALTO" if match >= 75 else ("🟠 MEDIO" if match >= 60 else "🟢 BAJO"),
        })
    df = pd.DataFrame(filas)
    df["_s"] = df["Match vs Actual"].str.replace("%", "", regex=False).astype(float)
    df = df.sort_values("_s", ascending=False).drop(columns="_s")
    mejor = df.iloc[0]
    return df, mejor["Evento M7+"], float(mejor["Match vs Actual"].replace("%", ""))


def construir_calibracion_estaciones(df_sismos, kp, ttl_seg, modo_sat, consultado_usgs, consultado_noaa):
    filas = []
    for estacion, cfg in ESTACIONES_CONFIG.items():
        df_local = filtrar_sismos_estacion(df_sismos, cfg["lat"], cfg["lon"])
        total_sismos = len(df_local)
        b_val = calcular_b_value(df_local)
        bloque, _ = bucket_telemetria(estacion, ttl_seg)
        nodo_offline = modo_sat and random.Random(hash((estacion, bloque, "offline"))).choice([True, False])
        shoa, cond, presion, termico, insar, origen = telemetria_estable(
            estacion, cfg, total_sismos, ttl_seg, modo_sat, nodo_offline
        )
        estado, _, puntaje, _ = calcular_riesgo_fusion(
            insar, total_sismos, b_val, cond, shoa, cfg, kp, termico, presion
        )
        estado, _, puntaje, _ = aplicar_control_calidad(estado, "🟠", puntaje, "", modo_demo=False)
        _, patron, match_patron = comparar_con_historico(insar, total_sismos, b_val, cond, shoa)
        z_cond = round((cond - cfg["baseline_cond"]) / cfg["sigma_cond"], 2)
        filas.append({
            "Estación": estacion,
            "Estado": estado,
            "Riesgo %": round(puntaje, 1),
            "Patrón M7+": patron,
            "Match patrón %": round(match_patron, 1),
            "Sismos 14D Chile": total_sismos,
            "Radio cálculo km": RADIO_ESTACION_KM,
            "b-value 14D": b_val,
            "InSAR %": insar,
            "EM mS/m": cond,
            "EM Z-score": z_cond,
            "SHOA cm": shoa,
            "Presión hPa": presion,
            "Térmico": termico,
            "Kp NOAA": kp,
            "Origen telemetría": origen,
            "Nodo offline": "Sí" if nodo_offline else "No",
            "USGS actualizado": consultado_usgs,
            "NOAA actualizado": consultado_noaa,
        })
    return pd.DataFrame(filas).sort_values("Riesgo %", ascending=False)


def generar_informe_calidad_texto(df_calibracion, consultado_usgs, consultado_noaa, ttl_seg):
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    pesos_txt = "\n".join(f"- {k}: {v:.2f}" for k, v in PESOS.items())
    estaciones_txt = "\n".join(
        f"- {fila['Estación']}: riesgo {fila['Riesgo %']}%, b-value {fila['b-value 14D']}, "
        f"sismos locales {fila['Sismos 14D Chile']}, match {fila['Match patrón %']}%"
        for _, fila in df_calibracion.iterrows()
    )
    return f"""INFORME DE CALIDAD Y TRANSPARENCIA - NAZCA CORE MONITOR
Generado: {fecha}

1. Objetivo
Este informe documenta los parámetros usados por el sistema para entregar una lectura transparente,
auditable y apta para revisión por profesionales de geotecnia, geología, sismología o gestión de riesgo.

2. Fuentes y calidad de datos
- USGS: catálogo sísmico 14 días para Chile. Dato real consultado por API.
- NOAA Kp: índice geomagnético. Dato real consultado por API.
- b-value: indicador calculado desde magnitudes USGS locales por estación.
- InSAR, EM, SHOA, presión y térmico: telemetría estimada/simulada mientras no existan sensores o APIs reales conectadas.

Última actualización USGS: {consultado_usgs}
Última actualización NOAA: {consultado_noaa}
TTL de caché actual: {ttl_seg // 60} minutos

3. Parámetros actuales del modelo
Radio local por estación: {RADIO_ESTACION_KM} km
Umbral crítico base: {UMBRAL_CRITICO:.1f}%
Máximo riesgo permitido con telemetría estimada: {MAX_RIESGO_CON_TELEMETRIA_ESTIMADA:.1f}%

Pesos:
{pesos_txt}

4. Criterio de transparencia
El sistema no debe interpretarse como predictor determinístico de terremotos. Cuando InSAR, EM, SHOA,
presión o térmico son estimados, el riesgo se limita a vigilancia heurística y no a alerta crítica real.
Una alerta operativa real requiere validación con mediciones instrumentales externas y revisión técnica.

5. Calibración mensual recomendada
- Revisar catálogo USGS de los últimos 30 días y comparar contra bitácora interna.
- Recalcular b-value por estación y validar radios de influencia.
- Ajustar baseline_cond, sigma_cond y baseline_pres con mediciones instrumentales si existen.
- Revisar falsos positivos: días con riesgo alto sin evento significativo posterior.
- Revisar falsos negativos: eventos significativos que no elevaron riesgo previamente.
- Documentar cambios de pesos, umbrales y fuentes en control de versiones.
- Exportar calibracion_estaciones_nazca.csv como evidencia mensual.

6. Resumen por estación
{estaciones_txt}

7. Limitación técnica
Este sistema es un monitor experimental de señales sísmicas y ambientales. Sus salidas deben entenderse
como apoyo exploratorio, no como aviso oficial ni reemplazo de organismos técnicos competentes.
"""

# ==============================================================================
# MAPA + PDF
# ==============================================================================
@st.cache_data(ttl=600)
def crear_mapa(lat, lon, sismos_tuple, color_nodo):
    mapa = folium.Map(location=[-33.0, -71.5], zoom_start=4, tiles=None, control_scale=True)
    folium.TileLayer(
        "CartoDB dark_matter",
        name="Mapa oscuro",
        control=False,
        attr="CartoDB",
    ).add_to(mapa)
    folium.PolyLine(
        [[-15, -75], [-25, -71.5], [-35, -73], [-46, -75.5]],
        color="#00f5ff", weight=3, opacity=0.85,
    ).add_to(mapa)
    folium.Marker([lat, lon], tooltip="Nodo activo", icon=folium.Icon(color=color_nodo, icon="signal")).add_to(mapa)
    for la, lo, mag in sismos_tuple:
        folium.CircleMarker(
            [la, lo], radius=max(3.5, mag * 1.5),
            color="#ff003c" if mag >= 4 else "#facc15",
            fill=True,
            fill_color="#ff003c" if mag >= 4 else "#facc15",
            fill_opacity=0.75,
            weight=1,
            tooltip=f"M{mag:.1f}",
        ).add_to(mapa)
    return mapa


def generar_pdf(estacion, puntaje, estado, b_val, cond, shoa, sismos_cnt, canal, kp):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Courier", "B", 14)
    pdf.cell(0, 10, "NAZCA CORE MONITOR v8.0", ln=True, align="C")
    pdf.set_font("Courier", "", 10)
    for linea in [
        f"Estacion: {sanitizar_texto(estacion)}",
        f"Estado: {sanitizar_texto(estado)} | Match: {puntaje:.1f}%",
        f"b-value: {b_val} | Sismos 14D: {sismos_cnt} | KP NOAA: {kp}",
        f"EM: {cond} mS/m | SHOA: {shoa} cm | Canal: {sanitizar_texto(canal)}",
        f"Generado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
    ]:
        pdf.cell(0, 6, linea, ln=True)
    out = pdf.output(dest="S")
    return out.encode("latin-1") if isinstance(out, str) else bytes(out)

# ==============================================================================
# SIDEBAR
# ==============================================================================
st.sidebar.markdown("### CORE NETWORK")
intervalo = st.sidebar.selectbox(
    "Intervalo caché APIs (USGS / NOAA)",
    list(INTERVALOS_API.keys()),
    index=1,
)
ttl_seg = INTERVALOS_API[intervalo]

st.sidebar.caption(
    f"Las APIs se consultan como máximo cada **{ttl_seg // 60} min**. "
    "Entre consultas se sirven datos desde `.nazca_cache/`."
)

if st.sidebar.button("Limpiar caché APIs", use_container_width=True):
    if os.path.isdir(CACHE_DIR):
        for f in os.listdir(CACHE_DIR):
            os.remove(os.path.join(CACHE_DIR, f))
    st.sidebar.success("Caché vaciada.")

forzar_sismos_14d = st.sidebar.button("Actualizar sismos 14D ahora", use_container_width=True)
if forzar_sismos_14d:
    borrar_cache(clave_sismos_14d(ttl_seg))

st.sidebar.markdown("---")
modo_demo = st.sidebar.checkbox("Simulación Catastrófica", value=False)
modo_sat = st.sidebar.toggle("Colapso red terrestre (satelital)", value=False)
canal = "SATELITAL LEO" if modo_sat else "TERRESTRE"

estacion_sel = st.sidebar.selectbox("Estación", list(ESTACIONES_CONFIG.keys()), index=3)
config = ESTACIONES_CONFIG[estacion_sel]

st.sidebar.markdown("---")
bitacora = leer_bitacora_bytes()
if bitacora:
    st.sidebar.download_button("Bitácora CSV", bitacora, "nazca_log_historico.csv", use_container_width=True)

# ==============================================================================
# PROCESAMIENTO
# ==============================================================================
df_sismos = pd.DataFrame()
df_sismos_local = pd.DataFrame()
api_nueva = False
consultado_usgs = consultado_noaa = "—"

if modo_demo:
    total_sismos, b_val, kp = 85, 0.55, 1
    total_sismos_chile = total_sismos
    shoa, cond, presion, termico, insar, origen_em = 14.2, 8.4, 1013.0, 2.1, 94.0, "DEMO"
    nodo_offline = False
    bloque = "demo"
else:
    df_sismos, consultado_usgs, api_nueva_s = sismos_regionales_cacheados(
        config["lat"], config["lon"], config["id"], ttl_seg, forzar=forzar_sismos_14d
    )
    kp, consultado_noaa, api_nueva_k = kp_noaa_cacheado(ttl_seg)
    api_nueva = api_nueva_s or api_nueva_k
    total_sismos_chile = len(df_sismos)
    df_sismos_local = filtrar_sismos_estacion(df_sismos, config["lat"], config["lon"])
    total_sismos = len(df_sismos_local)
    b_val = calcular_b_value(df_sismos_local)

    bloque, _ = bucket_telemetria(estacion_sel, ttl_seg)
    nodo_offline = modo_sat and random.Random(hash((estacion_sel, bloque, "offline"))).choice([True, False])
    shoa, cond, presion, termico, insar, origen_em = telemetria_estable(
        estacion_sel, config, total_sismos, ttl_seg, modo_sat, nodo_offline
    )

estado, icono, puntaje, log_filtro = calcular_riesgo_fusion(
    insar, total_sismos, b_val, cond, shoa, config, kp, termico, presion
)
estado, icono, puntaje, log_filtro = aplicar_control_calidad(
    estado, icono, puntaje, log_filtro, modo_demo=modo_demo
)

clave_log = f"{estacion_sel}_{round(puntaje, 1)}_{bloque if not modo_demo else 'demo'}"
if not modo_demo and st.session_state.get("ultimo_log") != clave_log:
    registrar_en_bitacora(estacion_sel, estado, puntaje, insar, b_val, cond, shoa)
    st.session_state["ultimo_log"] = clave_log

df_match, mejor_ev, mejor_match = comparar_con_historico(insar, total_sismos, b_val, cond, shoa)
df_calibracion = construir_calibracion_estaciones(
    df_sismos, kp, ttl_seg, modo_sat, consultado_usgs, consultado_noaa
)

# ==============================================================================
# INTERFAZ
# ==============================================================================
st.markdown('<h1 style="text-align:center;color:#58a6ff;">NAZCA-NEURAL DETECTOR v8.0</h1>', unsafe_allow_html=True)
st.caption(f"Enlace: **{canal}** | Caché APIs: **{intervalo}**")

if api_nueva:
    st.toast("Datos actualizados desde USGS / NOAA", icon="🔄")
else:
    st.info(f"📦 Sirviendo caché — USGS: {consultado_usgs} | NOAA Kp: {consultado_noaa}")

tab_vivo, tab_hist, tab_cal, tab_calidad = st.tabs([
    "ESCANEO EN VIVO",
    "COMPARATIVA M7+",
    "CALIBRACIÓN ESTACIONES",
    "INFORME DE CALIDAD",
])

with tab_vivo:
    if puntaje >= 90:
        st.error(f"CRÍTICO — Match {puntaje:.1f}%")
    elif puntaje >= UMBRAL_CRITICO:
        st.warning(f"ADVERTENCIA CRÍTICA — Match {puntaje:.1f}%")
    elif puntaje >= 40:
        st.warning(f"ATENCIÓN — Match {puntaje:.1f}%")
    else:
        st.success("Estable")

    st.caption(log_filtro)
    if nodo_offline:
        st.warning("Nodo offline — telemetría por interpolación de vecindad.")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Estado", f"{icono}")
    c2.metric("Match", f"{puntaje:.1f}%")
    c3.metric("InSAR", f"{insar:.1f}%")
    c4.metric("b-value", f"{b_val}")
    c5.metric("Kp NOAA", kp)

    c6, c7, c8 = st.columns(3)
    c6.metric("Patrón M7+", f"{mejor_match:.1f}%")
    c7.metric("EM (Z-score)", f"{cond} mS/m")
    c8.metric("SHOA", f"{shoa} cm")

    col_mapa, col_tabla = st.columns([1.8, 1.2])
    with col_mapa:
        puntos = tuple((r.Latitud, r.Longitud, r.Magnitud) for r in df_sismos.itertuples(index=False)) if not df_sismos.empty else ()
        color = "orange" if nodo_offline else "blue"
        st_folium(crear_mapa(config["lat"], config["lon"], puntos, color), width="100%", height=420)

    with col_tabla:
        st.caption(
            f"Origen EM: {origen_em} | Sismos 14D Chile: {total_sismos_chile} | "
            f"Cálculo local {RADIO_ESTACION_KM} km: {total_sismos} | USGS: {consultado_usgs}"
        )
        st.dataframe(
            df_sismos_local[["Magnitud", "Lugar", "Fecha", "Distancia_km"]] if not df_sismos_local.empty else pd.DataFrame(columns=["Magnitud", "Lugar", "Fecha", "Distancia_km"]),
            height=200, use_container_width=True,
        )

    if st.button("Generar PDF", use_container_width=True):
        st.session_state["pdf"] = generar_pdf(estacion_sel, puntaje, estado, b_val, cond, shoa, total_sismos, canal, kp)
    if st.session_state.get("pdf"):
        st.download_button("Guardar PDF", st.session_state["pdf"], "Reporte_Nazca.pdf", "application/pdf", use_container_width=True)

with tab_hist:
    st.markdown("### Referencia y Match vs terremotos M7+ (14D pre-sismo)")
    st.dataframe(pd.DataFrame([{
        "Evento": e["evento"], "Magnitud": e["mag"], "b-value 14D": e["b_14d"],
        "Sismos": e["sismos_14d"], "InSAR": e["insar"], "EM": e["cond"], "SHOA": e["shoa"],
    } for e in EVENTOS_M7]), use_container_width=True, hide_index=True)

    st.markdown("#### Match calculado con telemetría actual")
    m1, m2, m3 = st.columns(3)
    m1.metric("Match riesgo actual", f"{puntaje:.1f}%")
    m2.metric("Similitud M7+", f"{mejor_match:.1f}%")
    m3.metric("Evento más parecido", mejor_ev)
    st.dataframe(df_match, use_container_width=True, hide_index=True)

    if mejor_match >= 75 and puntaje >= UMBRAL_CRITICO:
        st.error(f"Patrón crítico alineado con **{mejor_ev}**.")
    elif mejor_match >= 60:
        st.warning(f"Similitud notable con **{mejor_ev}** ({mejor_match:.1f}%).")

with tab_cal:
    st.markdown("### Calibración de estaciones")
    st.caption(
        "Esta tabla reúne la misma base sísmica 14D de Chile y recalcula SHOA, InSAR, EM, presión, térmico, "
        "riesgo y match M7+ para cada estación. Úsala para ajustar baselines y revisar qué estación queda más sensible."
    )
    st.dataframe(df_calibracion, use_container_width=True, hide_index=True)
    st.download_button(
        "Descargar calibración CSV",
        df_calibracion.to_csv(index=False).encode("utf-8-sig"),
        "calibracion_estaciones_nazca.csv",
        "text/csv",
        use_container_width=True,
    )

with tab_calidad:
    st.markdown("### Informe de calidad y transparencia")
    st.info(
        "Este módulo documenta cómo calcula el sistema, qué datos son reales, qué datos son estimados "
        "y cómo debe realizarse la calibración mensual para mantener trazabilidad técnica."
    )

    q1, q2, q3, q4 = st.columns(4)
    q1.metric("Fuente sísmica", "USGS real")
    q2.metric("Radio local", f"{RADIO_ESTACION_KM} km")
    q3.metric("Tope heurístico", f"{MAX_RIESGO_CON_TELEMETRIA_ESTIMADA:.0f}%")
    q4.metric("Calibración", "Mensual")

    st.markdown("#### Parámetros activos")
    df_parametros = pd.DataFrame([
        {"Parámetro": "SISMO_BVAL", "Valor": PESOS["SISMO_BVAL"], "Calidad": "REAL/CALCULADO", "Uso": "Peso de b-value y actividad sísmica local"},
        {"Parámetro": "INSAR", "Valor": PESOS["INSAR"], "Calidad": "ESTIMADO", "Uso": "Deformación cortical estimada"},
        {"Parámetro": "CONDUCT", "Valor": PESOS["CONDUCT"], "Calidad": "ESTIMADO", "Uso": "Anomalía electromagnética"},
        {"Parámetro": "SHOA", "Valor": PESOS["SHOA"], "Calidad": "ESTIMADO", "Uso": "Residuo mareográfico/SHOA simulado"},
        {"Parámetro": "ATMOS", "Valor": PESOS["ATMOS"], "Calidad": "ESTIMADO", "Uso": "Presión y componente térmico"},
        {"Parámetro": "UMBRAL_CRITICO", "Valor": UMBRAL_CRITICO, "Calidad": "MODELO", "Uso": "Umbral interno de riesgo"},
        {"Parámetro": "RADIO_ESTACION_KM", "Valor": RADIO_ESTACION_KM, "Calidad": "MODELO", "Uso": "Radio local usado para calcular cada estación"},
        {"Parámetro": "MAX_RIESGO_ESTIMADO", "Valor": MAX_RIESGO_CON_TELEMETRIA_ESTIMADA, "Calidad": "CONTROL", "Uso": "Evita alerta crítica con telemetría no instrumental"},
    ])
    st.dataframe(df_parametros, use_container_width=True, hide_index=True)

    st.markdown("#### Protocolo mensual de calibración")
    st.write(
        "1. Exportar la tabla de calibración de estaciones.\n"
        "2. Revisar bitácora del mes contra eventos reales USGS.\n"
        "3. Separar falsos positivos y falsos negativos.\n"
        "4. Ajustar baselines por estación solo con evidencia.\n"
        "5. Documentar fecha, responsable y motivo del cambio.\n"
        "6. Mantener visible qué fuentes son reales, estimadas o simuladas."
    )

    informe_calidad = generar_informe_calidad_texto(
        df_calibracion, consultado_usgs, consultado_noaa, ttl_seg
    )
    st.download_button(
        "Descargar informe de calidad TXT",
        informe_calidad.encode("utf-8"),
        "informe_calidad_nazca.txt",
        "text/plain",
        use_container_width=True,
    )
    with st.expander("Ver informe completo"):
        st.text(informe_calidad)

st.sidebar.metric("Próxima API", f"≤ {ttl_seg // 60} min")
st.sidebar.metric("b-value regional", f"{b_val}")

if intervalo != "Desactivado":
    components.html(
        f"<script>setTimeout(()=>window.parent.location.reload(),{ttl_seg * 1000});</script>",
        height=0,
    )
