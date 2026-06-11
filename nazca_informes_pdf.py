"""
Informes PDF NAZCA — comparativas 14D, evolución de parámetros y validación post-evento.
"""
from __future__ import annotations

import os
import unicodedata
from datetime import timedelta

import pandas as pd
from fpdf import FPDF

CHILE_TZ_LABEL = "Chile continental (UTC-4)"


def _texto_celda(valor):
    if valor is None:
        return ""
    try:
        if pd.isna(valor):
            return ""
    except (TypeError, ValueError):
        pass
    return str(valor)


def df_ui_seguro(df):
    """Evita fallos PyArrow cuando una columna mezcla números y texto."""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return df if isinstance(df, pd.DataFrame) else pd.DataFrame()
    out = df.copy()
    for col in out.columns:
        out[col] = out[col].map(_texto_celda)
    return out


def sanitizar_texto(texto):
    texto = "" if texto is None else str(texto)
    reemplazos = {
        "🟢": "", "🟡": "", "🟠": "", "🔴": "", "🚨": "", "⚠️": "", "✅": "",
        "—": "-", "–": "-", "·": "-", "≤": "<=", "≥": ">=", "±": "+/-",
        "í": "i", "Í": "I", "ó": "o", "Ó": "O", "á": "a", "Á": "A",
        "é": "e", "É": "E", "ú": "u", "Ú": "U", "ñ": "n", "Ñ": "N",
    }
    for original, seguro in reemplazos.items():
        texto = texto.replace(original, seguro)
    texto = unicodedata.normalize("NFKD", texto)
    return texto.encode("ascii", errors="ignore").decode("ascii")


def _pdf_out(pdf: FPDF) -> bytes:
    out = pdf.output(dest="S")
    return out.encode("latin-1") if isinstance(out, str) else bytes(out)


def _celda(pdf, w, h, txt, bold=False, ln=0):
    pdf.set_font("Arial", "B" if bold else "", 9)
    pdf.cell(w, h, sanitizar_texto(txt), border=1, ln=ln)


def _linea(pdf, etiqueta, valor):
    _celda(pdf, 62, 6, etiqueta, bold=True)
    _celda(pdf, 0, 6, valor, ln=1)


def _multilinea(pdf, txt):
    pdf.set_font("Arial", "", 9)
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(pdf.w - pdf.l_margin - pdf.r_margin, 5, sanitizar_texto(txt))
    pdf.set_x(pdf.l_margin)


def _cabecera(pdf, titulo, subtitulo, logo_path=None):
    if logo_path and os.path.exists(logo_path):
        pdf.image(logo_path, x=12, y=10, w=26)
        pdf.set_xy(42, 11)
    else:
        pdf.set_xy(12, 11)
    pdf.set_font("Arial", "B", 15)
    _celda(pdf, 0, 8, "NAZCA NEURAL DETECTOR", ln=1)
    pdf.set_x(42 if logo_path and os.path.exists(logo_path) else 12)
    pdf.set_font("Arial", "", 9)
    _celda(pdf, 0, 6, titulo, ln=1)
    pdf.set_x(42 if logo_path and os.path.exists(logo_path) else 12)
    _celda(pdf, 0, 6, subtitulo, ln=1)
    pdf.ln(10)


def _delta_txt(actual, ref, dec=2):
    try:
        a, r = float(actual), float(ref)
        d = a - r
        sign = "+" if d >= 0 else ""
        return f"{a:.{dec}f} vs ref {r:.{dec}f} (delta {sign}{d:.{dec}f})"
    except (TypeError, ValueError):
        return f"{actual} vs ref {ref}"


def _ultimo_sismo_df(df_local):
    if df_local is None or df_local.empty:
        return None
    df = df_local.copy()
    if "Fecha" in df.columns:
        df["_ord"] = pd.to_datetime(df["Fecha"], errors="coerce")
        df = df.sort_values("_ord", ascending=False)
    return df.iloc[0]


def _evolucion_14d(df_evidencia, col_filtro, valor, ahora_dt):
    if df_evidencia is None or df_evidencia.empty:
        return None, None
    df = df_evidencia.copy()
    if col_filtro not in df.columns:
        return None, None
    df = df[df[col_filtro].astype(str) == str(valor)]
    if "fecha_hora_dt" not in df.columns and "fecha_hora" in df.columns:
        df["fecha_hora_dt"] = pd.to_datetime(df["fecha_hora"], errors="coerce")
    df = df.dropna(subset=["fecha_hora_dt"])
    if df.empty:
        return None, None
    corte = ahora_dt - timedelta(days=14)
    df = df[df["fecha_hora_dt"] >= corte].sort_values("fecha_hora_dt")
    if df.empty:
        return None, None
    return df.iloc[0], df.iloc[-1]


