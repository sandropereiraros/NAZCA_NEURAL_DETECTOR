# NAZCA Neural Detector

Prototipo experimental de vigilancia sismica para pruebas privadas e investigacion personal.

## Alcance

Este sistema no emite alertas oficiales ni predice terremotos. Integra datos sismicos, cache local, comparativas M7+, niveles de vigilancia experimental, PDF tecnico y notificaciones Telegram para pruebas internas.

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
