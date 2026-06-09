import importlib.util
import json
import os
import sys
import random
import base64
import unicodedata
import hashlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components
from fpdf import FPDF

APP_BUILD = "2026-06-08-v8"
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _cargar_modulo_local(nombre, archivo):
    ruta = os.path.join(_BASE_DIR, archivo)
    if not os.path.exists(ruta):
        return None, f"Falta archivo: {archivo}"
    try:
        sys.modules.pop(nombre, None)
        spec = importlib.util.spec_from_file_location(nombre, ruta)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[nombre] = mod
        spec.loader.exec_module(mod)
        return mod, None
    except Exception as exc:
        sys.modules.pop(nombre, None)
        return None, f"Error cargando {archivo}: {exc}"


informes_pdf, _err_informes = _cargar_modulo_local("nazca_informes_pdf", "nazca_informes_pdf.py")
mapa_tect, _err_mapa = _cargar_modulo_local("nazca_mapa_tectonico", "nazca_mapa_tectonico.py")
mundo_lab, _err_mundo = _cargar_modulo_local("nazca_mundo_lab", "nazca_mundo_lab.py")
gnss_mod, _err_gnss = _cargar_modulo_local("nazca_gnss", "nazca_gnss.py")
atmos_mod, _err_atmos = _cargar_modulo_local("nazca_atmosfera", "nazca_atmosfera.py")
cond_mod, _err_cond = _cargar_modulo_local("nazca_conductividad", "nazca_conductividad.py")
shoa_mod, _err_shoa = _cargar_modulo_local("nazca_shoa", "nazca_shoa.py")
alertas, _err_alertas = _cargar_modulo_local("nazca_alertas", "nazca_alertas.py")

# ==============================================================================
# CONFIGURACIÓN
# ==============================================================================
st.set_page_config(page_title=f"NAZCA CORE MONITOR v8.0 · {APP_BUILD}", layout="wide")

if alertas is None:
    st.error(f"No se pudo cargar nazca_alertas.py: {_err_alertas}")
    st.stop()

PESOS = {"SISMO_BVAL": 0.62, "INSAR": 0.18, "CONDUCT": 0.10, "SHOA": 0.06, "ATMOS": 0.01}
UMBRAL_CRITICO = alertas.UMBRAL_CRITICO
UMBRAL_NOTIFICACION_TELEGRAM = alertas.UMBRAL_NOTIFICACION_TELEGRAM
UMBRAL_MATCH_M7_TELEGRAM = alertas.UMBRAL_MATCH_M7_TELEGRAM
COOLDOWN_TELEGRAM_MIN = alertas.COOLDOWN_TELEGRAM_MIN
UMBRAL_SIRENA_ROJA = alertas.UMBRAL_SIRENA_ROJA
RADIO_ESTACION_KM = 350
MAX_RIESGO_CON_TELEMETRIA_ESTIMADA = 74.0
INTERVALOS_API = {"3 horas": 10800, "6 horas": 21600, "12 horas": 43200, "24 horas": 86400}
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".nazca_cache")
LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "nazca_logo.png")
SUSCRIPTORES_TELEGRAM = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nazca_suscriptores_telegram.json")
CANAL_SUSCRIPCION_CHILE = alertas.CANAL_SUSCRIPCION_CHILE
EVIDENCIA_PREEVENTO_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nazca_evidencia_preevento.csv")
CHILE_BOUNDS = {
    "min_lat": -56.0,
    "max_lat": -17.0,
    "min_lon": -76.5,
    "max_lon": -66.0,
}
CHILE_TZ = ZoneInfo("America/Santiago")
CHILE_UTC_OFFSET_HOURS = -4
CHILE_TZ_LABEL = "Chile continental (UTC-4)"


def ahora_chile():
    return datetime.now(CHILE_TZ).replace(tzinfo=None)


def _df_ui(df):
    if informes_pdf and hasattr(informes_pdf, "df_ui_seguro"):
        return informes_pdf.df_ui_seguro(df)
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return df if isinstance(df, pd.DataFrame) else pd.DataFrame()
    out = df.copy()
    for col in out.columns:
        out[col] = out[col].apply(lambda v: "" if pd.isna(v) else str(v))
    return out


def timestamp_usgs_a_chile(timestamp_ms):
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=CHILE_TZ).strftime("%Y-%m-%d %H:%M")


def fecha_evidencia_a_chile(fecha_valor, zona_horaria=None):
    ts = pd.to_datetime(fecha_valor, errors="coerce")
    if pd.isna(ts):
        return pd.NaT
    zona = str(zona_horaria or "").strip()
    if zona in (CHILE_TZ_LABEL, "America/Santiago"):
        return ts
    return ts - timedelta(hours=4)

st.markdown(
    """
    <style>
    .stApp { background-color: #0d1117; color: #c9d1d9; }
    .metric-card {
        background: linear-gradient(145deg, #161b22, #0d1117);
        border: 1px solid #30363d; border-radius: 12px;
        padding: 20px; margin-bottom: 10px;
    }
    .nazca-header {
        display: flex;
        justify-content: flex-start;
        align-items: center;
        gap: 34px;
        padding: 34px 42px 30px 42px;
        margin: 4px 0 20px 0;
        border: 1px solid rgba(88, 166, 255, .28);
        border-radius: 24px;
        background:
            radial-gradient(circle at 12% 45%, rgba(0,245,255,.22), transparent 22%),
            linear-gradient(135deg, #07111d 0%, #0d1117 45%, #061827 100%);
        box-shadow: 0 0 38px rgba(88, 166, 255, .12);
    }
    .nazca-logo {
        width: 156px;
        height: 156px;
        object-fit: contain;
        filter: drop-shadow(0 0 28px rgba(0, 245, 255, .34));
    }
    .nazca-title {
        font-family: 'Courier New', monospace;
        line-height: 1.08;
    }
    .nazca-title h1 {
        color: #58a6ff;
        margin: 0;
        letter-spacing: 4px;
        font-size: 3.25rem;
        text-shadow: 0 0 18px rgba(88, 166, 255, .26);
    }
    .nazca-title span {
        display: block;
        color: #c9d1d9;
        font-size: 1.05rem;
        letter-spacing: 3.5px;
        margin-top: 12px;
    }
    .nazca-title p {
        color: #8b949e;
        margin: 16px 0 0 0;
        max-width: 780px;
        font-size: 1.02rem;
        letter-spacing: .5px;
    }
    .nazca-badge {
        display: inline-block;
        margin-top: 14px;
        padding: 7px 12px;
        border: 1px solid rgba(0,245,255,.45);
        border-radius: 999px;
        color: #00f5ff;
        background: rgba(0,245,255,.07);
        font-size: .82rem;
        letter-spacing: 1.8px;
    }
    .nazca-credit {
        display: block;
        margin-top: 10px;
        color: #58a6ff;
        font-size: .84rem;
        letter-spacing: 1.4px;
        opacity: .92;
    }
    .nazca-footer {
        margin-top: 32px;
        padding: 18px;
        text-align: center;
        border-top: 1px solid rgba(88,166,255,.22);
        color: #8b949e;
        font-family: 'Courier New', monospace;
        font-size: .86rem;
        letter-spacing: 1px;
    }
    h1, h2, h3 { font-family: 'Courier New', monospace !important; }
    </style>
    """,
    unsafe_allow_html=True,
)