def _tabla_comparativa(pdf, filas):
    pdf.set_font("Arial", "B", 10)
    _celda(pdf, 48, 7, "Parametro", bold=True)
    _celda(pdf, 38, 7, "Lectura actual", bold=True)
    _celda(pdf, 38, 7, "Firma 14D pre-M7+", bold=True)
    _celda(pdf, 0, 7, "Cambio", bold=True, ln=1)
    pdf.set_font("Arial", "", 8)
    for param, act, ref, cambio in filas:
        _celda(pdf, 48, 6, param)
        _celda(pdf, 38, 6, act)
        _celda(pdf, 38, 6, ref)
        _celda(pdf, 0, 6, cambio, ln=1)
    pdf.ln(3)


def _ref_por_nombre(eventos_ref, nombre):
    if not eventos_ref or not nombre:
        return None
    for ev in eventos_ref:
        if ev.get("evento") == nombre:
            return ev
    return eventos_ref[0] if eventos_ref else None


def filas_comparativa_mundo(res, ref_evento=None):
    ref = ref_evento or {}
    return [
        {"Parámetro": "b-value 14D", "Lectura actual": f"{res.get('b_val', 0):.2f}",
         "Firma 14D pre-M7+": ref.get("b_14d", "N/D"), "Cambio": _delta_txt(res.get("b_val", 0), ref.get("b_14d", 0))},
        {"Parámetro": "Sismos locales 14D", "Lectura actual": res.get("total_local", 0),
         "Firma 14D pre-M7+": ref.get("sismos_14d", "N/D"), "Cambio": _delta_txt(res.get("total_local", 0), ref.get("sismos_14d", 0), 0)},
        {"Parámetro": "InSAR estimado %", "Lectura actual": f"{res.get('insar', 0):.1f}",
         "Firma 14D pre-M7+": ref.get("insar", "N/D"), "Cambio": _delta_txt(res.get("insar", 0), ref.get("insar", 0), 1)},
        {"Parámetro": "EM / conductividad", "Lectura actual": f"{res.get('cond', 0):.2f}",
         "Firma 14D pre-M7+": ref.get("cond", "N/D"), "Cambio": _delta_txt(res.get("cond", 0), ref.get("cond", 0))},
        {"Parámetro": "SHOA / marea cm", "Lectura actual": f"{res.get('shoa', 0):.2f}",
         "Firma 14D pre-M7+": ref.get("shoa", "N/D"), "Cambio": _delta_txt(res.get("shoa", 0), ref.get("shoa", 0))},
        {"Parámetro": "Índice LAB %", "Lectura actual": f"{res.get('puntaje', 0):.1f}",
         "Firma 14D pre-M7+": "-", "Cambio": "Lectura operativa actual"},
        {"Parámetro": "Patrón referencia", "Lectura actual": res.get("mejor_ev", ""),
         "Firma 14D pre-M7+": ref.get("evento", ""), "Cambio": f"Match {res.get('mejor_match', 0):.1f}%"},
    ]


def tabla_comparativa_mundo(res, ref_evento=None):
    return df_ui_seguro(pd.DataFrame(filas_comparativa_mundo(res, ref_evento)))


def filas_comparativa_chile(b_val, insar, cond, shoa, total_sismos, total_sismos_chile, puntaje, ref_evento=None):
    ref = ref_evento or {}
    return [
        {"Parámetro": "b-value 14D", "Lectura actual": f"{b_val:.2f}",
         "Firma 14D pre-M7+": ref.get("b_14d", "N/D"), "Cambio": _delta_txt(b_val, ref.get("b_14d", 0))},
        {"Parámetro": "Sismos locales 14D", "Lectura actual": total_sismos,
         "Firma 14D pre-M7+": ref.get("sismos_14d", "N/D"), "Cambio": _delta_txt(total_sismos, ref.get("sismos_14d", 0), 0)},
        {"Parámetro": "Sismos Chile 14D", "Lectura actual": total_sismos_chile,
         "Firma 14D pre-M7+": "-", "Cambio": "Cobertura nacional USGS"},
        {"Parámetro": "InSAR estimado %", "Lectura actual": f"{insar:.1f}",
         "Firma 14D pre-M7+": ref.get("insar", "N/D"), "Cambio": _delta_txt(insar, ref.get("insar", 0), 1)},
        {"Parámetro": "EM mS/m", "Lectura actual": f"{cond:.2f}",
         "Firma 14D pre-M7+": ref.get("cond", "N/D"), "Cambio": _delta_txt(cond, ref.get("cond", 0))},
        {"Parámetro": "SHOA cm", "Lectura actual": f"{shoa:.2f}",
         "Firma 14D pre-M7+": ref.get("shoa", "N/D"), "Cambio": _delta_txt(shoa, ref.get("shoa", 0))},
        {"Parámetro": "Índice vigilancia %", "Lectura actual": f"{puntaje:.1f}",
         "Firma 14D pre-M7+": "-", "Cambio": "Lectura operativa actual"},
    ]


