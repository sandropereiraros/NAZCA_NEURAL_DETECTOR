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


def _preparar_etiquetas_sismos(df_sismos, max_etiquetas=12, df_fuente=None):
    sismos = _preparar_sismos(df_fuente if df_fuente is not None else df_sismos)
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
            df_sismos, max_etiquetas=max_etiquetas, df_fuente=df_etiquetas or df_sismos,
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
        "🟠 Cinturón de Fuego del Pacífico · "
        "🔴 M6.0+ · 🟡 M4.5–5.9 · 🟢 M<4.5 · "
        "Tooltip USGS: magnitud + lugar + fecha · "
        "🔵 Nodo/estación activa"
    )
