# Registra tarea programada Windows: NAZCA Pipeline LAB cada 10 min (automatico).
# Ejecutar UNA vez:
#   powershell -ExecutionPolicy Bypass -File scripts/pipeline/registrar_tarea_windows.ps1

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Bat = Join-Path $PSScriptRoot "run_tarea_pipeline.bat"
$TaskName = "NAZCA-Pipeline-LAB"

New-Item -ItemType Directory -Force -Path (Join-Path $Root "data\pipeline_lab") | Out-Null

schtasks /Delete /TN $TaskName /F 2>$null | Out-Null
schtasks /Create /F /TN $TaskName /TR "`"$Bat`"" /SC MINUTE /MO 10 /RL LIMITED | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Error "No se pudo registrar la tarea."
    exit 1
}

schtasks /Run /TN $TaskName | Out-Null

Write-Host "OK: Tarea '$TaskName' activa (cada 10 minutos, en segundo plano)."
Write-Host "  Log: data\pipeline_lab\tarea_pipeline.log"
Write-Host "  Carpeta: $Root"
Write-Host ""
Write-Host "Estado: schtasks /Query /TN $TaskName"
Write-Host "Borrar: schtasks /Delete /TN $TaskName /F"
