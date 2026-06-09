@echo off
cd /d "%~dp0..\.."
python scripts\pipeline\ejecutar_pipeline.py --todo >> data\pipeline_lab\tarea_pipeline.log 2>&1
