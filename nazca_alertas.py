"""Umbrales Telegram, firma de ruptura y envío de alertas (Chile)."""
from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

CHILE_TZ = ZoneInfo("America/Santiago")
CANAL_SUSCRIPCION_CHILE = "chile"

# --- Umbrales generales ---
UMBRAL_CRITICO = 75.0
UMBRAL_SIRENA_ROJA = 85.0
MAX_RIESGO_CON_TELEMETRIA_ESTIMADA = 74.0
MAX_RIESGO_CON_GNSS_CONFIABLE = 92.0
MAX_RIESGO_CON_ATMOS_REAL = 85.0
MAX_RIESGO_CON_GNSS_Y_ATMOS = 96.0
MAX_RIESGO_CON_TELEMETRIA_REAL = 98.0
GNSS_DIST_MAX_CONFIABLE_KM = 100.0
SHOA_DIST_MAX_CONFIABLE_KM = 120.0

# --- Telegram: patrón M7+ histórico ---
UMBRAL_NOTIFICACION_TELEGRAM = 68.0
UMBRAL_MATCH_M7_TELEGRAM = 78.0

# --- Telegram: firma ruptura abrupta (b-value + actividad) ---
UMBRAL_B_RUPTURA = 0.68
UMBRAL_B_RUPTURA_CRITICO = 0.65
MIN_SISMOS_RUPTURA = 12
MIN_MATCH_RUPTURA = 60.0
INSAR_COMPUERTA = 50.0

COOLDOWN_TELEGRAM_MIN = 90
COOLDOWN_RUPTURA_MIN = 120


def ahora_chile() -> datetime:
    return datetime.now(CHILE_TZ).replace(tzinfo=None)


def sanitizar_texto(texto) -> str:
    if texto is None:
        return ""
    limpio = unicodedata.normalize("NFKD", str(texto))
    return limpio.encode("ascii", "ignore").decode("ascii")


def obtener_secret(nombre: str, secrets: dict[str, str] | None = None) -> str:
    valor = str(os.environ.get(nombre, "") or "").strip()
    if valor:
        return valor
    if secrets and nombre in secrets:
        return str(secrets[nombre] or "").strip()
    return ""


def leer_secrets_toml(ruta: Path | None = None) -> dict[str, str]:
    ruta = ruta or Path(__file__).resolve().parent / ".streamlit" / "secrets.toml"
    vals: dict[str, str] = {}
    if not ruta.exists():
        return vals
    for line in ruta.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        vals[key.strip()] = val.strip().strip('"')
    return vals


def compuerta_abierta(insar: float, total_sismos: int) -> bool:
    return insar >= INSAR_COMPUERTA or total_sismos >= 2


def gnss_es_confiable(gnss_info: dict | None) -> bool:
    if not gnss_info:
        return False
    dist = gnss_info.get("dist_km")
    if dist is None:
        return False
    return float(dist) <= GNSS_DIST_MAX_CONFIABLE_KM


def atmos_es_real(atmos_info: dict | None) -> bool:
    return bool(atmos_info and atmos_info.get("atmos_real"))


def cond_es_proxy_fisico(cond_info: dict | None) -> bool:
    return bool(cond_info and cond_info.get("cond_proxy_fisico"))


def shoa_es_real(shoa_info: dict | None) -> bool:
    if not shoa_info or not shoa_info.get("shoa_real"):
        return False
    dist = shoa_info.get("dist_km")
    if dist is None:
        return True
    return float(dist) <= SHOA_DIST_MAX_CONFIABLE_KM


