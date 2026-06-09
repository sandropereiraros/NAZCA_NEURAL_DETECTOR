"""CLI — sincronizar catálogo PIPELINE LAB (aislado del núcleo NAZCA)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import nazca_catalogo_db as catalogo
import nazca_pipeline_colector as colector


def main() -> int:
    parser = argparse.ArgumentParser(description="NAZCA Pipeline LAB — recolector USGS/CSN")
    parser.add_argument("--usgs-dias", type=int, default=30, help="Ventana USGS hacia atrás")
    parser.add_argument("--csn-dias", type=int, default=7, help="Días CSN (api.xor.cl)")
    parser.add_argument("--mag-min", type=float, default=2.5)
    parser.add_argument("--solo-usgs", action="store_true")
    parser.add_argument("--solo-csn", action="store_true")
    args = parser.parse_args()

    catalogo.asegurar_db()
    print(f"DB: {catalogo.DB_PATH}")

    if not args.solo_csn:
        r = colector.sync_usgs_ultimos_dias(args.usgs_dias, mag_min=args.mag_min)
        print(f"USGS: recibidos={r['recibidos']} guardados={r['guardados']}")

    if not args.solo_usgs:
        r2 = colector.sync_csn_ultimos_dias(args.csn_dias, mag_min=args.mag_min)
        print(f"CSN: recibidos={r2['recibidos']} guardados={r2['guardados']}")

    print(catalogo.resumen_db())
    return 0


if __name__ == "__main__":
    sys.exit(main())
