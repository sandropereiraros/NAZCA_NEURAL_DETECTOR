import importlib.util
import json
import os
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
from fpdf import FPDF

APP_BUILD = "2026-06-08-v4"
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _cargar_modulo_local(nombre, archivo):
    ruta = os.path.join(_BASE_DIR, archivo)
    if not os.path.exists(ruta):
        return None, f"Falta archivo: {archivo}"
    try:
        spec = importlib.util.spec_from_file_location(nombre, ruta)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod, None
    except Exception as exc:
        return None, f"Error cargando {archivo}: {exc}"


mundo_lab, _err_mundo = _cargar_modulo_local("nazca_mundo_lab", "nazca_mundo_lab.py")
mapa_tect, _err_mapa = _cargar_modulo_local("nazca_mapa_tectonico", "nazca_mapa_tectonico.py")

# ==============================================================================
# CONFIGURACIÓN
# ==============================================================================
st.set_page_config(page_title=f"NAZCA CORE MONITOR v8.0 · {APP_BUILD}", layout="wide")

PESOS = {"SISMO_BVAL": 0.62, "INSAR": 0.18, "CONDUCT": 0.10, "SHOA": 0.06, "ATMOS": 0.01}
UMBRAL_CRITICO = 75.0
UMBRAL_NOTIFICACION_TELEGRAM = 70.0
UMBRAL_MATCH_M7_TELEGRAM = 80.0
COOLDOWN_TELEGRAM_MIN = 60
UMBRAL_SIRENA_ROJA = 85.0
RADIO_ESTACION_KM = 350
MAX_RIESGO_CON_TELEMETRIA_ESTIMADA = 74.0
INTERVALOS_API = {"3 horas": 10800, "6 horas": 21600, "12 horas": 43200, "24 horas": 86400}
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".nazca_cache")
LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "nazca_logo.png")
SUSCRIPTORES_TELEGRAM = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nazca_suscriptores_telegram.json")
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
    try:
        return st.secrets.get(nombre, "")
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
        })
    return normalizados


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
    chat_id = chat_id or obtener_secret("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False, "Telegram no configurado en secrets."
    try:
        res = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
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
    for sub in cargar_suscriptores_telegram():
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
    return f"Suscriptores notificados: {enviados} | errores: {errores}"


def enviar_prueba_suscriptores(mensaje):
    enviados = 0
    errores = 0
    for sub in cargar_suscriptores_telegram():
        if not sub.get("activo", True):
            continue
        ok, _ = enviar_telegram(mensaje, chat_id=sub.get("chat_id"))
        enviados += 1 if ok else 0
        errores += 0 if ok else 1
    return enviados, errores


def contar_suscriptores_activos():
    return sum(1 for sub in cargar_suscriptores_telegram() if sub.get("activo", True))


def debe_notificar_telegram(estacion, mejor_ev, puntaje, mejor_match, modo_demo):
    if not modo_demo and puntaje < UMBRAL_NOTIFICACION_TELEGRAM:
        return False, "Riesgo bajo umbral Telegram."
    if not modo_demo and mejor_match < UMBRAL_MATCH_M7_TELEGRAM:
        return False, "Match M7+ bajo umbral Telegram."

    clave = f"telegram_{'demo_' if modo_demo else ''}{estacion}_{mejor_ev}"
    ultimo = st.session_state.get(clave)
    ahora = ahora_chile()
    if ultimo and ahora - ultimo < timedelta(minutes=COOLDOWN_TELEGRAM_MIN):
        restante = COOLDOWN_TELEGRAM_MIN - int((ahora - ultimo).total_seconds() // 60)
        return False, f"Cooldown activo ({restante} min)."
    return True, clave


def construir_mensaje_telegram(
    estacion, estado, puntaje, b_val, total_sismos, insar, cond, shoa,
    mejor_ev, mejor_match, consultado_usgs, nivel_alerta, ventana_vigilancia, modo_demo=False,
):
    if modo_demo:
        encabezado = "NAZCA CORE MONITOR - SIMULACION DE EMERGENCIA\n"
        nota_demo = "\nMODO DEMO ACTIVO: mensaje de prueba operacional, no corresponde a evento real.\n"
    else:
        encabezado = "NAZCA CORE MONITOR - VIGILANCIA EXPERIMENTAL M7+\n"
        nota_demo = ""
    return (
        encabezado +
        "No es alerta oficial ni prediccion deterministica.\n\n"
        f"Estacion: {estacion}\n"
        f"Estado interno: {estado}\n"
        f"Nivel de alerta: {nivel_alerta}\n"
        f"Ventana vigilancia: {ventana_vigilancia}\n"
        f"Indice vigilancia: {puntaje:.1f}%\n"
        f"Patron M7+ similar: {mejor_ev} ({mejor_match:.1f}%)\n"
        f"Sismos locales 14D: {total_sismos}\n"
        f"b-value local: {b_val}\n"
        f"InSAR estimado: {insar:.1f}%\n"
        f"EM: {cond} mS/m | SHOA: {shoa} cm\n"
        f"USGS: {consultado_usgs}\n\n"
        f"{nota_demo}"
        "Accion sugerida: revisar tendencia, generar PDF tecnico y validar con especialista."
    )


def clasificar_nivel_alerta(puntaje, mejor_match, b_val, total_sismos):
    if puntaje >= UMBRAL_SIRENA_ROJA and mejor_match >= UMBRAL_MATCH_M7_TELEGRAM and b_val <= 0.70:
        return {
            "nivel": "ROJO",
            "color": "🔴",
            "ventana": "6 a 24 horas",
            "mensaje": "Vigilancia maxima experimental. Requiere revision tecnica inmediata.",
            "sirena": True,
        }
    if puntaje >= UMBRAL_NOTIFICACION_TELEGRAM and mejor_match >= UMBRAL_MATCH_M7_TELEGRAM:
        return {
            "nivel": "NARANJO",
            "color": "🟠",
            "ventana": "12 a 24 horas",
            "mensaje": "Vigilancia alta experimental. Validar tendencia y fuentes externas.",
            "sirena": False,
        }
    if puntaje >= 55 or mejor_match >= 65 or total_sismos >= 12:
        return {
            "nivel": "AMARILLO",
            "color": "🟡",
            "ventana": "24 a 36 horas",
            "mensaje": "Observacion reforzada. Podrian presentarse cambios positivos o negativos en umbrales.",
            "sirena": False,
        }
    return {
        "nivel": "VERDE",
        "color": "🟢",
        "ventana": "Sin ventana critica",
        "mensaje": "Condicion estable dentro del modelo experimental.",
        "sirena": False,
    }


def render_sirena_alerta():
    st.error("SIRENA LOCAL: vigilancia roja experimental. Validar con fuentes oficiales.")


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


def generar_sismos_demo(config, cantidad=85):
    rng = random.Random(f"demo_{config['lat']}_{config['lon']}")
    ahora = ahora_chile()
    filas = []
    for i in range(cantidad):
        mag = round(rng.uniform(3.4, 6.8), 1)
        if i < 6:
            mag = round(rng.uniform(5.8, 7.4), 1)
        filas.append({
            "Magnitud": mag,
            "Lugar": "SIMULACIÓN CATASTRÓFICA - enjambre local",
            "Latitud": config["lat"] + rng.uniform(-1.4, 1.4),
            "Longitud": config["lon"] + rng.uniform(-1.4, 1.4),
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
- InSAR, EM, SHOA, presión y térmico: telemetría estimada/simulada mientras no existan sensores o APIs reales conectadas.

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
intervalo = st.sidebar.selectbox(
    "Intervalo caché APIs (USGS / NOAA)",
    list(INTERVALOS_API.keys()),
    index=1,
)
ttl_seg = INTERVALOS_API[intervalo]
ttl_horas = max(1, ttl_seg // 3600)

st.sidebar.caption(
    f"Las APIs se consultan como máximo cada **{ttl_horas} h**. "
    "Entre consultas se sirven datos desde `.nazca_cache/`."
)

st.sidebar.markdown("---")
admin_pin = st.sidebar.text_input("PIN admin", type="password", placeholder="Opcional")
admin_esperado = obtener_secret("ADMIN_PIN")
admin_activo = bool(admin_esperado and admin_pin == admin_esperado)
if admin_activo:
    st.sidebar.success("Modo admin activo.")
    _ver_mundo = getattr(mundo_lab, "MUNDO_LAB_VERSION", None) if mundo_lab else None
    st.sidebar.caption(
        f"Build app: **{APP_BUILD}** · MUNDO: **{_ver_mundo or 'NO'}** · "
        f"Mapa: **{'OK' if mapa_tect else 'NO'}**"
    )
    if _err_mundo:
        st.sidebar.error(_err_mundo)
    if _err_mapa:
        st.sidebar.warning(_err_mapa)
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
    modo_demo = st.sidebar.checkbox("Simulación Catastrófica", value=False)
    modo_sat = st.sidebar.toggle("Colapso red terrestre (satelital)", value=False)
    sirena_activa = st.sidebar.toggle("Sirena local en alerta roja", value=True)
else:
    modo_demo = False
    modo_sat = False
    sirena_activa = False
canal = "SATELITAL LEO" if modo_sat else "TERRESTRE"

st.sidebar.markdown("---")
telegram_activo = st.sidebar.toggle("Telegram vigilancia M7+", value=False) if admin_activo else False
if telegram_activo:
    if telegram_configurado():
        st.sidebar.success("Telegram configurado.")
    else:
        st.sidebar.warning("Falta TELEGRAM_TOKEN / TELEGRAM_CHAT_ID en secrets.")

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

_nodos_mundo = mundo_lab.listar_nodos_mundo() if _mundo_sidebar else []
_default_mundo = mundo_lab.nodo_por_defecto() if _mundo_sidebar else None
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
    df_sismos = generar_sismos_demo(config)
    df_sismos_local = filtrar_sismos_estacion(df_sismos, config["lat"], config["lon"])
    total_sismos_chile = len(df_sismos)
    total_sismos = len(df_sismos_local)
    b_val, kp = 0.55, 1
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
nivel_alerta = clasificar_nivel_alerta(puntaje, mejor_match, b_val, total_sismos)

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
    puede_notificar, detalle_notificacion = debe_notificar_telegram(
        estacion_sel, mejor_ev, puntaje, mejor_match, modo_demo
    )
    if puede_notificar:
        mensaje = construir_mensaje_telegram(
            estacion_sel, estado, puntaje, b_val, total_sismos, insar, cond, shoa,
            mejor_ev, mejor_match, consultado_usgs,
            f"{nivel_alerta['color']} {nivel_alerta['nivel']}", nivel_alerta["ventana"],
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
st.caption(
    f"Build **{APP_BUILD}** | Enlace: **{canal}** | Caché APIs: **{intervalo}** | "
    f"MUNDO LAB: **{getattr(mundo_lab, 'MUNDO_LAB_VERSION', 'no cargado')}**"
)
if not mundo_lab or not mapa_tect:
    st.warning(
        "Deploy incompleto en el servidor. Deben existir en GitHub: "
        "`nazca_mundo_lab.py`, `nazca_mapa_tectonico.py` y `pydeck` en requirements.txt. "
        "Luego Reboot en Streamlit Cloud."
    )

if api_nueva:
    st.success("Datos actualizados desde USGS / NOAA")
else:
    st.info(f"📦 Sirviendo caché — USGS: {consultado_usgs} | NOAA Kp: {consultado_noaa}")

_tab_labels = [
    "ESCANEO EN VIVO",
    "COMPARATIVA M7+",
    "CALIBRACIÓN ESTACIONES",
    "INFORME DE CALIDAD",
    "SUSCRIPCIÓN TELEGRAM",
    "EVIDENCIA Y VALIDACIÓN",
]
_tab_labels.append("MUNDO (LAB)")
_tabs = st.tabs(_tab_labels)
tab_vivo, tab_hist, tab_cal, tab_calidad, tab_suscripcion, tab_evidencia = _tabs[:6]
tab_mundo = _tabs[6] if len(_tabs) > 6 else None

with tab_vivo:
    if modo_demo and admin_activo:
        st.error("MODO SIMULACIÓN CATASTRÓFICA ACTIVO - datos ficticios para prueba de respuesta.")
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
        if sirena_activa:
            clave_sirena = f"sirena_{estacion_sel}_{round(puntaje, 1)}_{mejor_ev}"
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
                f"{nivel_alerta['color']} {nivel_alerta['nivel']}", nivel_alerta["ventana"],
                modo_demo=True,
            )
            ok_demo, msg_demo = enviar_telegram(mensaje_demo)
            if ok_demo:
                st.success(msg_demo)
            else:
                st.warning(msg_demo)
        if modo_demo and st.button("Enviar demo de emergencia a suscriptores", use_container_width=True):
            mensaje_demo_suscriptores = construir_mensaje_telegram(
                estacion_sel, estado, puntaje, b_val, total_sismos, insar, cond, shoa,
                mejor_ev, mejor_match, consultado_usgs,
                f"{nivel_alerta['color']} {nivel_alerta['nivel']}", nivel_alerta["ventana"],
                modo_demo=True,
            )
            enviados, errores = enviar_prueba_suscriptores(mensaje_demo_suscriptores)
            st.info(f"Demo enviada a suscriptores activos: {enviados} | errores: {errores}")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Estado", f"{icono}")
    c2.metric("Match", f"{puntaje:.1f}%")
    c3.metric("InSAR", f"{insar:.1f}%")
    c4.metric("b-value", f"{b_val}")
    c5.metric("Kp NOAA", kp)

    c6, c7, c8 = st.columns(3)
    c6.metric("Patrón M7+", f"{mejor_match:.1f}%")
    c7.metric("Nivel alerta", f"{nivel_alerta['color']} {nivel_alerta['nivel']}")
    c8.metric("Ventana vigilancia", nivel_alerta["ventana"])

    c9, c10 = st.columns(2)
    c9.metric("EM (Z-score)", f"{cond} mS/m")
    c10.metric("SHOA", f"{shoa} cm")

    col_mapa, col_tabla = st.columns([1.8, 1.2])
    with col_mapa:
        st.markdown("#### Mapa sísmico regional + Cinturón de Fuego")
        if mapa_tect:
            mapa_tect.render_mapa_tectonico(
                df_sismos=df_sismos_local,
                estacion_lat=config["lat"],
                estacion_lon=config["lon"],
                estacion_label=estacion_sel,
                estacion_color_rgb=[249, 115, 22, 255] if nodo_offline else [59, 130, 246, 255],
                lat_center=config["lat"],
                lon_center=config["lon"],
                zoom=4,
                altura=400,
                mostrar_anillo=True,
            )
            st.caption(mapa_tect.leyenda_mapa_tectonico())
        else:
            mapa_df = pd.DataFrame([{"lat": config["lat"], "lon": config["lon"], "size": 160, "color": "#3b82f6"}])
            if not df_sismos.empty:
                sismos_mapa = df_sismos.rename(columns={"Latitud": "lat", "Longitud": "lon"})
                sismos_mapa["size"] = (sismos_mapa["Magnitud"].clip(lower=2.5) ** 2) * 12
                sismos_mapa["color"] = np.where(sismos_mapa["Magnitud"] >= 4.0, "#ef4444", "#facc15")
                mapa_df = pd.concat([mapa_df, sismos_mapa[["lat", "lon", "size", "color"]]], ignore_index=True)
            st.map(mapa_df, latitude="lat", longitude="lon", size="size", color="color", zoom=4)

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
        st.session_state["pdf"] = generar_pdf(
            estacion_sel, puntaje, estado, b_val, cond, shoa, total_sismos, canal, kp,
            config, insar, presion, termico, origen_em, mejor_ev, mejor_match,
            total_sismos_chile, consultado_usgs, consultado_noaa, nivel_alerta=nivel_alerta, modo_demo=modo_demo,
        )
    if st.session_state.get("pdf"):
        st.download_button(
            "Guardar PDF",
            st.session_state["pdf"],
            f"Informe_Tecnico_Nazca_{config['id']}.pdf",
            "application/pdf",
            use_container_width=True,
        )

with tab_hist:
    st.markdown("### Referencia histórica CHILE — Match vs terremotos M7+ (14D pre-sismo)")
    st.caption("Solo eventos nacionales. Terremotos mundiales están en la pestaña MUNDO (LAB).")
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
        "Esta tabla usa una ventana móvil sísmica 14D de Chile y recalcula SHOA, InSAR, EM, presión, térmico, "
        "riesgo y match M7+ por estación. La base se refresca por caché en horas, no en cada recarga, para evitar ruido y lentitud."
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
    q1.metric("Fuente sísmica", "USGS 14D móvil")
    q2.metric("Radio local", f"{RADIO_ESTACION_KM} km")
    q3.metric("Tope heurístico", f"{MAX_RIESGO_CON_TELEMETRIA_ESTIMADA:.0f}%")
    q4.metric("Caché APIs", f"{ttl_horas} h")

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
        {"Parámetro": "VENTANA_SISMICA", "Valor": "14D móvil", "Calidad": "OPERATIVO", "Uso": "Recalcula con datos frescos disponibles sin esperar un ciclo completo"},
        {"Parámetro": "CACHE_API", "Valor": f"{ttl_horas} h", "Calidad": "OPERATIVO", "Uso": "Reduce llamadas a USGS/NOAA y estabiliza la app pública"},
    ])
    st.dataframe(df_parametros, use_container_width=True, hide_index=True)

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
    st.markdown("### Suscripción gratuita Telegram")
    st.info(
        "Registro gratuito para participar en pruebas privadas del sistema. Las notificaciones son experimentales, "
        "no oficiales y no representan una predicción determinística."
    )
    st.caption(
        "Privacidad: el registro no se muestra públicamente en la web. Los datos se usan solo para enviar avisos "
        "experimentales por Telegram."
    )
    st.caption(
        "Nota técnica: en Streamlit Cloud los registros hechos desde la web pueden reiniciarse al redeploy. "
        "Para suscriptores permanentes usa TELEGRAM_SUBSCRIBERS_JSON en Secrets privados."
    )
    if apps_script_configurado():
        st.success("Registro persistente conectado a Google Sheets privado.")
    else:
        st.warning("Registro persistente Google Sheets no configurado. La suscripción web puede ser temporal.")
    st.write(
        "Para suscribirte: abre el bot de Telegram, presiona **Start** o envía `/start`, "
        "obtén tu **Chat ID** con @userinfobot o @RawDataBot, y completa este formulario."
    )

    with st.form("form_suscripcion_telegram"):
        nombre_sub = st.text_input("Nombre o alias", placeholder="Ej: Sandro, primo, equipo pruebas")
        chat_id_sub = st.text_input("Telegram Chat ID", placeholder="Ej: 7321245766")
        estacion_sub = st.selectbox("Zona / estación de interés", ["Todas"] + list(ESTACIONES_CONFIG.keys()))
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
                "NAZCA CORE MONITOR - suscripcion gratuita registrada. Recibiras avisos experimentales segun tu configuracion. No es alerta oficial.",
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
            st.dataframe(df_evidencia[cols_evidencia].tail(25).sort_values("fecha_hora", ascending=False), use_container_width=True, hide_index=True)
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
            st.dataframe(coincidencias, use_container_width=True, hide_index=True)
        else:
            st.caption("No hay coincidencias bajo los criterios actuales.")

        informe_validacion = generar_informe_validacion_texto(coincidencias)
        st.download_button(
            "Descargar informe de validación TXT",
            informe_validacion.encode("utf-8"),
            "informe_validacion_post_evento_nazca.txt",
            "text/plain",
            use_container_width=True,
        )
        with st.expander("Ver informe de validación"):
            st.text(informe_validacion)

if tab_mundo is not None:
    with tab_mundo:
        if not mundo_lab:
            st.error("Módulo MUNDO LAB no cargó en el servidor.")
            st.code(_err_mundo or "nazca_mundo_lab.py no encontrado", language="text")
            st.info("Sube `nazca_mundo_lab.py` a GitHub y haz Reboot en Streamlit Cloud.")
        elif not getattr(mundo_lab, "MODULO_MUNDO_ACTIVO", False):
            st.warning("MUNDO LAB desactivado (MODULO_MUNDO_ACTIVO = False).")
        else:
            mundo_lab.render_mundo_lab(
                admin_activo=admin_activo,
                ttl_seg=ttl_seg,
                ttl_horas=ttl_horas,
                nodo_sel=nodo_mundo_sel,
                forzar=forzar_mundo,
                modo_sat=modo_sat,
                modo_demo=modo_demo,
                kp=kp,
            )

st.sidebar.metric("Próxima API", f"≤ {ttl_horas} h")
st.sidebar.metric("b-value regional", f"{b_val}")

st.markdown(
    """
    <div class="nazca-footer">
        NAZCA Neural Detector · Desarrollado por Sandro Pereira A. · CEO & Developer · Proyecto experimental privado
    </div>
    """,
    unsafe_allow_html=True,
)