def tope_riesgo_permitido(
    gnss_info: dict | None = None,
    atmos_info: dict | None = None,
    cond_info: dict | None = None,
    shoa_info: dict | None = None,
) -> float:
    gnss_ok = gnss_es_confiable(gnss_info)
    atmos_ok = atmos_es_real(atmos_info)
    cond_ok = cond_es_proxy_fisico(cond_info)
    shoa_ok = shoa_es_real(shoa_info)
    if gnss_ok and atmos_ok and cond_ok and shoa_ok:
        return MAX_RIESGO_CON_TELEMETRIA_REAL
    if gnss_ok and atmos_ok and cond_ok:
        return MAX_RIESGO_CON_GNSS_Y_ATMOS
    if gnss_ok:
        return MAX_RIESGO_CON_GNSS_CONFIABLE
    if atmos_ok and cond_ok:
        return MAX_RIESGO_CON_ATMOS_REAL
    return MAX_RIESGO_CON_TELEMETRIA_ESTIMADA


def es_firma_ruptura(
    b_val: float,
    total_sismos: int,
    insar: float,
    mejor_match: float,
) -> tuple[bool, str]:
    if not compuerta_abierta(insar, total_sismos):
        return False, "Compuerta cerrada."
    if total_sismos < MIN_SISMOS_RUPTURA:
        return False, f"Actividad local insuficiente ({total_sismos} < {MIN_SISMOS_RUPTURA})."
    if b_val > UMBRAL_B_RUPTURA:
        return False, f"b-value {b_val} sobre umbral ruptura ({UMBRAL_B_RUPTURA})."
    if mejor_match < MIN_MATCH_RUPTURA:
        return False, f"Match {mejor_match:.1f}% bajo mínimo ruptura ({MIN_MATCH_RUPTURA})."
    if b_val <= UMBRAL_B_RUPTURA_CRITICO:
        return True, f"Firma ruptura CRITICA: b-value {b_val}."
    return True, f"Firma ruptura: b-value {b_val} con {total_sismos} sismos 14D."


def clasificar_nivel_alerta(
    puntaje: float,
    mejor_match: float,
    b_val: float,
    total_sismos: int,
    insar: float = 0.0,
):
    ruptura, _ = es_firma_ruptura(b_val, total_sismos, insar, mejor_match)
    if ruptura and b_val <= UMBRAL_B_RUPTURA_CRITICO:
        return {
            "nivel": "ROJO",
            "color": "🔴",
            "ventana": "6 a 24 horas",
            "mensaje": "Firma b-value pre-ruptura critica. Vigilancia maxima experimental.",
            "sirena": True,
            "origen": "ruptura",
        }
    if puntaje >= UMBRAL_SIRENA_ROJA and mejor_match >= UMBRAL_MATCH_M7_TELEGRAM and b_val <= 0.70:
        return {
            "nivel": "ROJO",
            "color": "🔴",
            "ventana": "6 a 24 horas",
            "mensaje": "Vigilancia maxima experimental. Requiere revision tecnica inmediata.",
            "sirena": True,
            "origen": "patron_m7",
        }
    if ruptura or (puntaje >= UMBRAL_NOTIFICACION_TELEGRAM and mejor_match >= UMBRAL_MATCH_M7_TELEGRAM):
        return {
            "nivel": "NARANJO",
            "color": "🟠",
            "ventana": "12 a 24 horas",
            "mensaje": "Vigilancia alta experimental. Validar tendencia y fuentes externas.",
            "sirena": False,
            "origen": "ruptura" if ruptura else "patron_m7",
        }
    if puntaje >= 55 or mejor_match >= 65 or total_sismos >= 12:
        return {
            "nivel": "AMARILLO",
            "color": "🟡",
            "ventana": "24 a 36 horas",
            "mensaje": "Observacion reforzada. Podrian presentarse cambios en umbrales.",
            "sirena": False,
            "origen": "vigilancia",
        }
    return {
        "nivel": "VERDE",
        "color": "🟢",
        "ventana": "Sin ventana critica",
        "mensaje": "Condicion estable dentro del modelo experimental.",
        "sirena": False,
        "origen": "estable",
    }


