from datetime import datetime, timedelta, timezone
from math import asin, cos, radians, sin, sqrt

import httpx


PESOS = {"SISMO_BVAL": 0.62, "INSAR": 0.18, "CONDUCT": 0.10, "SHOA": 0.06, "ATMOS": 0.01}
UMBRAL_CRITICO = 75.0
UMBRAL_NOTIFICACION_TELEGRAM = 70.0
UMBRAL_MATCH_M7_TELEGRAM = 80.0
UMBRAL_SIRENA_ROJA = 85.0
RADIO_ESTACION_KM = 350
MAX_RIESGO_CON_TELEMETRIA_ESTIMADA = 74.0

CHILE_BOUNDS = {
    "min_lat": -56.0,
    "max_lat": -17.0,
    "min_lon": -76.5,
    "max_lon": -66.0,
}

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


def listar_estaciones() -> list[str]:
    return list(ESTACIONES_CONFIG.keys())


def distancia_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radio_tierra_km = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * radio_tierra_km * asin(sqrt(a))


async def fetch_sismos_chile(dias: int = 14) -> list[dict]:
    inicio = (datetime.now(timezone.utc) - timedelta(days=dias)).strftime("%Y-%m-%d")
    url = (
        "https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson"
        f"&starttime={inicio}"
        f"&minlatitude={CHILE_BOUNDS['min_lat']}&maxlatitude={CHILE_BOUNDS['max_lat']}"
        f"&minlongitude={CHILE_BOUNDS['min_lon']}&maxlongitude={CHILE_BOUNDS['max_lon']}"
        "&minmagnitude=2.5&orderby=time&limit=300"
    )
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as client:
        res = await client.get(url)
        res.raise_for_status()
        eventos = []
        for feature in res.json().get("features", []):
            props = feature["properties"]
            coords = feature["geometry"]["coordinates"]
            eventos.append({
                "magnitud": float(props.get("mag") or 0),
                "lugar": props.get("place", ""),
                "latitud": coords[1],
                "longitud": coords[0],
                "fecha": datetime.fromtimestamp(props["time"] / 1000, tz=timezone.utc),
            })
        return eventos


async def fetch_kp_noaa() -> int:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=5.0)) as client:
            res = await client.get("https://services.swpc.noaa.gov/products/noaa-scales.json")
            res.raise_for_status()
            return int(res.json().get("0", {}).get("GeomagneticStorms", {}).get("Scale", 0))
    except (httpx.HTTPError, ValueError, TypeError):
        return 0


def filtrar_sismos_estacion(sismos: list[dict], lat: float, lon: float) -> list[dict]:
    filtrados = []
    for sismo in sismos:
        distancia = distancia_km(lat, lon, sismo["latitud"], sismo["longitud"])
        if distancia <= RADIO_ESTACION_KM:
            filtrados.append({**sismo, "distancia_km": round(distancia, 1)})
    return filtrados


def calcular_b_value(sismos: list[dict]) -> float:
    if len(sismos) < 10:
        return 1.0
    magnitudes = [s["magnitud"] for s in sismos]
    mc = min(magnitudes)
    filtradas = [mag for mag in magnitudes if mag >= mc]
    if not filtradas:
        return 1.0
    promedio = sum(filtradas) / len(filtradas)
    if promedio <= mc:
        return 1.0
    b_value = (1.0 / (promedio - mc)) * 0.4343
    return round(max(0.4, min(b_value, 2.0)), 2)


def estimar_telemetria(config: dict, total_sismos: int) -> dict:
    insar = round(min(98.0, 45.0 + total_sismos * 3.2), 1)
    cond = round(config["baseline_cond"] + min(1.8, total_sismos * 0.035), 2)
    shoa = round(min(12.0, total_sismos * 0.11), 2)
    presion = round(config["baseline_pres"] - min(5.0, total_sismos * 0.08), 1)
    termico = round(min(2.5, total_sismos * 0.04), 2)
    return {
        "insar_pct": insar,
        "conductividad_ms_m": cond,
        "shoa_cm": shoa,
        "presion_hpa": presion,
        "termico": termico,
        "origen": "estimado_api",
    }


def calcular_riesgo_fusion(insar: float, total_sismos: int, b_val: float, cond: float, shoa: float, config: dict, kp: int, termico: float, presion: float) -> tuple[str, str, float, str]:
    compuerta = (insar >= 50.0) or (total_sismos >= 2)
    z = (cond - config["baseline_cond"]) / config["sigma_cond"]
    cond_val = cond if z > 1.2 else config["baseline_cond"]

    if not compuerta:
        score = 15.0 + min(insar * 0.1, 10.0)
        return "ESTABLE cortical", "verde", score, "INTERRUPTOR: sin estres mecanico verificado."

    if b_val <= 0.65:
        score_sismo = 100.0 * PESOS["SISMO_BVAL"]
        filtro = f"COMPUERTA ABIERTA // b-value critico ({b_val})."
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
        return "CRITICO", "rojo", score, filtro
    if score >= UMBRAL_CRITICO:
        return "ADVERTENCIA CRITICA", "naranjo", score, filtro
    if score >= 40:
        return "ATENCION SISMICA", "amarillo", score, filtro
    return "ESTABLE", "verde", score, filtro


