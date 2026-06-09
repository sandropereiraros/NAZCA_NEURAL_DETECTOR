"""Tendencia sísmica — Gutenberg-Richter y Omori-Utsu (capa aparte del semáforo NAZCA)."""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

CHILE_TZ = ZoneInfo("America/Santiago")
MIN_EVENTOS_GR = 10
MAG_PRINCIPAL_OMORI = 4.5
VENTANA_TENDENCIA_D = 7
ALPHA_SIGNIFICANCIA = 0.05
LOG10_E = math.log10(math.e)  # estimador Aki / MLE estándar

ESTILO_DIRECCION = {
    "SUBE": {
        "color": "#f85149",
        "bg": "rgba(248, 81, 73, 0.14)",
        "border": "#f85149",
        "icono": "↑",
        "etiqueta_corta": "Sube",
        "etiqueta_larga": "La tasa sísmica **sube** (cambio significativo)",
    },
    "BAJA": {
        "color": "#3fb950",
        "bg": "rgba(63, 185, 80, 0.14)",
        "border": "#3fb950",
        "icono": "↓",
        "etiqueta_corta": "Baja",
        "etiqueta_larga": "La tasa sísmica **baja** (cambio significativo)",
    },
    "ESTABLE": {
        "color": "#58a6ff",
        "bg": "rgba(88, 166, 255, 0.14)",
        "border": "#58a6ff",
        "icono": "→",
        "etiqueta_corta": "Estable",
        "etiqueta_larga": "La tasa sísmica se mantiene **estable**",
    },
    "SIN_DATO": {
        "color": "#8b949e",
        "bg": "rgba(139, 148, 158, 0.12)",
        "border": "#484f58",
        "icono": "·",
        "etiqueta_corta": "Sin dato",
        "etiqueta_larga": "Datos insuficientes para tendencia",
    },
}


def _ahora_chile() -> datetime:
    return datetime.now(CHILE_TZ).replace(tzinfo=None)


def _parse_fecha(texto: str) -> datetime | None:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(str(texto), fmt)
        except ValueError:
            continue
    return None


def _log_comb(n: int, k: int) -> float:
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


def test_poisson_dos_ventanas(
    n_reciente: int,
    n_anterior: int,
    dias_reciente: float = VENTANA_TENDENCIA_D,
    dias_anterior: float = VENTANA_TENDENCIA_D,
    alpha: float = ALPHA_SIGNIFICANCIA,
) -> dict:
    """
    Contraste de tasas Poisson en dos ventanas (estándar en vigilancia de enjambres).
    Ventanas iguales: test binomial exacto sobre n_reciente | n_total.
    Ventanas distintas: razón de tasas con aproximación normal.
    """
    n_total = n_reciente + n_anterior
    if n_total == 0:
        return {
            "p_value": 1.0,
            "significativo": False,
            "direccion": "SIN_DATO",
            "tasa_reciente_dia": 0.0,
            "tasa_anterior_dia": 0.0,
            "ratio": 1.0,
            "metodo": "sin_eventos",
        }

    tasa_r = n_reciente / max(dias_reciente, 1e-6)
    tasa_a = n_anterior / max(dias_anterior, 1e-6)
    ratio = tasa_r / tasa_a if tasa_a > 0 else (float("inf") if tasa_r > 0 else 1.0)

    if abs(dias_reciente - dias_anterior) < 1e-6:
        p_tail = 0.0
        p_k = math.exp(_log_comb(n_total, n_reciente) + n_total * math.log(0.5))
        for i in range(n_total + 1):
            p_i = math.exp(_log_comb(n_total, i) + n_total * math.log(0.5))
            if p_i <= p_k + 1e-15:
                p_tail += p_i
        p_value = min(1.0, p_tail)
        metodo = "binomial_exacto"
    else:
        # Aproximación normal para comparación de tasas Poisson (epidemiología / sismología operativa)
        se = math.sqrt(tasa_r / max(dias_reciente, 1e-6) + tasa_a / max(dias_anterior, 1e-6))
        z = (tasa_r - tasa_a) / se if se > 0 else 0.0
        p_value = math.erfc(abs(z) / math.sqrt(2.0))
        metodo = "normal_tasas"

    significativo = p_value < alpha
    if not significativo:
        direccion = "ESTABLE"
    elif n_reciente > n_anterior:
        direccion = "SUBE"
    elif n_reciente < n_anterior:
        direccion = "BAJA"
    else:
        direccion = "ESTABLE"

    return {
        "p_value": round(p_value, 4),
        "significativo": significativo,
        "direccion": direccion,
        "tasa_reciente_dia": round(tasa_r, 4),
        "tasa_anterior_dia": round(tasa_a, 4),
        "ratio": round(ratio, 3) if math.isfinite(ratio) else None,
        "metodo": metodo,
        "alpha": alpha,
    }