def cargar_logo_base64():
    try:
        with open(LOGO_PATH, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except OSError:
        return ""

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

ESCENARIO_DEMO_CATASTROFICO = {
    "estacion": "Coquimbo / Illapel (85540)",
    "evento_ref": "Terremoto Illapel 2015",
    "mag_ref": "M8.3",
    "descripcion": (
        "Ejemplo didáctico: estación Coquimbo–Illapel con firma de 14 días previa al M8.3 de 2015. "
        "Cumple umbrales de alerta experimental. No es predicción ni alerta oficial."
    ),
    "b_value": 0.64,
    "sismos_locales_14d": 44,
    "sismos_chile_14d": 52,
    "insar": 94.0,
    "cond": 4.2,
    "shoa": 5.0,
    "presion": 1012.8,
    "termico": 2.1,
    "kp": 1,
    "consultado_usgs": "DEMO · ventana 14D ficticia (Illapel 2015)",
    "consultado_noaa": "DEMO · Kp simulado",
}

ESCENARIO_DEMO_MUNDO = {
    "nodo": "Filipinas · Mindanao (complejo)",
    "evento_ref": "Mindanao 2026",
    "mag_ref": "M7.8",
    "descripcion": (
        "Ejemplo didáctico mundial: nodo Filipinas–Mindanao con firma previa al evento de referencia. "
        "Simulación LAB — no es alerta oficial."
    ),
    "b_value": 0.67,
    "sismos_locales_14d": 31,
    "insar": 82.0,
    "cond": 4.1,
    "shoa": 14.0,
}

# ==============================================================================
# CACHÉ EN DISCO (APIs en ventana móvil 14D, refresco recomendado cada 3-24 h)
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
        vigente = ahora_chile() <= expira
        return datos["payload"], datos.get("consultado"), expira, vigente
    except (json.JSONDecodeError, KeyError, ValueError):
        return None, None, None, False


def leer_cache(clave, ttl_seg):
    payload, consultado, _, vigente = leer_cache_detalle(clave)
    if vigente:
        return payload, consultado
    return None, consultado


def guardar_cache(clave, payload, ttl_seg):
    ahora = ahora_chile()
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
        return payload_nuevo, ahora_chile().strftime("%Y-%m-%d %H:%M:%S"), True

    # Si USGS/NOAA falla, mantenemos la última lectura buena para no dejar el sistema sin cálculo.
    if payload_cache is not None:
        return payload_cache, f"{consultado} (caché anterior)", False
    return [] if clave.startswith("sismos_") else 0, None, False


def bucket_telemetria(estacion, ttl_seg):
    return int(ahora_chile().timestamp() // ttl_seg), estacion

# ==============================================================================
# APIs (solo invocadas cuando la caché expira)
# ==============================================================================
def _fetch_sismos_regionales(lat, lon, dias=14):
    inicio = (ahora_chile() - timedelta(days=dias)).strftime("%Y-%m-%d")
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
                    "Fecha": timestamp_usgs_a_chile(p["time"]),
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
    texto = "" if texto is None else str(texto)
    reemplazos = {
        "🟢": "",
        "🟡": "",
        "🟠": "",
        "🔴": "",
        "🚨": "",
        "⚠️": "",
        "✅": "",
        "🛰️": "",
        "🌐": "",
        "—": "-",
        "–": "-",
        "―": "-",
        "−": "-",
        "‐": "-",
        "‑": "-",
        "·": "-",
        "≤": "<=",
        "≥": ">=",
        "±": "+/-",
        "Δ": "Delta",
        "σ": "sigma",
        "í": "i",
        "Í": "I",
        "ó": "o",
        "Ó": "O",
        "á": "a",
        "Á": "A",
        "é": "e",
        "É": "E",
        "ú": "u",
        "Ú": "U",
        "ñ": "n",
        "Ñ": "N",
    }
    for original, seguro in reemplazos.items():
        texto = texto.replace(original, seguro)
    texto = unicodedata.normalize("NFKD", texto)
    return texto.encode("ascii", errors="ignore").decode("ascii")


def registrar_en_bitacora(estacion, estado, puntaje, insar, b_val, cond, shoa):
    reg = pd.DataFrame([{
        "Fecha_Hora": ahora_chile().strftime("%Y-%m-%d %H:%M:%S"),
        "Estacion": estacion, "Estado": estado, "Criticidad_%": puntaje,
        "InSAR_%": insar, "b-value_14D": b_val, "EM_mS/m": cond, "SHOA_cm": shoa,
    }])
    archivo = "nazca_log_historico.csv"
    reg.to_csv(archivo, index=False, mode="a", header=not os.path.exists(archivo))


def hash_evidencia(payload):
    base = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:16]


def registrar_evidencia_preevento(
    estacion, config, estado, puntaje, nivel_alerta, mejor_ev, mejor_match,
    total_sismos, total_sismos_chile, b_val, insar, cond, shoa, presion,
    termico, kp, consultado_usgs, consultado_noaa, origen_em, log_filtro,
):
    ahora = ahora_chile()
    payload = {
        "fecha_hora": ahora.strftime("%Y-%m-%d %H:%M:%S"),
        "estacion": estacion,
        "lat": config["lat"],
        "lon": config["lon"],
        "estado": estado,
        "nivel": nivel_alerta["nivel"],
        "ventana": nivel_alerta["ventana"],
        "puntaje": round(float(puntaje), 2),
        "match_m7": round(float(mejor_match), 2),
        "patron_m7": mejor_ev,
        "sismos_locales_14d": int(total_sismos),
        "sismos_chile_14d": int(total_sismos_chile),
        "b_value": b_val,
        "insar": round(float(insar), 2),
        "em": round(float(cond), 2),
        "shoa": round(float(shoa), 2),
        "presion": round(float(presion), 2),
        "termico": round(float(termico), 2),
        "kp_noaa": int(kp),
        "consultado_usgs": consultado_usgs,
        "consultado_noaa": consultado_noaa,
        "origen_telemetria": origen_em,
        "log_modelo": log_filtro,
        "modelo": "NAZCA_CORE_MONITOR_v8.0",
        "zona_horaria": CHILE_TZ_LABEL,
    }
    payload["hash_evidencia"] = hash_evidencia(payload)
    reg = pd.DataFrame([payload])
    reg.to_csv(EVIDENCIA_PREEVENTO_CSV, index=False, mode="a", header=not os.path.exists(EVIDENCIA_PREEVENTO_CSV))
    return payload["hash_evidencia"]


def leer_evidencia_preevento():
    if not os.path.exists(EVIDENCIA_PREEVENTO_CSV):
        return pd.DataFrame()
    try:
        df = pd.read_csv(EVIDENCIA_PREEVENTO_CSV)
        if "fecha_hora" in df.columns:
            zonas = df["zona_horaria"] if "zona_horaria" in df.columns else None
            df["fecha_hora_dt"] = [
                fecha_evidencia_a_chile(f, z if zonas is not None else None)
                for f, z in zip(
                    df["fecha_hora"],
                    zonas if zonas is not None else [None] * len(df),
                )
            ]
            df["fecha_hora"] = pd.to_datetime(df["fecha_hora_dt"], errors="coerce").dt.strftime("%Y-%m-%d %H:%M:%S")
        return df
    except (OSError, pd.errors.EmptyDataError, pd.errors.ParserError):
        return pd.DataFrame()


def eventos_usgs_validacion(df_sismos, magnitud_min=5.0):
    if df_sismos.empty:
        return pd.DataFrame(columns=["Magnitud", "Lugar", "Latitud", "Longitud", "Fecha", "fecha_dt"])
    eventos = df_sismos.copy()
    eventos["fecha_dt"] = pd.to_datetime(eventos["Fecha"], errors="coerce")
    eventos = eventos[eventos["Magnitud"] >= magnitud_min].dropna(subset=["fecha_dt"])
    return eventos.sort_values("fecha_dt", ascending=False)


def evaluar_coincidencias_evidencia(df_evidencia, df_eventos, horas_previas=336, radio_km=RADIO_ESTACION_KM):
    if df_evidencia.empty or df_eventos.empty:
        return pd.DataFrame()
    filas = []
    for _, ev in df_eventos.iterrows():
        for _, snap in df_evidencia.dropna(subset=["fecha_hora_dt"]).iterrows():
            delta_horas = (ev["fecha_dt"] - snap["fecha_hora_dt"]).total_seconds() / 3600
            if delta_horas < 0 or delta_horas > horas_previas:
                continue
            distancia = distancia_km(float(snap["lat"]), float(snap["lon"]), float(ev["Latitud"]), float(ev["Longitud"]))
            if distancia > radio_km:
                continue
            nivel = str(snap.get("nivel", "VERDE"))
            match = float(snap.get("match_m7", 0) or 0)
            puntaje = float(snap.get("puntaje", 0) or 0)
            if nivel not in ("AMARILLO", "NARANJO", "ROJO") and match < 65 and puntaje < 55:
                continue
            filas.append({
                "Evento real": ev["Lugar"],
                "Magnitud": ev["Magnitud"],
                "Fecha evento": ev["Fecha"],
                "Estación previa": snap["estacion"],
                "Fecha evidencia": snap["fecha_hora"],
                "Anticipación horas": round(delta_horas, 1),
                "Anticipación días": round(delta_horas / 24, 2),
                "Distancia km": round(distancia, 1),
                "Nivel previo": nivel,
                "Índice previo %": puntaje,
                "Match M7+ previo %": match,
                "b-value previo": snap.get("b_value"),
                "Sismos locales 14D": snap.get("sismos_locales_14d"),
                "Hash evidencia": snap.get("hash_evidencia"),
            })
    return pd.DataFrame(filas).sort_values(["Fecha evento", "Anticipación horas"], ascending=[False, True]) if filas else pd.DataFrame()


def generar_informe_validacion_texto(coincidencias):
    fecha = ahora_chile().strftime("%Y-%m-%d %H:%M:%S")
    if coincidencias.empty:
        return (
            "INFORME DE VALIDACION POST-EVENTO - NAZCA CORE MONITOR\n"
            f"Generado: {fecha}\n\n"
            "No se encontraron coincidencias entre eventos USGS y evidencia previa guardada bajo los criterios actuales.\n"
        )
    filas = []
    for _, row in coincidencias.iterrows():
        filas.append(
            f"- Evento {row['Magnitud']} | {row['Evento real']} | evento {row['Fecha evento']} | "
            f"evidencia {row['Fecha evidencia']} | anticipacion {row['Anticipación días']} dias | "
            f"estacion {row['Estación previa']} | nivel {row['Nivel previo']} | "
            f"indice {row['Índice previo %']}% | match {row['Match M7+ previo %']}% | "
            f"hash {row['Hash evidencia']}"
        )
    return f"""INFORME DE VALIDACION POST-EVENTO - NAZCA CORE MONITOR
Generado: {fecha}
Uso: evidencia privada para revision tecnica. No corresponde a prediccion oficial.

Resumen:
- Coincidencias encontradas: {len(coincidencias)}
- Criterio temporal: evidencia registrada antes del evento dentro de 14 dias.
- Criterio espacial: evento dentro de {RADIO_ESTACION_KM} km de la estacion.
- Criterio de activacion: nivel amarillo/naranjo/rojo, match >= 65% o indice >= 55%.

Coincidencias:
{chr(10).join(filas)}

Transparencia:
Cada fila contiene un hash de evidencia generado al momento del snapshot para fortalecer trazabilidad.
La validacion debe revisarse junto a falsos positivos, falsos negativos, fuentes disponibles y cambios de modelo.
"""


@st.cache_data(ttl=30)
def leer_bitacora_bytes():
    if os.path.exists("nazca_log_historico.csv"):
        with open("nazca_log_historico.csv", "rb") as f:
            return f.read()
    return None


def obtener_secret(nombre):
    valor = str(os.environ.get(nombre, "") or "").strip()
    if valor:
        return valor
    try:
        return str(st.secrets.get(nombre, "") or "").strip()
    except Exception:
        return ""


def telegram_configurado():
    return bool(obtener_secret("TELEGRAM_TOKEN") and obtener_secret("TELEGRAM_CHAT_ID"))


def normalizar_suscriptores(suscriptores):
    normalizados = []
    vistos = set()
    for sub in suscriptores:
        if not isinstance(sub, dict):
            continue
        chat_id = str(sub.get("chat_id", "")).strip()
        if not chat_id or chat_id in vistos:
            continue
        vistos.add(chat_id)
        normalizados.append({
            "nombre": sanitizar_texto(sub.get("nombre", "Suscriptor")).strip() or "Suscriptor",
            "chat_id": chat_id,
            "estacion": sub.get("estacion", "Todas"),
            "nivel_minimo": sub.get("nivel_minimo", "AMARILLO"),
            "activo": bool(sub.get("activo", True)),
            "registrado": sub.get("registrado", "secrets"),
            "canal": str(sub.get("canal", CANAL_SUSCRIPCION_CHILE) or CANAL_SUSCRIPCION_CHILE).strip().lower(),
        })
    return normalizados


def cargar_suscriptores_chile():
    return [
        sub for sub in cargar_suscriptores_telegram()
        if sub.get("canal", CANAL_SUSCRIPCION_CHILE) == CANAL_SUSCRIPCION_CHILE
    ]


def apps_script_configurado():
    return bool(obtener_secret("SUBSCRIBERS_WEBAPP_URL") and obtener_secret("SUBSCRIBERS_API_KEY"))


def llamar_apps_script(payload):
    url = obtener_secret("SUBSCRIBERS_WEBAPP_URL")
    api_key = obtener_secret("SUBSCRIBERS_API_KEY")
    if not url or not api_key:
        return None, "Google Apps Script no configurado."
    try:
        res = requests.post(
            url,
            json={**payload, "api_key": api_key},
            timeout=12,
        )
        if res.status_code != 200:
            return None, f"Apps Script HTTP {res.status_code}: {res.text[:160]}"
        datos = res.json()
        if not datos.get("ok"):
            return None, datos.get("error", "Apps Script rechazo la solicitud.")
        return datos, "OK"
    except (requests.RequestException, ValueError) as exc:
        return None, f"Error Apps Script: {exc}"


def cargar_suscriptores_apps_script():
    datos, _ = llamar_apps_script({"action": "list"})
    if not datos:
        return []
    return normalizar_suscriptores(datos.get("subscribers", []))


def guardar_suscriptor_apps_script(suscriptor):
    datos, msg = llamar_apps_script({"action": "upsert", "subscriber": suscriptor})
    return bool(datos), msg


def enviar_telegram(mensaje, chat_id=None):
    token = obtener_secret("TELEGRAM_TOKEN")
    destino = str(chat_id or obtener_secret("TELEGRAM_CHAT_ID") or "").strip()
    if not token:
        return False, "Falta TELEGRAM_TOKEN en secrets (.streamlit/secrets.toml o Streamlit Cloud)."
    if not destino:
        return False, "Falta chat_id destino o TELEGRAM_CHAT_ID en secrets."
    try:
        res = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": destino,
                "text": sanitizar_texto(mensaje),
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        if res.status_code == 200:
            return True, "Notificacion enviada."
        return False, f"Telegram HTTP {res.status_code}: {res.text[:160]}"
    except requests.RequestException as exc:
        return False, f"Error Telegram: {exc}"


def cargar_suscriptores_telegram():
    suscriptores = []
    suscriptores.extend(cargar_suscriptores_apps_script())

    secretos_json = obtener_secret("TELEGRAM_SUBSCRIBERS_JSON")
    if secretos_json:
        try:
            datos_secretos = json.loads(secretos_json)
            if isinstance(datos_secretos, list):
                suscriptores.extend(datos_secretos)
        except json.JSONDecodeError:
            pass

    if not os.path.exists(SUSCRIPTORES_TELEGRAM):
        return normalizar_suscriptores(suscriptores)
    try:
        with open(SUSCRIPTORES_TELEGRAM, "r", encoding="utf-8") as f:
            datos = json.load(f)
        if isinstance(datos, list):
            suscriptores.extend(datos)
    except (json.JSONDecodeError, OSError):
        pass
    return normalizar_suscriptores(suscriptores)


def guardar_suscriptores_telegram(suscriptores):
    with open(SUSCRIPTORES_TELEGRAM, "w", encoding="utf-8") as f:
        json.dump(suscriptores, f, ensure_ascii=False, indent=2)


def upsert_suscriptor_telegram(nombre, chat_id, estacion, nivel_minimo):
    nombre = sanitizar_texto(nombre).strip() or "Suscriptor"
    chat_id = str(chat_id).strip()
    suscriptores = cargar_suscriptores_telegram()
    nuevo = {
        "nombre": nombre,
        "chat_id": chat_id,
        "estacion": estacion,
        "nivel_minimo": nivel_minimo,
        "activo": True,
        "registrado": ahora_chile().strftime("%Y-%m-%d %H:%M:%S"),
        "canal": CANAL_SUSCRIPCION_CHILE,
    }
    actualizados = []
    reemplazado = False
    for sub in suscriptores:
        if str(sub.get("chat_id")) == chat_id:
            actualizados.append({**sub, **nuevo})
            reemplazado = True
        else:
            actualizados.append(sub)
    if not reemplazado:
        actualizados.append(nuevo)
    guardar_suscriptores_telegram(actualizados)
    if apps_script_configurado():
        guardar_suscriptor_apps_script(nuevo)
    return nuevo


def nivel_valor(nombre_nivel):
    orden = {"VERDE": 0, "AMARILLO": 1, "NARANJO": 2, "ROJO": 3}
    return orden.get(str(nombre_nivel).upper(), 0)


def enviar_alerta_suscriptores(mensaje, estacion_actual, nivel_alerta, modo_demo):
    if modo_demo:
        return "Modo demo: suscriptores no notificados."
    enviados = 0
    errores = 0
    for sub in cargar_suscriptores_chile():
        if not sub.get("activo", True):
            continue
        estacion_sub = sub.get("estacion", "Todas")
        if estacion_sub not in ("Todas", estacion_actual):
            continue
        if nivel_valor(nivel_alerta["nivel"]) < nivel_valor(sub.get("nivel_minimo", "AMARILLO")):
            continue
        ok, _ = enviar_telegram(mensaje, chat_id=sub.get("chat_id"))
        enviados += 1 if ok else 0
        errores += 0 if ok else 1
    return f"Suscriptores Chile notificados: {enviados} | errores: {errores}"


def enviar_prueba_suscriptores(mensaje):
    enviados = 0
    errores = 0
    for sub in cargar_suscriptores_chile():
        if not sub.get("activo", True):
            continue
        ok, _ = enviar_telegram(mensaje, chat_id=sub.get("chat_id"))
        enviados += 1 if ok else 0
        errores += 0 if ok else 1
    return enviados, errores


def contar_suscriptores_activos():
    return sum(1 for sub in cargar_suscriptores_chile() if sub.get("activo", True))


class _SessionCooldown(alertas.CooldownStore):
    def __init__(self, session_state):
        self._ss = session_state

    def get(self, clave):
        raw = self._ss.get(clave)
        if not raw:
            return None
        if isinstance(raw, datetime):
            return raw
        try:
            return datetime.fromisoformat(str(raw))
        except ValueError:
            return None

    def set(self, clave, cuando=None):
        self._ss[clave] = cuando or ahora_chile()


def debe_notificar_telegram(estacion, mejor_ev, puntaje, mejor_match, modo_demo, b_val, total_sismos, insar):
    cooldown = _SessionCooldown(st.session_state)
    disparar, detalle, clave = alertas.evaluar_disparo_telegram(
        estacion, mejor_ev, puntaje, mejor_match, b_val, total_sismos, insar, modo_demo, cooldown
    )
    if disparar:
        return True, clave, detalle
    return False, detalle, ""


def construir_mensaje_telegram(*args, **kwargs):
    return alertas.construir_mensaje_telegram(*args, **kwargs)


def clasificar_nivel_alerta(puntaje, mejor_match, b_val, total_sismos, insar=0.0):
    return alertas.clasificar_nivel_alerta(puntaje, mejor_match, b_val, total_sismos, insar)


def render_sirena_alerta(duracion_seg=6):
    """Alerta visual + tono de sirena en el navegador (Web Audio API)."""
    st.error("SIRENA LOCAL: vigilancia roja experimental. Validar con fuentes oficiales.")
    components.html(
        f"""
        <script>
        (function () {{
          const DUR = {int(duracion_seg)};
          const AC = window.AudioContext || window.webkitAudioContext;
          if (!AC) return;
          const ctx = new AC();
          function tocar() {{
            const gain = ctx.createGain();
            gain.gain.value = 0.28;
            gain.connect(ctx.destination);
            const osc = ctx.createOscillator();
            osc.type = "square";
            osc.connect(gain);
            const t0 = ctx.currentTime;
            osc.start(t0);
            for (let i = 0; i < DUR * 2; i++) {{
              osc.frequency.setValueAtTime(i % 2 ? 720 : 980, t0 + i * 0.42);
            }}
            osc.stop(t0 + DUR);
            setTimeout(function () {{ ctx.close(); }}, (DUR + 0.6) * 1000);
          }}
          if (ctx.state === "suspended") {{
            ctx.resume().then(tocar).catch(tocar);
          }} else {{
            tocar();
          }}
        }})();
        </script>
        """,
        height=0,
    )


def _entorno_streamlit_cloud():
    env = os.environ.get("STREAMLIT_RUNTIME_ENV", "").lower()
    return env in ("cloud", "community", "production") or bool(os.environ.get("STREAMLIT_SHARING"))


def _usar_mapa_nativo(modo_demo=False):
    # pydeck provoca removeChild en navegador/Cloud; st.map es estable.
    # Solo usar pydeck en local si defines NAZCA_USAR_PYDECK=1
    if os.environ.get("NAZCA_USAR_PYDECK", "").strip() == "1" and not _entorno_streamlit_cloud():
        return False
    return True


def _render_mapa_st_map_nativo(df_sismos, est_lat, est_lon, zoom=4):
    filas = []
    if est_lat is not None and est_lon is not None:
        filas.append({"lat": est_lat, "lon": est_lon})
    if df_sismos is not None and not df_sismos.empty:
        for _, r in df_sismos.iterrows():
            filas.append({
                "lat": float(r["Latitud"] if "Latitud" in r else r["lat"]),
                "lon": float(r["Longitud"] if "Longitud" in r else r["lon"]),
            })
    if mapa_tect:
        mapa_tect.st_map_minimo(filas, zoom=zoom)
    elif filas:
        st.map(pd.DataFrame(filas), latitude="lat", longitude="lon")
    else:
        st.caption("Sin datos para mapa.")
    st.caption("Mapa simplificado — un solo mapa en Escaneo en vivo (estable en Cloud).")


def distancia_km(lat1, lon1, lat2, lon2):
    radio_tierra = 6371.0
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return float(2 * radio_tierra * np.arcsin(np.sqrt(a)))


# ==============================================================================
# MUNDO LAB + MAPA TECTÓNICO INLINE (funciona aunque falten .py auxiliares en Cloud)
# ==============================================================================
_ANILLO_FUEGO_PATHS = [
    {"path": [[-175, 51], [-165, 55], [-155, 59], [-145, 61], [-135, 58]], "color": [255, 90, 40, 210], "ancho": 4},
    {"path": [[155, 52], [148, 44], [143, 39], [139, 35]], "color": [255, 90, 40, 210], "ancho": 4},
    {"path": [[126, 8], [119, -1], [108, -9], [100, -13], [96, -15]], "color": [255, 90, 40, 210], "ancho": 4},
    {"path": [[176, -18], [178, -22], [179, -26]], "color": [255, 90, 40, 210], "ancho": 4},
    {"path": [[-178, -30], [-176, -34], [-174, -38], [-172, -42]], "color": [255, 90, 40, 210], "ancho": 4},
    {"path": [[-81, -4], [-77, -12], [-74, -24], [-72, -36], [-74, -48], [-75, -52]], "color": [255, 90, 40, 210], "ancho": 4},
    {"path": [[-108, 16], [-98, 7], [-90, 1], [-84, -5]], "color": [255, 90, 40, 210], "ancho": 4},
    {"path": [[-132, 54], [-122, 42], [-115, 30]], "color": [255, 90, 40, 210], "ancho": 4},
]

_CATALOGO_MUNDO = [
    {"region": "Japón", "evento": "Tohoku 2011", "mag": "M9.0", "b_14d": 0.55, "sismos": 72, "insar": 98.0},
    {"region": "Indonesia", "evento": "Aceh 2004", "mag": "M9.1", "b_14d": 0.54, "sismos": 78, "insar": 97.0},
    {"region": "Alaska", "evento": "Alaska 1964", "mag": "M9.2", "b_14d": 0.52, "sismos": 58, "insar": 95.0},
    {"region": "Filipinas", "evento": "Mindanao 2026", "mag": "M7.8", "b_14d": 0.67, "sismos": 31, "insar": 82.0},
    {"region": "Filipinas", "evento": "Bohol 2013", "mag": "M7.2", "b_14d": 0.74, "sismos": 22, "insar": 71.0},
    {"region": "Turquía", "evento": "Kahramanmaras 2023", "mag": "M7.8", "b_14d": 0.70, "sismos": 40, "insar": 72.0},
    {"region": "Nepal", "evento": "Nepal 2015", "mag": "M7.8", "b_14d": 0.59, "sismos": 18, "insar": 92.0},
    {"region": "Nueva Zelanda", "evento": "Kaikoura 2016", "mag": "M7.8", "b_14d": 0.69, "sismos": 44, "insar": 74.0},
    {"region": "México", "evento": "Michoacán 1985", "mag": "M8.0", "b_14d": 0.61, "sismos": 47, "insar": 91.0},
    {"region": "Perú", "evento": "Pisco 2007", "mag": "M8.0", "b_14d": 0.66, "sismos": 38, "insar": 88.0},
    {"region": "California", "evento": "Ridgecrest 2019", "mag": "M7.1", "b_14d": 0.78, "sismos": 48, "insar": 65.0},
    {"region": "Taiwán", "evento": "Ji-Ji 1999", "mag": "M7.7", "b_14d": 0.64, "sismos": 39, "insar": 85.0},
    {"region": "Islandia", "evento": "Reykjanes 2024", "mag": "M6.8", "b_14d": 0.85, "sismos": 55, "insar": 55.0},
]

_NODOS_MUNDO_INLINE = {
    "Filipinas · Mindanao": {"pais": "Filipinas", "lat": 6.20, "lon": 125.10},
    "Japón · Tohoku": {"pais": "Japón", "lat": 38.25, "lon": 142.35},
    "Indonesia · Sumatra": {"pais": "Indonesia", "lat": 3.30, "lon": 95.85},
    "Turquía · Anatolia": {"pais": "Turquía", "lat": 37.20, "lon": 37.00},
    "Nepal · Himalaya": {"pais": "Nepal", "lat": 28.15, "lon": 84.00},
    "California · San Andreas": {"pais": "EE.UU.", "lat": 36.10, "lon": -120.30},
    "Nueva Zelanda · Kaikoura": {"pais": "Nueva Zelanda", "lat": -42.40, "lon": 173.70},
    "Islandia · Reykjanes": {"pais": "Islandia", "lat": 63.90, "lon": -22.50},
}


def _color_mag_inline(mag):
    if mag >= 6.0:
        return [239, 68, 68, 210]
    if mag >= 4.5:
        return [250, 204, 21, 200]
    return [74, 222, 128, 210]


def _render_mapa_anillo_fuego(
    df_sismos, est_lat, est_lon, label, zoom=3, altura=400, df_etiquetas=None, modo_demo=False,
    mapa_principal=False,
):
    mapa_nativo = _usar_mapa_nativo(modo_demo)
    if mapa_nativo and not mapa_principal:
        st.info(
            "En la web publica el mapa interactivo se muestra solo en **Escaneo en vivo** "
            "(evita errores del navegador). Revisa la tabla de sismos aqui abajo."
        )
        vista = df_etiquetas if df_etiquetas is not None and not df_etiquetas.empty else df_sismos
        if vista is not None and not vista.empty:
            cols = [c for c in ("Magnitud", "Lugar", "Fecha", "lat", "lon", "Latitud", "Longitud") if c in vista.columns]
            if cols:
                st.dataframe(_df_ui(vista[cols].head(15)), use_container_width=True, hide_index=True)
        return
    if mapa_nativo:
        _render_mapa_st_map_nativo(df_sismos, est_lat, est_lon, zoom=zoom)
        return
    if mapa_tect:
        mapa_tect.render_mapa_tectonico(
            df_sismos=df_sismos, df_etiquetas=df_etiquetas,
            estacion_lat=est_lat, estacion_lon=est_lon,
            estacion_label=label, lat_center=est_lat, lon_center=est_lon,
            zoom=zoom, altura=altura, mostrar_anillo=True,
            max_etiquetas=15 if zoom <= 3 else 12,
            mapa_nativo=False,
        )
        st.caption(mapa_tect.leyenda_mapa_tectonico())
        return
    try:
        import pydeck as pdk
    except ImportError:
        st.warning("Instala pydeck (requirements.txt) para ver el Anillo de Fuego.")
        if not df_sismos.empty:
            sm = df_sismos.rename(columns={"Latitud": "lat", "Longitud": "lon"})
            st.map(sm, latitude="lat", longitude="lon", zoom=zoom)
        return
    sismos = []
    if df_sismos is not None and not df_sismos.empty:
        for _, r in df_sismos.iterrows():
            mag = float(r.get("Magnitud", r.get("mag", 4.5)))
            lugar = str(r.get("Lugar", r.get("lugar", "")))
            fecha = str(r.get("Fecha", r.get("fecha", "")))
            sismos.append({
                "lon": float(r["Longitud"] if "Longitud" in r else r["lon"]),
                "lat": float(r["Latitud"] if "Latitud" in r else r["lat"]),
                "mag": mag, "lugar": lugar, "fecha": fecha,
                "radio": (max(mag, 2.5) ** 2) * 1800,
                "color": _color_mag_inline(mag),
                "label": "Sismo USGS",
            })
    capas = [pdk.Layer(
        "PathLayer", data=_ANILLO_FUEGO_PATHS, get_path="path", get_color="color",
        get_width="ancho", width_min_pixels=2, pickable=False, auto_highlight=False,
    )]
    if sismos:
        capas.append(pdk.Layer(
            "ScatterplotLayer", data=sismos, get_position=["lon", "lat"], get_radius="radio",
            get_fill_color="color", pickable=True, opacity=0.82, stroked=True,
            get_line_color=[255, 255, 255, 80], line_width_min_pixels=1,
        ))
        fuente_etiquetas = []
        if df_etiquetas is not None and not df_etiquetas.empty:
            for _, r in df_etiquetas.iterrows():
                mag = float(r.get("Magnitud", r.get("mag", 4.5)))
                fuente_etiquetas.append({
                    "lon": float(r["Longitud"] if "Longitud" in r else r["lon"]),
                    "lat": float(r["Latitud"] if "Latitud" in r else r["lat"]),
                    "mag": mag,
                    "lugar": str(r.get("Lugar", r.get("lugar", ""))),
                    "fecha": str(r.get("Fecha", r.get("fecha", ""))),
                })
        etiquetas_src = fuente_etiquetas or sismos
        etiquetas = []
        for item in sorted(etiquetas_src, key=lambda x: x.get("fecha", ""), reverse=True)[:15]:
            lugar_corto = item["lugar"].split(" of ")[-1].split(",")[0].strip() if item["lugar"] else "Sin lugar"
            if len(lugar_corto) > 34:
                lugar_corto = lugar_corto[:33] + "…"
            etiquetas.append({
                "lon": item["lon"], "lat": item["lat"],
                "etiqueta": f"M{item['mag']:.1f} · {lugar_corto}",
            })
        if etiquetas:
            capas.append(pdk.Layer(
                "TextLayer", data=etiquetas, get_position=["lon", "lat"], get_text="etiqueta",
                get_size=13, get_color=[235, 235, 245, 240], get_text_anchor="start",
                get_alignment_baseline="bottom", get_pixel_offset=[10, -12],
            ))
    if est_lat is not None:
        capas.append(pdk.Layer("ScatterplotLayer", data=[{"lon": est_lon, "lat": est_lat, "radio": 28000, "color": [59, 130, 246, 255]}],
                                 get_position=["lon", "lat"], get_radius="radio", get_fill_color="color"))
    deck = pdk.Deck(
        layers=capas,
        initial_view_state=pdk.ViewState(latitude=est_lat or 10, longitude=est_lon or 120, zoom=zoom),
        map_style=None,
        tooltip={
            "html": "<b>Sismo USGS</b><br/>Magnitud: <b>M{mag}</b><br/>{lugar}<br/>{fecha}",
            "style": {"backgroundColor": "#161b22", "color": "#c9d1d9"},
        },
    )
    if mapa_tect:
        mapa_tect.pydeck_chart_compat(deck, altura=altura)
    else:
        st.pydeck_chart(deck, height=altura, use_container_width=True)
    st.caption("🟠 Cinturón de Fuego · 🔴 M6+ · 🟡 M4.5–5.9 · 🟢 M<4.5 · Tooltip USGS · 🔵 nodo activo")


def _fetch_usgs_global_inline():
    inicio = (ahora_chile() - timedelta(days=14)).strftime("%Y-%m-%d")
    url = (
        "https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson"
        f"&starttime={inicio}&minmagnitude=4.5&orderby=time&limit=500"
    )
    try:
        res = requests.get(url, timeout=15)
        if res.status_code == 200:
            filas = []
            for f in res.json().get("features", []):
                p, c = f["properties"], f["geometry"]["coordinates"]
                if -56 <= c[1] <= -17 and -76.5 <= c[0] <= -66:
                    continue
                filas.append({
                    "Magnitud": float(p.get("mag") or 0), "Lugar": p.get("place", ""),
                    "Latitud": c[1], "Longitud": c[0],
                    "Fecha": timestamp_usgs_a_chile(p["time"]),
                })
            return pd.DataFrame(filas)
    except requests.RequestException:
        pass
    return pd.DataFrame()


def _render_mundo_lab_inline(admin_activo, nodo_sel, ttl_seg, modo_demo):
    st.markdown("### 🌍 NAZCA MUNDO LAB (inline v4)")
    st.success(f"Build **{APP_BUILD}** — Catálogo mundial SIN Chile (Maule/Iquique solo en pestaña nacional).")
    if not admin_activo:
        st.info("Ingresa PIN admin para operar el laboratorio mundial.")
        return
    nodo_sel = nodo_sel or "Filipinas · Mindanao"
    if nodo_sel not in _NODOS_MUNDO_INLINE:
        nodo_sel = "Filipinas · Mindanao"
    nodo = _NODOS_MUNDO_INLINE[nodo_sel]
    df_g = _fetch_usgs_global_inline()
    st.metric("Sismos mundiales USGS M4.5+ (sin Chile)", len(df_g))
    st.markdown("#### Terremotos históricos MUNDIALES (Japón, Filipinas, Indonesia…)")
    st.dataframe(_df_ui(pd.DataFrame(_CATALOGO_MUNDO)), use_container_width=True, hide_index=True)
    df_nodo = filtrar_sismos_estacion(df_g, nodo["lat"], nodo["lon"], radio_km=400)
    st.markdown(f"#### Mapa — Cinturón de Fuego + USGS · Nodo: **{nodo_sel}**")
    _render_mapa_anillo_fuego(
        df_g, nodo["lat"], nodo["lon"], nodo_sel,
        zoom=2, altura=420, df_etiquetas=df_nodo, modo_demo=modo_demo,
        mapa_principal=False,
    )
    if modo_demo:
        st.error("MODO DEMO MUNDO — ejemplo experimental, no alerta oficial.")
        st.info(ESCENARIO_DEMO_MUNDO["descripcion"])


def _render_mundo_lab_ui(admin_activo, ttl_seg, ttl_horas, nodo_sel, forzar, modo_sat, modo_demo, kp):
    if mundo_lab and getattr(mundo_lab, "MODULO_MUNDO_ACTIVO", False):
        mundo_lab.render_mundo_lab(
            admin_activo=admin_activo, ttl_seg=ttl_seg, ttl_horas=ttl_horas,
            nodo_sel=nodo_sel, forzar=forzar, modo_sat=modo_sat, modo_demo=modo_demo, kp=kp,
        )
    else:
        if _err_mundo:
            st.warning(f"Módulo externo no cargó ({_err_mundo}). Usando versión integrada en streamlit_app.py.")
        _render_mundo_lab_inline(admin_activo, nodo_sel, ttl_seg, modo_demo)


def filtrar_sismos_estacion(df_sismos, lat, lon, radio_km=RADIO_ESTACION_KM):
    if df_sismos.empty:
        return df_sismos.copy()
    df = df_sismos.copy()
    df["Distancia_km"] = df.apply(
        lambda r: distancia_km(lat, lon, r["Latitud"], r["Longitud"]),
        axis=1,
    )
    return df[df["Distancia_km"] <= radio_km].sort_values("Fecha", ascending=False)


def generar_sismos_demo_escenario(config, escenario=None):
    esc = escenario or ESCENARIO_DEMO_CATASTROFICO
    rng = random.Random(f"demo_{esc['evento_ref']}_{config['id']}")
    ahora = ahora_chile()
    filas = []
    lugar_demo = f"DEMO · enjambre pre-{esc['evento_ref']} — ejemplo, no USGS real"
    for i in range(esc["sismos_locales_14d"]):
        if i < 8:
            mag = round(rng.uniform(5.6, 6.9), 1)
        elif i < 22:
            mag = round(rng.uniform(4.5, 5.5), 1)
        else:
            mag = round(rng.uniform(3.8, 4.8), 1)
        filas.append({
            "Magnitud": mag,
            "Lugar": lugar_demo,
            "Latitud": config["lat"] + rng.uniform(-0.75, 0.75),
            "Longitud": config["lon"] + rng.uniform(-0.75, 0.75),
            "Fecha": (ahora - timedelta(hours=rng.uniform(0, 14 * 24))).strftime("%Y-%m-%d %H:%M"),
        })
    extra = max(0, esc["sismos_chile_14d"] - esc["sismos_locales_14d"])
    for _ in range(extra):
        filas.append({
            "Magnitud": round(rng.uniform(4.0, 5.4), 1),
            "Lugar": "DEMO · actividad Chile central — ejemplo",
            "Latitud": config["lat"] + rng.uniform(-2.5, 2.5),
            "Longitud": config["lon"] + rng.uniform(-2.5, 2.5),
            "Fecha": (ahora - timedelta(hours=rng.uniform(0, 14 * 24))).strftime("%Y-%m-%d %H:%M"),
        })
    return pd.DataFrame(filas).sort_values("Fecha", ascending=False)


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

    gnss_info = None
    atmos_info = None
    cond_info = None
    shoa_info = None
    if not nodo_offline and not modo_sat:
        if shoa_mod:
            try:
                shoa_info = shoa_mod.lectura_marea_nodo(
                    estacion, config["lat"], config["lon"], ttl_seg=min(ttl_seg, 1800)
                )
                if shoa_info:
                    shoa = shoa_info["shoa_cm"]
                    origen = shoa_info["origen"]
            except Exception:
                shoa_info = None
        if gnss_mod:
            try:
                gnss_info = gnss_mod.lectura_gnss_nodo(
                    estacion, config["lat"], config["lon"], ttl_seg=ttl_seg
                )
                if gnss_info:
                    insar = gnss_info["insar_pct"]
                    origen = gnss_info["origen"]
            except Exception:
                gnss_info = None
        if atmos_mod:
            try:
                atmos_info = atmos_mod.lectura_atmosfera(
                    config["lat"],
                    config["lon"],
                    baseline_pres=config["baseline_pres"],
                    codigo_omm=config.get("id"),
                    ttl_seg=min(ttl_seg, 3600),
                )
                if atmos_info:
                    pres = atmos_info["presion_hpa"]
                    termico = atmos_info["termico"]
                    origen = atmos_info["origen"]
            except Exception:
                atmos_info = None
        if cond_mod:
            try:
                cond_info = cond_mod.estimar_conductividad(estacion, config, atmos_info)
                if cond_info and cond_info.get("cond_proxy_fisico"):
                    cond = cond_info["conductividad_ms_m"]
            except Exception:
                cond_info = None

    return shoa, cond, pres, termico, insar, origen, gnss_info, atmos_info, cond_info, shoa_info

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


def _tope_riesgo_permitido(gnss_info=None, atmos_info=None, cond_info=None, shoa_info=None):
    fn = getattr(alertas, "tope_riesgo_permitido", None)
    if callable(fn):
        return fn(gnss_info, atmos_info, cond_info, shoa_info)
    gnss_ok = getattr(alertas, "gnss_es_confiable", lambda _: False)(gnss_info)
    atmos_ok = getattr(alertas, "atmos_es_real", lambda _: False)(atmos_info)
    cond_ok = getattr(alertas, "cond_es_proxy_fisico", lambda _: False)(cond_info)
    if gnss_ok and atmos_ok and cond_ok:
        return getattr(alertas, "MAX_RIESGO_CON_GNSS_Y_ATMOS", 96.0)
    if gnss_ok:
        return getattr(alertas, "MAX_RIESGO_CON_GNSS_CONFIABLE", 92.0)
    if atmos_ok and cond_ok:
        return getattr(alertas, "MAX_RIESGO_CON_ATMOS_REAL", 85.0)
    return getattr(alertas, "MAX_RIESGO_CON_TELEMETRIA_ESTIMADA", 74.0)


def aplicar_control_calidad(
    estado, icono, puntaje, log_filtro, modo_demo=False,
    gnss_info=None, atmos_info=None, cond_info=None, shoa_info=None,
):
    if modo_demo:
        return estado, icono, puntaje, f"{log_filtro} // MODO DEMO."
    tope = _tope_riesgo_permitido(gnss_info, atmos_info, cond_info, shoa_info)
    if puntaje > tope:
        if tope >= alertas.MAX_RIESGO_CON_TELEMETRIA_REAL:
            msg = f"Tope telemetría real ({tope:.0f}%): modelo casi completo."
        elif tope >= alertas.MAX_RIESGO_CON_GNSS_Y_ATMOS:
            msg = f"Tope multi-sensor ({tope:.0f}%): SHOA sin mareógrafo cercano."
        elif alertas.gnss_es_confiable(gnss_info):
            msg = f"Tope GNSS confiable ({tope:.0f}%): capas parciales estimadas."
        elif alertas.atmos_es_real(atmos_info):
            msg = f"Tope atmósfera real ({tope:.0f}%): GNSS/SHOA parciales."
        else:
            msg = "Riesgo limitado: telemetría parcialmente estimada."
        if tope <= alertas.MAX_RIESGO_CON_TELEMETRIA_ESTIMADA:
            return "VIGILANCIA ALTA HEURÍSTICA", "🟠", tope, f"{log_filtro} // {msg}"
        return estado, icono, tope, f"{log_filtro} // {msg}"
    capas = ["USGS/NOAA"]
    if alertas.gnss_es_confiable(gnss_info):
        capas.append(f"GNSS {gnss_info['estacion_gnss']}")
    if alertas.atmos_es_real(atmos_info):
        capas.append(atmos_info.get("origen", "Atmos"))
    if alertas.cond_es_proxy_fisico(cond_info):
        capas.append(f"EM-{cond_info.get('zona_suelo', 'proxy')}")
    if alertas.shoa_es_real(shoa_info):
        capas.append(f"SHOA-{shoa_info.get('codigo_ioc', 'IOC')}")
    return estado, icono, puntaje, f"{log_filtro} // Calidad: {', '.join(capas)}."


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
        shoa, cond, presion, termico, insar, origen, gnss_info, atmos_info, cond_info, shoa_info = telemetria_estable(
            estacion, cfg, total_sismos, ttl_seg, modo_sat, nodo_offline
        )
        estado, _, puntaje, _ = calcular_riesgo_fusion(
            insar, total_sismos, b_val, cond, shoa, cfg, kp, termico, presion
        )
        estado, _, puntaje, _ = aplicar_control_calidad(
            estado, "🟠", puntaje, "", modo_demo=False,
            gnss_info=gnss_info, atmos_info=atmos_info, cond_info=cond_info, shoa_info=shoa_info,
        )
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
            "GNSS estación": gnss_info["estacion_gnss"] if gnss_info else "—",
            "GNSS H mm/yr": gnss_info["horiz_mm_anio"] if gnss_info else None,
            "GNSS V mm/yr": gnss_info["vu_mm_anio"] if gnss_info else None,
            "Presión hPa": atmos_info["presion_hpa"] if atmos_info else presion,
            "Atmósfera": atmos_info["origen"] if atmos_info else "estimado",
            "EM proxy zona": cond_info.get("zona_suelo") if cond_info else "—",
            "SHOA IOC": shoa_info.get("codigo_ioc") if shoa_info else "—",
            "SHOA real": "Sí" if alertas.shoa_es_real(shoa_info) else "No",
            "Nodo offline": "Sí" if nodo_offline else "No",
            "USGS actualizado": consultado_usgs,
            "NOAA actualizado": consultado_noaa,
        })
    return pd.DataFrame(filas).sort_values("Riesgo %", ascending=False)


