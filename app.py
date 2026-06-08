"""
NAZCA CORE MONITOR — entrada legacy.

Delega en streamlit_app.py (fuente única). Preferir:
  streamlit run streamlit_app.py
"""
from pathlib import Path
import runpy

runpy.run_path(
    str(Path(__file__).resolve().parent / "streamlit_app.py"),
    run_name="__main__",
)