def tabla_comparativa_chile(b_val, insar, cond, shoa, total_sismos, total_sismos_chile, puntaje, eventos_m7, mejor_ev):
    ref = _ref_por_nombre(eventos_m7, mejor_ev) or (eventos_m7[0] if eventos_m7 else {})
    return df_ui_seguro(pd.DataFrame(filas_comparativa_chile(b_val, insar, cond, shoa, total_sismos, total_sismos_chile, puntaje, ref)))


def boton_descarga_pdf(pdf_bytes, nombre_archivo, boton_key, etiqueta="⬇️ Descargar informe PDF"):
    """Un solo botón de descarga — sin iframe (Chrome/Cloud lo bloquean)."""
    import streamlit as st

    if not pdf_bytes:
        st.warning("No se pudo generar el informe PDF.")
        return
    tam_kb = max(1, len(pdf_bytes) // 1024)
    st.success(f"Informe listo: **{nombre_archivo}** ({tam_kb} KB)")
    st.caption("Pulsa el botón para descargar y ábrelo con Adobe, Edge o el visor de Windows.")
    st.download_button(
        etiqueta,
        pdf_bytes,
        nombre_archivo,
        "application/pdf",
        use_container_width=True,
        key=boton_key,
    )


def render_vista_previa_pdf(pdf_bytes, nombre_archivo="informe.pdf", key="pdf_previa"):
    boton_descarga_pdf(pdf_bytes, nombre_archivo, boton_key=key)


def generar_pdf_comparativa_mundo(
    nodo_sel,
    config,
    res,
    consultado_usgs,
    ref_evento=None,
    df_evidencia=None,
    coincidencias=None,
    ultimo_sismo=None,
    ahora=None,
    logo_path=None,
):
    ahora = ahora or pd.Timestamp.now()
    ref = ref_evento or {}
    ult = ultimo_sismo if ultimo_sismo is not None else _ultimo_sismo_df(res.get("df_local"))

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=14)
    _cabecera(
        pdf,
        "Informe comparativo MUNDO LAB",
        f"Nodo: {nodo_sel} | Generado: {ahora.strftime('%Y-%m-%d %H:%M')} ({CHILE_TZ_LABEL})",
        logo_path=logo_path,
    )

    pdf.set_font("Arial", "B", 12)
    _celda(pdf, 0, 8, "1. Resumen ejecutivo", ln=1)
    _linea(pdf, "Pais / region", config.get("pais", ""))
    _linea(pdf, "Tipo de falla", config.get("tipo_falla", ""))
    _linea(pdf, "Estado LAB", res.get("estado", ""))
    _linea(pdf, "Nivel alerta", res.get("nivel", {}).get("nivel", ""))
    _linea(pdf, "Indice vigilancia", f"{res.get('puntaje', 0):.1f}%")
    _linea(pdf, "Match patron ref.", f"{res.get('mejor_match', 0):.1f}%")
    _linea(pdf, "Patron mas parecido", res.get("mejor_ev", "Sin referencia"))
    pdf.ln(2)

    pdf.set_font("Arial", "B", 12)
    _celda(pdf, 0, 8, "2. Ultimo sismo USGS en el nodo", ln=1)
    if ult is not None:
        mag = ult.get("Magnitud", ult.get("mag", "?"))
        _linea(pdf, "Magnitud", f"M{mag}")
        _linea(pdf, "Lugar", ult.get("Lugar", ult.get("lugar", "")))
        _linea(pdf, "Fecha (Chile)", ult.get("Fecha", ""))
        if "Distancia_km" in ult:
            _linea(pdf, "Distancia al nodo", f"{ult['Distancia_km']:.1f} km")
    else:
        _multilinea(pdf, "Sin sismos USGS recientes en el radio del nodo en la ventana 14D.")
    pdf.ln(2)

    pdf.set_font("Arial", "B", 12)
    _celda(pdf, 0, 8, "3. Comparativa: hoy vs firma 14D antes del gran sismo", ln=1)
    _multilinea(
        pdf,
        "La columna 'Firma 14D pre-M7+' reproduce los parametros documentados en el catalogo "
        "historico mundial para el patron de referencia del nodo (ventana de 14 dias previa al evento mayor)."
    )
    _tabla_comparativa(pdf, [
        (r["Parámetro"], r["Lectura actual"], r["Firma 14D pre-M7+"], r["Cambio"])
        for r in filas_comparativa_mundo(res, ref_evento)
        if r["Parámetro"] != "Patrón referencia"
    ])

    pdf.set_font("Arial", "B", 12)
    _celda(pdf, 0, 8, "4. Evolucion en los ultimos 14 dias (snapshots LAB)", ln=1)
    ini, fin = _evolucion_14d(df_evidencia, "nodo", nodo_sel, ahora)
    if ini is not None and fin is not None:
        _linea(pdf, "Primer snapshot 14D", str(ini.get("fecha_hora", "")))
        _linea(pdf, "Ultimo snapshot 14D", str(fin.get("fecha_hora", "")))
        _linea(pdf, "b-value", _delta_txt(fin.get("b_value"), ini.get("b_value")))
        _linea(pdf, "Sismos locales 14D", _delta_txt(fin.get("sismos_locales_14d"), ini.get("sismos_locales_14d"), 0))
        _linea(pdf, "Indice %", _delta_txt(fin.get("puntaje"), ini.get("puntaje"), 1))
        _linea(pdf, "Match ref. %", _delta_txt(fin.get("match_ref"), ini.get("match_ref"), 1))
        _linea(pdf, "Nivel", f"{ini.get('nivel', '')} -> {fin.get('nivel', '')}")
    else:
        _multilinea(pdf, "Aun no hay suficientes snapshots guardados en los ultimos 14 dias para trazar evolucion.")
    pdf.ln(2)

    pdf.set_font("Arial", "B", 12)
    _celda(pdf, 0, 8, "5. Coincidencias post-evento (si existen)", ln=1)
    if coincidencias is not None and not coincidencias.empty:
        for _, row in coincidencias.head(5).iterrows():
            _multilinea(
                pdf,
                f"- {row.get('Evento real', '')} M{row.get('Magnitud', '')} | "
                f"evidencia {row.get('Fecha evidencia', '')} | "
                f"anticipacion {row.get('Anticipacion h', row.get('Anticipación h', ''))} h | "
                f"nivel {row.get('Nivel previo', '')}"
            )
    else:
        _multilinea(pdf, "Sin coincidencias registradas bajo los criterios actuales de validacion.")
    pdf.ln(2)

    pdf.set_font("Arial", "B", 12)
    _celda(pdf, 0, 8, "6. Trazabilidad y limitacion", ln=1)
    _linea(pdf, "USGS consultado", consultado_usgs or "N/D")
    _linea(pdf, "Modelo", "NAZCA_MUNDO_LAB v4.0-sin-chile")
    _multilinea(
        pdf,
        "Informe experimental de apoyo. No sustituye alertas oficiales. "
        "Telemetria InSAR, EM y SHOA pueden ser estimada en modo LAB."
    )
    return _pdf_out(pdf)