def generar_informe_calidad_texto(df_calibracion, consultado_usgs, consultado_noaa, ttl_seg):
    fecha = ahora_chile().strftime("%Y-%m-%d %H:%M:%S")
    ttl_horas = max(1, ttl_seg // 3600)
    pesos_txt = "\n".join(f"- {k}: {v:.2f}" for k, v in PESOS.items())
    estaciones_txt = "\n".join(
        f"- {fila['Estación']}: riesgo {fila['Riesgo %']}%, b-value {fila['b-value 14D']}, "
        f"sismos locales {fila['Sismos 14D Chile']}, match {fila['Match patrón %']}%"
        for _, fila in df_calibracion.iterrows()
    )
    return f"""INFORME DE CALIDAD Y TRANSPARENCIA - NAZCA CORE MONITOR
Generado: {fecha}
Desarrollado por: Sandro Pereira A. - CEO & Developer

1. Objetivo
Este informe documenta los parámetros usados por el sistema para entregar una lectura transparente,
auditable y apta para revisión por profesionales de geotecnia, geología, sismología o gestión de riesgo.

2. Fuentes y calidad de datos
- USGS: catálogo sísmico con ventana móvil de 14 días para Chile. Dato real consultado por API.
- NOAA Kp: índice geomagnético. Dato real consultado por API y servido por caché operativa.
- b-value: indicador calculado desde magnitudes USGS locales por estación.
- GNSS (NGL MIDAS), atmósfera (Open-Meteo), EM proxy y mareógrafo IOC UNESCO: datos reales cuando la API responde.
- InSAR deriva de GNSS; EM es proxy físico por zona geológica; SHOA es anomalía mareográfica IOC (no SHOA directo).

Última actualización USGS: {consultado_usgs}
Última actualización NOAA: {consultado_noaa}
TTL de caché actual: {ttl_horas} horas
Política operativa: no se espera a completar 14 días nuevos; el sistema recalcula con los datos frescos disponibles y mantiene siempre una ventana móvil hacia atrás.

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
- Revisar la bitácora mensual y contrastar contra ventanas móviles USGS 14D.
- Recalcular b-value por estación usando la ventana móvil 14D y validar radios de influencia.
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


def _texto_acerca_de(ttl_horas, consultado_usgs, consultado_noaa):
    return f"""NAZCA CORE MONITOR — ACERCA DE Y FUENTES DE DATOS
Build: {APP_BUILD}
Desarrollado por: Sandro Pereira A. · CEO & Developer

Qué es: monitor experimental de vigilancia sísmica y ambiental para la costa de Chile.
No es alerta oficial ni predicción determinística de terremotos.

FUENTES PRINCIPALES
- Sismos 14D: USGS FDSN Event API (Chile, M>=2.5)
- b-value: calculado desde magnitudes USGS en radio {RADIO_ESTACION_KM} km
- Kp geomagnético: NOAA SWPC
- Deformación (InSAR%): GNSS NGL MIDAS marco Sudamérica + series tenv3
- Atmósfera: Open-Meteo (gratis); opcional OpenWeatherMap y MeteoChile
- EM conductividad: proxy físico Archie por zona geológica + humedad real
- Marea/SHOA: mareógrafos IOC UNESCO (anomalía residual filtrada)
- Patrones M7+: catálogo histórico interno de referencia Chile

Caché operativa: {ttl_horas} h · USGS: {consultado_usgs} · NOAA: {consultado_noaa}
Vigilancia 24/7: scripts/vigilancia_automatica.py (GitHub Actions)
"""


def render_tab_acerca_de(ttl_seg, ttl_horas, consultado_usgs, consultado_noaa):
    st.markdown("### Acerca de NAZCA CORE MONITOR")
    st.markdown(
        "**NAZCA CORE MONITOR** es un sistema experimental de vigilancia sísmica y ambiental "
        "para el cinturón de subducción de Chile. Combina catálogo sísmico en tiempo casi real, "
        "deformación GNSS, atmósfera, proxy electromagnético del suelo y mareas costeras "
        "para estimar un índice heurístico de tensión cortical.\n\n"
        "**No es una alerta oficial** ni un predictor determinístico de terremotos. "
        "Sus salidas deben validarse con fuentes institucionales (CSN, SHOA, SERNAGEOMIN) "
        "y revisión técnica especializada."
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Versión", APP_BUILD)
    c2.metric("Caché APIs", f"{ttl_horas} h")
    c3.metric("Último USGS", str(consultado_usgs)[:16])
    c4.metric("Último NOAA Kp", str(consultado_noaa)[:16])

    st.markdown("#### Fuentes de datos por variable")
    filas_fuentes = [
        {
            "Variable": "Sismos 14D (Chile)",
            "Fuente": "USGS Earthquake Hazards Program",
            "Endpoint / referencia": "earthquake.usgs.gov/fdsnws/event/1/query",
            "Tipo": "REAL",
            "Caché": f"{ttl_horas} h",
            "Uso en modelo": "Actividad sísmica regional y filtro local por estación",
        },
        {
            "Variable": "b-value 14D",
            "Fuente": "Calculado NAZCA desde USGS",
            "Endpoint / referencia": "Gutenberg-Richter sobre magnitudes locales",
            "Tipo": "CALCULADO",
            "Caché": "Derivado de caché USGS",
            "Uso en modelo": "Firma de ruptura y peso SISMO_BVAL (62%)",
        },
        {
            "Variable": "Índice Kp",
            "Fuente": "NOAA Space Weather Prediction Center",
            "Endpoint / referencia": "services.swpc.noaa.gov/products/noaa-scales.json",
            "Tipo": "REAL",
            "Caché": f"{ttl_horas} h",
            "Uso en modelo": "Modulador del componente electromagnético",
        },
        {
            "Variable": "InSAR % (deformación)",
            "Fuente": "Nevada Geodetic Laboratory (NGL) — MIDAS SA",
            "Endpoint / referencia": "geodesy.unr.edu/velocidades/midas.SA.txt",
            "Tipo": "REAL (GNSS)",
            "Caché": f"{ttl_horas} h",
            "Uso en modelo": "Sustituto InSAR desde velocidades GNSS (peso 18%)",
        },
        {
            "Variable": "Aceleración GNSS 1 año",
            "Fuente": "NGL series tenv3 (marco SA)",
            "Endpoint / referencia": "geodesy.unr.edu/gps_timeseries/IGS20/tenv3/SA/",
            "Tipo": "CALCULADO",
            "Caché": f"{ttl_horas} h",
            "Uso en modelo": "Boost si deformación reciente supera baseline MIDAS",
        },
        {
            "Variable": "Presión / temperatura / HR",
            "Fuente": "Open-Meteo (principal, sin API key)",
            "Endpoint / referencia": "api.open-meteo.com/v1/forecast",
            "Tipo": "REAL",
            "Caché": "≤ 1 h",
            "Uso en modelo": "Presión atmosférica, índice térmico y entrada al proxy EM",
        },
        {
            "Variable": "Presión (alternativa)",
            "Fuente": "OpenWeatherMap (opcional)",
            "Endpoint / referencia": "openweathermap.org — secret OPENWEATHER_API_KEY",
            "Tipo": "REAL (opcional)",
            "Caché": "≤ 1 h",
            "Uso en modelo": "Respaldo si Open-Meteo no responde",
        },
        {
            "Variable": "Presión (alternativa)",
            "Fuente": "MeteoChile EMA (opcional)",
            "Endpoint / referencia": "climatologia.meteochile.gob.cl — secrets METEOCHILE_*",
            "Tipo": "REAL (opcional)",
            "Caché": "≤ 1 h",
            "Uso en modelo": "Estación EMA más cercana al nodo",
        },
        {
            "Variable": "EM conductividad (mS/m)",
            "Fuente": "Proxy físico Archie + zona geológica NAZCA",
            "Endpoint / referencia": "nazca_conductividad.py — perfiles por costa Chile",
            "Tipo": "PROXY FÍSICO",
            "Caché": "En tiempo de cálculo",
            "Uso en modelo": "Anomalía EM estimada (peso 10%); no es medición in situ",
        },
        {
            "Variable": "SHOA / marea (cm)",
            "Fuente": "IOC UNESCO Sea Level Monitoring Facility",
            "Endpoint / referencia": "ioc-sealevelmonitoring.org/service.php?query=data&code=",
            "Tipo": "REAL",
            "Caché": "30 min",
            "Uso en modelo": "Anomalía mareográfica residual (peso 6%)",
        },
        {
            "Variable": "Patrones M7+ históricos",
            "Fuente": "Catálogo de referencia NAZCA (literatura / CSN)",
            "Endpoint / referencia": "Maule 2010, Iquique 2014, Illapel 2015, etc.",
            "Tipo": "REFERENCIA",
            "Caché": "Estático en código",
            "Uso en modelo": "Similitud heurística y disparo Telegram experimental",
        },
        {
            "Variable": "Mapa tensión / sismos",
            "Fuente": "USGS 14D + modelo NAZCA por zona",
            "Endpoint / referencia": "nazca_mapa_tectonico.py",
            "Tipo": "CALCULADO",
            "Caché": f"{ttl_horas} h",
            "Uso en modelo": "Visualización de acumulación de tensión",
        },
        {
            "Variable": "Alertas Telegram",
            "Fuente": "Bot Telegram + suscriptores (opcional)",
            "Endpoint / referencia": "api.telegram.org — secrets TELEGRAM_*",
            "Tipo": "OPERATIVO",
            "Caché": "Cooldown 90–120 min",
            "Uso en modelo": "Notificación experimental a admin y suscriptores",
        },
        {
            "Variable": "Vigilancia 24/7",
            "Fuente": "GitHub Actions + nazca_vigilancia_core.py",
            "Endpoint / referencia": "scripts/vigilancia_automatica.py",
            "Tipo": "OPERATIVO",
            "Caché": f"{ttl_horas} h",
            "Uso en modelo": "Escaneo automático cada 6 h sin Streamlit abierto",
        },
    ]
    st.dataframe(_df_ui(pd.DataFrame(filas_fuentes)), use_container_width=True, hide_index=True)

    st.markdown("#### Mapeo nodos CORE → sensores reales")
    filas_nodos = []
    gnss_pref = getattr(gnss_mod, "NODOS_GNSS_PREFERIDOS", {}) if gnss_mod else {}
    ioc_map = getattr(shoa_mod, "NODOS_IOC", {}) if shoa_mod else {}
    for nombre, cfg in ESTACIONES_CONFIG.items():
        filas_nodos.append({
            "Nodo NAZCA": nombre,
            "Código OMM": cfg.get("id", "—"),
            "GNSS preferida": ", ".join(gnss_pref.get(nombre, [])) or "cercana automática",
            "Mareógrafo IOC": (ioc_map.get(nombre, "—") or "—").upper(),
            "Lat/Lon nodo": f"{cfg['lat']:.2f}, {cfg['lon']:.2f}",
        })
    st.dataframe(_df_ui(pd.DataFrame(filas_nodos)), use_container_width=True, hide_index=True)

    with st.expander("Detalle mareógrafos IOC por nodo"):
        st.markdown(
            "| Nodo | Código IOC | Ubicación IOC |\n"
            "|------|------------|---------------|\n"
            "| Arica / Iquique | ARIC | Arica |\n"
            "| Antofagasta | ANTO | Antofagasta |\n"
            "| Coquimbo | COQU | Coquimbo |\n"
            "| Valparaíso / San Antonio | SANO | San Antonio |\n"
            "| Concepción / Lebu | LEBU | Lebu |\n"
            "| Valdivia / Puerto Montt | PMON | Puerto Montt |\n"
            "| Pto. Aysén / Taitao | CSTR | Castro (referencia patagónica) |\n\n"
            "La anomalía SHOA se calcula como residual filtrado (media móvil de marea + umbral sigma), "
            "no como nivel absoluto del mar. No reemplaza el servicio oficial del SHOA."
        )

    with st.expander("Detalle GNSS e índice InSAR"):
        st.markdown(
            "- **Velocidades:** archivo MIDAS del marco de referencia Sudamérica (SA), Universidad de Nevada Reno.\n"
            "- **Catálogo Chile:** estaciones dentro de límites nacionales + semillas IGS (`gnss_catalogo_chile.json`).\n"
            "- **Confiable:** estación GNSS a menos de **100 km** del nodo.\n"
            "- **InSAR %:** mapeo heurístico de velocidades horizontales/verticales y subsidencia hacia la fosa.\n"
            "- **Aceleración:** pendiente de la serie tenv3 en el último año vs. velocidad MIDAS de largo plazo."
        )

    with st.expander("Detalle atmósfera y conductividad (EM)"):
        st.markdown(
            "- **Open-Meteo** es la fuente por defecto (gratuita, sin registro).\n"
            "- **OpenWeatherMap** y **MeteoChile** se activan solo si existen keys en `.streamlit/secrets.toml`.\n"
            "- **EM:** proxy tipo Archie calibrado por zona (`árido norte`, `costa central`, `sur húmedo`, etc.) "
            "usando humedad relativa y precipitación reales. **No** es una medición geofísica de campo.\n"
            "- Zonas inspiradas en contexto geológico costero/subducción (referencia IDE/SERNAGEOMIN)."
        )

    st.markdown("#### Topes de riesgo según calidad de telemetría")
    df_topes = pd.DataFrame([
        {
            "Condición": "Telemetría parcialmente estimada",
            "Tope máx.": f"{getattr(alertas, 'MAX_RIESGO_CON_TELEMETRIA_ESTIMADA', 74):.0f}%",
            "Descripción": "Sin GNSS confiable ni paquete atmos+EM completo",
        },
        {
            "Condición": "Atmósfera real + EM proxy físico",
            "Tope máx.": f"{getattr(alertas, 'MAX_RIESGO_CON_ATMOS_REAL', 85):.0f}%",
            "Descripción": "Open-Meteo (u otra fuente real) + proxy Archie activo",
        },
        {
            "Condición": "GNSS confiable (< 100 km)",
            "Tope máx.": f"{getattr(alertas, 'MAX_RIESGO_CON_GNSS_CONFIABLE', 92):.0f}%",
            "Descripción": "Deformación NGL cercana al nodo",
        },
        {
            "Condición": "GNSS + Atmos + EM proxy",
            "Tope máx.": f"{getattr(alertas, 'MAX_RIESGO_CON_GNSS_Y_ATMOS', 96):.0f}%",
            "Descripción": "Tres capas reales/proxy físico sin mareógrafo cercano",
        },
        {
            "Condición": "Stack completo (+ SHOA IOC < 120 km)",
            "Tope máx.": f"{getattr(alertas, 'MAX_RIESGO_CON_TELEMETRIA_REAL', 98):.0f}%",
            "Descripción": "GNSS + atmósfera + EM + mareógrafo IOC confiable",
        },
    ])
    st.dataframe(_df_ui(df_topes), use_container_width=True, hide_index=True)

    st.markdown("#### Pesos del modelo de fusión")
    st.dataframe(
        _df_ui(pd.DataFrame([
            {"Componente": k, "Peso": f"{v * 100:.0f}%", "Descripción": {
                "SISMO_BVAL": "Actividad sísmica y b-value",
                "INSAR": "Deformación GNSS → índice InSAR",
                "CONDUCT": "Proxy electromagnético del suelo",
                "SHOA": "Anomalía mareográfica IOC",
                "ATMOS": "Presión y componente térmico",
            }.get(k, "")}
            for k, v in PESOS.items()
        ])),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("#### APIs opcionales (secrets.toml)")
    st.code(
        "# .streamlit/secrets.toml — todas opcionales salvo Telegram si quieres alertas\n"
        "OPENWEATHER_API_KEY = \"...\"          # respaldo atmósfera\n"
        "METEOCHILE_USUARIO = \"...\"           # EMA MeteoChile\n"
        "METEOCHILE_TOKEN = \"...\"\n"
        "TELEGRAM_TOKEN = \"...\"               # alertas experimentales\n"
        "TELEGRAM_CHAT_ID = \"...\"\n"
        "ADMIN_PIN = \"...\"                    # herramientas admin en sidebar\n",
        language="toml",
    )

    st.warning(
        "**Limitación legal y técnica:** NAZCA CORE MONITOR es un proyecto experimental privado. "
        "No sustituye al Centro Sismológico Nacional (CSN), al Servicio Hidrográfico y Oceanográfico "
        "de la Armada (SHOA), ni a ningún sistema de alerta temprana oficial. "
        "Ante cualquier evento real, siga las instrucciones de autoridades competentes."
    )

    texto = _texto_acerca_de(ttl_horas, consultado_usgs, consultado_noaa)
    st.download_button(
        "Descargar Acerca de (TXT)",
        texto.encode("utf-8"),
        "nazca_acerca_de_fuentes.txt",
        "text/plain",
        use_container_width=True,
    )


def nombre_zona_simple(estacion_sel: str) -> str:
    base = estacion_sel.split("(")[0].strip()
    return base.replace(" / ", " y ")


def accion_sugerida_simple(nivel: str) -> str:
    return {
        "VERDE": "Ninguna medida especial. Para alertas oficiales, consulte el CSN (sismologia.cl).",
        "AMARILLO": "Mantener observación. Revise esta página cada 6–12 horas y las fuentes oficiales.",
        "NARANJO": "Informe al equipo de monitoreo. Contraste con CSN/SHOA antes de tomar decisiones operativas.",
        "ROJO": "Escale a responsable técnico de inmediato. No difunda como alerta pública sin validación experta.",
    }.get(nivel, "Revise con su equipo técnico.")


def frase_estado_simple(zona: str, nivel: str, total_sismos: int) -> str:
    if nivel == "VERDE":
        return (
            f"La costa de **{zona}** se ve **tranquila** en el monitoreo experimental. "
            f"Actividad sísmica reciente: **{total_sismos}** temblores cerca en 14 días."
        )
    if nivel == "AMARILLO":
        return (
            f"Hay **actividad a observar** en **{zona}**. "
            f"Se registraron **{total_sismos}** temblores cercanos en las últimas 2 semanas."
        )
    if nivel == "NARANJO":
        return (
            f"**Vigilancia reforzada** en **{zona}**. "
            f"El modelo detecta señales que merecen seguimiento técnico (**{total_sismos}** sismos locales 14D)."
        )
    return (
        f"**Atención máxima experimental** en **{zona}**. "
        f"Requiere revisión técnica urgente (**{total_sismos}** sismos locales 14D)."
    )


def render_vista_simple(
    estacion_sel,
    nivel_alerta,
    puntaje,
    total_sismos,
    total_sismos_chile,
    mejor_ev,
    mejor_match,
    estado,
    b_val,
    insar,
    shoa,
    cond,
    df_sismos,
    df_sismos_local,
    df_calibracion,
    config,
    consultado_usgs,
    modo_demo,
    mapa_tect,
    nodo_offline,
):
    zona = nombre_zona_simple(estacion_sel)
    nivel = nivel_alerta.get("nivel", "VERDE")
    color = nivel_alerta.get("color", "🟢")

    if modo_demo:
        st.error("Modo demostración activo — los valores son un ejemplo, no un evento real.")

    st.markdown(f"## {color} {zona}")
    st.markdown(frase_estado_simple(zona, nivel, total_sismos))

    if mejor_match >= 50:
        st.info(
            f"El patrón actual tiene **{mejor_match:.0f}%** de similitud con **{mejor_ev}** "
            "(terremoto grande del pasado). **No es una predicción**, solo una referencia histórica."
        )

    st.warning(
        "Monitor **experimental** de apoyo al monitoreo. **No** reemplaza alertas del CSN, SHOA "
        "ni de autoridades. No indica cuándo ni dónde ocurrirá un próximo terremoto."
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric(
        "Nivel de vigilancia",
        f"{color} {nivel}",
        help="Verde=tranquilo · Amarillo=observar · Naranjo=reforzar · Rojo=máxima atención experimental",
    )
    c2.metric(
        "Temblores cerca (14 días)",
        total_sismos,
        help=f"Dentro de {RADIO_ESTACION_KM} km del nodo {zona}",
    )
    c3.metric(
        "Índice de vigilancia",
        f"{puntaje:.0f}%",
        help="Resumen interno del modelo NAZCA. No es probabilidad de terremoto.",
    )
    c4.metric(
        "Ventana sugerida",
        nivel_alerta.get("ventana", "—"),
        help="Horizonte de observación sugerido por el modelo",
    )

    st.markdown(f"**Qué hacer ahora:** {accion_sugerida_simple(nivel)}")
    st.caption(f"Estado interno del modelo: {estado} · Chile 14D: {total_sismos_chile} sismos · USGS: {consultado_usgs}")

    if nodo_offline:
        st.warning("Señal de red limitada — lectura estimada por vecindad.")

    st.markdown("#### Mapa de actividad")
    st.caption("Puntos = temblores recientes. El círculo azul marca la zona que está mirando.")
    df_tension_tabla = pd.DataFrame()
    if mapa_tect:
        df_tension_tabla, _ = mapa_tect.render_mapa_tension(
            df_sismos=df_sismos,
            df_calibracion=df_calibracion,
            estaciones_config=ESTACIONES_CONFIG,
            estacion_lat=config["lat"],
            estacion_lon=config["lon"],
            estacion_label=estacion_sel,
            zoom=4,
            altura=380,
            mapa_nativo=_usar_mapa_nativo(modo_demo),
        )
    else:
        _render_mapa_anillo_fuego(
            df_sismos_local, config["lat"], config["lon"], estacion_sel,
            zoom=4, altura=380, modo_demo=modo_demo, mapa_principal=True,
        )

    col_sismos, col_resumen = st.columns([1.4, 1])
    with col_sismos:
        st.markdown("#### Temblores recientes cerca de esta zona")
        cols_tabla = ["Magnitud", "Lugar", "Fecha"]
        if not df_sismos_local.empty and "Distancia_km" in df_sismos_local.columns:
            df_show = df_sismos_local[cols_tabla + ["Distancia_km"]].copy()
            df_show = df_show.rename(columns={"Distancia_km": "Distancia km"})
        else:
            df_show = df_sismos_local[cols_tabla] if not df_sismos_local.empty else pd.DataFrame(columns=cols_tabla)
        st.dataframe(_df_ui(df_show), height=220, use_container_width=True)

    with col_resumen:
        st.markdown("#### Lectura rápida")
        lectura = [
            ("Movimiento lento del suelo", "Normal" if insar < 55 else ("Elevado" if insar < 75 else "Alto")),
            ("Marea / costa", "Normal" if shoa < 5 else ("Alterada" if shoa < 12 else "Muy alterada")),
            ("Actividad de enjambre", "Típica" if b_val >= 0.75 else ("Inusual" if b_val >= 0.68 else "Muy inusual")),
        ]
        for etiqueta, valor in lectura:
            st.markdown(f"- **{etiqueta}:** {valor}")

        if not df_tension_tabla.empty and "tension_pct" in df_tension_tabla.columns:
            n_alta = int((df_tension_tabla["tension_pct"] >= 70).sum())
            if n_alta:
                st.caption(f"{n_alta} zona(s) del litoral con tensión alta en el modelo.")

    with st.expander("Ver números técnicos (opcional)"):
        t1, t2, t3, t4 = st.columns(4)
        t1.metric("Deformación (índice)", f"{insar:.1f}%")
        t2.metric("b-value", f"{b_val}")
        t3.metric("Similitud M7+", f"{mejor_match:.1f}%")
        t4.metric("Marea residual", f"{shoa:.1f} cm")
        st.caption(f"Conductividad proxy: {cond:.2f} mS/m · Patrón más parecido: {mejor_ev}")


# ==============================================================================
# PDF
# ==============================================================================
def agregar_linea_pdf(pdf, etiqueta, valor):
    pdf.set_font("Arial", "B", 9)
    pdf.cell(55, 6, sanitizar_texto(str(etiqueta)), border=1)
    pdf.set_font("Arial", "", 9)
    pdf.cell(0, 6, sanitizar_texto(str(valor)), border=1, ln=True)


def pdf_cell(pdf, w, h, texto, **kwargs):
    if w == 0:
        pdf.set_x(pdf.l_margin)
    pdf.cell(w, h, sanitizar_texto(texto), **kwargs)


def pdf_multi_cell(pdf, w, h, texto, **kwargs):
    pdf.set_x(pdf.l_margin)
    ancho = pdf.w - pdf.l_margin - pdf.r_margin if w == 0 else w
    pdf.multi_cell(ancho, h, sanitizar_texto(texto), **kwargs)
    pdf.set_x(pdf.l_margin)


def generar_pdf(
    estacion, puntaje, estado, b_val, cond, shoa, sismos_cnt, canal, kp,
    config, insar, presion, termico, origen_em, mejor_ev, mejor_match,
    total_sismos_chile, consultado_usgs, consultado_noaa, nivel_alerta=None, modo_demo=False,
):
    nivel_alerta = nivel_alerta or {"nivel": "NO CALCULADO", "ventana": "No disponible", "mensaje": "No disponible"}
    z_cond = round((cond - config["baseline_cond"]) / config["sigma_cond"], 2)
    delta_cond = round(cond - config["baseline_cond"], 2)
    delta_presion = round(presion - config["baseline_pres"], 2)
    calidad = "SIMULACION" if modo_demo else "USGS/NOAA real + telemetria ambiental estimada"
    interpretacion = (
        "Condicion de vigilancia alta: se recomienda contrastar la tendencia local con instrumentacion independiente, "
        "revisar continuidad temporal de los eventos y solicitar validacion profesional antes de cualquier decision operacional."
        if puntaje >= 60 else
        "Condicion de observacion: mantener seguimiento, conservar trazabilidad y actualizar la calibracion mensual."
    )
    diagnostico_sector = (
        "La lectura se basa principalmente en actividad sismica local, b-value y desviaciones contra parametros base "
        "de la estacion seleccionada. Las variables ambientales estimadas no deben usarse como confirmacion instrumental."
    )

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=14)

    if os.path.exists(LOGO_PATH):
        pdf.image(LOGO_PATH, x=12, y=10, w=28)
    pdf.set_xy(44, 11)
    pdf.set_font("Arial", "B", 16)
    pdf_cell(pdf, 0, 8, "NAZCA NEURAL DETECTOR", ln=True)
    pdf.set_x(44)
    pdf.set_font("Arial", "", 9)
    pdf_cell(pdf, 0, 6, "Informe tecnico preliminar de condicion sismica local - Core Monitor v8.0", ln=True)
    pdf.set_x(44)
    pdf_cell(pdf, 0, 6, f"Generado: {ahora_chile().strftime('%Y-%m-%d %H:%M:%S')} ({CHILE_TZ_LABEL})", ln=True)
    pdf.set_x(44)
    pdf_cell(pdf, 0, 6, "Desarrollado por Sandro Pereira A. - CEO & Developer", ln=True)
    pdf.ln(12)

    pdf.set_font("Arial", "B", 12)
    pdf_cell(pdf, 0, 8, "1. Resumen ejecutivo", ln=True)
    agregar_linea_pdf(pdf, "Estacion evaluada", estacion)
    agregar_linea_pdf(pdf, "Estado del sistema", estado)
    agregar_linea_pdf(pdf, "Nivel de alerta", nivel_alerta["nivel"])
    agregar_linea_pdf(pdf, "Ventana vigilancia", nivel_alerta["ventana"])
    agregar_linea_pdf(pdf, "Indice de vigilancia", f"{puntaje:.1f}%")
    agregar_linea_pdf(pdf, "Canal operativo", canal)
    agregar_linea_pdf(pdf, "Calidad de datos", calidad)
    pdf.ln(4)

    pdf.set_font("Arial", "", 9)
    pdf_multi_cell(pdf, 0, 5, f"Lectura tecnica: {interpretacion}")
    pdf_multi_cell(pdf, 0, 5, diagnostico_sector)
    pdf_multi_cell(pdf, 0, 5, f"Nivel temporal experimental: {nivel_alerta['mensaje']}")
    pdf.ln(3)

    pdf.set_font("Arial", "B", 12)
    pdf_cell(pdf, 0, 8, "2. Parametros actuales medidos/calculados", ln=True)
    agregar_linea_pdf(pdf, "Sismos locales 14D", f"{sismos_cnt} eventos en radio {RADIO_ESTACION_KM} km")
    agregar_linea_pdf(pdf, "Sismos Chile 14D", total_sismos_chile)
    agregar_linea_pdf(pdf, "b-value local 14D", b_val)
    agregar_linea_pdf(pdf, "InSAR", f"{insar:.1f}% (estimado)")
    agregar_linea_pdf(pdf, "Conductividad EM", f"{cond} mS/m")
    agregar_linea_pdf(pdf, "SHOA", f"{shoa} cm (estimado)")
    agregar_linea_pdf(pdf, "Presion", f"{presion} hPa")
    agregar_linea_pdf(pdf, "Termico", termico)
    agregar_linea_pdf(pdf, "Kp NOAA", kp)
    pdf.ln(4)

    pdf.set_font("Arial", "B", 12)
    pdf_cell(pdf, 0, 8, "3. Comparativa contra parametros normales del sector", ln=True)
    agregar_linea_pdf(pdf, "EM normal sector", f"{config['baseline_cond']} mS/m")
    agregar_linea_pdf(pdf, "EM actual vs normal", f"{cond} mS/m | delta {delta_cond:+.2f} | z-score {z_cond:+.2f}")
    agregar_linea_pdf(pdf, "Presion normal sector", f"{config['baseline_pres']} hPa")
    agregar_linea_pdf(pdf, "Presion actual vs normal", f"{presion} hPa | delta {delta_presion:+.2f}")
    agregar_linea_pdf(pdf, "Sigma EM calibracion", config["sigma_cond"])
    agregar_linea_pdf(pdf, "Criterio local", f"Eventos considerados dentro de {RADIO_ESTACION_KM} km de la estacion")
    pdf.ln(4)

    pdf.set_font("Arial", "B", 12)
    pdf_cell(pdf, 0, 8, "4. Comparativa historica M7+", ln=True)
    agregar_linea_pdf(pdf, "Patron mas similar", mejor_ev)
    agregar_linea_pdf(pdf, "Match con patron", f"{mejor_match:.1f}%")
    agregar_linea_pdf(pdf, "Criterio", "Comparacion heuristica con firmas historicas precargadas")
    pdf.ln(4)

    pdf.set_font("Arial", "B", 12)
    pdf_cell(pdf, 0, 8, "5. Fuentes y trazabilidad", ln=True)
    agregar_linea_pdf(pdf, "USGS actualizado", consultado_usgs)
    agregar_linea_pdf(pdf, "NOAA actualizado", consultado_noaa)
    agregar_linea_pdf(pdf, "Origen EM/telemetria", origen_em)
    agregar_linea_pdf(pdf, "Modo demo", "Si" if modo_demo else "No")
    pdf.ln(4)

    pdf.set_font("Arial", "B", 12)
    pdf_cell(pdf, 0, 8, "6. Recomendacion operacional preliminar", ln=True)
    pdf.set_font("Arial", "", 9)
    pdf_multi_cell(pdf, 0, 5,
        f"{interpretacion} Mantener registro del informe, revisar la bitacora historica y no escalar el resultado "
        "sin corroboracion de sensores reales o criterio profesional."
    )
    pdf.ln(3)

    pdf.set_font("Arial", "B", 12)
    pdf_cell(pdf, 0, 8, "7. Limitacion tecnica", ln=True)
    pdf.set_font("Arial", "", 9)
    pdf_multi_cell(pdf, 0, 5,
        "NAZCA Core Monitor es un prototipo experimental de apoyo al monitoreo. "
        "Las variables InSAR, SHOA, EM, presion y termico pueden ser estimadas si no existen sensores reales conectados. "
        "Toda decision operacional debe ser validada por profesionales competentes y organismos oficiales."
    )

    out = pdf.output(dest="S")
    return out.encode("latin-1") if isinstance(out, str) else bytes(out)

# ==============================================================================
# SIDEBAR
# ==============================================================================
st.sidebar.markdown("### CORE NETWORK")
modo_simple = st.sidebar.radio(
    "Vista",
    ["Simple", "Técnica"],
    index=0,
    horizontal=True,
    help="Simple: resumen para decisiones. Técnica: monitoreo completo con todas las variables.",
) == "Simple"

intervalo = st.sidebar.selectbox(
    "Intervalo caché APIs (USGS / NOAA)",
    list(INTERVALOS_API.keys()),
    index=1,
)
ttl_seg = INTERVALOS_API[intervalo]
ttl_horas = max(1, ttl_seg // 3600)

if modo_simple:
    st.sidebar.caption(f"Datos sísmicos se actualizan cada **{ttl_horas} h** como máximo.")
else:
    st.sidebar.caption(
        f"Las APIs se consultan como máximo cada **{ttl_horas} h**. "
        "Entre consultas se sirven datos desde `.nazca_cache/`."
    )

st.sidebar.markdown("---")
admin_pin = st.sidebar.text_input("PIN admin", type="password", placeholder="Opcional")
admin_esperado = obtener_secret("ADMIN_PIN")
if admin_esperado and admin_pin == admin_esperado:
    st.session_state["admin_autenticado"] = True
admin_activo = bool(
    admin_esperado
    and (
        st.session_state.get("admin_autenticado", False)
        or admin_pin == admin_esperado
    )
)
if not admin_esperado:
    st.sidebar.warning(
        "ADMIN_PIN no configurado. Agrégalo en `.streamlit/secrets.toml` y reinicia Streamlit."
    )
elif admin_activo:
    st.sidebar.success("Modo admin activo.")
    if st.sidebar.button("Cerrar sesión admin", use_container_width=True):
        st.session_state.pop("admin_autenticado", None)
        st.rerun()
    _ver_mundo = getattr(mundo_lab, "MUNDO_LAB_VERSION", None) if mundo_lab else None
    st.sidebar.caption(
        f"Build app: **{APP_BUILD}** · MUNDO: **{_ver_mundo or 'NO'}** · "
        f"Mapa: **{'OK' if mapa_tect else 'NO'}** · PDF: **{'OK' if informes_pdf else 'NO'}**"
    )
    if _err_mundo:
        st.sidebar.error(_err_mundo)
    if _err_mapa:
        st.sidebar.warning(_err_mapa)
    if _err_informes:
        st.sidebar.warning(_err_informes)
elif admin_pin:
    st.sidebar.warning("PIN admin incorrecto.")

if admin_activo:
    st.sidebar.markdown("#### Herramientas admin")
    if st.sidebar.button("Limpiar caché APIs", use_container_width=True):
        if os.path.isdir(CACHE_DIR):
            for f in os.listdir(CACHE_DIR):
                os.remove(os.path.join(CACHE_DIR, f))
        st.sidebar.success("Caché vaciada.")

    forzar_sismos_14d = st.sidebar.button("Actualizar sismos 14D ahora", use_container_width=True)
    if forzar_sismos_14d:
        borrar_cache(clave_sismos_14d(ttl_seg))
    if mundo_lab and mundo_lab.MODULO_MUNDO_ACTIVO:
        forzar_mundo = st.sidebar.button("Actualizar sismos MUNDO ahora", use_container_width=True)
        if forzar_mundo:
            mundo_lab.borrar_cache_mundo(mundo_lab.clave_sismos_global(ttl_seg))
    else:
        forzar_mundo = False
else:
    forzar_sismos_14d = False
    forzar_mundo = False

st.sidebar.markdown("---")
if admin_activo:
    modo_demo_prev = st.session_state.get("modo_demo_activo", False)
    modo_demo = st.sidebar.checkbox(
        "Simulación Catastrófica",
        value=modo_demo_prev,
        key="chk_modo_demo",
        help="Fija Illapel 2015 (Chile) y Mindanao (MUNDO) como ejemplo con umbrales de alerta. No es predicción.",
    )
    if modo_demo != modo_demo_prev:
        st.session_state["modo_demo_activo"] = modo_demo
        for _k in ("ultima_sirena", "ultimo_log", "ultima_evidencia", "pdf"):
            st.session_state.pop(_k, None)
    modo_sat = st.sidebar.toggle("Colapso red terrestre (satelital)", value=False)
    sirena_activa = st.sidebar.toggle("Sirena local en alerta roja", value=True)
else:
    modo_demo = False
    st.session_state["modo_demo_activo"] = False
    modo_sat = False
    sirena_activa = False
canal = "SATELITAL LEO" if modo_sat else "TERRESTRE"

st.sidebar.markdown("---")
if admin_activo:
    if "telegram_vigilancia_activa" not in st.session_state:
        st.session_state["telegram_vigilancia_activa"] = False
    telegram_activo = st.sidebar.toggle(
        "Telegram vigilancia Chile",
        key="telegram_vigilancia_activa",
    )
else:
    telegram_activo = False
if telegram_activo:
    if telegram_configurado():
        st.sidebar.success("Telegram configurado.")
        st.sidebar.caption(
            f"Disparo: patron M7+ (≥{UMBRAL_NOTIFICACION_TELEGRAM}% / match ≥{UMBRAL_MATCH_M7_TELEGRAM}%) "
            f"o firma ruptura (b≤{alertas.UMBRAL_B_RUPTURA}, ≥{alertas.MIN_SISMOS_RUPTURA} sismos)."
        )
    else:
        st.sidebar.warning("Falta TELEGRAM_TOKEN / TELEGRAM_CHAT_ID en secrets.")
if admin_activo:
    st.sidebar.caption("Vigilancia 24/7: GitHub Actions cada 6 h (scripts/vigilancia_automatica.py).")

_mundo_sidebar = bool(mundo_lab and mundo_lab.MODULO_MUNDO_ACTIVO and admin_activo)
if _mundo_sidebar:
    red_operativa = st.sidebar.radio(
        "Red CORE NETWORK",
        ["Chile Nacional", "Mundo LAB"],
        horizontal=True,
    )
else:
    red_operativa = "Chile Nacional"
    nodo_mundo_sel = None

_nodos_mundo = (
    mundo_lab.listar_nodos_mundo() if _mundo_sidebar and mundo_lab
    else list(_NODOS_MUNDO_INLINE.keys())
)
_default_mundo = (
    mundo_lab.nodo_por_defecto() if _mundo_sidebar and mundo_lab
    else "Filipinas · Mindanao"
)
if "nodo_mundo_sel" not in st.session_state and _default_mundo:
    st.session_state["nodo_mundo_sel"] = _default_mundo

if red_operativa == "Mundo LAB" and _mundo_sidebar:
    nodo_mundo_sel = st.sidebar.selectbox(
        "Nodo global CORE NETWORK",
        _nodos_mundo,
        index=_nodos_mundo.index(st.session_state.get("nodo_mundo_sel", _default_mundo)),
    )
    st.session_state["nodo_mundo_sel"] = nodo_mundo_sel
    estacion_sel = list(ESTACIONES_CONFIG.keys())[3]
    config = ESTACIONES_CONFIG[estacion_sel]
    st.sidebar.caption(f"Red mundial activa · {nodo_mundo_sel}")
else:
    nodo_mundo_sel = st.session_state.get("nodo_mundo_sel", _default_mundo) if _mundo_sidebar else None
    estacion_sel = st.sidebar.selectbox("Estación Chile", list(ESTACIONES_CONFIG.keys()), index=3)
    config = ESTACIONES_CONFIG[estacion_sel]
    if _mundo_sidebar:
        st.sidebar.caption("Pestaña MUNDO (LAB) usa el último nodo global guardado.")

if modo_demo:
    estacion_sel = ESCENARIO_DEMO_CATASTROFICO["estacion"]
    config = ESTACIONES_CONFIG[estacion_sel]
    nodo_demo = ESCENARIO_DEMO_MUNDO["nodo"]
    if nodo_demo in _nodos_mundo:
        nodo_mundo_sel = nodo_demo
        st.session_state["nodo_mundo_sel"] = nodo_demo
    st.sidebar.warning(
        f"Demo: **{estacion_sel}** · firma **{ESCENARIO_DEMO_CATASTROFICO['evento_ref']}** "
        f"({ESCENARIO_DEMO_CATASTROFICO['mag_ref']})"
    )
    if nodo_demo in _nodos_mundo:
        st.sidebar.caption(f"MUNDO LAB demo: **{nodo_demo}** · ref. {ESCENARIO_DEMO_MUNDO['evento_ref']}")

st.sidebar.markdown("---")
bitacora = leer_bitacora_bytes()
if bitacora and admin_activo:
    st.sidebar.download_button("Bitácora CSV", bitacora, "nazca_log_historico.csv", use_container_width=True)

# ==============================================================================
# PROCESAMIENTO
# ==============================================================================
df_sismos = pd.DataFrame()
df_sismos_local = pd.DataFrame()
api_nueva = False
consultado_usgs = consultado_noaa = "—"

if modo_demo:
    esc = ESCENARIO_DEMO_CATASTROFICO
    df_sismos = generar_sismos_demo_escenario(config, esc)
    df_sismos_local = filtrar_sismos_estacion(df_sismos, config["lat"], config["lon"])
    total_sismos_chile = esc["sismos_chile_14d"]
    total_sismos = esc["sismos_locales_14d"]
    b_val = esc["b_value"]
    kp = esc["kp"]
    shoa = esc["shoa"]
    cond = esc["cond"]
    presion = esc["presion"]
    termico = esc["termico"]
    insar = esc["insar"]
    consultado_usgs = esc["consultado_usgs"]
    consultado_noaa = esc["consultado_noaa"]
    origen_em = f"DEMO · firma {esc['evento_ref']}"
    gnss_info = None
    atmos_info = None
    cond_info = None
    shoa_info = None
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
    shoa, cond, presion, termico, insar, origen_em, gnss_info, atmos_info, cond_info, shoa_info = telemetria_estable(
        estacion_sel, config, total_sismos, ttl_seg, modo_sat, nodo_offline
    )

estado, icono, puntaje, log_filtro = calcular_riesgo_fusion(
    insar, total_sismos, b_val, cond, shoa, config, kp, termico, presion
)
estado, icono, puntaje, log_filtro = aplicar_control_calidad(
    estado, icono, puntaje, log_filtro, modo_demo=modo_demo,
    gnss_info=gnss_info, atmos_info=atmos_info, cond_info=cond_info, shoa_info=shoa_info,
)

clave_log = f"{estacion_sel}_{round(puntaje, 1)}_{bloque if not modo_demo else 'demo'}"
if not modo_demo and st.session_state.get("ultimo_log") != clave_log:
    registrar_en_bitacora(estacion_sel, estado, puntaje, insar, b_val, cond, shoa)
    st.session_state["ultimo_log"] = clave_log

df_match, mejor_ev, mejor_match = comparar_con_historico(insar, total_sismos, b_val, cond, shoa)
df_calibracion = construir_calibracion_estaciones(
    df_sismos, kp, ttl_seg, modo_sat, consultado_usgs, consultado_noaa
)
nivel_alerta = clasificar_nivel_alerta(puntaje, mejor_match, b_val, total_sismos, insar)

clave_evidencia = f"evidencia_{estacion_sel}_{bloque}_{nivel_alerta['nivel']}_{round(puntaje, 1)}_{round(mejor_match, 1)}"
if not modo_demo and st.session_state.get("ultima_evidencia") != clave_evidencia:
    registrar_evidencia_preevento(
        estacion_sel, config, estado, puntaje, nivel_alerta, mejor_ev, mejor_match,
        total_sismos, total_sismos_chile, b_val, insar, cond, shoa, presion,
        termico, kp, consultado_usgs, consultado_noaa, origen_em, log_filtro,
    )
    st.session_state["ultima_evidencia"] = clave_evidencia

telegram_estado = "Telegram desactivado."
if telegram_activo:
    puede_notificar, detalle_notificacion, motivo_telegram = debe_notificar_telegram(
        estacion_sel, mejor_ev, puntaje, mejor_match, modo_demo, b_val, total_sismos, insar
    )
    if puede_notificar:
        mensaje = construir_mensaje_telegram(
            estacion_sel, estado, puntaje, b_val, total_sismos, insar, cond, shoa,
            mejor_ev, mejor_match, consultado_usgs,
            nivel_alerta, nivel_alerta["ventana"],
            motivo_disparo=motivo_telegram,
            modo_demo=modo_demo,
        )
        ok_telegram, telegram_estado = enviar_telegram(mensaje)
        if ok_telegram:
            estado_suscriptores = enviar_alerta_suscriptores(mensaje, estacion_sel, nivel_alerta, modo_demo)
            telegram_estado = f"{telegram_estado} {estado_suscriptores}"
            st.session_state[detalle_notificacion] = ahora_chile()
    else:
        telegram_estado = detalle_notificacion

# ==============================================================================
# INTERFAZ
# ==============================================================================
logo_base64 = cargar_logo_base64()
st.markdown(
    f"""
    <div class="nazca-header">
        <img class="nazca-logo" src="data:image/png;base64,{logo_base64}" alt="Logo NAZCA" />
        <div class="nazca-title">
            <h1>NAZCA NEURAL DETECTOR</h1>
            <span>CORE MONITOR v8.0 · VIGILANCIA SISMICA EXPERIMENTAL</span>
            <p>Monitoreo inteligente de señales sismicas, patrones M7+ y telemetria regional para apoyar decisiones tempranas con trazabilidad tecnica.</p>
            <div class="nazca-badge">PRIVATE TEST NETWORK · CHILE SEISMIC WATCH</div>
            <span class="nazca-credit">Desarrollado por Sandro Pereira A. · CEO & Developer</span>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)
