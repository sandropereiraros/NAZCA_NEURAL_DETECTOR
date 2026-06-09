@echo off
cd /d "%~dp0..\.."
echo NAZCA PIPELINE LAB - servicio cada 10 minutos
echo Ctrl+C para detener.
:loop
python scripts\pipeline\ejecutar_pipeline.py --todo
echo [%date% %time%] Ciclo completado.
timeout /t 600 /nobreak >nul
goto loop