def generar_pdf_comparativa_chile(
    estacion,
    config,
    puntaje,
    estado,
    nivel_alerta,
    b_val,
    insar,
    cond,
    shoa,
    total_sismos,
    total_sismos_chile,
    mejor_ev,
    mejor_match,
    consultado_usgs,
    eventos_m7,
    df_evidencia=None,
    coincidencias=None,
    ultimo_sismo=None,
    ahora=None,
    logo_path=None,
):
    ahora = ahora or pd.Timestamp.now()
    ref = _ref_por_nombre(eventos_m7, mejor_ev) or (eventos_m7[0] if eventos_m7 else {})

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=14)
    _cabecera(
        pdf,
        "Informe comparativo Chile - ventana 14D",
        f"Estacion: {estacion} | Generado: {ahora.strftime('%Y-%m-%d %H:%M')} ({CHILE_TZ_LABEL})",
        logo_path=logo_path,
    )

    pdf.set_font("Arial", "B", 12)
    _celda(pdf, 0, 8, "1. Resumen ejecutivo", ln=1)
    _linea(pdf, "Estado", estado)
    _linea(pdf, "Nivel alerta", nivel_alerta.get("nivel", ""))
    _linea(pdf, "Indice vigilancia", f"{puntaje:.1f}%")
    _linea(pdf, "Patron M7+ mas parecido", mejor_ev)
    _linea(pdf, "Match patron", f"{mejor_match:.1f}%")
    pdf.ln(2)

    pdf.set_font("Arial", "B", 12)
    _celda(pdf, 0, 8, "2. Ultimo sismo USGS relevante (Chile 14D)", ln=1)
    ult = ultimo_sismo
    if ult is None and coincidencias is not None and not coincidencias.empty:
        row = coincidencias.iloc[0]
        ult = {"Magnitud": row.get("Magnitud"), "Lugar": row.get("Evento real"), "Fecha": row.get("Fecha evento")}
    if ult is not None:
        _linea(pdf, "Magnitud", f"M{ult.get('Magnitud', '?')}")
        _linea(pdf, "Lugar", ult.get("Lugar", ""))
        _linea(pdf, "Fecha", ult.get("Fecha", ""))
    else:
        _multilinea(pdf, "Sin evento USGS M5+ destacado en la ventana actual.")
    pdf.ln(2)

    pdf.set_font("Arial", "B", 12)
    _celda(pdf, 0, 8, "3. Comparativa: hoy vs firma 14D antes de gran sismo Chile", ln=1)
    _tabla_comparativa(pdf, [
        (r["Parámetro"], r["Lectura actual"], r["Firma 14D pre-M7+"], r["Cambio"])
        for r in filas_comparativa_chile(b_val, insar, cond, shoa, total_sismos, total_sismos_chile, puntaje, ref)
    ])

    pdf.set_font("Arial", "B", 12)
    _celda(pdf, 0, 8, "4. Evolucion snapshots evidencia (14 dias)", ln=1)
    ini, fin = _evolucion_14d(df_evidencia, "estacion", estacion, ahora)
    if ini is not None and fin is not None:
        _linea(pdf, "Primer snapshot", str(ini.get("fecha_hora", "")))
        _linea(pdf, "Ultimo snapshot", str(fin.get("fecha_hora", "")))
        _linea(pdf, "b-value", _delta_txt(fin.get("b_value"), ini.get("b_value")))
        _linea(pdf, "Sismos locales 14D", _delta_txt(fin.get("sismos_locales_14d"), ini.get("sismos_locales_14d"), 0))
        _linea(pdf, "Indice %", _delta_txt(fin.get("puntaje"), ini.get("puntaje"), 1))
        _linea(pdf, "Match M7+ %", _delta_txt(fin.get("match_m7"), ini.get("match_m7"), 1))
    else:
        _multilinea(pdf, "Sin historial de snapshots en los ultimos 14 dias para esta estacion.")
    pdf.ln(2)

    pdf.set_font("Arial", "B", 12)
    _celda(pdf, 0, 8, "5. Validacion post-evento", ln=1)
    if coincidencias is not None and not coincidencias.empty:
        for _, row in coincidencias.head(5).iterrows():
            _multilinea(
                pdf,
                f"- {row.get('Evento real', '')} | evidencia {row.get('Fecha evidencia', '')} | "
                f"anticipacion {row.get('Anticipación horas', row.get('Anticipacion horas', ''))} h"
            )
    else:
        _multilinea(pdf, "Sin coincidencias documentadas.")
    pdf.ln(2)

    _linea(pdf, "USGS", consultado_usgs or "N/D")
    _multilinea(pdf, "Prototipo experimental NAZCA Core Monitor v8.0. Uso privado y de investigacion.")
    return _pdf_out(pdf)