if modo_simple:
    st.caption(
        f"Build **{APP_BUILD}** · Zona: **{nombre_zona_simple(estacion_sel)}** · "
        f"Vista simple para decisiones · Cambia a **Técnica** en la barra lateral para monitoreo completo."
    )
else:
    st.caption(
        f"Build **{APP_BUILD}** | Enlace: **{canal}** | Caché APIs: **{intervalo}** | "
        f"MUNDO LAB: **{getattr(mundo_lab, 'MUNDO_LAB_VERSION', 'no cargado')}**"
    )
if not modo_simple and (not mundo_lab or not mapa_tect or not informes_pdf):
    st.warning(
        "Deploy incompleto en el servidor. Deben existir en GitHub: "
        "`nazca_mundo_lab.py`, `nazca_mapa_tectonico.py`, `nazca_informes_pdf.py` y `pydeck` en requirements.txt. "
        "Luego Reboot en Streamlit Cloud."
    )

if modo_simple:
    if api_nueva:
        st.caption("Datos sísmicos recién actualizados.")
    else:
        st.caption(f"Última actualización registrada: {consultado_usgs}")
else:
    if api_nueva:
        st.success("Datos actualizados desde USGS / NOAA")
    else:
        st.info(f"📦 Sirviendo caché — USGS: {consultado_usgs} | NOAA Kp: {consultado_noaa}")

