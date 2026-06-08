"""
Mapa sísmico con línea de fuego / límites de placas (simplificados) + sismos USGS.
Usa pydeck; si no está disponible, hace fallback a st.map sin líneas tectónicas.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

# Segmentos simplificados del Anillo de Fuego y zonas de subducción/colisión activas.
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
        "nombre": "Nueva Zelanda · Tonga",
        "tipo": "subduccion",
        "path": [
            [176, -18], [178, -22], [179, -26], [-178, -30],
            [-175, -34], [-178, -38], [177, -42], [175, -46],
        ],
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
    {
        "nombre": "Mediterráneo · Egeo",
        "tipo": "colision",
        "path": [
            [25, 38], [27, 37], [29, 36], [31, 35], [33, 34],
        ],
    },
    {
        "nombre": "Himalaya · colisión",
        "tipo": "colision",
        "path": [
            [70, 28], [74, 29], [78, 30], [82, 31], [86, 32], [90, 33],
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


def _preparar_sismos(df_sismos):
    if df_sismos is None or df_sismos.empty:
        return pd.DataFrame(columns=["lon", "lat", "mag", "radio", "color_rgb", "lugar"])
    df = df_sismos.copy()
    if "Latitud" in df.columns:
        df = df.rename(columns={"Latitud": "lat", "Longitud": "lon", "Magnitud": "mag", "Lugar": "lugar"})
    df["mag"] = pd.to_numeric(df.get("mag", 4.0), errors="coerce").fillna(4.0)
    df["radio"] = (df["mag"].clip(lower=2.5) ** 2) * 1800
    df["color_rgb"] = df["mag"].apply(
        lambda m: [239, 68, 68, 210] if m >= 6.0 else ([250, 204, 21, 200] if m >= 4.5 else [148, 163, 184, 180])
    )
    df["label"] = "Sismo USGS"
    if "lugar" not in df.columns:
        df["lugar"] = ""
    return df[["lon", "lat", "mag", "radio", "color_rgb", "lugar", "label"]].dropna(subset=["lon", "lat"])


def _paths_tectonicos(segmentos=None):
    segmentos = segmentos or ANILLO_DE_FUEGO
    filas = []
    for seg in segmentos:
        filas.append({
            "nombre": seg["nombre"],
            "tipo": seg.get("tipo", "subduccion"),
            "path": seg["path"],
            "color": COLOR_TECTONICA.get(seg.get("tipo", "subduccion"), COLOR_TECTONICA["subduccion"]),
            "ancho": 4 if seg.get("tipo") == "subduccion" else 3,
        })
    return filas


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
):
    estacion_color_rgb = estacion_color_rgb or [59, 130, 246, 255]
    sismos = _preparar_sismos(df_sismos)

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
            pickable=True,
            auto_highlight=True,
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
            "html": "<b>{label}</b><br/>Mag: {mag}<br/>{lugar}",
            "style": {"backgroundColor": "#161b22", "color": "#c9d1d9"},
        },
    )

    st.pydeck_chart(deck, height=altura, use_container_width=True)
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
    if filas:
        st.map(pd.DataFrame(filas), latitude="lat", longitude="lon", size="size", color="color", zoom=zoom)
    else:
        st.caption("Sin datos para mapa.")
    st.caption("Instala pydeck para ver la línea de fuego tectónica en el mapa.")
    return False


def leyenda_mapa_tectonico():
    return (
        "🟠 Líneas naranjas: subducción (Anillo de Fuego) · "
        "🟡 Amarillo: colisión · 🔴 Sismos USGS M6+ · 🟡 M4.5–5.9 · "
        "🔵 Punto grande: estación/nodo activo"
    )