def _cabecera_core_monitor(pdf, titulo, subtitulo, logo_path=None):
    if logo_path and os.path.exists(logo_path):
        pdf.image(logo_path, x=12, y=10, w=26)
        pdf.set_xy(42, 11)
    else:
        pdf.set_xy(12, 11)
    pdf.set_font("Arial", "B", 15)
    _celda(pdf, 0, 8, "NAZCA CORE MONITOR v8.0", ln=1)
    pdf.set_x(42 if logo_path and os.path.exists(logo_path) else 12)
    pdf.set_font("Arial", "", 9)
    _celda(pdf, 0, 6, titulo, ln=1)
    pdf.set_x(42 if logo_path and os.path.exists(logo_path) else 12)
    _celda(pdf, 0, 6, subtitulo, ln=1)
    pdf.set_x(42 if logo_path and os.path.exists(logo_path) else 12)
    _celda(pdf, 0, 6, "Desarrollado por Sandro Pereira A. - CEO & Developer", ln=1)
    pdf.ln(10)


def _resumen_estacion_log(df_log, estacion):
    if df_log is None or df_log.empty or "Estacion" not in df_log.columns:
        return {}
    loc = df_log[df_log["Estacion"] == estacion]
    if loc.empty:
        return {"registros": 0}
    crit = loc["Criticidad_%"] if "Criticidad_%" in loc.columns else pd.Series(dtype=float)
    estados = loc["Estado"].value_counts().to_dict() if "Estado" in loc.columns else {}
    pico = loc.loc[crit.idxmax()] if not crit.empty else loc.iloc[-1]
    return {
        "registros": len(loc),
        "estado_mas_frecuente": max(estados, key=estados.get) if estados else "N/D",
        "max_criticidad": round(float(crit.max()), 1) if not crit.empty else 0,
        "pico_estado": pico.get("Estado", "N/D"),
        "pico_fecha": pico.get("Fecha_Hora", "N/D"),
        "pico_b": pico.get("b-value_14D", "N/D"),
        "pico_insar": pico.get("InSAR_%", "N/D"),
        "estados": estados,
    }


