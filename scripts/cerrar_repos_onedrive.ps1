# Cierra las copias duplicadas del repo en OneDrive (no en D:).
# Ejecutar en PowerShell: clic derecho -> Ejecutar con PowerShell
# O desde terminal: powershell -ExecutionPolicy Bypass -File scripts\cerrar_repos_onedrive.ps1

$reposOneDrive = @(
    "C:\Users\sandr\OneDrive\Desktop\proyecto SITEMA SISMICO\SISTEMA SISMICO\.git",
    "C:\Users\sandr\OneDrive\Documentos\GitHub\NAZCA_NEURAL_DETECTOR\.git",
    "C:\Users\sandr\OneDrive\Documentos\GitHub\https-github.com-sandropereiraros-NAZCA_NEURAL_DETECTOR\.git"
)

Write-Host "Cerrando repos duplicados (solo OneDrive, no toca D:)..." -ForegroundColor Cyan

foreach ($p in $reposOneDrive) {
    if (Test-Path $p) {
        Rename-Item -Path $p -NewName ".git_DESACTIVADO" -Force
        Write-Host "  OK desactivado: $p" -ForegroundColor Green
    } else {
        Write-Host "  Ya no existe: $p" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "Ahora en GitHub Desktop:" -ForegroundColor Cyan
Write-Host "  1. File -> Add local repository"
Write-Host "  2. Carpeta: D:\proyectos\NAZCA\SISTEMA SISMICO"
Write-Host "  3. Si aparecen repos OneDrive rotos: clic derecho -> Remove"
Write-Host "  4. Push origin (boton azul) para subir a GitHub"