def b_value_mle_aki(mags: np.ndarray, mc: float) -> float:
    """Estimador MLE tipo Aki (1965): b = log10(e) / (M̄ - Mc)."""
    filtrado = mags[mags >= mc]
    if len(filtrado) < MIN_EVENTOS_GR:
        return 1.0
    media = float(np.mean(filtrado))
    if media <= mc:
        return 1.0
    return max(0.4, min(LOG10_E / (media - mc), 2.0))


def estimar_mc_maxc(mags: np.ndarray, paso: float = 0.1) -> tuple[float, float]:
    """
    Mc por método MAXC (máximo b-value estable) — Woessner & Wiemer (2000), simplificado.
    """
    if len(mags) < MIN_EVENTOS_GR:
        return float(np.min(mags)) if len(mags) else 2.5, 1.0

    m_min = float(np.min(mags))
    m_max = float(np.max(mags))
    mejor_mc = m_min
    mejor_b = b_value_mle_aki(mags, m_min)

    candidato = m_min
    while candidato <= m_max - 0.2:
        subset = mags[mags >= candidato]
        if len(subset) >= MIN_EVENTOS_GR:
            b_c = b_value_mle_aki(mags, candidato)
            if b_c >= mejor_b:
                mejor_b = b_c
                mejor_mc = candidato
        candidato = round(candidato + paso, 2)

    return round(mejor_mc, 2), round(mejor_b, 3)


def estimar_b_value(mags: np.ndarray) -> tuple[float, float]:
    """b-value MLE y Mc (MAXC) — estándar operativo en catálogos cortos."""
    if len(mags) < MIN_EVENTOS_GR:
        return 1.0, float(np.min(mags)) if len(mags) else 2.5
    mc, b = estimar_mc_maxc(mags)
    return b, mc


def duracion_catalogo_dias(prep: pd.DataFrame) -> float:
    if prep.empty or "fecha_dt" not in prep.columns:
        return 14.0
    span = (prep["fecha_dt"].max() - prep["fecha_dt"].min()).total_seconds() / 86400.0
    return max(span, 1.0)


def estimar_a_value(
    n_eventos: int,
    b: float,
    mc: float,
    dias_catalogo: float,
    m_ref: float | None = None,
) -> float:
    """
    Parámetro a de Gutenberg-Richter: log10(N(≥M)) = a - b·M + log10(T_años).
    """
    m_ref = m_ref if m_ref is not None else mc
    if n_eventos <= 0 or b <= 0 or dias_catalogo <= 0:
        return 0.0
    t_anios = dias_catalogo / 365.25
    return round(math.log10(n_eventos) + b * m_ref - math.log10(t_anios), 3)


def tasa_diaria_gr(magnitud_umbral: float, b: float, a: float) -> float:
    """Tasa diaria λ(M≥m) desde ley GR con a calibrado en años."""
    if b <= 0:
        return 0.0
    lambda_anual = 10 ** (a - b * magnitud_umbral)
    return lambda_anual / 365.25


def tasa_esperada_mag_supera(
    dias: float,
    magnitud_umbral: float,
    b: float,
    a: float,
) -> float:
    """Número esperado de eventos M ≥ umbral en `dias` (proceso de Poisson, ley GR)."""
    if dias <= 0 or b <= 0:
        return 0.0
    lam_dia = tasa_diaria_gr(magnitud_umbral, b, a)
    return round(lam_dia * dias, 2)