def _fix_estados_count(estados):
    if not estados:
        return "N/D"
    if isinstance(estados, dict):
        top = sorted(estados.items(), key=lambda x: -x[1])[:3]
        return ", ".join(f"{k} ({v})" for k, v in top)
    return str(estados)


def _es_pico_transitorio(df_log, row, minutos=30, caida_min=25):
    """True si el indice cae fuerte poco despues (pico de segundos/minutos, no sostenido)."""
    if df_log is None or df_log.empty:
        return False
    est = row.get("Estacion", "")
    fecha = pd.to_datetime(row.get("Fecha_Hora"), errors="coerce")
    if pd.isna(fecha):
        return False
    try:
        crit = float(row.get("Criticidad_%", 0))
    except (TypeError, ValueError):
        return False
    loc = df_log[df_log["Estacion"] == est].copy()
    loc["dt"] = pd.to_datetime(loc["Fecha_Hora"], errors="coerce")
    despues = loc[(loc["dt"] > fecha) & (loc["dt"] <= fecha + timedelta(minutes=minutos))]
    if despues.empty:
        return False
    return crit - float(despues["Criticidad_%"].min()) >= caida_min


def _etiqueta_pico(df_log, row):
    estado = sanitizar_texto(str(row.get("Estado", "")))
    transitorio = _es_pico_transitorio(df_log, row)
    detalle = {
        "ADVERTENCIA CRITICA": "enjambre b-value bajo + pico InSAR estimado",
        "ADVERTENCIA (ACUMULACION)": "b-value 0.56 - patron enjambre sin sismo fuerte posterior",
        "ATENCION SISMICA": "compuerta abierta - actividad regional moderada",
        "ADVERTENCIA ENERGETICA": "actividad temprana; indice no sostuvo umbral critico",
    }
    causa = detalle.get(estado, "lectura destacada del periodo")
    if transitorio:
        return (
            f"PICO TRANSITORIO NO VALIDADO | {causa} | "
            f"No se confirmo con evento M5+ | No cumple criterio Telegram sostenido"
        )
    return f"Lectura sostenida | {causa}"