class CooldownStore:
    def __init__(self, ruta: str | Path | None = None, data: dict | None = None):
        self._data = dict(data or {})
        self._ruta = Path(ruta) if ruta else None
        if self._ruta and self._ruta.exists():
            try:
                self._data = json.loads(self._ruta.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def get(self, clave: str):
        raw = self._data.get(clave)
        if not raw:
            return None
        try:
            return datetime.fromisoformat(str(raw))
        except ValueError:
            return None

    def set(self, clave: str, cuando: datetime | None = None):
        self._data[clave] = (cuando or ahora_chile()).isoformat()
        if self._ruta:
            self._ruta.parent.mkdir(parents=True, exist_ok=True)
            self._ruta.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")


def evaluar_disparo_telegram(
    estacion: str,
    mejor_ev: str,
    puntaje: float,
    mejor_match: float,
    b_val: float,
    total_sismos: int,
    insar: float,
    modo_demo: bool,
    cooldown: CooldownStore,
):
    if modo_demo:
        return False, "Modo demo: Telegram desactivado.", ""

    ruptura, detalle_ruptura = es_firma_ruptura(b_val, total_sismos, insar, mejor_match)
    patron_ok = puntaje >= UMBRAL_NOTIFICACION_TELEGRAM and mejor_match >= UMBRAL_MATCH_M7_TELEGRAM

    if not ruptura and not patron_ok:
        if puntaje < UMBRAL_NOTIFICACION_TELEGRAM:
            return False, "Indice bajo umbral Telegram.", ""
        if mejor_match < UMBRAL_MATCH_M7_TELEGRAM:
            return False, "Match M7+ bajo umbral Telegram.", ""
        return False, "Sin condicion de disparo.", ""

    tipo = "ruptura" if ruptura else "patron_m7"
    clave = f"telegram_{tipo}_{estacion}_{mejor_ev}"
    cooldown_min = COOLDOWN_RUPTURA_MIN if ruptura else COOLDOWN_TELEGRAM_MIN
    ultimo = cooldown.get(clave)
    ahora = ahora_chile()
    if ultimo and ahora - ultimo < timedelta(minutes=cooldown_min):
        restante = cooldown_min - int((ahora - ultimo).total_seconds() // 60)
        return False, f"Cooldown {tipo} activo ({restante} min).", clave

    motivo = detalle_ruptura if ruptura else (
        f"Patron M7+ {mejor_ev} ({mejor_match:.1f}%) | indice {puntaje:.1f}%"
    )
    return True, motivo, clave


def construir_mensaje_telegram(
    estacion,
    estado,
    puntaje,
    b_val,
    total_sismos,
    insar,
    cond,
    shoa,
    mejor_ev,
    mejor_match,
    consultado_usgs,
    nivel_alerta,
    ventana_vigilancia,
    motivo_disparo="",
    modo_demo=False,
):
    if modo_demo:
        encabezado = "NAZCA CORE MONITOR - SIMULACION DE EMERGENCIA\n"
        nota_demo = "\nMODO DEMO ACTIVO: mensaje de prueba operacional, no corresponde a evento real.\n"
    else:
        encabezado = "NAZCA CORE MONITOR - VIGILANCIA CHILE\n"
        nota_demo = ""
    origen = nivel_alerta.get("origen", "vigilancia") if isinstance(nivel_alerta, dict) else "vigilancia"
    tipo_txt = {
        "ruptura": "FIRMA b-value PRE-RUPTURA",
        "patron_m7": "PATRON M7+ HISTORICO",
    }.get(origen, "VIGILANCIA EXPERIMENTAL")
    return (
        encabezado
        + "No es alerta oficial ni prediccion deterministica.\n\n"
        + f"Tipo disparo: {tipo_txt}\n"
        + (f"Motivo: {motivo_disparo}\n" if motivo_disparo else "")
        + f"Estacion: {estacion}\n"
        + f"Estado interno: {estado}\n"
        + f"Nivel de alerta: {nivel_alerta if isinstance(nivel_alerta, str) else nivel_alerta.get('color', '') + ' ' + nivel_alerta.get('nivel', '')}\n"
        + f"Ventana vigilancia: {ventana_vigilancia}\n"
        + f"Indice vigilancia: {puntaje:.1f}%\n"
        + f"Patron M7+ similar: {mejor_ev} ({mejor_match:.1f}%)\n"
        + f"Sismos locales 14D: {total_sismos}\n"
        + f"b-value local: {b_val}\n"
        + f"InSAR estimado: {insar:.1f}%\n"
        + f"EM: {cond} mS/m | SHOA: {shoa} cm\n"
        + f"USGS: {consultado_usgs}\n\n"
        + nota_demo
        + "Accion sugerida: revisar tendencia, generar PDF tecnico y validar con especialista."
    )


def enviar_telegram(mensaje: str, chat_id=None, secrets: dict[str, str] | None = None):
    token = obtener_secret("TELEGRAM_TOKEN", secrets)
    destino = str(chat_id or obtener_secret("TELEGRAM_CHAT_ID", secrets) or "").strip()
    if not token:
        return False, "Falta TELEGRAM_TOKEN en secrets."
    if not destino:
        return False, "Falta chat_id destino o TELEGRAM_CHAT_ID en secrets."
    try:
        res = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": destino,
                "text": sanitizar_texto(mensaje),
                "disable_web_page_preview": True,
            },
            timeout=12,
        )
        if res.status_code == 200:
            return True, "Notificacion enviada."
        return False, f"Telegram HTTP {res.status_code}: {res.text[:160]}"
    except requests.RequestException as exc:
        return False, f"Error Telegram: {exc}"


