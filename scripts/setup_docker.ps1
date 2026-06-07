# NAZCA EEW — arranque con Docker Desktop
# Ejecutar: .\scripts\setup_docker.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

Write-Host "`n=== 1/6 Docker Compose version ===" -ForegroundColor Cyan
docker compose version

Write-Host "`n=== 2/6 Levantando PostgreSQL + PostGIS y Redis ===" -ForegroundColor Cyan
docker compose up -d postgres redis

Write-Host "`n=== 3/6 Esperando contenedores healthy (max 2 min) ===" -ForegroundColor Cyan
$deadline = (Get-Date).AddMinutes(2)
do {
    Start-Sleep -Seconds 4
    docker compose ps
    $raw = docker compose ps --format json 2>$null
    if ($raw) {
        $services = @($raw | ConvertFrom-Json)
        $healthy = ($services | Where-Object { $_.Service -in @("postgres","redis") -and $_.Health -eq "healthy" }).Count
        if ($healthy -eq 2) { break }
    }
} until ((Get-Date) -gt $deadline)

Write-Host "`n=== 4/6 Dependencias Python ===" -ForegroundColor Cyan
pip install -r requirements-api.txt -q

Write-Host "`n=== 5/6 Migraciones Alembic ===" -ForegroundColor Cyan
alembic upgrade head

Write-Host "`n=== 6/6 Datos demo ===" -ForegroundColor Cyan
python scripts/seed_demo.py

Write-Host "`n=== LISTO ===" -ForegroundColor Green
Write-Host "Inicia la API con:"
Write-Host "  uvicorn eew_api.main:app --reload --port 8000"
Write-Host ""
Write-Host "Luego abre: http://localhost:8000/docs"
Write-Host "API Key: dev-master-key-change-me (ver .env)"
