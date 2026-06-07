# NAZCA Neural Detector

Prototipo experimental de vigilancia sismica para pruebas privadas e investigacion personal.

## Alcance

Este sistema no emite alertas oficiales ni predice terremotos. Integra datos sismicos, cache local, comparativas M7+, niveles de vigilancia experimental, PDF tecnico y notificaciones Telegram para pruebas internas.

## Estado actual

Version web operativa en Streamlit Cloud con registro privado de suscriptores Telegram, mapa nativo estable para navegador/celular y cache de APIs pensado para evitar llamadas excesivas.

## Politica de actualizacion de datos

La ventana de analisis se mantiene movil sobre los ultimos 14 dias disponibles. USGS/NOAA se consultan mediante cache, con 6 horas como intervalo recomendado por defecto para uso publico, y boton manual para refresco controlado.

## Ejecucion local

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Variables privadas

Configurar en Streamlit Secrets o `.streamlit/secrets.toml` local:

```toml
TELEGRAM_TOKEN = "..."
TELEGRAM_CHAT_ID = "..."
```

No subir secrets a GitHub.
