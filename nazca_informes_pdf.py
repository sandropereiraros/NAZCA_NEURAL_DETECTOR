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
    return pd.DataFrame(filas_comparativa_mundo(res, ref_evento))


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
    return pd.DataFrame(filas_comparativa_chile(b_val, insar, cond, shoa, total_sismos, total_sismos_chile, puntaje, ref))


def html_vista_previa_pdf(pdf_bytes, alto=500):
    import base64
    b64 = base64.b64encode(pdf_bytes).decode("ascii")
    return (
        f'<iframe src="data:application/pdf;base64,{b64}" '
        f'width="100%" height="{alto}" style="border:1px solid #334155;border-radius:8px;"></iframe>'
    )


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
