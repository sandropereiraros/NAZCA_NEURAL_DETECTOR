"""Prueba atmósfera + conductividad proxy por nodo CORE."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import nazca_alertas as alertas
import nazca_atmosfera as atmosfera
import nazca_conductividad as conductividad
from nazca_vigilancia_core import ESTACIONES_CONFIG


def main() -> int:
    print("NAZCA Atmosfera + EM proxy Chile\n")
    for nombre, cfg in ESTACIONES_CONFIG.items():
        atmos = atmosfera.lectura_atmosfera(
            cfg["lat"], cfg["lon"], baseline_pres=cfg["baseline_pres"], codigo_omm=cfg.get("id")
        )
        cond = conductividad.estimar_conductividad(nombre, cfg, atmos)
        tope = alertas.tope_riesgo_permitido(None, atmos, cond)
        print(f"## {nombre}")
        if atmos:
            print(
                f"  Atmos: {atmos['origen']} | P={atmos['presion_hpa']:.1f} hPa | "
                f"T={atmos['temp_c']:.1f} C | HR={atmos['humedad_pct']:.0f}% | termico={atmos['termico']}"
            )
        else:
            print("  Atmos: sin datos")
        print(
            f"  EM: {cond['conductividad_ms_m']:.2f} mS/m | zona={cond.get('zona_suelo')} | "
            f"proxy={cond.get('cond_proxy_fisico')} | {cond.get('origen')}"
        )
        print(f"  Tope riesgo (solo atmos+EM): {tope:.0f}%\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