def aplicar_control_calidad(estado: str, color: str, puntaje: float, log_filtro: str) -> tuple[str, str, float, str]:
    if puntaje > MAX_RIESGO_CON_TELEMETRIA_ESTIMADA:
        return (
            "VIGILANCIA ALTA HEURISTICA",
            "naranjo",
            MAX_RIESGO_CON_TELEMETRIA_ESTIMADA,
            f"{log_filtro} // Riesgo limitado: InSAR/EM/SHOA/presion/termico son estimados.",
        )
    return estado, color, puntaje, f"{log_filtro} // Calidad: USGS/NOAA real + telemetria estimada."


def similitud(actual: float, referencia: float, escala: float) -> float:
    return max(0.0, 100.0 - abs(actual - referencia) / escala * 100.0)


def comparar_con_historico(insar: float, total_sismos: int, b_val: float, cond: float, shoa: float) -> tuple[str, float]:
    matches = []
    for evento in EVENTOS_M7:
        match = round(
            similitud(b_val, evento["b_14d"], 0.6) * 0.30
            + similitud(insar, evento["insar"], 85) * 0.25
            + similitud(total_sismos, evento["sismos_14d"], max(evento["sismos_14d"], 15)) * 0.20
            + similitud(cond, evento["cond"], 2.0) * 0.15
            + similitud(abs(shoa), abs(evento["shoa"]), 15.0) * 0.10,
            1,
        )
        matches.append((evento["evento"], match))
    return max(matches, key=lambda item: item[1])


def clasificar_nivel_vigilancia(puntaje: float, similitud_m7: float, b_val: float, total_sismos: int) -> dict:
    if puntaje >= UMBRAL_SIRENA_ROJA and similitud_m7 >= UMBRAL_MATCH_M7_TELEGRAM and b_val <= 0.70:
        return {"nivel": "ROJO", "color": "rojo", "ventana": "6 a 24 horas", "sirena": True}
    if puntaje >= UMBRAL_NOTIFICACION_TELEGRAM and similitud_m7 >= UMBRAL_MATCH_M7_TELEGRAM:
        return {"nivel": "NARANJO", "color": "naranjo", "ventana": "12 a 24 horas", "sirena": False}
    if puntaje >= 55 or similitud_m7 >= 65 or total_sismos >= 12:
        return {"nivel": "AMARILLO", "color": "amarillo", "ventana": "24 a 36 horas", "sirena": False}
    return {"nivel": "VERDE", "color": "verde", "ventana": "Sin ventana critica", "sirena": False}


async def calcular_estado_nazca(estacion: str) -> dict:
    if estacion not in ESTACIONES_CONFIG:
        raise ValueError(f"Estacion no encontrada: {estacion}")

    config = ESTACIONES_CONFIG[estacion]
    sismos = await fetch_sismos_chile()
    kp = await fetch_kp_noaa()
    sismos_locales = filtrar_sismos_estacion(sismos, config["lat"], config["lon"])
    total_sismos = len(sismos_locales)
    b_val = calcular_b_value(sismos_locales)
    telemetria = estimar_telemetria(config, total_sismos)
    estado, color_estado, puntaje, log_filtro = calcular_riesgo_fusion(
        telemetria["insar_pct"],
        total_sismos,
        b_val,
        telemetria["conductividad_ms_m"],
        telemetria["shoa_cm"],
        config,
        kp,
        telemetria["termico"],
        telemetria["presion_hpa"],
    )
    estado, color_estado, puntaje, log_filtro = aplicar_control_calidad(estado, color_estado, puntaje, log_filtro)
    evento_m7, similitud_m7 = comparar_con_historico(
        telemetria["insar_pct"],
        total_sismos,
        b_val,
        telemetria["conductividad_ms_m"],
        telemetria["shoa_cm"],
    )
    vigilancia = clasificar_nivel_vigilancia(puntaje, similitud_m7, b_val, total_sismos)

    return {
        "estacion": estacion,
        "ubicacion": {"lat": config["lat"], "lon": config["lon"]},
        "estado_operativo": {
            "estado": estado,
            "color": color_estado,
            "indice_actual_pct": round(puntaje, 1),
            "descripcion": "Condicion actual del sistema segun fusion de riesgo local.",
        },
        "nivel_vigilancia": {
            **vigilancia,
            "similitud_historica_m7_pct": similitud_m7,
            "patron_m7_referencia": evento_m7,
            "descripcion": "Vigilancia preventiva por similitud con patrones historicos M7+.",
        },
        "metricas": {
            "sismos_chile_14d": len(sismos),
            "sismos_locales_14d": total_sismos,
            "b_value": b_val,
            "kp_noaa": kp,
            **telemetria,
        },
        "trazabilidad": {
            "fuentes": ["USGS", "NOAA SWPC", "telemetria estimada"],
            "radio_local_km": RADIO_ESTACION_KM,
            "log_modelo": log_filtro,
            "generado_utc": datetime.now(timezone.utc).isoformat(),
            "aviso": "Prototipo experimental. No corresponde a alerta oficial ni prediccion deterministica.",
        },
    }