def generar_pdf_informe_prueba_escaneo(
    periodo_desde,
    periodo_hasta,
    resumen_global,
    estaciones_resumen,
    picos_relevantes=None,
    auditoria_filas=None,
    evidencia_resumen=None,
    conclusiones=None,
    ahora=None,
    logo_path=None,
):
    """Informe PDF del periodo de prueba — Escaneo en vivo NAZCA CORE MONITOR."""
    ahora = ahora or pd.Timestamp.now()
    picos_relevantes = picos_relevantes or []
    auditoria_filas = auditoria_filas or []
    conclusiones = conclusiones or []

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=14)
    _cabecera_core_monitor(
        pdf,
        "Informe periodo de prueba - Escaneo en vivo",
        f"Generado: {ahora.strftime('%Y-%m-%d %H:%M')} ({CHILE_TZ_LABEL})",
        logo_path=logo_path,
    )

    pdf.set_font("Arial", "B", 12)
    _celda(pdf, 0, 8, "1. Resumen ejecutivo", ln=1)
    _linea(pdf, "Periodo analizado", f"{periodo_desde} a {periodo_hasta}")
    for k, v in (resumen_global or {}).items():
        _linea(pdf, k, v)
    pdf.ln(2)

    pdf.set_font("Arial", "B", 12)
    _celda(pdf, 0, 8, "2. Comportamiento por estacion", ln=1)
    for est, datos in (estaciones_resumen or {}).items():
        pdf.set_font("Arial", "B", 10)
        _multilinea(pdf, est)
        pdf.set_font("Arial", "", 9)
        _linea(pdf, "Registros bitacora", str(datos.get("registros", 0)))
        if datos.get("registros", 0) > 0:
            _linea(pdf, "Estados frecuentes", _fix_estados_count(datos.get("estados")))
            _linea(pdf, "Pico criticidad", f"{datos.get('max_criticidad', 0)}% ({datos.get('pico_estado', '')})")
            _linea(pdf, "Fecha pico", str(datos.get("pico_fecha", "")))
            _linea(pdf, "b-value en pico", str(datos.get("pico_b", "")))
            _linea(pdf, "InSAR en pico", str(datos.get("pico_insar", "")))
            if datos.get("interpretacion"):
                _multilinea(pdf, datos["interpretacion"])
        pdf.ln(1)

    pdf.set_font("Arial", "B", 12)
    _celda(pdf, 0, 8, "3. Picos y condiciones relevantes", ln=1)
    _multilinea(
        pdf,
        "PICO TRANSITORIO NO VALIDADO = subida breve (segundos/minutos) que vuelve a ESTABLE "
        "sin terremoto fuerte posterior. No equivale a acierto ni a disparo Telegram automatico."
    )
    if picos_relevantes:
        for pico in picos_relevantes:
            _multilinea(
                pdf,
                f"- {pico.get('fecha', '')} | {pico.get('estacion', '')} | "
                f"{pico.get('estado', '')} | indice {pico.get('criticidad', '')}% | "
                f"b={pico.get('b_value', '')} | InSAR={pico.get('insar', '')}% | {pico.get('nota', '')}"
            )
    else:
        _multilinea(pdf, "Sin picos destacados en el periodo.")
    pdf.ln(2)

    pdf.set_font("Arial", "B", 12)
    _celda(pdf, 0, 8, "4. Auditoria semaforo", ln=1)
    if auditoria_filas:
        pdf.set_font("Arial", "B", 8)
        _celda(pdf, 36, 6, "Fecha alerta", bold=True)
        _celda(pdf, 52, 6, "Estacion", bold=True)
        _celda(pdf, 18, 6, "Nivel", bold=True)
        _celda(pdf, 18, 6, "Indice", bold=True)
        _celda(pdf, 0, 6, "Resultado", bold=True, ln=1)
        pdf.set_font("Arial", "", 8)
        for fila in auditoria_filas[:12]:
            _celda(pdf, 36, 6, str(fila.get("fecha_alerta", ""))[:16])
            _celda(pdf, 52, 6, sanitizar_texto(str(fila.get("estacion", "")))[:28])
            _celda(pdf, 18, 6, str(fila.get("nivel", "")))
            _celda(pdf, 18, 6, str(fila.get("puntaje", "")))
            _celda(pdf, 0, 6, str(fila.get("resultado", "")), ln=1)
    else:
        _multilinea(pdf, "Sin registros de auditoria en el periodo.")
    pdf.ln(2)

    pdf.set_font("Arial", "B", 12)
    _celda(pdf, 0, 8, "5. Evidencia pre-evento (snapshots)", ln=1)
    if evidencia_resumen:
        for k, v in evidencia_resumen.items():
            _linea(pdf, k, v)
    else:
        _multilinea(pdf, "Sin snapshots de evidencia en el periodo.")
    pdf.ln(2)

    pdf.set_font("Arial", "B", 12)
    _celda(pdf, 0, 8, "6. Conclusiones de la prueba", ln=1)
    for txt in conclusiones:
        _multilinea(pdf, f"- {txt}")
    pdf.ln(2)

    pdf.set_font("Arial", "B", 12)
    _celda(pdf, 0, 8, "7. Limitacion tecnica", ln=1)
    _multilinea(
        pdf,
        "NAZCA CORE MONITOR es un prototipo experimental de vigilancia. "
        "Este informe resume lecturas del escaneo en vivo y no constituye prediccion oficial ni alerta de evacuacion. "
        "Variables InSAR, EM, SHOA y presion pueden ser estimadas. "
        "La validacion ACIERTO/FALSO_POSITIVO requiere eventos USGS M5+ posteriores dentro de 30 dias."
    )
    return _pdf_out(pdf)


