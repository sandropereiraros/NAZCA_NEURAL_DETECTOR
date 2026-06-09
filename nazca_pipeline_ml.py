"""MLP sklearn para PIPELINE LAB — entrenamiento, calibración e inferencia."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

import nazca_catalogo_db as catalogo
import nazca_pipeline_features as features

CHILE_TZ = ZoneInfo("America/Santiago")
PIPELINE_DATA_DIR = Path(__file__).resolve().parent / "data" / "pipeline_lab"
MODEL_PATH = PIPELINE_DATA_DIR / "modelo_mlp.joblib"
ESTADO_PATH = PIPELINE_DATA_DIR / "estado_pipeline.json"
META_ENTRENAMIENTO = "ultimo_entrenamiento_ml"
META_PIPELINE_RUN = "ultimo_pipeline_run"

TRAIN_FRAC = 0.70
CAL_FRAC = 0.15
MIN_FILAS = 80
MIN_POSITIVOS = 3
MIN_CAL_FILAS = 35
MIN_CAL_POSITIVOS = 3
UMBRAL_ALERTA_PCT = 25.0
AUC_MIN_CALIFICADO = 0.58
PASO_DIAS_ENTRENAMIENTO = 7
PROB_MIN_PCT = 0.5
PROB_MAX_PCT = 95.0


def _ahora() -> str:
    return datetime.now(CHILE_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _sklearn_disponible() -> bool:
    try:
        import sklearn  # noqa: F401
        return True
    except ImportError:
        return False


def guardar_estado(payload: dict) -> None:
    PIPELINE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    ESTADO_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def leer_estado() -> dict:
    if not ESTADO_PATH.exists():
        return {}
    try:
        return json.loads(ESTADO_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def prob_poisson_fallback(esperado_m5: float) -> float:
    if esperado_m5 < 0:
        return 0.0
    return round((1.0 - np.exp(-float(esperado_m5))) * 100.0, 2)


def formatear_prob_pct(prob: float) -> float:
    """Acota probabilidades a rango operativo tras calibración."""
    pct = float(np.clip(prob * 100.0, PROB_MIN_PCT, PROB_MAX_PCT))
    return round(pct, 2)


def crear_pipeline_mlp():
    from sklearn.neural_network import MLPClassifier
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    return Pipeline([
        ("scaler", StandardScaler()),
        ("mlp", MLPClassifier(
            hidden_layer_sizes=(32, 16),
            activation="relu",
            max_iter=500,
            random_state=42,
            early_stopping=True,
            validation_fraction=0.12,
        )),
    ])


def partir_temporal(df_ord: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    n = len(df_ord)
    i_train = int(n * TRAIN_FRAC)
    i_cal = int(n * (TRAIN_FRAC + CAL_FRAC))
    return df_ord.iloc[:i_train], df_ord.iloc[i_train:i_cal], df_ord.iloc[i_cal:]


def _wrapper_calibracion(base, metodo: str):
    """Compat sklearn 1.9+ (FrozenEstimator) y versiones anteriores (cv=prefit)."""
    from sklearn.calibration import CalibratedClassifierCV

    try:
        from sklearn.frozen import FrozenEstimator
        return CalibratedClassifierCV(FrozenEstimator(base), method=metodo)
    except ImportError:
        return CalibratedClassifierCV(base, method=metodo, cv="prefit")


def calibrar_modelo(
    base,
    X_cal: np.ndarray,
    y_cal: np.ndarray,
) -> tuple[object, str | None, dict]:
    """Elige Platt (sigmoid) o isotónica según Brier en set de calibración."""
    from sklearn.metrics import brier_score_loss

    if len(y_cal) < MIN_CAL_FILAS or int(y_cal.sum()) < MIN_CAL_POSITIVOS:
        return base, None, {"motivo": "set calibración insuficiente"}

    candidatos: list[tuple[str, object, float]] = []
    metodos = ["sigmoid"]
    if len(y_cal) >= 80:
        metodos.append("isotonic")

    ultimo_error = None
    for metodo in metodos:
        try:
            calibrado = _wrapper_calibracion(base, metodo)
            calibrado.fit(X_cal, y_cal)
            prob_cal = calibrado.predict_proba(X_cal)[:, 1]
            brier = float(brier_score_loss(y_cal, prob_cal))
            candidatos.append((metodo, calibrado, brier))
        except Exception as exc:
            ultimo_error = str(exc)
            continue

    if not candidatos:
        return base, None, {"motivo": ultimo_error or "falló calibración sklearn"}

    metodo, modelo, brier = min(candidatos, key=lambda x: x[2])
    return modelo, metodo, {"brier_cal": round(brier, 4), "metodo": metodo}


def entrenar_modelo_en_bloques(
    train: pd.DataFrame,
    cal: pd.DataFrame,
    test: pd.DataFrame,
    cols: list[str],
) -> tuple[object, dict]:
    """Entrena MLP base y aplica calibración temporal."""
    from sklearn.metrics import roc_auc_score, brier_score_loss
    from sklearn.utils.class_weight import compute_sample_weight

    X_train = train[cols].fillna(0).to_numpy()
    y_train = train["etiqueta_m5_5d"].to_numpy()
    X_cal = cal[cols].fillna(0).to_numpy()
    y_cal = cal["etiqueta_m5_5d"].to_numpy()
    X_test = test[cols].fillna(0).to_numpy()
    y_test = test["etiqueta_m5_5d"].to_numpy()

    pesos = compute_sample_weight(class_weight="balanced", y=y_train)
    base = crear_pipeline_mlp()
    base.fit(X_train, y_train, mlp__sample_weight=pesos)

    modelo, metodo_cal, info_cal = calibrar_modelo(base, X_cal, y_cal)

    metricas = {
        "n_train": len(train),
        "n_cal": len(cal),
        "n_test": len(test),
        "positivos_train": int(y_train.sum()),
        "positivos_cal": int(y_cal.sum()),
        "positivos_test": int(y_test.sum()),
    }

    if len(test) > 0 and len(np.unique(y_test)) > 1:
        prob_cruda = base.predict_proba(X_test)[:, 1]
        prob_final = modelo.predict_proba(X_test)[:, 1]
        metricas["auc_test"] = round(float(roc_auc_score(y_test, prob_final)), 4)
        metricas["brier_crudo_test"] = round(float(brier_score_loss(y_test, prob_cruda)), 4)
        metricas["brier_cal_test"] = round(float(brier_score_loss(y_test, prob_final)), 4)
        metricas["brier_mejora"] = round(metricas["brier_crudo_test"] - metricas["brier_cal_test"], 4)
    else:
        metricas["auc_test"] = None
        metricas["brier_crudo_test"] = None
        metricas["brier_cal_test"] = None

    metricas["calibracion"] = {
        **info_cal,
        "activa": metodo_cal is not None,
    }
    return modelo, metricas


def entrenar_modelo(df: pd.DataFrame, calificado_previo: bool | None = None) -> dict:
    if not _sklearn_disponible():
        return {"ok": False, "error": "scikit-learn no instalado", "calificado": False}

    if df.empty or len(df) < MIN_FILAS:
        return {
            "ok": False,
            "error": f"Datos insuficientes ({len(df)} < {MIN_FILAS})",
            "calificado": False,
        }

    positivos = int(df["etiqueta_m5_5d"].sum())
    if positivos < MIN_POSITIVOS:
        return {
            "ok": False,
            "error": f"Pocos eventos M≥5 en etiquetas ({positivos})",
            "calificado": False,
        }

    import joblib

    cols = features.FEATURE_COLS
    df_ord = df.sort_values("fecha_corte")
    train, cal, test = partir_temporal(df_ord)
    modelo, metricas = entrenar_modelo_en_bloques(train, cal, test, cols)

    calificado = calificado_previo
    if calificado is None:
        auc = metricas.get("auc_test")
        calificado = auc is not None and auc >= AUC_MIN_CALIFICADO

    info_cal = metricas.get("calibracion") or {}
    PIPELINE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump({
        "modelo": modelo,
        "features": cols,
        "entrenado": _ahora(),
        "calificado": bool(calificado),
        "auc_test": metricas.get("auc_test"),
        "umbral_auc": AUC_MIN_CALIFICADO,
        "calibrado": bool(info_cal.get("activa")),
        "metodo_calibracion": info_cal.get("metodo"),
        "brier_cal_test": metricas.get("brier_cal_test"),
    }, MODEL_PATH)
    catalogo.guardar_meta(META_ENTRENAMIENTO, _ahora())

    return {
        "ok": True,
        "metricas": metricas,
        "modelo": str(MODEL_PATH),
        "calificado": bool(calificado),
        "umbral_auc": AUC_MIN_CALIFICADO,
    }


def cargar_modelo():
    if not MODEL_PATH.exists():
        return None
    try:
        import joblib
        return joblib.load(MODEL_PATH)
    except Exception:
        return None


def modelo_esta_calificado(pack: dict | None = None) -> bool:
    if pack is None:
        pack = cargar_modelo()
    if pack is None:
        return False
    if "calificado" in pack:
        return bool(pack["calificado"])
    auc = pack.get("auc_test")
    return auc is not None and auc >= AUC_MIN_CALIFICADO


def inferir_features(feat: dict, forzar_mlp: bool = False) -> dict:
    pack = cargar_modelo()
    cols = features.FEATURE_COLS
    row = {c: float(feat.get(c, 0)) for c in cols}
    esperado = float(feat.get("esperado_m5_7d", 0))
    fallback = prob_poisson_fallback(esperado)

    if pack is None:
        return {
            "metodo": "poisson_fallback",
            "prob_m5_5d_pct": fallback,
            "modelo": None,
            "calificado": False,
        }

    calificado = modelo_esta_calificado(pack)
    if not calificado and not forzar_mlp:
        return {
            "metodo": "poisson_fallback",
            "prob_m5_5d_pct": fallback,
            "prob_poisson_pct": fallback,
            "modelo": str(MODEL_PATH.name),
            "entrenado": pack.get("entrenado"),
            "calificado": False,
            "motivo": f"MLP no calificado (AUC < {AUC_MIN_CALIFICADO} o backtest)",
        }

    modelo = pack["modelo"]
    X = np.array([[row[c] for c in pack["features"]]])
    prob_cruda = float(modelo.predict_proba(X)[0, 1])
    prob_pct = formatear_prob_pct(prob_cruda)
    metodo = "mlp_calibrado" if pack.get("calibrado") else "mlp_sklearn"
    return {
        "metodo": metodo,
        "prob_m5_5d_pct": prob_pct,
        "prob_cruda_pct": round(prob_cruda * 100.0, 2),
        "prob_poisson_pct": fallback,
        "modelo": str(MODEL_PATH.name),
        "entrenado": pack.get("entrenado"),
        "calibrado": bool(pack.get("calibrado")),
        "metodo_calibracion": pack.get("metodo_calibracion"),
        "calificado": True,
    }


def inferir_todas_estaciones(df_raw: pd.DataFrame) -> dict:
    out = {}
    for nombre, cfg in features.ESTACIONES.items():
        feat = features.features_vivo(df_raw, nombre, cfg)
        if not feat:
            out[nombre] = {"metodo": "sin_datos", "prob_m5_5d_pct": None, "calificado": False}
            continue
        inf = inferir_features(feat)
        inf["features"] = {k: feat.get(k) for k in features.FEATURE_COLS}
        out[nombre] = inf
    return out


def _resolver_calificacion(backtest_res: dict, hold_auc: float | None) -> bool:
    if backtest_res.get("calificado"):
        return True
    if hold_auc is None or hold_auc < AUC_MIN_CALIFICADO:
        return False
    g = backtest_res.get("global") or {}
    mlp_auc = (g.get("mlp") or {}).get("auc")
    poi_auc = (g.get("poisson") or {}).get("auc")
    if mlp_auc is not None and mlp_auc >= AUC_MIN_CALIFICADO:
        return True
    if mlp_auc is not None and (poi_auc is None or mlp_auc >= poi_auc - 0.03):
        backtest_res["nota_calificacion"] = "holdout_auc + walk-forward global"
        return True
    return hold_auc >= AUC_MIN_CALIFICADO + 0.08


def ejecutar_entrenamiento_e_inferencia(ejecutar_backtest: bool = True) -> dict:
    import nazca_pipeline_backtest as backtest
    import joblib

    df_raw = catalogo.leer_sismos()
    dataset = features.construir_dataset(
        df_raw,
        paso_dias=PASO_DIAS_ENTRENAMIENTO,
        modo_rapido=True,
    )
    backtest_res = {"ok": False, "error": "no ejecutado"}
    calificado = False

    train_res = {"ok": False, "error": "no ejecutado", "calificado": False}
    if not dataset.empty:
        train_res = entrenar_modelo(dataset, calificado_previo=None)

    hold_auc = (train_res.get("metricas") or {}).get("auc_test")

    if ejecutar_backtest and not dataset.empty:
        backtest_res = backtest.walk_forward_backtest(dataset)
        backtest_res["dataset"] = {
            "filas": len(dataset),
            "positivos": int(dataset["etiqueta_m5_5d"].sum()),
            "paso_dias": PASO_DIAS_ENTRENAMIENTO,
            "modo_rapido": True,
        }
        if hold_auc is not None:
            backtest_res["holdout_auc"] = hold_auc
        calificado = _resolver_calificacion(backtest_res, hold_auc)
        backtest_res["calificado"] = calificado
        backtest_res["metodo_recomendado"] = "mlp_sklearn" if calificado else "poisson_fallback"
        backtest.guardar_reporte(backtest_res)

    if train_res.get("ok"):
        train_res["calificado"] = calificado
        train_res["metodo_activo"] = backtest_res.get("metodo_recomendado", "poisson_fallback")
        pack = cargar_modelo()
        if pack is not None:
            pack["calificado"] = calificado
            joblib.dump(pack, MODEL_PATH)

    inferencias = inferir_todas_estaciones(df_raw)
    estado = {
        "actualizado": _ahora(),
        "catalogo": catalogo.resumen_db(),
        "dataset": {
            "filas": len(dataset),
            "positivos": int(dataset["etiqueta_m5_5d"].sum()) if not dataset.empty else 0,
            "paso_dias": PASO_DIAS_ENTRENAMIENTO,
        },
        "backtest": backtest_res,
        "entrenamiento": train_res,
        "inferencias": inferencias,
        "modelo_activo": MODEL_PATH.exists(),
        "modelo_calificado": calificado,
        "metodo_activo": backtest_res.get("metodo_recomendado", "poisson_fallback"),
        "umbral_auc": AUC_MIN_CALIFICADO,
    }
    guardar_estado(estado)
    catalogo.guardar_meta(META_PIPELINE_RUN, _ahora())
    return estado
