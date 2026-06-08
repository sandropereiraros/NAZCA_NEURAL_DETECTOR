# Sube el codigo limpio de D: a GitHub (rama main).
# Ejecutar: powershell -ExecutionPolicy Bypass -File scripts\subir_a_github.ps1

$git = "C:\Users\sandr\AppData\Local\GitHubDesktop\app-3.5.12\resources\app\git\cmd\git.exe"
$repo = "D:\proyectos\NAZCA\SISTEMA SISMICO"

Set-Location $repo

Write-Host "Estado actual:" -ForegroundColor Cyan
& $git status
Write-Host ""

$ahead = & $git rev-list --count origin/main..HEAD 2>$null
if ($ahead -eq "0") {
    Write-Host "No hay commits pendientes de subir." -ForegroundColor Yellow
    exit 0
}

Write-Host "Subiendo $ahead commit(s) a origin/main..." -ForegroundColor Cyan
& $git push origin main

if ($LASTEXITCODE -eq 0) {
    Write-Host "Listo. Reinicia la app en Streamlit Cloud (Reboot app)." -ForegroundColor Green
} else {
    Write-Host "Error al subir. Abre GitHub Desktop en D:\proyectos\NAZCA\SISTEMA SISMICO y pulsa Push." -ForegroundColor Red
}