def _preparar_df_tiempo(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty or "Fecha" not in df.columns:
        return pd.DataFrame()
    out = df.copy()
    out["fecha_dt"] = out["Fecha"].apply(_parse_fecha)
    out = out.dropna(subset=["fecha_dt"]).sort_values("fecha_dt")
    return out


def tendencia_tasa_reciente(
    df: pd.DataFrame,
    ventana_d: int = VENTANA_TENDENCIA_D,
    alpha: float = ALPHA_SIGNIFICANCIA,
) -> dict:
    """Contraste 7d vs 7d previos con test Poisson (α=0.05)."""
    prep = _preparar_df_tiempo(df)
    if prep.empty:
        return {
            "direccion": "SIN_DATO",
            "etiqueta": "Sin datos",
            "reciente": 0,
            "anterior": 0,
            "delta_pct": 0.0,
            "test": {},
            "estilo": ESTILO_DIRECCION["SIN_DATO"],
        }

    ahora = _ahora_chile()
    t1 = ahora - timedelta(days=ventana_d)
    t0 = ahora - timedelta(days=ventana_d * 2)
    reciente = int((prep["fecha_dt"] >= t1).sum())
    anterior = int(((prep["fecha_dt"] >= t0) & (prep["fecha_dt"] < t1)).sum())

    test = test_poisson_dos_ventanas(reciente, anterior, ventana_d, ventana_d, alpha)
    direccion = test["direccion"]

    if anterior == 0 and reciente == 0:
        etiqueta = "Sin actividad reciente"
        delta_pct = 0.0
        direccion = "ESTABLE"
    elif anterior == 0:
        etiqueta = "Actividad nueva (sin base previa comparable)"
        delta_pct = 100.0
        if reciente >= 3:
            direccion = "SUBE"
            test = {**test, "direccion": "SUBE", "significativo": True, "metodo": "base_cero"}
    else:
        delta_pct = round((reciente - anterior) / anterior * 100.0, 1)
        if direccion == "SUBE":
            etiqueta = f"Tasa **sube** (p={test['p_value']:.3f}, α={alpha})"
        elif direccion == "BAJA":
            etiqueta = f"Tasa **baja** (p={test['p_value']:.3f}, α={alpha})"
        else:
            etiqueta = f"Tasa **estable** — sin cambio significativo (p={test['p_value']:.3f})"

    return {
        "direccion": direccion,
        "etiqueta": etiqueta,
        "reciente": reciente,
        "anterior": anterior,
        "delta_pct": delta_pct,
        "ventana_dias": ventana_d,
        "test": test,
        "estilo": ESTILO_DIRECCION.get(direccion, ESTILO_DIRECCION["SIN_DATO"]),
    }


def _integral_omori(t0: float, t1: float, k: float, c: float, p: float) -> float:
    if t1 <= t0 or k <= 0:
        return 0.0
    if abs(p - 1.0) < 1e-6:
        return k * (math.log(t1 + c) - math.log(t0 + c))
    exp = 1.0 - p
    return (k / exp) * ((t1 + c) ** exp - (t0 + c) ** exp)


def ajustar_omori_utsu(
    tiempos_d: np.ndarray,
    t_max: float = 14.0,
) -> dict | None:
    """
    Ajuste Omori-Utsu: n(t) = K / (t + c)^p por máxima verosimilitud en rejilla.
    Parámetros típicos: p ≈ 0.9–1.1, c ≈ 0.01–1 día (Utsu et al.).
    """
    tiempos = np.asarray(tiempos_d, dtype=float)
    tiempos = tiempos[(tiempos > 0) & (tiempos <= t_max)]
    if len(tiempos) < 5:
        return None

    mejor: dict | None = None
    mejor_ll = -math.inf

    for p in np.arange(0.7, 1.35, 0.05):
        for c in (0.01, 0.03, 0.05, 0.1, 0.3, 0.5, 1.0):
            denom = float(np.sum((tiempos + c) ** (-p)))
            if denom <= 0:
                continue
            k = len(tiempos) / denom
            if k <= 0:
                continue
            ll = float(np.sum(np.log(k) - p * np.log(tiempos + c)))
            if ll > mejor_ll:
                mejor_ll = ll
                mejor = {
                    "K": round(k, 4),
                    "c": c,
                    "p": round(float(p), 3),
                    "log_likelihood": round(ll, 2),
                    "n_replicas": int(len(tiempos)),
                }

    return mejor


def analisis_omori_utsu(
    df: pd.DataFrame,
    mag_min_principal: float = MAG_PRINCIPAL_OMORI,
    alpha: float = ALPHA_SIGNIFICANCIA,
) -> dict:
    """Enjambre réplica con ley Omori-Utsu y contraste observado vs esperado."""
    prep = _preparar_df_tiempo(df)
    vacio = {
        "aplica": False,
        "etiqueta": "Sin enjambre principal detectado",
        "direccion": "N/A",
        "estilo": ESTILO_DIRECCION["SIN_DATO"],
    }
    if prep.empty or "Magnitud" not in prep.columns:
        return vacio

    principales = prep[prep["Magnitud"] >= mag_min_principal]
    if principales.empty:
        return {
            "aplica": False,
            "etiqueta": f"Sin sismo ≥ M{mag_min_principal} en 14D (Omori no aplica)",
            "direccion": "N/A",
            "estilo": ESTILO_DIRECCION["SIN_DATO"],
        }

    fila_p = principales.iloc[-1]
    t_main = fila_p["fecha_dt"]
    replicas = prep[(prep["fecha_dt"] > t_main) & (prep["Magnitud"] < mag_min_principal)]
    dias_rep = (replicas["fecha_dt"] - t_main).dt.total_seconds() / 86400.0

    if len(replicas) < 4:
        return {
            "aplica": True,
            "etiqueta": "Enjambre muy pequeño — Omori-Utsu no estimable",
            "direccion": "ESTABLE",
            "estilo": ESTILO_DIRECCION["ESTABLE"],
            "evento_principal": float(fila_p["Magnitud"]),
            "fecha_principal": fila_p["Fecha"],
            "ajuste": None,
        }

    ajuste = ajustar_omori_utsu(dias_rep.to_numpy())
    early = int((dias_rep <= 3).sum())
    late = int(((dias_rep > 3) & (dias_rep <= 7)).sum())

    direccion = "ESTABLE"
    etiqueta = "Enjambre en fase intermedia"

    if ajuste:
        k, c, p = ajuste["K"], ajuste["c"], ajuste["p"]
        esp_early = _integral_omori(0.0, 3.0, k, c, p)
        esp_late = _integral_omori(3.0, 7.0, k, c, p)
        total_obs = early + late
        total_esp = esp_early + esp_late
        if total_esp > 0 and total_obs > 0:
            esp_e = esp_early * total_obs / total_esp
            esp_l = esp_late * total_obs / total_esp
            test_env = test_poisson_dos_ventanas(early, late, 3.0, 4.0, alpha)
            ratio_obs = early / max(late, 1)
            ratio_esp = esp_early / max(esp_late, 1e-6)

            if early > esp_e * 1.4 and test_env.get("significativo"):
                direccion = "SUBE"
                etiqueta = (
                    f"Réplicas **por encima** del decaimiento Omori-Utsu "
                    f"(p={p:.2f}, K={k:.2f}, c={c} d)"
                )
            elif late >= early and ratio_obs <= ratio_esp * 0.85:
                direccion = "BAJA"
                etiqueta = (
                    f"Réplicas **decaen** según Omori-Utsu "
                    f"(p={p:.2f}, K={k:.2f}, c={c} d)"
                )
            else:
                etiqueta = (
                    f"Enjambre coherente con Omori-Utsu "
                    f"(p={p:.2f}, c={c} d, observado/ esperado ≈ {ratio_obs:.1f}/{ratio_esp:.1f})"
                )
        ajuste["esperado_1_3d"] = round(esp_early, 2)
        ajuste["esperado_4_7d"] = round(esp_late, 2)
    else:
        if late == 0 or early > late * 1.5:
            direccion = "SUBE"
            etiqueta = "Réplicas aún activas (fase temprana)"
        elif early > 0 and late < early * 0.6:
            direccion = "BAJA"
            etiqueta = "Réplicas decaen (patrón tipo Omori)"

    return {
        "aplica": True,
        "etiqueta": etiqueta,
        "direccion": direccion,
        "estilo": ESTILO_DIRECCION.get(direccion, ESTILO_DIRECCION["ESTABLE"]),
        "evento_principal": float(fila_p["Magnitud"]),
        "fecha_principal": fila_p["Fecha"],
        "replicas_1_3d": early,
        "replicas_4_7d": late,
        "ajuste": ajuste,
    }


def sintetizar_veredicto(tendencia: dict, omori: dict) -> dict:
    """Veredicto principal = test Poisson GR; Omori modula el mensaje."""
    dir_t = tendencia.get("direccion", "SIN_DATO")
    estilo = ESTILO_DIRECCION.get(dir_t, ESTILO_DIRECCION["SIN_DATO"])
    flecha = estilo["icono"]

    if dir_t == "SUBE":
        sintesis = (
            "La actividad sísmica local **tiende a subir** "
            f"(test Poisson p={tendencia.get('test', {}).get('p_value', '—')})."
        )
    elif dir_t == "BAJA":
        sintesis = (
            "La actividad sísmica local **tiende a bajar** "
            f"(test Poisson p={tendencia.get('test', {}).get('p_value', '—')})."
        )
    elif dir_t == "ESTABLE":
        sintesis = (
            "La actividad sísmica local se mantiene **estable** "
            "(sin cambio significativo al α=0.05)."
        )
    else:
        sintesis = "Datos insuficientes para tendencia."

    if omori.get("aplica") and omori.get("direccion") == "BAJA":
        sintesis += " El enjambre réplica **decaen** (Omori-Utsu)."
    elif omori.get("aplica") and omori.get("direccion") == "SUBE":
        sintesis += " El enjambre réplica sigue **activo** por encima del decaimiento esperado."

    return {
        "direccion": dir_t,
        "flecha": flecha,
        "sintesis": sintesis,
        "estilo": estilo,
    }


def resumen_forecast_sismico(df_local: pd.DataFrame) -> dict:
    """Capa independiente: tendencia GR + Omori-Utsu sin mezclar con semáforo NAZCA."""
    prep = _preparar_df_tiempo(df_local)
    n = len(prep)
    mags = prep["Magnitud"].to_numpy() if n and "Magnitud" in prep.columns else np.array([])

    dias_cat = duracion_catalogo_dias(prep)
    confiable = n >= MIN_EVENTOS_GR

    if confiable:
        b, mc = estimar_b_value(mags)
        n_mc = int((mags >= mc).sum())
        a = estimar_a_value(n_mc, b, mc, dias_cat, mc)
    else:
        b, mc, a = 1.0, 2.5, 0.0
        n_mc = n

    esperado_m4 = tasa_esperada_mag_supera(7.0, 4.0, b, a) if confiable else None
    esperado_m5 = tasa_esperada_mag_supera(7.0, 5.0, b, a) if confiable else None
    lambda_mc_dia = round(tasa_diaria_gr(mc, b, a), 4) if confiable else None

    tendencia = tendencia_tasa_reciente(prep)
    omori = analisis_omori_utsu(prep)
    veredicto = sintetizar_veredicto(tendencia, omori)

    return {
        "capa": "GR_OMORI",
        "sistema": "TENDENCIA_CIENTIFICA",
        "independiente_semaforo": True,
        "n_eventos": n,
        "n_eventos_mc": n_mc,
        "dias_catalogo": round(dias_cat, 1),
        "b_value": b,
        "mc": mc,
        "a_value": a,
        "lambda_mc_dia": lambda_mc_dia,
        "esperado_m4_7d": esperado_m4,
        "esperado_m5_7d": esperado_m5,
        "tendencia": tendencia,
        "omori": omori,
        "veredicto": veredicto,
        "flecha": veredicto["flecha"],
        "sintesis": veredicto["sintesis"],
        "estilo": veredicto["estilo"],
        "confiable": confiable,
        "metodo": "GR MAXC + Poisson α=0.05 + Omori-Utsu MLE rejilla",
    }
