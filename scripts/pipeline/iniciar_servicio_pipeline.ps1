# NAZCA PIPELINE LAB - servicio local (cada 10 minutos)
# Uso: powershell -ExecutionPolicy Bypass -File scripts/pipeline/iniciar_servicio_pipeline.ps1

$Root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Set-Location $Root

Write-Host "NAZCA PIPELINE LAB - servicio local iniciado $(Get-Date)"
Write-Host "Directorio: $Root"
Write-Host "Ctrl+C para detener."

while ($true) {
    try {
        python scripts/pipeline/ejecutar_pipeline.py --todo
        $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        Write-Host "[$ts] Ciclo completado."
    }
    catch {
        Write-Host "[ERROR] $($_.Exception.Message)"
    }
    Start-Sleep -Seconds 600
}
