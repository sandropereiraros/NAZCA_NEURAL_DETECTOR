"""
NAZCA PIPELINE LAB — módulo desmontable (catálogo + cruce con núcleo Chile).

Desactivar: MODULO_PIPELINE_LAB_ACTIVO = False
Eliminar: nazca_pipeline_lab.py, nazca_catalogo_db.py, nazca_pipeline_colector.py
           y carpeta data/pipeline_lab/ — el monitor principal no se altera.
"""
from __future__ import annotations

import importlib.util
import math
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

import nazca_catalogo_db as catalogo
import nazca_pipeline_colector as colector
import nazca_pipeline_ml as pipeline_ml
import nazca_pipeline_features as pipeline_features

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CHILE_TZ = ZoneInfo("America/Santiago")

# ==============================================================================
# INTERRUPTOR — False = pestaña oculta, cero impacto en Chile
# ==============================================================================
MODULO_PIPELINE_LAB_ACTIVO = True
PIPELINE_LAB_VERSION = "v0.4-calibrado"
RADIO_CRUCE_KM = 350
MAG_UMBRAL_LAB = 5.0
HORIZONTE_DIAS_LAB = 5
PIPELINE_LAB_PROB_ELEVADA_PCT = 35.0  # Umbral más conservador para reducir falsas alertas

ESTILO_PANEL = {
    "color": "#a371f7",
    "bg": "rgba(163, 113, 247, 0.10)",
    "border": "#a371f7",
}


def _cargar_aux(nombre: str, archivo: str):
    ruta = os.path.join(BASE_DIR, archivo)
    if not os.path.exists(ruta):
        return None
    try:
        spec = importlib.util.spec_from_file_location(nombre, ruta)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


forecast_mod = _cargar_aux("nazca_forecast_sismico", "nazca_forecast_sismico.py")


def ahora_chile() -> datetime:
    return datetime.now(CHILE_TZ).replace(tzinfo=None)


