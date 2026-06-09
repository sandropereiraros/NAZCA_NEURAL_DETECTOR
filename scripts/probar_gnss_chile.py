"""Prueba GNSS Chile — MIDAS SA + aceleración 1 año por nodo CORE."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import nazca_alertas as alertas
import nazca_gnss as gnss
from nazca_vigilancia_core import ESTACIONES_CONFIG


def main() -> int:
    print("NAZCA GNSS Chile — etapa 2 (serie temporal + aceleración)\n")
    filas = gnss.resumen_nodos_core(ESTACIONES_CONFIG)
    for item in filas:
        nodo = item["nodo"]
        lect = item["lectura"]
        print(f"## {nodo}")
        if not lect:
            print("  Sin estación GNSS asociada.\n")
            continue
        tope = alertas.tope_riesgo_permitido(lect)
        print(
            f"  Estación: {lect['estacion_gnss']} ({lect.get('match')}, {lect.get('dist_km')} km) "
            f"| confiable: {'SI' if lect.get('gnss_confiable') else 'no'} | tope riesgo: {tope:.0f}%"
        )
        print(f"  MIDAS H={lect['horiz_mm_anio']:.1f} V={lect['vu_mm_anio']:.1f} mm/yr -> indice {lect['insar_pct']:.1f}%")
        acel = lect.get("aceleracion")
        if acel:
            print(
                f"  Serie 1A: H={acel.get('horiz_reciente_mm_anio', 0):.1f} V={acel.get('vert_reciente_mm_anio', 0):.1f} "
                f"mm/yr | ratio H={acel.get('ratio_horizontal', 1):.2f} | acelerando: "
                f"{'SI' if acel.get('acelerando') else 'no'} ({acel.get('puntos', 0)} pts)"
            )
        else:
            print("  Serie 1A: no disponible")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