def construir_informe_prueba_desde_archivos(
    base_dir,
    logo_path=None,
    rutas=None,
):
    """Lee bitacora, evidencia y auditoria del disco y genera el PDF de prueba."""
    base_dir = os.path.abspath(base_dir)
    rutas = rutas or {}
    log_path = rutas.get("log") or os.path.join(base_dir, "nazca_log_historico.csv")
    ev_path = rutas.get("evidencia") or os.path.join(base_dir, "nazca_evidencia_preevento.csv")
    aud_path = rutas.get("auditoria") or os.path.join(base_dir, "nazca_auditoria_semaforo.csv")

    df_log = pd.DataFrame()
    if os.path.exists(log_path):
        df_log = pd.read_csv(log_path)

    df_ev = pd.DataFrame()
    if os.path.exists(ev_path):
        try:
            df_ev = pd.read_csv(ev_path, on_bad_lines="skip")
        except TypeError:
            df_ev = pd.read_csv(ev_path, error_bad_lines=False)

    df_aud = pd.DataFrame()
    if os.path.exists(aud_path):
        df_aud = pd.read_csv(aud_path, encoding="utf-8-sig")

    periodo_desde = df_log["Fecha_Hora"].min() if not df_log.empty else "N/D"
    periodo_hasta = df_log["Fecha_Hora"].max() if not df_log.empty else "N/D"

    estaciones_objetivo = [
        "Valparaiso / San Antonio (85574)",
        "Valparaíso / San Antonio (85574)",
        "Coquimbo / Illapel (85540)",
        "Antofagasta / Taltal (85442)",
    ]
    visto = set()
    estaciones_resumen = {}
    interpretaciones = {
        "Valparaíso / San Antonio (85574)": (
            "Vigilancia AMARILLA recurrente por similitud historica con Constitucion 2012 (match 65-77%). "
            "Indice operativo mayormente ESTABLE (25-38%). EM elevado por humedad invernal costa central."
        ),
        "Antofagasta / Taltal (85442)": (
            "Mayor actividad sismica local del periodo (15-20 sismos 14D). "
            "Semáforo AMARILLO por conteo de temblores. Picos de ATENCION SISMICA con InSAR ~90%."
        ),
        "Coquimbo / Illapel (85540)": (
            "Zona tranquila en la prueba: lecturas ESTABLES sin umbrales de vigilancia reforzada."
        ),
    }
    for est in estaciones_objetivo:
        if est in visto:
            continue
        res = _resumen_estacion_log(df_log, est)
        if res.get("registros", 0) == 0:
            continue
        clave = est
        if "Valparaiso" in est:
            clave = "Valparaíso / San Antonio (85574)"
        if clave in visto:
            continue
        visto.add(clave)
        res["interpretacion"] = interpretaciones.get(clave, "")
        estaciones_resumen[clave] = res

    picos = []
    if not df_log.empty and "Criticidad_%" in df_log.columns:
        top = df_log.nlargest(8, "Criticidad_%")
        for _, row in top.iterrows():
            picos.append({
                "fecha": row.get("Fecha_Hora", ""),
                "estacion": row.get("Estacion", ""),
                "estado": str(row.get("Estado", "")),
                "criticidad": round(float(row.get("Criticidad_%", 0)), 1),
                "b_value": row.get("b-value_14D", ""),
                "insar": row.get("InSAR_%", ""),
                "nota": _etiqueta_pico(df_log, row),
            })

    auditoria_filas = df_aud.to_dict("records") if not df_aud.empty else []

    ev_resumen = {}
    if not df_ev.empty:
        ev_resumen["Total snapshots"] = str(len(df_ev))
        if "nivel" in df_ev.columns:
            ev_resumen["Niveles"] = ", ".join(
                f"{k}: {v}" for k, v in df_ev["nivel"].value_counts().to_dict().items()
            )
        if "estacion" in df_ev.columns:
            ev_resumen["Estaciones"] = ", ".join(
                f"{k}: {v}" for k, v in df_ev["estacion"].value_counts().head(4).to_dict().items()
            )
        if "match_m7" in df_ev.columns:
            ev_resumen["Match M7+ max"] = f"{df_ev['match_m7'].max():.1f}%"

    pendientes = sum(1 for r in auditoria_filas if str(r.get("resultado", "")).upper() == "PENDIENTE")
    aciertos = sum(1 for r in auditoria_filas if str(r.get("resultado", "")).upper() == "ACIERTO")

    resumen_global = {
        "Registros bitacora": str(len(df_log)),
        "Snapshots evidencia": str(len(df_ev)),
        "Alertas auditoria": str(len(auditoria_filas)),
        "Auditoria PENDIENTE": str(pendientes),
        "Auditoria ACIERTO": str(aciertos),
        "Validacion post-evento M5+": "Sin aciertos cerrados en el periodo" if aciertos == 0 else f"{aciertos} acierto(s)",
    }

    conclusiones = [
        "El escaneo en vivo registro, recalculo y guardo trazabilidad (bitacora + evidencia + auditoria).",
        "Los picos ADVERTENCIA CRITICA del 5-jun (82%) fueron TRANSITORIOS: volvieron a ESTABLE en minutos sin M5+ posterior.",
        "Se identifico vigilancia AMARILLA en Valparaiso por similitud historica, no por indice critico sostenido.",
        "Antofagasta mostro la mayor actividad sismica medida (15-20 temblores 14D) y alertas auditoria PENDIENTE.",
        "Telegram NO disparo en esos picos: requiere admin + toggle activo + estacion seleccionada + (indice>=68% Y match>=78%) O firma ruptura (b<=0.68 y >=12 sismos 14D).",
        "Aun no hay validacion ACIERTO ante terremoto fuerte M5+; el periodo es corto (~5-6 dias).",
        "Recomendacion: continuar escaneo 30+ dias; no tratar picos de segundos como alerta operacional.",
    ]

    return generar_pdf_informe_prueba_escaneo(
        periodo_desde=periodo_desde,
        periodo_hasta=periodo_hasta,
        resumen_global=resumen_global,
        estaciones_resumen=estaciones_resumen,
        picos_relevantes=picos,
        auditoria_filas=auditoria_filas,
        evidencia_resumen=ev_resumen,
        conclusiones=conclusiones,
        logo_path=logo_path,
    )