def llamar_apps_script(payload: dict, secrets: dict[str, str]):
    url = obtener_secret("SUBSCRIBERS_WEBAPP_URL", secrets)
    api_key = obtener_secret("SUBSCRIBERS_API_KEY", secrets)
    if not url or not api_key:
        return None
    try:
        res = requests.post(url, json={**payload, "api_key": api_key}, timeout=12)
        if res.status_code != 200:
            return None
        datos = res.json()
        return datos if datos.get("ok") else None
    except (requests.RequestException, ValueError):
        return None


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
            "canal": str(sub.get("canal", CANAL_SUSCRIPCION_CHILE) or CANAL_SUSCRIPCION_CHILE).strip().lower(),
        })
    return normalizados


def cargar_suscriptores_chile(secrets: dict[str, str] | None = None):
    secrets = secrets or leer_secrets_toml()
    suscriptores = []
    datos = llamar_apps_script({"action": "list"}, secrets)
    if datos:
        suscriptores.extend(datos.get("subscribers", []))
    ruta_local = Path(__file__).resolve().parent / "nazca_suscriptores_telegram.json"
    if ruta_local.exists():
        try:
            local = json.loads(ruta_local.read_text(encoding="utf-8"))
            if isinstance(local, list):
                suscriptores.extend(local)
        except (json.JSONDecodeError, OSError):
            pass
    return [
        s for s in normalizar_suscriptores(suscriptores)
        if s.get("canal", CANAL_SUSCRIPCION_CHILE) == CANAL_SUSCRIPCION_CHILE
    ]


def nivel_valor(nombre_nivel: str) -> int:
    orden = {"VERDE": 0, "AMARILLO": 1, "NARANJO": 2, "ROJO": 3}
    return orden.get(str(nombre_nivel).upper(), 0)


def enviar_alerta_suscriptores(mensaje: str, estacion_actual: str, nivel_alerta: dict, secrets: dict | None = None):
    enviados = 0
    errores = 0
    nivel_nombre = nivel_alerta.get("nivel", "AMARILLO") if isinstance(nivel_alerta, dict) else str(nivel_alerta)
    for sub in cargar_suscriptores_chile(secrets):
        if not sub.get("activo", True):
            continue
        estacion_sub = sub.get("estacion", "Todas")
        if estacion_sub not in ("Todas", estacion_actual):
            continue
        if nivel_valor(nivel_nombre) < nivel_valor(sub.get("nivel_minimo", "AMARILLO")):
            continue
        ok, _ = enviar_telegram(mensaje, chat_id=sub.get("chat_id"), secrets=secrets)
        enviados += 1 if ok else 0
        errores += 0 if ok else 1
    return enviados, errores
