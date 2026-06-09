"""
Mapa sísmico con línea de fuego / límites de placas (simplificados) + sismos USGS.
Usa pydeck; si no está disponible, hace fallback a st.map sin líneas tectónicas.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

# Cinturón de Fuego del Pacífico (solo subducción pacífica; sin Mediterráneo ni Himalaya).
# Formato: lista de [lon, lat] por tramo.
ANILLO_DE_FUEGO = [
    {
        "nombre": "Aleutianas · Alaska",
        "tipo": "subduccion",
        "path": [
            [-175, 51], [-170, 53], [-165, 55], [-160, 57], [-155, 59],
            [-150, 60], [-145, 61], [-140, 60], [-135, 58],
        ],
    },
    {
        "nombre": "Kamchatka · Japón",
        "tipo": "subduccion",
        "path": [
            [155, 52], [152, 48], [148, 44], [145, 41], [143, 39],
            [141, 37], [139, 35], [137, 33],
        ],
    },
    {
        "nombre": "Filipinas · Indonesia",
        "tipo": "subduccion",
        "path": [
            [126, 8], [124, 5], [122, 2], [119, -1], [116, -4],
            [112, -7], [108, -9], [104, -11], [100, -13], [96, -15],
        ],
    },
    {
        "nombre": "Nueva Zelanda · Tonga (norte)",
        "tipo": "subduccion",
        "path": [[176, -18], [178, -22], [179, -26]],
    },
    {
        "nombre": "Nueva Zelanda · Tonga (sur)",
        "tipo": "subduccion",
        "path": [[-178, -30], [-176, -34], [-174, -38], [-172, -42], [-170, -46]],
    },
    {
        "nombre": "Andes · Chile · Perú",
        "tipo": "subduccion",
        "path": [
            [-81, -4], [-79, -8], [-77, -12], [-76, -16], [-75, -20],
            [-74, -24], [-73, -28], [-72, -32], [-71, -36], [-72, -40],
            [-73, -44], [-74, -48], [-75, -52], [-74, -56],
        ],
    },
    {
        "nombre": "Centroamérica · México",
        "tipo": "subduccion",
        "path": [
            [-108, 16], [-105, 13], [-102, 10], [-98, 7], [-94, 4],
            [-90, 1], [-87, -2], [-84, -5],
        ],
    },
    {
        "nombre": "Pacífico NW · EE.UU.",
        "tipo": "subduccion",
        "path": [
            [-132, 54], [-128, 50], [-125, 46], [-122, 42], [-120, 38],
            [-118, 34], [-115, 30], [-112, 26],
        ],
    },
]

COLOR_TECTONICA = {
    "subduccion": [255, 90, 40, 210],
    "colision": [255, 200, 60, 210],
    "transformante": [120, 200, 255, 210],
    "divergente": [80, 255, 160, 210],
    "complejo": [200, 120, 255, 210],
}


def _acortar_lugar(lugar, max_len=34):
    if not lugar:
        return "Sin lugar"
    txt = str(lugar).strip()
    bajo = txt.lower()
    if " of " in bajo:
        txt = txt.split(" of ", 1)[-1]
    txt = txt.split(",")[0].strip()
    if len(txt) > max_len:
        txt = txt[: max_len - 1] + "…"
    return txt


COLOR_MAG_ALTA = [239, 68, 68, 210]      # 🔴 M6.0+
COLOR_MAG_MEDIA = [250, 204, 21, 200]    # 🟡 M4.5–5.9
COLOR_MAG_BAJA = [74, 222, 128, 210]     # 🟢 M<4.5 — criterio verde Chile


def pydeck_chart_compat(deck, altura=430):
    """pydeck sin key — versiones antiguas de Streamlit no aceptan key en st.map/pydeck."""
    st.pydeck_chart(deck, height=altura, use_container_width=True)


def st_map_minimo(puntos, zoom=None, max_puntos=80, usar_color=False):
    """Mapa nativo Streamlit; con usar_color=True pinta círculos de tensión."""
    if not puntos:
        st.caption("Sin datos para mapa.")
        return
    df = pd.DataFrame(puntos).dropna(subset=["lat", "lon"])
    if df.empty:
        st.caption("Sin datos para mapa.")
        return
    if len(df) > max_puntos:
        df = df.head(max_puntos)
    tiene_color = usar_color and "color" in df.columns
    tiene_size = usar_color and "size" in df.columns
    try:
        kwargs = {"latitude": "lat", "longitude": "lon"}
        if zoom is not None:
            kwargs["zoom"] = zoom
        if tiene_color:
            kwargs["color"] = "color"
        if tiene_size:
            kwargs["size"] = "size"
        st.map(df, **kwargs)
    except TypeError:
        st.map(df, latitude="lat", longitude="lon", zoom=zoom) if zoom else st.map(df, latitude="lat", longitude="lon")


def color_tension_rgb(pct):
    """Verde → amarillo → naranjo → rojo según tensión acumulada (0–100)."""
    p = max(0.0, min(float(pct or 0), 100.0))
    if p >= 85:
        return [239, 68, 68, 200]
    if p >= 70:
        return [249, 115, 22, 195]
    if p >= 50:
        return [250, 204, 21, 190]
    if p >= 30:
        return [163, 230, 53, 175]
    return [34, 197, 94, 160]


def color_tension_hex(pct):
    r, g, b, _ = color_tension_rgb(pct)
    return f"#{r:02x}{g:02x}{b:02x}"


def _calcular_b_value_celda(mags):
    import numpy as np

    if len(mags) < 8:
        return None
    arr = np.asarray(mags, dtype=float)
    mc = arr.min()
    filtrado = arr[arr >= mc]
    if len(filtrado) == 0:
        return None
    b = (1.0 / (np.mean(filtrado) - mc)) * 0.4343
    return round(max(0.4, min(float(b), 2.0)), 2)


def _indice_tension_celda(n_sismos, mags, b_local=None):
    """Índice 0–100: densidad de sismos + energía acumulada + b-value bajo."""
    if n_sismos <= 0:
        return 0.0
    dens = min(n_sismos / 12.0, 1.0) * 100.0
    energia = sum(10 ** (1.5 * float(m)) for m in mags)
    ener = min(energia / 400.0, 1.0) * 100.0
    if b_local is None:
        b_part = min(n_sismos / 20.0, 1.0) * 55.0
    elif b_local <= 0.65:
        b_part = 100.0
    elif b_local <= 0.75:
        b_part = 75.0
    elif b_local <= 0.90:
        b_part = 45.0
    else:
        b_part = 20.0
    return round(min(0.45 * dens + 0.35 * b_part + 0.20 * ener, 100.0), 1)


def _detectar_anomalias_nodo(fila):
    flags = []
    if float(fila.get("b-value 14D", 1.0)) < 0.75:
        flags.append("b-value bajo")
    if float(fila.get("EM Z-score", 0)) > 1.2:
        flags.append("EM elevado")
    if float(fila.get("Riesgo %", 0)) >= 75:
        flags.append("riesgo alto")
    if float(fila.get("Match patrón %", 0)) >= 75:
        flags.append("patrón M7+")
    if int(fila.get("Sismos 14D Chile", 0)) >= 20:
        flags.append("enjambre 14D")
    return flags


def preparar_nodos_tension(df_calibracion, estaciones_config):
    """Nodos CORE NETWORK con tensión del modelo (no epicentros históricos)."""
    if df_calibracion is None or df_calibracion.empty:
        return pd.DataFrame()
    filas = []
    for _, row in df_calibracion.iterrows():
        est = row.get("Estación", "")
        cfg = estaciones_config.get(est)
        if not cfg:
            continue
        anom = _detectar_anomalias_nodo(row)
        filas.append({
            "lat": cfg["lat"],
            "lon": cfg["lon"],
            "zona": est.split("(")[0].strip(),
            "tension_pct": float(row.get("Riesgo %", 0)),
            "b_value": float(row.get("b-value 14D", 1.0)),
            "sismos_14d": int(row.get("Sismos 14D Chile", 0)),
            "match_m7": float(row.get("Match patrón %", 0)),
            "estado": row.get("Estado", ""),
            "anomalias": ", ".join(anom) if anom else "Parámetros normales",
            "tipo": "nodo",
        })
    return pd.DataFrame(filas)


def construir_malla_tension(
    df_sismos,
    lat_min=-56.0,
    lat_max=-17.0,
    lon_min=-76.5,
    lon_max=-66.0,
    paso=1.0,
    max_celdas=40,
):
    """Cuadrícula Chile: acumulación de tensión por celda (ventana 14D USGS)."""
    sismos = _preparar_sismos(df_sismos)
    if sismos.empty:
        return pd.DataFrame()
    celdas = {}
    for _, row in sismos.iterrows():
        lat, lon, mag = float(row["lat"]), float(row["lon"]), float(row["mag"])
        if not (lat_min <= lat <= lat_max and lon_min <= lon <= lon_max):
            continue
        clat = round((lat - lat_min) / paso) * paso + lat_min
        clon = round((lon - lon_min) / paso) * paso + lon_min
        key = (round(clat, 2), round(clon, 2))
        celdas.setdefault(key, []).append(mag)

    filas = []
    for (clat, clon), mags in celdas.items():
        n = len(mags)
        b_local = _calcular_b_value_celda(mags)
        tension = _indice_tension_celda(n, mags, b_local)
        anom = []
        if b_local is not None and b_local < 0.75:
            anom.append("b-value bajo")
        if n >= 15:
            anom.append("alta densidad")
        if max(mags) >= 5.5:
            anom.append("M>=5.5")
        filas.append({
            "lat": clat,
            "lon": clon,
            "zona": f"Celda {clat:.1f}°, {clon:.1f}°",
            "tension_pct": tension,
            "b_value": b_local if b_local is not None else "—",
            "sismos_14d": n,
            "mag_max": round(max(mags), 1),
            "mag_prom": round(sum(mags) / n, 1),
            "anomalias": ", ".join(anom) if anom else "Normal",
            "tipo": "celda",
        })
    if not filas:
        return pd.DataFrame()
    df = pd.DataFrame(filas).sort_values("tension_pct", ascending=False).head(max_celdas)
    return df.reset_index(drop=True)


def _capas_mapa_tension(df_malla, df_nodos, estacion_lat, estacion_lon, estacion_label):
    """Prepara filas para st.map (color/size) o capas pydeck."""
    puntos = []
    if df_malla is not None and not df_malla.empty:
        for _, r in df_malla.iterrows():
            pct = float(r["tension_pct"])
            puntos.append({
                "lat": r["lat"],
                "lon": r["lon"],
                "color": color_tension_hex(pct),
                "color_rgb": color_tension_rgb(pct),
                "size": 1200 + pct * 35,
                "radio": 18000 + pct * 900,
                "tension_pct": pct,
                "zona": r["zona"],
                "anomalias": r["anomalias"],
                "tipo": "celda",
                "tooltip": (
                    f"Tensión {pct:.0f}% · {r['sismos_14d']} sismos · "
                    f"Mmax {r['mag_max']} · {r['anomalias']}"
                ),
            })
    if df_nodos is not None and not df_nodos.empty:
        for _, r in df_nodos.iterrows():
            pct = float(r["tension_pct"])
            puntos.append({
                "lat": r["lat"],
                "lon": r["lon"],
                "color": color_tension_hex(pct),
                "color_rgb": color_tension_rgb(pct),
                "size": 2200 + pct * 18,
                "radio": 42000 + pct * 500,
                "tension_pct": pct,
                "zona": r["zona"],
                "anomalias": r["anomalias"],
                "tipo": "nodo",
                "tooltip": (
                    f"Nodo {r['zona']} · Tensión {pct:.0f}% · b={r['b_value']} · {r['anomalias']}"
                ),
            })
    if estacion_lat is not None and estacion_lon is not None:
        puntos.append({
            "lat": estacion_lat,
            "lon": estacion_lon,
            "color": "#3b82f6",
            "color_rgb": [59, 130, 246, 255],
            "size": 2800,
            "radio": 32000,
            "tension_pct": 0,
            "zona": estacion_label,
            "anomalias": "Estación activa",
            "tipo": "activa",
            "tooltip": f"Estación activa: {estacion_label}",
        })
    return puntos


def tabla_resumen_tension(df_malla, df_nodos):
    partes = []
    if df_nodos is not None and not df_nodos.empty:
        n = df_nodos.copy()
        n["Origen"] = "Nodo CORE"
        partes.append(n)
    if df_malla is not None and not df_malla.empty:
        c = df_malla.copy()
        c["Origen"] = "Celda regional"
        partes.append(c)
    if not partes:
        return pd.DataFrame()
    df = pd.concat(partes, ignore_index=True)
    cols = ["Origen", "zona", "tension_pct", "sismos_14d", "b_value", "anomalias"]
    extra = [c for c in ("mag_max", "mag_prom", "match_m7", "estado") if c in df.columns]
    return df[cols + extra].sort_values("tension_pct", ascending=False)


def render_mapa_tension(
    df_sismos=None,
    df_calibracion=None,
    estaciones_config=None,
    estacion_lat=None,
    estacion_lon=None,
    estacion_label="Estación",
    lat_center=None,
    lon_center=None,
    zoom=4,
    altura=400,
    mostrar_anillo=True,
    segmentos_tectonicos=None,
    mapa_nativo=False,
    paso_malla=1.0,
):
    """Mapa de tensión acumulada (círculos). Los sismos van en tablas, no como puntos del mapa."""
    mapa_nativo = _forzar_mapa_nativo_por_defecto(mapa_nativo)
    estaciones_config = estaciones_config or {}
    df_nodos = preparar_nodos_tension(df_calibracion, estaciones_config)
    df_malla = construir_malla_tension(df_sismos, paso=paso_malla)
    puntos = _capas_mapa_tension(df_malla, df_nodos, estacion_lat, estacion_lon, estacion_label)

    if lat_center is None or lon_center is None:
        if estacion_lat is not None and estacion_lon is not None:
            lat_center, lon_center = estacion_lat, estacion_lon
        elif puntos:
            lat_center = sum(p["lat"] for p in puntos) / len(puntos)
            lon_center = sum(p["lon"] for p in puntos) / len(puntos)
        else:
            lat_center, lon_center = -35.0, -71.0

    if not puntos:
        st.caption("Sin datos de tensión para el mapa.")
        return tabla_resumen_tension(df_malla, df_nodos), False

    if mapa_nativo:
        st_map_minimo(puntos, zoom=zoom, max_puntos=60, usar_color=True)
        st.caption("Mapa de tensión — círculos por acumulación sísmica (14D). Sismos en tabla lateral.")
        return tabla_resumen_tension(df_malla, df_nodos), False

    try:
        import pydeck as pdk
    except ImportError:
        st_map_minimo(puntos, zoom=zoom, max_puntos=60, usar_color=True)
        return tabla_resumen_tension(df_malla, df_nodos), False

    capas = []
    if mostrar_anillo:
        paths = _paths_tectonicos(segmentos_tectonicos)
        capas.append(pdk.Layer(
            "PathLayer",
            data=paths,
            get_path="path",
            get_color="color",
            get_width="ancho",
            width_min_pixels=2,
            pickable=False,
        ))

    df_plot = pd.DataFrame(puntos)
    capas.append(pdk.Layer(
        "ScatterplotLayer",
        data=df_plot,
        get_position=["lon", "lat"],
        get_radius="radio",
        get_fill_color="color_rgb",
        pickable=True,
        opacity=0.72,
        stroked=True,
        get_line_color=[255, 255, 255, 90],
        line_width_min_pixels=1,
    ))

    deck = pdk.Deck(
        layers=capas,
        initial_view_state=pdk.ViewState(
            latitude=lat_center,
            longitude=lon_center,
            zoom=zoom,
            pitch=0,
        ),
        map_style=None,
        tooltip={
            "html": "<b>{zona}</b><br/>{tooltip}",
            "style": {"backgroundColor": "#161b22", "color": "#e6edf3"},
        },
    )
    pydeck_chart_compat(deck, altura=altura)
    return tabla_resumen_tension(df_malla, df_nodos), True


def leyenda_mapa_tension():
    return (
        "Mapa de tensión acumulada (14D) · "
        "🟢 baja · 🟡 media · 🟠 alta · 🔴 crítica · "
        "Círculos grandes = nodos CORE · pequeños = celdas · "
        "🔵 estación activa · Sismos USGS en tabla"
    )


def color_por_magnitud(mag):
    m = float(mag or 0)
    if m >= 6.0:
        return COLOR_MAG_ALTA
    if m >= 4.5:
        return COLOR_MAG_MEDIA
    return COLOR_MAG_BAJA


def _preparar_sismos(df_sismos):
    if df_sismos is None or df_sismos.empty:
        return pd.DataFrame(columns=["lon", "lat", "mag", "radio", "color_rgb", "lugar", "fecha", "label"])
    df = df_sismos.copy()
    if "Latitud" in df.columns:
        df = df.rename(columns={"Latitud": "lat", "Longitud": "lon", "Magnitud": "mag", "Lugar": "lugar"})
    df["mag"] = pd.to_numeric(df.get("mag", 4.0), errors="coerce").fillna(4.0)
    df["radio"] = (df["mag"].clip(lower=2.5) ** 2) * 1800
    df["color_rgb"] = df["mag"].apply(color_por_magnitud)
    df["label"] = "Sismo USGS"
    if "lugar" not in df.columns:
        df["lugar"] = ""
    if "fecha" not in df.columns:
        df["fecha"] = df["Fecha"] if "Fecha" in df.columns else ""
    return df[["lon", "lat", "mag", "radio", "color_rgb", "lugar", "fecha", "label"]].dropna(subset=["lon", "lat"])


def _fuente_etiquetas(df_etiquetas, df_sismos):
    """Evita 'df_a or df_b' — pandas no permite evaluar DataFrames como booleano."""
    if df_etiquetas is not None and not df_etiquetas.empty:
        return df_etiquetas
    return df_sismos


def _preparar_etiquetas_sismos(df_sismos, max_etiquetas=12, df_fuente=None):
    sismos = _preparar_sismos(_fuente_etiquetas(df_fuente, df_sismos))
    if sismos.empty:
        return pd.DataFrame(columns=["lon", "lat", "etiqueta", "mag", "lugar", "fecha", "label"])
    orden = sismos.copy()
    if "fecha" in orden.columns and orden["fecha"].astype(str).str.strip().ne("").any():
        orden["_orden"] = pd.to_datetime(orden["fecha"], errors="coerce")
        orden = orden.sort_values("_orden", ascending=False, na_position="last")
    else:
        orden = orden.sort_values("mag", ascending=False)
    orden = orden.head(max_etiquetas)
    orden["etiqueta"] = orden.apply(
        lambda r: f"M{r['mag']:.1f} · {_acortar_lugar(r.get('lugar', ''))}", axis=1
    )
    orden["label"] = "Sismo reciente"
    return orden[["lon", "lat", "etiqueta", "mag", "lugar", "fecha", "label"]]


def _cruza_antimeridiano(lon1, lon2):
    return (lon1 > 90 and lon2 < -90) or (lon1 < -90 and lon2 > 90) or abs(lon2 - lon1) > 120


def _dividir_path_antimeridiano(path):
    if len(path) < 2:
        return [path]
    tramos, tramo = [], [list(path[0])]
    for lon2, lat2 in path[1:]:
        lon1 = tramo[-1][0]
        if _cruza_antimeridiano(lon1, lon2):
            if len(tramo) >= 2:
                tramos.append(tramo)
            tramo = [[lon2, lat2]]
        else:
            tramo.append([lon2, lat2])
    if len(tramo) >= 2:
        tramos.append(tramo)
    return tramos if tramos else [path]


def _paths_tectonicos(segmentos=None):
    segmentos = segmentos or ANILLO_DE_FUEGO
    filas = []
    for seg in segmentos:
        color = COLOR_TECTONICA.get(seg.get("tipo", "subduccion"), COLOR_TECTONICA["subduccion"])
        ancho = 4 if seg.get("tipo") == "subduccion" else 3
        for tramo in _dividir_path_antimeridiano(seg["path"]):
            filas.append({
                "nombre": seg["nombre"],
                "tipo": seg.get("tipo", "subduccion"),
                "path": tramo,
                "color": color,
                "ancho": ancho,
            })
    return filas


def _forzar_mapa_nativo_por_defecto(mapa_nativo):
    import os
    env = os.environ.get("STREAMLIT_RUNTIME_ENV", "").lower()
    en_cloud = env in ("cloud", "community", "production") or bool(os.environ.get("STREAMLIT_SHARING"))
    if os.environ.get("NAZCA_USAR_PYDECK", "").strip() == "1" and not en_cloud:
        return mapa_nativo
    return True


def render_mapa_tectonico(
    df_sismos=None,
    estacion_lat=None,
    estacion_lon=None,
    estacion_label="Estación",
    estacion_color_rgb=None,
    lat_center=None,
    lon_center=None,
    zoom=3,
    altura=430,
    mostrar_anillo=True,
    segmentos_tectonicos=None,
    mostrar_etiquetas=True,
    max_etiquetas=12,
    df_etiquetas=None,
    mapa_nativo=False,
):
    mapa_nativo = _forzar_mapa_nativo_por_defecto(mapa_nativo)
    estacion_color_rgb = estacion_color_rgb or [59, 130, 246, 255]
    sismos = _preparar_sismos(df_sismos)

    if mapa_nativo:
        _fallback_st_map(sismos, estacion_lat, estacion_lon, estacion_color_rgb, zoom)
        st.caption("Mapa nativo Streamlit — estable en navegador y Streamlit Cloud.")
        return False

    if lat_center is None or lon_center is None:
        if estacion_lat is not None and estacion_lon is not None:
            lat_center, lon_center = estacion_lat, estacion_lon
        elif not sismos.empty:
            lat_center, lon_center = float(sismos["lat"].mean()), float(sismos["lon"].mean())
        else:
            lat_center, lon_center = -20.0, -70.0

    try:
        import pydeck as pdk
    except ImportError:
        return _fallback_st_map(sismos, estacion_lat, estacion_lon, estacion_color_rgb, zoom)

    capas = []

    if mostrar_anillo:
        paths = _paths_tectonicos(segmentos_tectonicos)
        capas.append(pdk.Layer(
            "PathLayer",
            data=paths,
            get_path="path",
            get_color="color",
            get_width="ancho",
            width_min_pixels=2,
            pickable=False,
            auto_highlight=False,
        ))

    if not sismos.empty:
        capas.append(pdk.Layer(
            "ScatterplotLayer",
            data=sismos,
            get_position=["lon", "lat"],
            get_radius="radio",
            get_fill_color="color_rgb",
            pickable=True,
            opacity=0.82,
            stroked=True,
            get_line_color=[255, 255, 255, 80],
            line_width_min_pixels=1,
        ))

    if mostrar_etiquetas:
        etiquetas = _preparar_etiquetas_sismos(
            df_sismos, max_etiquetas=max_etiquetas, df_fuente=df_etiquetas,
        )
        if not etiquetas.empty:
            capas.append(pdk.Layer(
                "TextLayer",
                data=etiquetas,
                get_position=["lon", "lat"],
                get_text="etiqueta",
                get_size=13,
                get_color=[235, 235, 245, 240],
                get_angle=0,
                get_text_anchor="start",
                get_alignment_baseline="bottom",
                get_pixel_offset=[10, -12],
                pickable=True,
            ))

    if estacion_lat is not None and estacion_lon is not None:
        capas.append(pdk.Layer(
            "ScatterplotLayer",
            data=pd.DataFrame([{
                "lon": estacion_lon,
                "lat": estacion_lat,
                "label": estacion_label,
                "mag": "",
                "lugar": "Nodo / estación activa",
                "radio": 28000,
                "color": estacion_color_rgb,
            }]),
            get_position=["lon", "lat"],
            get_radius="radio",
            get_fill_color="color",
            pickable=True,
            opacity=0.95,
            stroked=True,
            get_line_color=[255, 255, 255, 220],
            line_width_min_pixels=2,
        ))

    deck = pdk.Deck(
        layers=capas,
        initial_view_state=pdk.ViewState(
            latitude=lat_center,
            longitude=lon_center,
            zoom=zoom,
            pitch=0,
            bearing=0,
        ),
        # None = Streamlit elige basemap Carto válido (light/dark según tema).
        # La URL raster dark_all/{z}/{x}/{y}.png no carga en pydeck → fondo negro.
        map_style=None,
        tooltip={
            "html": "<b>Sismo USGS</b><br/>Magnitud: <b>M{mag}</b><br/>{lugar}<br/>{fecha}",
            "style": {"backgroundColor": "#161b22", "color": "#c9d1d9"},
        },
    )

    pydeck_chart_compat(deck, altura=altura)
    return True


def _fallback_st_map(sismos, estacion_lat, estacion_lon, estacion_color_rgb, zoom):
    filas = []
    if estacion_lat is not None and estacion_lon is not None:
        r, g, b, _ = estacion_color_rgb
        filas.append({
            "lat": estacion_lat, "lon": estacion_lon,
            "size": 200, "color": f"#{r:02x}{g:02x}{b:02x}",
        })
    if not sismos.empty:
        for _, row in sismos.iterrows():
            r, g, b, _ = row["color_rgb"]
            filas.append({
                "lat": row["lat"], "lon": row["lon"],
                "size": max(30, row["mag"] ** 2 * 10),
                "color": f"#{r:02x}{g:02x}{b:02x}",
            })
    st_map_minimo(filas, zoom=zoom)
    st.caption("Mapa simplificado (lat/lon) — estable en navegador y Streamlit Cloud.")
    return False


def leyenda_mapa_tectonico():
    return leyenda_mapa_tension()