def distancia_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math as m
    r = 6371.0
    lat1r, lon1r, lat2r, lon2r = map(m.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2r - lat1r
    dlon = lon2r - lon1r
    a = m.sin(dlat / 2) ** 2 + m.cos(lat1r) * m.cos(lat2r) * m.sin(dlon / 2) ** 2
    return float(2 * r * m.asin(m.sqrt(a)))


def filtrar_por_estacion(df: pd.DataFrame, lat: float, lon: float, radio_km: float = RADIO_CRUCE_KM) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    if "lat" in out.columns:
        out["Distancia_km"] = out.apply(
            lambda r: distancia_km(lat, lon, r["lat"], r["lon"]), axis=1
        )
    elif "Latitud" in out.columns:
        out["Distancia_km"] = out.apply(
            lambda r: distancia_km(lat, lon, r["Latitud"], r["Longitud"]), axis=1
        )
    else:
        return pd.DataFrame()
    return out[out["Distancia_km"] <= radio_km].sort_values(
        "fecha_local" if "fecha_local" in out.columns else "Fecha", ascending=False
    )


def prob_poisson_lab(esperado: float | None) -> float | None:
    """P(≥1 evento) ≈ 1 - e^{-λ} desde expectativa GR (orientativo, no calibrado)."""
    if esperado is None or esperado < 0:
        return None
    return round((1.0 - math.exp(-float(esperado))) * 100.0, 1)


def _render_nodo_mapa_simple(df: pd.DataFrame | None, lat: float, lon: float, label: str):
    """Renderiza un mapa simple con el nodo central y marcadores M6+ si existen.
    Usa `st.map` como fallback simple (compatible con Streamlit sin pydeck).
    """
    try:
        mapa_df = pd.DataFrame([{"lat": lat, "lon": lon, "tipo": "Nodo"}])
        if df is not None and not df.empty:
            if "Latitud" in df.columns and "Longitud" in df.columns:
                df2 = df.rename(columns={"Latitud": "lat", "Longitud": "lon", "Magnitud": "mag"})
            elif "lat" in df.columns and "lon" in df.columns:
                # attempt to find mag column name
                mag_col = None
                for c in ("mag", "Magnitud", "magnitude"):
                    if c in df.columns:
                        mag_col = c
                        break
                df2 = df.rename(columns={"lat": "lat", "lon": "lon"})
                if mag_col:
                    df2 = df2.rename(columns={mag_col: "mag"})
            else:
                df2 = pd.DataFrame()
            if not df2.empty and "mag" in df2.columns:
                m6 = df2[df2["mag"] >= 6.0]
                if not m6.empty:
                    mapa_df = pd.concat([mapa_df, m6[["lat", "lon"]]], ignore_index=True)
        # Render
        if mapa_df.empty:
            st.caption("Sin datos para mostrar en mapa.")
            return
        st.map(mapa_df[["lat", "lon"]])
        st.caption(f"Nodo: {label} · centro del mapa mostrado en azul")
    except Exception as exc:
        st.warning(f"No fue posible renderizar mapa simple: {exc}")


def evaluar_sistema_principal(ctx: dict) -> dict:
    nivel = str(ctx.get("nivel", "VERDE")).upper()
    puntaje = float(ctx.get("puntaje", 0))
    tendencia = ctx.get("tendencia_dir", "ESTABLE")
    alerta = nivel != "VERDE" or puntaje >= 55
    return {
        "sistema": "S1 · Semáforo NAZCA",
        "senal": "ELEVADA" if alerta else "NORMAL",
        "detalle": f"{ctx.get('color', '')} {nivel} · índice {puntaje:.0f}%",
        "color": "#d29922" if alerta else "#3fb950",
    }


def evaluar_sistema_gr(fc: dict | None) -> dict:
    if not fc:
        return {
            "sistema": "S2 · GR / Omori",
            "senal": "SIN_DATO",
            "detalle": "Módulo forecast no disponible",
            "color": "#8b949e",
        }
    t = fc.get("tendencia") or {}
    direccion = t.get("direccion", "SIN_DATO")
    elevada = direccion == "SUBE"
    return {
        "sistema": "S2 · GR / Omori",
        "senal": "ELEVADA" if elevada else ("BAJA" if direccion == "BAJA" else "NORMAL"),
        "detalle": f"{fc.get('flecha', '·')} {direccion} · p Poisson={t.get('test', {}).get('p_value', '—')}",
        "color": "#f85149" if elevada else ("#3fb950" if direccion == "BAJA" else "#58a6ff"),
    }


def evaluar_sistema_pipeline_lab(
    fc: dict | None,
    prob_m5: float | None,
    inf_ml: dict | None = None,
) -> dict:
    metodo = (inf_ml or {}).get("metodo", "poisson_fallback")
    prob_ml = (inf_ml or {}).get("prob_m5_5d_pct")
    prob_final = prob_ml if prob_ml is not None else prob_m5
    elevada = prob_final is not None and prob_final >= PIPELINE_LAB_PROB_ELEVADA_PCT
    calificado = (inf_ml or {}).get("calificado", metodo == "mlp_sklearn")
    if prob_ml is not None and metodo in ("mlp_sklearn", "mlp_calibrado") and calificado:
        cal_tag = inf_ml.get("metodo_calibracion") or "sin cal"
        detalle = f"P(M≥{MAG_UMBRAL_LAB:.0f}, {HORIZONTE_DIAS_LAB}d) ≈ {prob_ml}% · MLP {cal_tag}"
        if inf_ml.get("prob_cruda_pct") is not None and inf_ml.get("calibrado"):
            detalle += f" (cruda {inf_ml['prob_cruda_pct']}%)"
        if inf_ml.get("prob_poisson_pct") is not None:
            detalle += f" · Poisson ref. {inf_ml['prob_poisson_pct']}%"
    elif prob_ml is not None and metodo == "poisson_fallback":
        detalle = f"P(M≥{MAG_UMBRAL_LAB:.0f}, {HORIZONTE_DIAS_LAB}d) ≈ {prob_ml}% · Poisson (gate activo)"
        if inf_ml.get("motivo"):
            detalle += f" · {inf_ml['motivo']}"
    elif prob_m5 is not None:
        detalle = f"P(M≥{MAG_UMBRAL_LAB:.0f}, {HORIZONTE_DIAS_LAB}d) ≈ {prob_m5}% · baseline Poisson"
    else:
        detalle = "Sin inferencia — ejecuta el servicio pipeline"
    if fc and fc.get("esperado_m5_7d") is not None:
        detalle += f" · λ M≥5 ~{fc['esperado_m5_7d']}"
    return {
        "sistema": "S3 · Pipeline LAB (ML)",
        "senal": "ELEVADA" if elevada else "NORMAL",
        "detalle": detalle,
        "color": "#a371f7" if elevada else "#8b949e",
        "prob_m5_pct": prob_final,
        "metodo": metodo,
    }


def concordancia_lab(s1: dict, s2: dict, s3: dict) -> dict:
    elevadas = sum(1 for s in (s1, s2, s3) if s.get("senal") == "ELEVADA")
    if elevadas >= 3:
        texto, color = "ALTA — 3/3 sistemas en vigilancia elevada", "#f85149"
    elif elevadas == 2:
        texto, color = "MEDIA — 2/3 sistemas coinciden", "#d29922"
    elif elevadas == 1:
        texto, color = "BAJA — solo 1/3 elevado (cautela)", "#58a6ff"
    else:
        texto, color = "TRANQUILA — 0/3 elevados", "#3fb950"
    return {
        "elevadas": elevadas,
        "texto": texto,
        "color": color,
        "recomendacion": (
            "Experimental: revisar CSN/ONEMI. Este bloque no modifica el semáforo principal."
            if elevadas >= 2
            else "Pipeline LAB acorde con monitor principal en modo conservador."
        ),
    }


def tabla_cruce_principal_vs_pipeline(ctx: dict, df_pipe_local: pd.DataFrame, fc: dict | None) -> pd.DataFrame:
    n_usgs_live = int(ctx.get("total_sismos", 0))
    n_pipe = len(df_pipe_local)
    filas = [
        {
            "Métrica": "Sismos zona (radio km)",
            "Monitor principal (USGS 14D vivo)": n_usgs_live,
            "Pipeline LAB (SQLite)": n_pipe,
            "Notas": f"Radio {RADIO_CRUCE_KM} km · fuentes USGS+CSN en lab",
        },
        {
            "Métrica": "b-value",
            "Monitor principal (USGS 14D vivo)": ctx.get("b_val"),
            "Pipeline LAB (SQLite)": fc.get("b_value") if fc else "—",
            "Notas": "S2 recalculado sobre catálogo pipeline local",
        },
        {
            "Métrica": "Nivel semáforo",
            "Monitor principal (USGS 14D vivo)": f"{ctx.get('color', '')} {ctx.get('nivel', '')}",
            "Pipeline LAB (SQLite)": "— (no altera semáforo)",
            "Notas": "S1 solo lectura en este LAB",
        },
        {
            "Métrica": "Match M7+",
            "Monitor principal (USGS 14D vivo)": f"{ctx.get('mejor_match', 0):.1f}%",
            "Pipeline LAB (SQLite)": "—",
            "Notas": "Patrón histórico no se mezcla con pipeline",
        },
        {
            "Métrica": "Tendencia GR",
            "Monitor principal (USGS 14D vivo)": ctx.get("tendencia_dir", "—"),
            "Pipeline LAB (SQLite)": (fc.get("tendencia") or {}).get("direccion") if fc else "—",
            "Notas": "Comparar S2 vivo vs S2 sobre SQLite",
        },
    ]
    return pd.DataFrame(filas)


def _render_resumen_simple(
    estacion_sel: str,
    config: dict,
    s3: dict,
    conc: dict,
) -> None:
    if not config:
        return
    pais = config.get("pais") or config.get("region") or "zona"
    lat = config.get("lat")
    lon = config.get("lon")
    radio = RADIO_CRUCE_KM
    prob = s3.get("prob_m5_pct")
    metodo = s3.get("metodo", "—")
    ventana = "5 días" if prob is not None else "ventana por determinar"
    detalle = s3.get("detalle", "Sin datos de riesgo ML")

    st.markdown("#### Resumen rápido para usuarios")
    st.markdown(
        f"<div style='border:2px solid rgba(167, 139, 250, 0.9);border-radius:14px;padding:16px;"
        f"background:rgba(99, 102, 241, 0.18);color:#f8fafc;'>"
        f"<b>Nodo de atención:</b> {estacion_sel} ({pais})<br/>"
        f"<b>Ubicación aproximada:</b> {lat if lat is not None else '—'}, {lon if lon is not None else '—'}<br/>"
        f"<b>Radio de vigilancia:</b> ~{radio} km alrededor del nodo<br/>"
        f"<b>Señal más relevante:</b> {s3.get('senal', 'NORMAL')} · {detalle}<br/>"
        f"<b>Ventana corta:</b> {ventana}<br/>"
        f"<b>Datos en vivo:</b> usados como insumo, no como predicción determinista<br/>"
        f"</div>",
        unsafe_allow_html=True,
    )


def render_pipeline_lab(
    admin_activo: bool,
    estacion_sel: str,
    config: dict,
    ctx_principal: dict,
    df_sismos_local: pd.DataFrame | None = None,
) -> None:
    if not MODULO_PIPELINE_LAB_ACTIVO:
        return

    if not admin_activo:
        st.info(
            "NAZCA PIPELINE LAB es privado (solo admin). "
            "Ingresa PIN admin para acceder al laboratorio de catálogo y cruce experimental."
        )
        return

    st.markdown("### 🧪 NAZCA PIPELINE LAB — Catálogo + ML + cruce")
    st.caption(
        f"Build **{PIPELINE_LAB_VERSION}** · Estación referencia: **{estacion_sel}** · "
        "Módulo **desmontable** — no modifica semáforo, Telegram ni vigilancia 24/7."
    )
    st.warning(
        "**Sistema de pruebas (IA experimental).** Datos en `data/pipeline_lab/`. "
        "Servicio: `scripts/pipeline/ejecutar_pipeline.py --todo` o `iniciar_servicio_pipeline.ps1`."
    )

    estado_ml = pipeline_ml.leer_estado()
    resumen = catalogo.resumen_db()
    ultimo_run = catalogo.leer_meta("ultimo_pipeline_run", "—")
    bt = estado_ml.get("backtest") or {}
    calificado = estado_ml.get("modelo_calificado", False)
    metodo_activo = estado_ml.get("metodo_activo", "poisson_fallback")
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Eventos en SQLite", resumen["total"])
    m2.metric("Método activo", "MLP" if metodo_activo == "mlp_sklearn" else "Poisson")
    m3.metric("Backtest", "OK" if bt.get("calificado") else ("—" if not bt.get("ok") else "Gate"))
    m4.metric("Último ciclo", str(ultimo_run)[:16])
    m5.metric("Último USGS", (resumen["ultimo_usgs"] or "—")[:16])
    m6.metric("Último CSN", (resumen["ultimo_csn"] or "—")[:16])
    tr = estado_ml.get("entrenamiento") or {}
    tm = tr.get("metricas") or {}
    cal_info = tm.get("calibracion") or {}
    if cal_info.get("activa") or tm.get("brier_cal_test") is not None:
        st.caption(
            f"Calibración **{cal_info.get('metodo', '—')}** · "
            f"Brier crudo **{tm.get('brier_crudo_test', '—')}** → "
            f"calibrado **{tm.get('brier_cal_test', '—')}** "
            f"(Δ {tm.get('brier_mejora', '—')})"
        )
    if bt.get("ok"):
        g = bt.get("global") or {}
        st.caption(
            f"Walk-forward **{bt.get('n_folds', 0)}** folds · "
            f"AUC MLP **{g.get('auc_mlp_media_folds', '—')}** · "
            f"AUC Poisson **{g.get('auc_poisson_media_folds', '—')}** · "
            f"umbral **{estado_ml.get('umbral_auc', pipeline_ml.AUC_MIN_CALIFICADO)}** · "
            f"modelo **{'calificado' if calificado else 'fallback Poisson'}**"
        )
    if estado_ml:
        ds = estado_ml.get("dataset") or {}
        st.caption(
            f"Dataset ML: **{ds.get('filas', 0)}** filas · "
            f"positivos M≥5: **{ds.get('positivos', 0)}** · "
            f"actualizado: **{estado_ml.get('actualizado', '—')}**"
        )

    with st.expander("Backtest walk-forward (validación S3)"):
        if bt.get("ok"):
            st.success(
                f"Método recomendado: **{bt.get('metodo_recomendado')}** · "
                f"Calificado: **{'Sí' if bt.get('calificado') else 'No — usa Poisson'}**"
            )
            if bt.get("folds"):
                st.dataframe(pd.DataFrame(bt["folds"]), use_container_width=True, hide_index=True)
            if bt.get("por_estacion"):
                st.dataframe(pd.DataFrame(bt["por_estacion"]), use_container_width=True, hide_index=True)
        else:
            st.info(bt.get("error", "Ejecuta **Ciclo completo** para generar backtest."))

    with st.expander("Estado del almacén aislado"):
        st.json(resumen)

    st.markdown("#### Servicio pipeline")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        if st.button("▶ Ciclo completo (sync+ML)", use_container_width=True, key="pl_ciclo"):
            with st.spinner("Sync + entrenamiento + inferencia…"):
                colector.sync_operativo()
                est = pipeline_ml.ejecutar_entrenamiento_e_inferencia()
            tr = est.get("entrenamiento", {})
            if tr.get("ok"):
                st.success(f"ML entrenado · AUC test: {tr.get('metricas', {}).get('auc_test')}")
            else:
                st.warning(f"ML: {tr.get('error', 'fallback Poisson')} — sync OK")
            st.rerun()
    with c2:
        if st.button("Sync operativo", use_container_width=True, key="pl_sync_op"):
            with st.spinner("USGS+CSN…"):
                r = colector.sync_operativo()
            st.success(f"DB total: {r['total_db']} eventos")
            st.rerun()
    with c3:
        if st.button("Bootstrap USGS 2015+", use_container_width=True, key="pl_boot_usgs"):
            with st.spinner("Histórico USGS mensual (varios min)…"):
                r = colector.backfill_usgs(anio_desde=2015)
            st.success(f"USGS: {r['meses']} meses · DB={r['total_db']}")
            st.rerun()
    with c4:
        if st.button("Bootstrap CSN 90d", use_container_width=True, key="pl_boot_csn"):
            with st.spinner("CSN día a día…"):
                r = colector.backfill_csn_dias(dias=90)
            st.success(f"CSN: {r['dias']} días · DB={r['total_db']}")
            st.rerun()

    df_raw = catalogo.leer_sismos()
    df_nazca = catalogo.df_a_formato_nazca(df_raw)
    df_pipe_local = filtrar_por_estacion(
        df_raw, config["lat"], config["lon"], RADIO_CRUCE_KM
    )
    df_fc_source = catalogo.df_a_formato_nazca(df_pipe_local)

    fc_pipe = None
    if forecast_mod and not df_fc_source.empty:
        fc_pipe = forecast_mod.resumen_forecast_sismico(df_fc_source)
    elif forecast_mod and df_sismos_local is not None and not df_sismos_local.empty:
        fc_pipe = forecast_mod.resumen_forecast_sismico(df_sismos_local)

    esperado_m5 = fc_pipe.get("esperado_m5_7d") if fc_pipe else None
    prob_lab = prob_poisson_lab(esperado_m5)

    inf_ml = (estado_ml.get("inferencias") or {}).get(estacion_sel)
    if not inf_ml and df_raw is not None and not df_raw.empty:
        feat_v = pipeline_features.features_vivo(df_raw, estacion_sel, config)
        if feat_v:
            inf_ml = pipeline_ml.inferir_features(feat_v)

    tendencia_live = "—"
    if forecast_mod and df_sismos_local is not None and not df_sismos_local.empty:
        fc_live = forecast_mod.resumen_forecast_sismico(df_sismos_local)
        tendencia_live = (fc_live.get("tendencia") or {}).get("direccion", "—")
    ctx = {**ctx_principal, "tendencia_dir": tendencia_live}

    s1 = evaluar_sistema_principal(ctx)
    s2 = evaluar_sistema_gr(fc_pipe)
    s3 = evaluar_sistema_pipeline_lab(fc_pipe, prob_lab, inf_ml)
    conc = concordancia_lab(s1, s2, s3)

    _render_resumen_simple(estacion_sel, config, s3, conc)

    st.markdown("#### Concordancia S1 / S2 / S3 (solo LAB)")
    st.markdown(
        f"<div style='border:2px solid {conc['color']};border-radius:12px;padding:14px;"
        f"background:rgba(0,0,0,.2);color:{conc['color']};font-weight:700;'>"
        f"{conc['texto']}</div>",
        unsafe_allow_html=True,
    )
    st.caption(conc["recomendacion"])

    cols = st.columns(3)
    for col, s in zip(cols, (s1, s2, s3)):
        with col:
            st.markdown(
                f"<div style='border-left:4px solid {s['color']};padding-left:12px;'>"
                f"<b>{s['sistema']}</b><br/>{s['senal']}<br/>"
                f"<span style='color:#8b949e;font-size:.88rem;'>{s['detalle']}</span></div>",
                unsafe_allow_html=True,
            )

    st.markdown("#### Cruce monitor principal ↔ pipeline (solo lectura)")
    st.dataframe(
        tabla_cruce_principal_vs_pipeline(ctx, df_pipe_local, fc_pipe),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("#### Catálogo pipeline — zona activa")
    if df_pipe_local.empty:
        st.info("Sin eventos en SQLite para esta zona. Usa **Sync USGS 30 días** arriba.")
    else:
        show = df_pipe_local.copy()
        show = show.rename(columns={
            "fecha_local": "Fecha",
            "magnitud": "Magnitud",
            "lugar": "Lugar",
            "fuente": "Fuente",
            "profundidad_km": "Prof. km",
        })
        cols_show = [c for c in ["Fecha", "Magnitud", "Lugar", "Fuente", "Prof. km", "Distancia_km"] if c in show.columns]
        st.dataframe(show[cols_show].head(40), use_container_width=True, hide_index=True)

    # Mapa simple del nodo y eventos M6+
    col_map, col_tbl = st.columns([1.6, 1])
    with col_map:
        st.markdown("#### Mapa: Nodo y M6+ recientes (simple)")
        _render_nodo_mapa_simple(df_raw, config["lat"], config["lon"], estacion_sel)
    with col_tbl:
        st.markdown("#### Eventos M6+ en SQLite (zona)")
        if not df_pipe_local.empty:
            mag_col = None
            for c in ("Magnitud", "magnitud", "mag"):
                if c in df_pipe_local.columns:
                    mag_col = c
                    break
            if mag_col is not None:
                m6_local = df_pipe_local[df_pipe_local[mag_col] >= 6.0]
            else:
                m6_local = pd.DataFrame()
            if m6_local.empty:
                st.caption("No hay M6+ en SQLite para esta zona.")
            else:
                st.dataframe(m6_local.head(20), use_container_width=True, hide_index=True)
        else:
            st.caption("Sin eventos locales.")

    with st.expander("Todo el SQLite (muestra global)"):
        if df_nazca.empty:
            st.caption("Vacío.")
        else:
            st.dataframe(df_nazca.head(80), use_container_width=True, hide_index=True)

    st.markdown("#### Inferencias ML por estación")
    if estado_ml.get("inferencias"):
        filas_inf = []
        for est, inf in estado_ml["inferencias"].items():
            filas_inf.append({
                "Estación": est,
                "P calibrada %": inf.get("prob_m5_5d_pct"),
                "P cruda %": inf.get("prob_cruda_pct"),
                "Poisson ref. %": inf.get("prob_poisson_pct"),
                "Método": inf.get("metodo"),
                "Calibración": inf.get("metodo_calibracion") or "—",
            })
        st.dataframe(pd.DataFrame(filas_inf), use_container_width=True, hide_index=True)
    else:
        st.caption("Ejecuta **Ciclo completo** o el servicio en background.")

    with st.expander("Estado ML (JSON)"):
        st.json(estado_ml if estado_ml else {"mensaje": "Sin estado — ejecutar pipeline"})

    st.markdown("#### Automatización (sin ventana abierta)")
    st.info(
        "**Opción A — Windows (recomendada en tu PC):** ejecuta **una sola vez**  \n"
        "`powershell -ExecutionPolicy Bypass -File scripts/pipeline/registrar_tarea_windows.ps1`  \n"
        "Crea la tarea **NAZCA-Pipeline-LAB** cada 10 min en segundo plano.\n\n"
        "**Opción B — GitHub (servidor/cloud):** al hacer push, corre solo  \n"
        "`.github/workflows/pipeline_lab.yml` (cada 30 min) y  \n"
        "`vigilancia_chile.yml` (cada 6 h).\n\n"
        "**Opción C — Manual:** `python scripts/pipeline/ejecutar_pipeline.py --todo`"
    )
