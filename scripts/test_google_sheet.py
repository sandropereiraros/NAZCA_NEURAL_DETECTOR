"""Prueba conexion con Google Apps Script (no imprime secretos)."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
SECRETS = ROOT / ".streamlit" / "secrets.toml"


def leer_secrets() -> dict[str, str]:
    vals: dict[str, str] = {}
    if not SECRETS.exists():
        return vals
    for line in SECRETS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        vals[key.strip()] = val.strip().strip('"')
    return vals


def html_a_texto(html: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


def main() -> int:
    secrets = leer_secrets()
    url = secrets.get("SUBSCRIBERS_WEBAPP_URL", "")
    api_key = secrets.get("SUBSCRIBERS_API_KEY", "")

    if not url or not api_key:
        print("FALTA: secrets incompletos (URL o API_KEY).")
        return 1
    if "XXXX" in url:
        print("FALTA: SUBSCRIBERS_WEBAPP_URL sigue con placeholder XXXX.")
        return 1

    print("OK: secrets presentes en .streamlit/secrets.toml")

    try:
        res_get = requests.get(url, timeout=25)
    except requests.RequestException as exc:
        print(f"GET error: {exc}")
        return 1

    print(f"GET HTTP {res_get.status_code}")
    if res_get.text.strip().startswith("{"):
        print("GET JSON:", res_get.text[:300])
    else:
        texto = html_a_texto(res_get.text)
        if "No se encontr" in texto:
            print("GET: Apps Script sin doGet (revisa codigo y redeploy).")
        else:
            print("GET HTML:", texto[:220])

    try:
        res_post = requests.post(
            url,
            json={"api_key": api_key, "action": "list"},
            timeout=25,
        )
    except requests.RequestException as exc:
        print(f"POST error: {exc}")
        return 1

    print(f"POST HTTP {res_post.status_code}")
    body = res_post.text.strip()
    if res_post.status_code == 401:
        print("POST 401: revisa SUBSCRIBERS_API_KEY en secrets y Script properties.")
        return 1
    if body.startswith("{"):
        datos = json.loads(body)
        if datos.get("ok"):
            n = len(datos.get("subscribers", []))
            print(f"POST OK: conexion autorizada, suscriptores en sheet: {n}")
            return 0
        print(f"POST rechazado: {datos.get('error', 'sin detalle')}")
        return 1

    texto = html_a_texto(body)
    if "scripts is not defined" in texto:
        print("POST: pegaste la ruta del archivo, no el codigo. Abre .gs, copia TODO y redeploy.")
    elif "doPost" in texto or "No se encontr" in texto:
        print("POST: Apps Script sin doPost — pega google_apps_script_subscribers.gs y redeploy.")
    else:
        print("POST HTML:", texto[:220])
    return 1


if __name__ == "__main__":
    sys.exit(main())
