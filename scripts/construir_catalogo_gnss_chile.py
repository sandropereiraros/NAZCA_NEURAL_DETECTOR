"""Construye catálogo GNSS Chile (NGL MIDAS SA) en .nazca_cache/gnss_catalogo_chile.json."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import nazca_gnss as gnss

if __name__ == "__main__":
    catalogo, meta = gnss.actualizar_catalogo_chile(forzar=True, max_nuevas=200)
    print(f"Catalogo Chile: {len(catalogo)} estaciones | consultadas {meta['consultadas']} | fuente {meta['fuente']}")
    for est in sorted(catalogo, key=lambda x: x["lat"]):
        print(
            f"  {est['id']:5s} {est['lat']:7.2f} {est['lon']:7.2f} "
            f"H={est['horiz_mm_anio']:5.1f} V={est['vu_mm_anio']:6.1f} mm/yr"
        )