if modo_simple:
    tab_vivo, tab_acerca = st.tabs(["MONITOREO", "ACERCA DE"])
    tab_hist = tab_cal = tab_calidad = tab_suscripcion = tab_evidencia = tab_mundo = None
else:
    (
        tab_vivo, tab_hist, tab_cal, tab_calidad, tab_acerca,
        tab_suscripcion, tab_evidencia, tab_mundo,
    ) = st.tabs([
        "ESCANEO EN VIVO",
        "COMPARATIVA M7+",
        "CALIBRACIÓN ESTACIONES",
        "INFORME DE CALIDAD",
        "ACERCA DE",
        "SUSCRIPCIÓN TELEGRAM",
        "EVIDENCIA Y VALIDACIÓN",
        "MUNDO (LAB)",
    ])

with tab_vivo:
    if modo_simple:
        render_vista_simple(
            estacion_sel, nivel_alerta, puntaje, total_sismos, total_sismos_chile,
            mejor_ev, mejor_match, estado, b_val, insar, shoa, cond,
            df_sismos, df_sismos_local, df_calibracion, config, consultado_usgs,
            modo_demo, mapa_tect, nodo_offline,
        )
    else:
        if modo_demo and admin_activo:
            st.error("MODO SIMULACIÓN CATASTRÓFICA ACTIVO — ejemplo experimental, no alerta oficial.")
            st.info(ESCENARIO_DEMO_CATASTROFICO["descripcion"])
        if puntaje >= 90:
            st.error(f"CRÍTICO — Match {puntaje:.1f}%")
        elif puntaje >= UMBRAL_CRITICO:
            st.warning(f"ADVERTENCIA CRÍTICA — Match {puntaje:.1f}%")
        elif puntaje >= 40:
            st.warning(f"ATENCIÓN — Match {puntaje:.1f}%")
        else:
            st.success("Estable")

        if nivel_alerta["nivel"] == "ROJO":
            st.error(
                f"{nivel_alerta['color']} ALERTA ROJA EXPERIMENTAL - ventana de vigilancia {nivel_alerta['ventana']}. "
                f"{nivel_alerta['mensaje']}"
            )
            if sirena_activa and nivel_alerta.get("sirena"):
                clave_sirena = f"sirena_{estacion_sel}_{round(puntaje, 1)}_{mejor_ev}_{'demo' if modo_demo else bloque}"
                if st.session_state.get("ultima_sirena") != clave_sirena:
                    render_sirena_alerta()
                    st.session_state["ultima_sirena"] = clave_sirena
        elif nivel_alerta["nivel"] == "NARANJO":
            st.warning(
                f"{nivel_alerta['color']} ALERTA NARANJA EXPERIMENTAL - ventana de vigilancia {nivel_alerta['ventana']}. "
                f"{nivel_alerta['mensaje']}"
            )
        elif nivel_alerta["nivel"] == "AMARILLO":
            st.warning(
                f"{nivel_alerta['color']} ALERTA AMARILLA EXPERIMENTAL - ventana de vigilancia {nivel_alerta['ventana']}. "
                f"{nivel_alerta['mensaje']}"
            )
        else:
            st.info(f"{nivel_alerta['color']} Nivel verde: {nivel_alerta['mensaje']}")

        st.caption(log_filtro)
        if nodo_offline:
            st.warning("Nodo offline — telemetría por interpolación de vecindad.")
        if modo_demo and admin_activo and sirena_activa:
            if st.button("Probar sirena de emergencia (demo)", use_container_width=True):
                render_sirena_alerta()
                st.session_state["ultima_sirena"] = f"demo_manual_{ahora_chile().isoformat()}"

        if telegram_activo and admin_activo:
            st.caption(f"Telegram vigilancia M7+: {telegram_estado}")
            if st.button("Enviar prueba Telegram", use_container_width=True):
                ok_test, msg_test = enviar_telegram(
                    "NAZCA CORE MONITOR - prueba de Telegram. Sistema experimental de vigilancia tecnica."
                )
                if ok_test:
                    st.success(msg_test)
                else:
                    st.warning(msg_test)
            if modo_demo and st.button("Enviar demo de emergencia Telegram", use_container_width=True):
                mensaje_demo = construir_mensaje_telegram(
                    estacion_sel, estado, puntaje, b_val, total_sismos, insar, cond, shoa,
                    mejor_ev, mejor_match, consultado_usgs,
                    nivel_alerta, nivel_alerta["ventana"],
                    motivo_disparo="Prueba demo admin",
                    modo_demo=True,
                )
                ok_demo, msg_demo = enviar_telegram(mensaje_demo)
                if sirena_activa:
                    render_sirena_alerta()
                if ok_demo:
                    st.success(msg_demo)
                else:
                    st.warning(msg_demo)
            if modo_demo and st.button("Enviar demo de emergencia a suscriptores", use_container_width=True):
                mensaje_demo_suscriptores = construir_mensaje_telegram(
                    estacion_sel, estado, puntaje, b_val, total_sismos, insar, cond, shoa,
                    mejor_ev, mejor_match, consultado_usgs,
                    nivel_alerta, nivel_alerta["ventana"],
                    motivo_disparo="Prueba demo suscriptores",
                    modo_demo=True,
                )
                enviados, errores = enviar_prueba_suscriptores(mensaje_demo_suscriptores)
                if sirena_activa:
                    render_sirena_alerta()
                st.info(f"Demo enviada a suscriptores activos: {enviados} | errores: {errores}")

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Estado", f"{icono}")
        c2.metric("Match", f"{puntaje:.1f}%")
        c3.metric("Deformación", f"{insar:.1f}%", help="Índice NAZCA; con GNSS usa velocidad real mm/año (NGL MIDAS SA).")
        c4.metric("b-value", f"{b_val}")
        c5.metric("Kp NOAA", kp)
        if atmos_info:
            st.caption(
                f"Atmósfera **{atmos_info['origen']}**: "
                f"P={atmos_info['presion_hpa']:.1f} hPa · T={atmos_info['temp_c']:.1f} °C · "
                f"HR={atmos_info['humedad_pct']:.0f}% · lluvia={atmos_info['precip_mm']:.1f} mm"
            )
        if cond_info and cond_info.get("cond_proxy_fisico"):
            st.caption(
                f"EM proxy **{cond_info['zona_suelo']}**: {cond_info['conductividad_ms_m']:.2f} mS/m "
                f"(saturación agua est. {cond_info.get('saturacion_agua_est', 0):.2f})"
            )
        if shoa_info and shoa_info.get("shoa_real"):
            conf_m = "confiable" if alertas.shoa_es_real(shoa_info) else "lejana"
            st.caption(
                f"SHOA **{shoa_info['codigo_ioc'].upper()}** ({conf_m}, {shoa_info.get('dist_km', '?')} km): "
                f"anom={shoa_info['anomalia_cm']:.1f} cm · tasa={shoa_info['tasa_cm_h']:.1f} cm/h · "
                f"{shoa_info.get('ultima_lectura', '')}"
            )
        if gnss_info:
            conf_txt = "confiable" if gnss_info.get("gnss_confiable") else "lejana"
            acel_txt = ""
            acel = gnss_info.get("aceleracion") or {}
            if acel.get("acelerando"):
                acel_txt = (
                    f" · **aceleración 1A** H={acel.get('horiz_reciente_mm_anio', 0):.1f} mm/yr "
                    f"(×{acel.get('ratio_horizontal', 1):.2f})"
                )
            st.caption(
                f"GNSS **{gnss_info['estacion_gnss']}** ({gnss_info.get('match', 'cercana')}, "
                f"{gnss_info.get('dist_km', '?')} km, {conf_txt}): "
                f"H={gnss_info['horiz_mm_anio']:.1f} mm/yr · V={gnss_info['vu_mm_anio']:.1f} mm/yr"
                f"{acel_txt} · {gnss_info['marco']}"
            )

        c6, c7, c8 = st.columns(3)
        c6.metric("Patrón M7+", f"{mejor_match:.1f}%")
        c7.metric("Nivel alerta", f"{nivel_alerta['color']} {nivel_alerta['nivel']}")
        c8.metric("Ventana vigilancia", nivel_alerta["ventana"])

        c9, c10 = st.columns(2)
        c9.metric("EM (Z-score)", f"{cond} mS/m")
        c10.metric("SHOA", f"{shoa} cm")

        col_mapa, col_tabla = st.columns([1.8, 1.2])
        df_tension_tabla = pd.DataFrame()
        with col_mapa:
            st.markdown("#### Mapa de tensión acumulada · Cinturón de Fuego")
            st.caption(
                "El mapa muestra **dónde se acumula tensión** (14D USGS + modelo NAZCA). "
                "Los temblores pasados quedan en la tabla lateral."
            )
            if mapa_tect:
                df_tension_tabla, _ = mapa_tect.render_mapa_tension(
                    df_sismos=df_sismos,
                    df_calibracion=df_calibracion,
                    estaciones_config=ESTACIONES_CONFIG,
                    estacion_lat=config["lat"],
                    estacion_lon=config["lon"],
                    estacion_label=estacion_sel,
                    zoom=4,
                    altura=400,
                    mapa_nativo=_usar_mapa_nativo(modo_demo),
                )
                st.caption(mapa_tect.leyenda_mapa_tension())
                if not df_tension_tabla.empty:
                    n_alta = int((df_tension_tabla["tension_pct"] >= 70).sum())
                    n_anom = int(
                        (~df_tension_tabla["anomalias"].astype(str).str.contains(
                            "Normal|normales", case=False, na=False
                        )).sum()
                    )
                    st.caption(f"**Vigilancia:** {n_alta} zona(s) con tension >=70% · {n_anom} con parametros anomalos")
            else:
                _render_mapa_anillo_fuego(
                    df_sismos_local, config["lat"], config["lon"], estacion_sel,
                    zoom=4, altura=400, modo_demo=modo_demo,
                    mapa_principal=True,
                )

        with col_tabla:
            st.markdown("##### Sismos 14D — estación activa")
            st.caption(
                f"Origen EM: {origen_em} | Sismos 14D Chile: {total_sismos_chile} | "
                f"Radio {RADIO_ESTACION_KM} km: {total_sismos} | USGS: {consultado_usgs}"
            )
            st.dataframe(
                _df_ui(df_sismos_local[["Magnitud", "Lugar", "Fecha", "Distancia_km"]] if not df_sismos_local.empty else pd.DataFrame(columns=["Magnitud", "Lugar", "Fecha", "Distancia_km"])),
                height=180, use_container_width=True,
            )
            if not df_tension_tabla.empty:
                st.markdown("##### Tensión por zona / nodo")
                st.dataframe(
                    _df_ui(df_tension_tabla.rename(columns={
                        "zona": "Zona",
                        "tension_pct": "Tensión %",
                        "sismos_14d": "Sismos 14D",
                        "b_value": "b-value",
                        "anomalias": "Parámetros",
                    })),
                    height=180,
                    use_container_width=True,
                    hide_index=True,
                )

        st.markdown("#### 📄 Informes PDF")
        col_pdf1, col_pdf2 = st.columns(2)
        with col_pdf1:
            if st.button("Generar PDF técnico", use_container_width=True):
                st.session_state["pdf"] = generar_pdf(
                    estacion_sel, puntaje, estado, b_val, cond, shoa, total_sismos, canal, kp,
                    config, insar, presion, termico, origen_em, mejor_ev, mejor_match,
                    total_sismos_chile, consultado_usgs, consultado_noaa, nivel_alerta=nivel_alerta, modo_demo=modo_demo,
                )
            if st.session_state.get("pdf"):
                st.download_button(
                    "⬇️ Guardar PDF técnico",
                    st.session_state["pdf"],
                    f"Informe_Tecnico_Nazca_{config['id']}.pdf",
                    "application/pdf",
                    use_container_width=True,
                    key=f"dl_pdf_tecnico_{config['id']}",
                )
        with col_pdf2:
            if informes_pdf:
                st.markdown("##### Comparativa 14D vs gran sismo Chile")
                st.dataframe(
                    _df_ui(informes_pdf.tabla_comparativa_chile(
                        b_val, insar, cond, shoa, total_sismos, total_sismos_chile, puntaje, EVENTOS_M7, mejor_ev,
                    )),
                    use_container_width=True,
                    hide_index=True,
                )
                ult_local = df_sismos_local.iloc[0].to_dict() if not df_sismos_local.empty else None
                pdf_comp_chile = informes_pdf.generar_pdf_comparativa_chile(
                    estacion=estacion_sel, config=config, puntaje=puntaje, estado=estado,
                    nivel_alerta=nivel_alerta, b_val=b_val, insar=insar, cond=cond, shoa=shoa,
                    total_sismos=total_sismos, total_sismos_chile=total_sismos_chile,
                    mejor_ev=mejor_ev, mejor_match=mejor_match, consultado_usgs=consultado_usgs,
                    eventos_m7=EVENTOS_M7, df_evidencia=leer_evidencia_preevento(),
                    coincidencias=pd.DataFrame(), ultimo_sismo=ult_local,
                    ahora=pd.Timestamp(ahora_chile()), logo_path=LOGO_PATH,
                )
                informes_pdf.boton_descarga_pdf(
                    pdf_comp_chile,
                    f"comparativa_chile_{config['id']}.pdf",
                    boton_key=f"dl_pdf_chile_vivo_{config['id']}",
                    etiqueta="⬇️ Informe comparativo 14D Chile (PDF)",
                )
            else:
                st.caption("Sube `nazca_informes_pdf.py` para activar comparativa PDF.")

