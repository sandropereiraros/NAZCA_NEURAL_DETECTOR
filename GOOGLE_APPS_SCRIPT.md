# Suscriptores Telegram con Google Apps Script

Esta integracion permite que los registros hechos desde la web queden persistentes en una Google Sheet privada.

## 1. Crear Google Sheet

1. Crea una hoja de calculo en Google Drive.
2. Nombra el archivo, por ejemplo: `NAZCA suscriptores Telegram`.
3. Abre `Extensiones > Apps Script`.

## 2. Copiar codigo

1. Copia el contenido de `scripts/google_apps_script_subscribers.gs`.
2. Pegalo en `Code.gs` dentro de Apps Script.
3. Guarda el proyecto.

## 3. Configurar clave privada

En Apps Script:

1. Abre `Project Settings`.
2. En `Script properties`, agrega:

```text
SUBSCRIBERS_API_KEY = una_clave_larga_privada
```

Usa una clave larga, por ejemplo una frase aleatoria. No la subas a GitHub.

## 4. Desplegar como Web App

1. Presiona `Deploy > New deployment`.
2. Tipo: `Web app`.
3. Execute as: `Me`.
4. Who has access: `Anyone`.
5. Deploy.
6. Copia la URL de la Web App.

La seguridad la entrega `SUBSCRIBERS_API_KEY`; sin esa clave la Web App rechaza solicitudes.

## 5. Configurar Streamlit Secrets

En Streamlit Cloud, abre `Manage app > Settings > Secrets` y agrega:

```toml
SUBSCRIBERS_WEBAPP_URL = "https://script.google.com/macros/s/XXXXX/exec"
SUBSCRIBERS_API_KEY = "la_misma_clave_larga_privada"
```

Mantén tambien:

```toml
TELEGRAM_TOKEN = "token_del_bot"
TELEGRAM_CHAT_ID = "chat_id_principal"
```

## 6. Probar

1. Haz `Reboot app` en Streamlit Cloud.
2. Entra a la pestaña `Suscripcion gratuita Telegram`.
3. Registra un suscriptor.
4. Verifica que aparezca en la Google Sheet.
5. Usa `Enviar prueba a todos los suscriptores activos`.

## Nota de privacidad

La app no muestra nombres ni Chat IDs publicamente. La Google Sheet queda en tu cuenta privada de Google y solo la Web App autorizada escribe/lee usando la clave privada.
