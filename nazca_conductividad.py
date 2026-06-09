"""Conductividad aparente del suelo — proxy físico (humedad + zona geológica IDE).

CoolProp modela fluidos (agua, refrigerantes), no conductividad electromagnética
del suelo rocoso/sedimentario. Para NAZCA usamos un proxy tipo Archie calibrado
por zona tectónica (referencia geológica costera/subducción Chile).
"""
from __future__ import annotations

# Zonas inspiradas en contexto geológico IDE/SERNAGEOMIN (costa/subducción).
ZONA_SUELO_POR_ESTACION = {
    "Arica / Iquique (85400)": "arido_norte",
    "Antofagasta / Taltal (85442)": "arido_norte",
    "Coquimbo / Illapel (85540)": "costa_semiarida",
    "Valparaíso / San Antonio (85574)": "costa_central",
    "Concepción / Lebu (85680)": "costa_sur",
    "Valdivia / Puerto Montt (85799)": "sur_humedo",
    "Pto. Aysén / Taitao (85850)": "patagonia",
}

PERFIL_SUELO = {
    "arido_norte": {"phi": 0.10, "a": 1.05, "m": 1.35, "sensibilidad_hr": 0.35},
    "costa_semiarida": {"phi": 0.16, "a": 1.10, "m": 1.55, "sensibilidad_hr": 0.55},
    "costa_central": {"phi": 0.20, "a": 1.15, "m": 1.65, "sensibilidad_hr": 0.70},
    "costa_sur": {"phi": 0.22, "a": 1.18, "m": 1.70, "sensibilidad_hr": 0.75},
    "sur_humedo": {"phi": 0.26, "a": 1.22, "m": 1.80, "sensibilidad_hr": 0.85},
    "patagonia": {"phi": 0.18, "a": 1.12, "m": 1.60, "sensibilidad_hr": 0.60},
}


def _saturacion_agua(humedad_pct: float, precip_mm: float) -> float:
    hr = max(0.0, min(100.0, humedad_pct))
    sw = 0.15 + (hr / 100.0) * 0.55 + min(precip_mm, 12.0) * 0.02
    return max(0.05, min(0.95, sw))


def estimar_conductividad(
    estacion: str,
    config: dict,
    atmos: dict | None = None,
) -> dict:
    """Estima conductividad aparente (mS/m) a partir de humedad/precipitación."""
    zona = ZONA_SUELO_POR_ESTACION.get(estacion, "costa_central")
    perfil = PERFIL_SUELO[zona]
    baseline = float(config["baseline_cond"])

    if atmos and atmos.get("atmos_real"):
        sw = _saturacion_agua(atmos.get("humedad_pct", 50.0), atmos.get("precip_mm", 0.0))
        archie = perfil["a"] * (sw ** perfil["m"]) * (perfil["phi"] ** 2)
        escala = baseline / max(0.02, perfil["a"] * (0.35 ** perfil["m"]) * (perfil["phi"] ** 2))
        cond = archie * escala
        hr_factor = 1.0 + perfil["sensibilidad_hr"] * ((atmos.get("humedad_pct", 50.0) - 50.0) / 100.0)
        cond = cond * hr_factor
        cond = max(baseline * 0.65, min(baseline * 1.85, cond))
        return {
            "conductividad_ms_m": round(cond, 2),
            "zona_suelo": zona,
            "saturacion_agua_est": round(sw, 3),
            "cond_real": False,
            "cond_proxy_fisico": True,
            "origen": f"Proxy Archie ({zona}) + atmósfera real",
            "fuente": "nazca_conductividad",
        }

    return {
        "conductividad_ms_m": round(baseline, 2),
        "zona_suelo": zona,
        "cond_real": False,
        "cond_proxy_fisico": False,
        "origen": "baseline estación (sin atmósfera)",
        "fuente": "estimado",
    }
