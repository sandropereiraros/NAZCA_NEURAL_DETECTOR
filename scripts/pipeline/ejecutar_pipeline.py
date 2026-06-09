"""Motor PIPELINE LAB — sync, entrenamiento MLP e inferencia (cron / Actions)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import nazca_catalogo_db as catalogo
import nazca_pipeline_colector as colector
import nazca_pipeline_ml as ml


def main() -> int:
    parser = argparse.ArgumentParser(description="NAZCA Pipeline LAB — operación continua")
    parser.add_argument("--sync", action="store_true", help="Sync USGS+CSN operativo")
    parser.add_argument("--bootstrap", action="store_true", help="Backfill histórico (lento, 1ª vez)")
    parser.add_argument("--entrenar", action="store_true", help="Entrenar MLP + inferir")
    parser.add_argument("--backtest", action="store_true", help="Solo backtest walk-forward")
    parser.add_argument("--todo", action="store_true", help="sync + entrenar + backtest (sin bootstrap)")
    parser.add_argument("--usgs-desde", type=int, default=2015, help="Año inicio backfill USGS")
    parser.add_argument("--csn-dias-backfill", type=int, default=90, help="Días CSN en bootstrap")
    args = parser.parse_args()

    if not any([args.sync, args.bootstrap, args.entrenar, args.todo, args.backtest]):
        args.todo = True

    catalogo.asegurar_db()
    print(f"PIPELINE LAB | DB: {catalogo.DB_PATH}")

    if args.bootstrap:
        print("Backfill USGS (mensual)…")
        r_u = colector.backfill_usgs(anio_desde=args.usgs_desde)
        print(f"  USGS: {r_u}")
        print("Backfill CSN (diario)…")
        r_c = colector.backfill_csn_dias(dias=args.csn_dias_backfill)
        print(f"  CSN: {r_c}")

    if args.sync or args.todo:
        print("Sync operativo…")
        r = colector.sync_operativo()
        print(f"  {r}")

    if args.backtest:
        import nazca_pipeline_backtest as backtest
        print("Backtest walk-forward…")
        rep = backtest.ejecutar_backtest_desde_catalogo()
        if rep.get("ok"):
            g = rep.get("global", {})
            print(f"  AUC MLP folds: {g.get('auc_mlp_media_folds')} | Poisson: {g.get('auc_poisson_media_folds')}")
            print(f"  Calificado: {rep.get('calificado')} | Método: {rep.get('metodo_recomendado')}")
        else:
            print(f"  Backtest: {rep.get('error', rep)}")
        print(f"  Reporte: {backtest.BACKTEST_PATH}")

    if args.entrenar or args.todo:
        print("Entrenamiento + backtest + inferencia…")
        estado = ml.ejecutar_entrenamiento_e_inferencia(ejecutar_backtest=True)
        bt = estado.get("backtest", {})
        tr = estado.get("entrenamiento", {})
        if bt.get("ok"):
            g = bt.get("global", {})
            print(f"  Backtest AUC MLP: {g.get('auc_mlp_media_folds')} | Poisson: {g.get('auc_poisson_media_folds')}")
            print(f"  Modelo calificado: {estado.get('modelo_calificado')} | activo: {estado.get('metodo_activo')}")
        else:
            print(f"  Backtest: {bt.get('error', bt)}")
        if tr.get("ok"):
            print(f"  Entrenamiento | métricas: {tr.get('metricas')}")
        else:
            print(f"  Entrenamiento: {tr.get('error', tr)} (inferencia con fallback Poisson)")
        print(f"  Inferencias: {len(estado.get('inferencias', {}))} estaciones")
        print(f"  Estado: {ml.ESTADO_PATH}")

    print(catalogo.resumen_db())
    return 0


if __name__ == "__main__":
    sys.exit(main())
