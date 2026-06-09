"""Backtest walk-forward para PIPELINE LAB — validación antes de activar MLP."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

import nazca_pipeline_features as features
import nazca_pipeline_ml as ml

CHILE_TZ = ZoneInfo("America/Santiago")
BACKTEST_PATH = ml.PIPELINE_DATA_DIR / "backtest_report.json"

MIN_FILAS_BACKTEST = 120
MIN_POSITIVOS_BACKTEST = 8
N_SPLITS_DEFAULT = 5
MIN_TRAIN_FRAC = 0.45
MIN_CAL_FILAS = 35


def _ahora() -> str:
    return datetime.now(CHILE_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _sklearn_ok() -> bool:
    try:
        import sklearn  # noqa: F401
        return True
    except ImportError:
        return False


def prob_poisson_desde_features(row: pd.Series) -> float:
    esperado = float(row.get("esperado_m5_7d", 0))
    return ml.prob_poisson_fallback(esperado) / 100.0


def _entrenar_fold_calibrado(train: pd.DataFrame, test: pd.DataFrame, cols: list[str]):
    """Entrena fold con calibración temporal (igual que producción)."""
    from sklearn.utils.class_weight import compute_sample_weight

    train_ord = train.sort_values("fecha_corte")
    n_cal = max(MIN_CAL_FILAS, int(len(train_ord) * 0.15))
    if n_cal >= len(train_ord) - 40:
        n_cal = max(20, int(len(train_ord) * 0.12))
    fit = train_ord.iloc[:-n_cal] if n_cal < len(train_ord) else train_ord.iloc[: int(len(train_ord) * 0.85)]
    cal_df = train_ord.iloc[-n_cal:]

    X_fit = fit[cols].fillna(0).to_numpy()
    y_fit = fit["etiqueta_m5_5d"].to_numpy()
    X_cal = cal_df[cols].fillna(0).to_numpy()
    y_cal = cal_df["etiqueta_m5_5d"].to_numpy()

    base = ml.crear_pipeline_mlp()
    pesos = compute_sample_weight(class_weight="balanced", y=y_fit)
    base.fit(X_fit, y_fit, mlp__sample_weight=pesos)
    modelo, _, _ = ml.calibrar_modelo(base, X_cal, y_cal)
    return modelo


def _metricas_binarias(y_true: np.ndarray, y_prob: np.ndarray) -> dict:
    from sklearn.metrics import roc_auc_score, brier_score_loss, average_precision_score

    out: dict = {"n": int(len(y_true)), "positivos": int(y_true.sum())}
    if len(y_true) < 5 or len(np.unique(y_true)) < 2:
        out["auc"] = None
        out["brier"] = None
        out["ap"] = None
        return out
    out["auc"] = round(float(roc_auc_score(y_true, y_prob)), 4)
    out["brier"] = round(float(brier_score_loss(y_true, y_prob)), 4)
    out["ap"] = round(float(average_precision_score(y_true, y_prob)), 4)
    return out


def walk_forward_backtest(
    df: pd.DataFrame,
    n_splits: int = N_SPLITS_DEFAULT,
    cols: list[str] | None = None,
) -> dict:
    """Entrena en ventanas crecientes y evalúa en bloques futuros (por fecha_corte)."""
    cols = cols or features.FEATURE_COLS
    if df is None or df.empty:
        return {"ok": False, "error": "Dataset vacío"}

    data = df.sort_values("fecha_corte").reset_index(drop=True)
    positivos = int(data["etiqueta_m5_5d"].sum())
    if len(data) < MIN_FILAS_BACKTEST:
        return {"ok": False, "error": f"Pocas filas ({len(data)} < {MIN_FILAS_BACKTEST})"}
    if positivos < MIN_POSITIVOS_BACKTEST:
        return {"ok": False, "error": f"Pocos positivos ({positivos} < {MIN_POSITIVOS_BACKTEST})"}
    if not _sklearn_ok():
        return {"ok": False, "error": "scikit-learn no instalado"}

    fechas = sorted(data["fecha_corte"].unique())
    n_fechas = len(fechas)
    n_splits = max(2, min(n_splits, 6))
    bloque = max(1, n_fechas // (n_splits + 1))
    min_train_fechas = max(bloque, int(n_fechas * MIN_TRAIN_FRAC))

    fold_rows = []
    preds_mlp = []
    preds_poisson = []
    y_all = []

    for i in range(n_splits):
        train_end_idx = min_train_fechas + i * bloque - 1
        test_start_idx = train_end_idx + 1
        test_end_idx = min(test_start_idx + bloque - 1, n_fechas - 1)
        if test_start_idx >= n_fechas or train_end_idx < bloque:
            continue

        train_fechas = set(fechas[: train_end_idx + 1])
        test_fechas = set(fechas[test_start_idx : test_end_idx + 1])
        train = data[data["fecha_corte"].isin(train_fechas)]
        test = data[data["fecha_corte"].isin(test_fechas)]
        if len(train) < 80 or len(test) < 20:
            continue
        if int(test["etiqueta_m5_5d"].sum()) < 1:
            continue

        X_train = train[cols].fillna(0).to_numpy()
        y_train = train["etiqueta_m5_5d"].to_numpy()
        X_test = test[cols].fillna(0).to_numpy()
        y_test = test["etiqueta_m5_5d"].to_numpy()

        if len(np.unique(y_train)) < 2:
            continue

        modelo = _entrenar_fold_calibrado(train, test, cols)
        prob_mlp = modelo.predict_proba(X_test)[:, 1]
        prob_mlp = np.clip(prob_mlp, ml.PROB_MIN_PCT / 100.0, ml.PROB_MAX_PCT / 100.0)
        prob_poi = test.apply(prob_poisson_desde_features, axis=1).to_numpy()

        m_mlp = _metricas_binarias(y_test, prob_mlp)
        m_poi = _metricas_binarias(y_test, prob_poi)
        fold_rows.append({
            "fold": len(fold_rows) + 1,
            "train_hasta": str(fechas[train_end_idx]),
            "test_desde": str(fechas[test_start_idx]),
            "test_hasta": str(fechas[test_end_idx]),
            "n_train": len(train),
            "n_test": len(test),
            "positivos_test": int(y_test.sum()),
            "auc_mlp": m_mlp.get("auc"),
            "auc_poisson": m_poi.get("auc"),
        })
        preds_mlp.extend(prob_mlp.tolist())
        preds_poisson.extend(prob_poi.tolist())
        y_all.extend(y_test.tolist())

    if not fold_rows:
        return {"ok": False, "error": "No se generaron folds válidos"}

    y_arr = np.array(y_all)
    mlp_global = _metricas_binarias(y_arr, np.array(preds_mlp))
    poi_global = _metricas_binarias(y_arr, np.array(preds_poisson))

    auc_folds_mlp = [f["auc_mlp"] for f in fold_rows if f["auc_mlp"] is not None]
    auc_folds_poi = [f["auc_poisson"] for f in fold_rows if f["auc_poisson"] is not None]

    por_estacion = []
    for est, grp in data.groupby("estacion"):
        y_e = grp["etiqueta_m5_5d"].to_numpy()
        p_poi = grp.apply(prob_poisson_desde_features, axis=1).to_numpy()
        por_estacion.append({
            "estacion": est,
            "filas": len(grp),
            "positivos": int(y_e.sum()),
            "auc_poisson_baseline": _metricas_binarias(y_e, p_poi).get("auc"),
        })

    auc_mlp_mean = round(float(np.mean(auc_folds_mlp)), 4) if auc_folds_mlp else None
    auc_poi_mean = round(float(np.mean(auc_folds_poi)), 4) if auc_folds_poi else None
    mlp_supera_poisson = (
        auc_mlp_mean is not None
        and auc_poi_mean is not None
        and auc_mlp_mean >= auc_poi_mean - 0.02
    )
    mlp_gana = (
        mlp_global.get("auc") is not None
        and mlp_global["auc"] >= ml.AUC_MIN_CALIFICADO
        and mlp_supera_poisson
    )

    return {
        "ok": True,
        "actualizado": _ahora(),
        "n_folds": len(fold_rows),
        "folds": fold_rows,
        "global": {
            "mlp": mlp_global,
            "poisson": poi_global,
            "auc_mlp_media_folds": auc_mlp_mean,
            "auc_poisson_media_folds": auc_poi_mean,
        },
        "por_estacion": por_estacion,
        "calificado": mlp_gana,
        "metodo_recomendado": "mlp_sklearn" if mlp_gana else "poisson_fallback",
        "umbral_auc": ml.AUC_MIN_CALIFICADO,
    }


def guardar_reporte(reporte: dict) -> None:
    ml.PIPELINE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKTEST_PATH.write_text(
        __import__("json").dumps(reporte, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def leer_reporte() -> dict:
    if not BACKTEST_PATH.exists():
        return {}
    try:
        return __import__("json").loads(BACKTEST_PATH.read_text(encoding="utf-8"))
    except (__import__("json").JSONDecodeError, OSError):
        return {}


def ejecutar_backtest_desde_catalogo(
    paso_dias: int = 7,
    modo_rapido: bool = True,
    n_splits: int = N_SPLITS_DEFAULT,
) -> dict:
    import nazca_catalogo_db as catalogo

    df_raw = catalogo.leer_sismos()
    dataset = features.construir_dataset(df_raw, paso_dias=paso_dias, modo_rapido=modo_rapido)
    reporte = walk_forward_backtest(dataset, n_splits=n_splits)
    reporte["dataset"] = {
        "filas": len(dataset),
        "positivos": int(dataset["etiqueta_m5_5d"].sum()) if not dataset.empty else 0,
        "paso_dias": paso_dias,
        "modo_rapido": modo_rapido,
    }
    guardar_reporte(reporte)
    return reporte
