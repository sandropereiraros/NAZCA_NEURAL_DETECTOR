# NAZCA EEW API

API REST de **Alerta Sísmica Temprana (EEW)**, analítica predictiva y estado NAZCA Monitor, construida con FastAPI, PostgreSQL+PostGIS y Redis.

## Arquitectura

```
eew_api/
├── core/           # Física (Haversine, ETA P/S), config, seguridad (bcrypt)
├── db/             # SQLAlchemy + GeoAlchemy2 (PostGIS)
├── models/         # Schemas Pydantic v2
├── services/       # data_fetcher (USGS/EMSC/FIRMS), eew_processor, redis
├── api/routes/     # Endpoints REST
└── main.py         # Punto de entrada FastAPI
```

## Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/api/v1/predictive/analytics` | Índice de riesgo 0–1 (7 días) |
| GET | `/api/v1/nazca/monitor` | Estado operativo y nivel de vigilancia NAZCA en JSON |
| GET | `/api/v1/nazca/stations` | Lista de estaciones disponibles para NAZCA Monitor |
| POST | `/api/v1/eew/trigger` | Webhook EEW: calcula ETA y despacha alertas |
| GET | `/api/v1/clients/subscriptions` | Geocercas de clientes institucionales |
| POST | `/api/v1/clients/register` | Registrar cliente (dev) |
| GET | `/health` | Estado DB + Redis |

Todas las rutas `/api/v1/*` requieren header `X-API-Key`.

## Inicio rápido

### 1. Infraestructura

```bash
cp .env.example .env
docker compose up -d postgres redis
```

### 2. Dependencias Python

```bash
pip install -r requirements-api.txt
```

### 3. Migraciones y datos demo

```bash
set DATABASE_SSL=false
alembic upgrade head
python scripts/seed_demo.py
```

### 4. Ejecutar API

```bash
uvicorn eew_api.main:app --reload --host 0.0.0.0 --port 8000
```

Documentación interactiva: http://localhost:8000/docs

## Endpoint multiplataforma NAZCA

Este endpoint permite que una web, app móvil, dashboard externo o integración institucional consuma el estado actual sin depender de la interfaz Streamlit.

PowerShell:

```powershell
Invoke-RestMethod `
  -Uri "http://localhost:8000/api/v1/nazca/monitor?estacion=Valpara%C3%ADso%20/%20San%20Antonio%20(85574)" `
  -Headers @{ "X-API-Key" = "dev-master-key-change-me" }
```

cURL:

```bash
curl "http://localhost:8000/api/v1/nazca/monitor?estacion=Valpara%C3%ADso%20/%20San%20Antonio%20(85574)" \
  -H "X-API-Key: dev-master-key-change-me"
```

La respuesta separa claramente:

- `estado_operativo`: condición actual del sistema según el índice de riesgo local.
- `nivel_vigilancia`: vigilancia preventiva por similitud con patrones históricos M7+.
- `metricas`: USGS, NOAA Kp, b-value y telemetría estimada.
- `trazabilidad`: fuentes, radio local, log del modelo y aviso experimental.

## Ejemplo: disparar alerta EEW

```bash
curl -X POST http://localhost:8000/api/v1/eew/trigger \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-master-key-change-me" \
  -d '{
    "event_id": "usgs_2026_06_05_001",
    "timestamp_utc": "2026-06-05T21:24:00Z",
    "epicenter": {"latitude": -34.5, "longitude": -72.0, "depth_km": 25},
    "magnitude_mw": 6.8,
    "source": "manual"
  }'
```

## Fórmulas implementadas

- **Distancia epicentral:** Haversine (R = 6371 km)
- **ETA onda P:** `d / 6.5` s
- **ETA onda S:** `d / 3.5` s
- **Ventana de alerta útil:** `d × (1/3.5 − 1/6.5) ≈ d × 0.1319` s

## Seguridad

- API keys hasheadas con **bcrypt** (nunca en texto plano)
- Credenciales vía variables de entorno (`.env`)
- TLS configurable para PostgreSQL (`DATABASE_SSL=true` en producción)

## Fuentes Open Data

- **USGS** — sismos en tiempo real (GeoJSON)
- **EMSC** — redundancia global
- **NASA FIRMS** — anomalías térmicas (requiere `FIRMS_API_KEY`)
- **Copernicus Sentinel-5P** — gases (requiere credenciales)
