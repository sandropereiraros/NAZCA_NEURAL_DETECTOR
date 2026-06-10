"""Prueba mareografo IOC UNESCO por nodo CORE."""

from __future__ import annotations



import sys

from pathlib import Path



ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(ROOT))



import nazca_alertas as alertas

import nazca_shoa as shoa

from nazca_vigilancia_core import ESTACIONES_CONFIG





def main() -> int:

    print("NAZCA SHOA IOC Chile\n")

    for nombre, cfg in ESTACIONES_CONFIG.items():

        info = shoa.lectura_marea_nodo(nombre, cfg["lat"], cfg["lon"])

        print(f"## {nombre}")

        if not info:

            print("  SHOA: sin datos IOC\n")

            continue

        conf = "confiable" if alertas.shoa_es_real(info) else "lejana"

        print(

            f"  IOC {info['codigo_ioc'].upper()} ({conf}, {info['dist_km']} km) | "

            f"shoa={info['shoa_cm']:.2f} cm | anom={info['anomalia_cm']:.1f} cm | "

            f"tasa={info['tasa_cm_h']:.1f} cm/h | sensor={info['sensor']}"

        )

        print(f"  nivel={info['nivel_m']:.3f} m | media 6h={info['media_6h_m']:.3f} m | {info['ultima_lectura']}\n")

    return 0





if __name__ == "__main__":

    sys.exit(main())


