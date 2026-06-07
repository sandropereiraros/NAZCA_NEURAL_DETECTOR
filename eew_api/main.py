from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from eew_api.api.routes import clients, eew, health, nazca, predictive
from eew_api.core.config import get_settings
from eew_api.core.logging_config import setup_logging

settings = get_settings()
setup_logging(settings.debug)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(settings.debug)
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="API REST de Alerta Sísmica Temprana (EEW) y Analítica Predictiva",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(predictive.router, prefix="/api/v1")
app.include_router(nazca.router, prefix="/api/v1")
app.include_router(eew.router, prefix="/api/v1")
app.include_router(clients.router, prefix="/api/v1")


@app.get("/")
async def root():
    return {
        "service": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "endpoints": [
            "GET  /api/v1/predictive/analytics",
            "GET  /api/v1/nazca/monitor",
            "GET  /api/v1/nazca/stations",
            "POST /api/v1/eew/trigger",
            "GET  /api/v1/clients/subscriptions",
        ],
    }