if not modo_simple:
    with tab_hist:
        st.markdown("### Referencia histórica CHILE — Match vs terremotos M7+ (14D pre-sismo)")
        st.caption("Solo eventos nacionales. Terremotos mundiales están en la pestaña MUNDO (LAB).")
        st.dataframe(_df_ui(pd.DataFrame([{
            "Evento": e["evento"], "Magnitud": e["mag"], "b-value 14D": e["b_14d"],
            "Sismos": e["sismos_14d"], "InSAR": e["insar"], "EM": e["cond"], "SHOA": e["shoa"],
        } for e in EVENTOS_M7])), use_container_width=True, hide_index=True)

        st.markdown("#### Match calculado con telemetría actual")
        m1, m2, m3 = st.columns(3)
        m1.metric("Match riesgo actual", f"{puntaje:.1f}%")
        m2.metric("Similitud M7+", f"{mejor_match:.1f}%")
        m3.metric("Evento más parecido", mejor_ev)
        st.dataframe(_df_ui(df_match), use_container_width=True, hide_index=True)

        if mejor_match >= 75 and puntaje >= UMBRAL_CRITICO:
            st.error(f"Patrón crítico alineado con **{mejor_ev}**.")
        elif mejor_match >= 60:
            st.warning(f"Similitud notable con **{mejor_ev}** ({mejor_match:.1f}%).")

    with tab_cal:
        st.markdown("### Calibración de estaciones")
        st.caption(
            "Esta tabla usa una ventana móvil sísmica 14D de Chile y recalcula SHOA, InSAR, EM, presión, térmico, "
            "riesgo y match M7+ por estación. La base se refresca por caché en horas, no en cada recarga, para evitar ruido y lentitud."
        )
        st.dataframe(_df_ui(df_calibracion), use_container_width=True, hide_index=True)
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
        q1.metric("Fuente sísmica", "USGS 14D móvil")
        q2.metric("Radio local", f"{RADIO_ESTACION_KM} km")
        q3.metric("Tope heurístico", f"{MAX_RIESGO_CON_TELEMETRIA_ESTIMADA:.0f}%")
        q4.metric("Caché APIs", f"{ttl_horas} h")

        st.markdown("#### Parámetros activos")
        df_parametros = pd.DataFrame([
            {"Parámetro": "SISMO_BVAL", "Valor": PESOS["SISMO_BVAL"], "Calidad": "REAL/CALCULADO", "Uso": "Peso de b-value y actividad sísmica local"},
            {"Parámetro": "INSAR", "Valor": PESOS["INSAR"], "Calidad": "ESTIMADO", "Uso": "Deformación cortical estimada"},
            {"Parámetro": "CONDUCT", "Valor": PESOS["CONDUCT"], "Calidad": "ESTIMADO", "Uso": "Anomalía electromagnética"},
            {"Parámetro": "SHOA", "Valor": PESOS["SHOA"], "Calidad": "REAL (IOC)", "Uso": "Anomalía mareográfica IOC UNESCO por nodo"},
            {"Parámetro": "ATMOS", "Valor": PESOS["ATMOS"], "Calidad": "ESTIMADO", "Uso": "Presión y componente térmico"},
            {"Parámetro": "UMBRAL_CRITICO", "Valor": UMBRAL_CRITICO, "Calidad": "MODELO", "Uso": "Umbral interno de riesgo"},
            {"Parámetro": "RADIO_ESTACION_KM", "Valor": RADIO_ESTACION_KM, "Calidad": "MODELO", "Uso": "Radio local usado para calcular cada estación"},
            {"Parámetro": "MAX_RIESGO_ESTIMADO", "Valor": MAX_RIESGO_CON_TELEMETRIA_ESTIMADA, "Calidad": "CONTROL", "Uso": "Evita alerta crítica con telemetría no instrumental"},
            {"Parámetro": "VENTANA_SISMICA", "Valor": "14D móvil", "Calidad": "OPERATIVO", "Uso": "Recalcula con datos frescos disponibles sin esperar un ciclo completo"},
            {"Parámetro": "CACHE_API", "Valor": f"{ttl_horas} h", "Calidad": "OPERATIVO", "Uso": "Reduce llamadas a USGS/NOAA y estabiliza la app pública"},
        ])
        st.dataframe(_df_ui(df_parametros), use_container_width=True, hide_index=True)

        st.markdown("#### Protocolo mensual de calibración")
        st.write(
            "1. Exportar la tabla de calibración de estaciones.\n"
            "2. Revisar bitácora del mes contra ventanas móviles USGS 14D.\n"
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

    with tab_suscripcion:
        st.markdown("### Suscripción gratuita Telegram — Chile")
        st.info(
            "Registro gratuito para vigilancia experimental de **Chile** (estaciones nacionales). "
            "La pestaña MUNDO (LAB) es implementación separada y **no usa esta lista de suscriptores**. "
            "Las notificaciones son experimentales, no oficiales y no representan una predicción determinística."
        )
        st.caption(
            "Privacidad: el registro no se muestra públicamente en la web. Los datos se usan solo para enviar avisos "
            "experimentales por Telegram."
        )
        st.caption(
            "Nota técnica: sin Google Sheets, los registros hechos desde la web pueden perderse al redeploy. "
            "Configura `SUBSCRIBERS_WEBAPP_URL` y `SUBSCRIBERS_API_KEY` (ver GOOGLE_APPS_SCRIPT.md)."
        )
        if apps_script_configurado():
            st.success("Registro persistente conectado a Google Sheets privado.")
        else:
            faltan = [
                nombre for nombre in ("SUBSCRIBERS_WEBAPP_URL", "SUBSCRIBERS_API_KEY")
                if not obtener_secret(nombre)
            ]
            st.warning(
                "Registro persistente Google Sheets no configurado. La suscripción web puede ser temporal. "
                f"Falta en secrets: {', '.join(faltan)}. Sigue GOOGLE_APPS_SCRIPT.md y reinicia la app."
            )
        st.write(
            "Para suscribirte: abre el bot de Telegram, presiona **Start** o envía `/start`, "
            "obtén tu **Chat ID** con @userinfobot o @RawDataBot, y completa este formulario."
        )

        with st.form("form_suscripcion_telegram"):
            nombre_sub = st.text_input("Nombre o alias", placeholder="Ej: Sandro, primo, equipo pruebas")
            chat_id_sub = st.text_input("Telegram Chat ID", placeholder="Ej: 7321245766")
            estacion_sub = st.selectbox(
                "Zona / estación Chile de interés",
                ["Todas"] + list(ESTACIONES_CONFIG.keys()),
            )
            nivel_sub = st.selectbox("Nivel mínimo para recibir aviso", ["AMARILLO", "NARANJO", "ROJO"], index=0)
            acepta_sub = st.checkbox("Acepto participar en una prueba gratuita, experimental y no oficial.")
            registrar_sub = st.form_submit_button("Suscribirme gratis / actualizar datos", use_container_width=True)

        if registrar_sub:
            if not chat_id_sub.strip().isdigit():
                st.warning("El Chat ID debe contener solo números.")
            elif not acepta_sub:
                st.warning("Debes aceptar la condición experimental/no oficial.")
            else:
                sub = upsert_suscriptor_telegram(nombre_sub, chat_id_sub, estacion_sub, nivel_sub)
                st.success(f"Suscripción gratuita registrada para {sub['nombre']} ({sub['nivel_minimo']}).")
                ok_bienvenida, msg_bienvenida = enviar_telegram(
                    "NAZCA CORE MONITOR - suscripcion Chile registrada. Recibiras avisos experimentales "
                    "de estaciones nacionales segun tu configuracion. MUNDO LAB no incluido. No es alerta oficial.",
                    chat_id=sub["chat_id"],
                )
                if ok_bienvenida:
                    st.success("Mensaje de bienvenida enviado por Telegram.")
                else:
                    st.warning(f"Suscripción guardada, pero Telegram respondió: {msg_bienvenida}")

        st.markdown("#### Estado privado de suscripción")
        st.caption(
            f"Suscriptores activos registrados: {contar_suscriptores_activos()}. "
            "Por privacidad, nombres y Chat ID no se muestran en la interfaz pública."
        )

        if admin_activo:
            st.markdown("#### Pruebas de envío admin")
            chat_prueba = st.text_input("Chat ID para prueba individual", placeholder="Pega aquí el Chat ID")
            if st.button("Enviar prueba a suscriptor", use_container_width=True):
                if not chat_prueba.strip().isdigit():
                    st.warning("Ingresa un Chat ID numérico.")
                else:
                    ok_sub, msg_sub = enviar_telegram(
                        "NAZCA CORE MONITOR - prueba de suscripcion familiar. Uso privado experimental, no alerta oficial.",
                        chat_id=chat_prueba.strip(),
                    )
                    if ok_sub:
                        st.success(msg_sub)
                    else:
                        st.warning(msg_sub)

            if st.button("Enviar prueba a todos los suscriptores activos", use_container_width=True):
                enviados, errores = enviar_prueba_suscriptores(
                    "NAZCA CORE MONITOR - prueba general de suscripcion gratuita. Uso experimental privado, no alerta oficial."
                )
                st.info(f"Prueba enviada a suscriptores activos: {enviados} | errores: {errores}")

    with tab_evidencia:
        if not admin_activo:
            st.info("Módulo privado. Ingresa PIN admin para revisar evidencia y validación.")
        else:
            st.markdown("### Evidencia y validación post-evento")
            st.caption(
                f"Hora actual del sistema: **{ahora_chile().strftime('%Y-%m-%d %H:%M:%S')}** ({CHILE_TZ_LABEL})"
            )
            st.info(
                "Este módulo cruza snapshots previos del sistema contra eventos USGS posteriores. "
                "Su objetivo es documentar coincidencias experimentales, falsos positivos y trazabilidad."
            )
            df_evidencia = leer_evidencia_preevento()
            eventos_validacion = eventos_usgs_validacion(df_sismos, magnitud_min=5.0)
            coincidencias = evaluar_coincidencias_evidencia(df_evidencia, eventos_validacion)

            e1, e2, e3 = st.columns(3)
            e1.metric("Snapshots guardados", len(df_evidencia))
            e2.metric("Eventos USGS M5+", len(eventos_validacion))
            e3.metric("Coincidencias", len(coincidencias))

            if not df_evidencia.empty:
                st.markdown("#### Últimas evidencias previas")
                st.caption(
                    f"Fechas en {CHILE_TZ_LABEL}. "
                    "Los registros guardados antes de este ajuste pueden mostrar hora UTC del servidor (+4 h respecto a Chile)."
                )
                cols_evidencia = [
                    "fecha_hora", "estacion", "nivel", "puntaje", "match_m7",
                    "b_value", "sismos_locales_14d", "hash_evidencia",
                ]
                st.dataframe(_df_ui(df_evidencia[cols_evidencia].tail(25).sort_values("fecha_hora", ascending=False)), use_container_width=True, hide_index=True)
                st.download_button(
                    "Descargar evidencia previa CSV",
                    df_evidencia.drop(columns=["fecha_hora_dt"], errors="ignore").to_csv(index=False).encode("utf-8-sig"),
                    "nazca_evidencia_preevento.csv",
                    "text/csv",
                    use_container_width=True,
                )
            else:
                st.caption("Aún no hay snapshots de evidencia previa guardados.")

            st.markdown("#### Coincidencias post-evento")
            if not coincidencias.empty:
                st.dataframe(_df_ui(coincidencias), use_container_width=True, hide_index=True)
            else:
                st.caption("No hay coincidencias bajo los criterios actuales.")

            st.markdown("#### 📄 Informes comparativos 14D (PDF)")
            if informes_pdf:
                st.dataframe(
                    _df_ui(informes_pdf.tabla_comparativa_chile(
                        b_val, insar, cond, shoa, total_sismos, total_sismos_chile, puntaje, EVENTOS_M7, mejor_ev,
                    )),
                    use_container_width=True,
                    hide_index=True,
                )
                ult_ev = eventos_validacion.iloc[0].to_dict() if not eventos_validacion.empty else None
                pdf_chile = informes_pdf.generar_pdf_comparativa_chile(
                    estacion=estacion_sel, config=config, puntaje=puntaje, estado=estado,
                    nivel_alerta=nivel_alerta, b_val=b_val, insar=insar, cond=cond, shoa=shoa,
                    total_sismos=total_sismos, total_sismos_chile=total_sismos_chile,
                    mejor_ev=mejor_ev, mejor_match=mejor_match, consultado_usgs=consultado_usgs,
                    eventos_m7=EVENTOS_M7, df_evidencia=df_evidencia, coincidencias=coincidencias,
                    ultimo_sismo=ult_ev, ahora=pd.Timestamp(ahora_chile()), logo_path=LOGO_PATH,
                )
                nombre_pdf_ev = f"comparativa_chile_{estacion_sel[:24].replace(' ', '_')}.pdf"
                informes_pdf.boton_descarga_pdf(
                    pdf_chile,
                    nombre_pdf_ev,
                    boton_key=f"dl_pdf_chile_evidencia_{config['id']}",
                    etiqueta="⬇️ Informe comparativo 14D Chile (PDF)",
                )
                informe_validacion = generar_informe_validacion_texto(coincidencias)
                st.download_button(
                    "Descargar validación TXT",
                    informe_validacion.encode("utf-8"),
                    "informe_validacion_post_evento_nazca.txt",
                    "text/plain",
                    use_container_width=True,
                    key=f"dl_txt_validacion_{config['id']}",
                )
                with st.expander("Ver informe de validación TXT"):
                    st.text(informe_validacion)
            else:
                informe_validacion = generar_informe_validacion_texto(coincidencias)
                st.warning("Sube `nazca_informes_pdf.py` para ver informes PDF en pantalla.")
                st.download_button(
                    "Descargar informe de validación TXT",
                    informe_validacion.encode("utf-8"),
                    "informe_validacion_post_evento_nazca.txt",
                    "text/plain",
                    use_container_width=True,
                )
                with st.expander("Ver informe de validación"):
                    st.text(informe_validacion)

    with tab_mundo:
        _render_mundo_lab_ui(
            admin_activo, ttl_seg, ttl_horas, nodo_mundo_sel,
            forzar_mundo, modo_sat, modo_demo, kp,
        )

with tab_acerca:
    render_tab_acerca_de(ttl_seg, ttl_horas, consultado_usgs, consultado_noaa)

if not modo_simple:
    st.sidebar.metric("Próxima API", f"≤ {ttl_horas} h")
    st.sidebar.metric("b-value regional", f"{b_val}")
else:
    st.sidebar.metric("Nivel actual", f"{nivel_alerta.get('color', '')} {nivel_alerta.get('nivel', '')}")

st.markdown(
    """
    <div class="nazca-footer">
        NAZCA Neural Detector · Desarrollado por Sandro Pereira A. · CEO & Developer · Proyecto experimental privado
    </div>
    """,
    unsafe_allow_html=True,
)

