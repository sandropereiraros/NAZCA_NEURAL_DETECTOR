"""Prueba TELEGRAM_TOKEN desde secrets.toml (no imprime el token)."""
from __future__ import annotations

import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
SECRETS = ROOT / ".streamlit" / "secrets.toml"


def leer_secrets() -> dict[str, str]:
    vals: dict[str, str] = {}
    if not SECRETS.exists():
        return vals
    for line in SECRETS.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        vals[key.strip()] = val.strip().strip('"')
    return vals


def main() -> int:
    secrets = leer_secrets()
    token = secrets.get("TELEGRAM_TOKEN", "")
    chat_id = secrets.get("TELEGRAM_CHAT_ID", "")

    if not token:
        print("FALTA: TELEGRAM_TOKEN en .streamlit/secrets.toml")
        return 1
    if not chat_id:
        print("FALTA: TELEGRAM_CHAT_ID en .streamlit/secrets.toml")
        return 1

    print("OK: TELEGRAM_TOKEN y TELEGRAM_CHAT_ID presentes en secrets.toml")

    try:
        res = requests.get(
            f"https://api.telegram.org/bot{token}/getMe",
            timeout=15,
        )
    except requests.RequestException as exc:
        print(f"Error red Telegram: {exc}")
        return 1

    if res.status_code != 200:
        print(f"Telegram HTTP {res.status_code}: token invalido o revocado.")
        return 1

    datos = res.json()
    if not datos.get("ok"):
        print(f"Telegram rechazo getMe: {datos.get('description', 'sin detalle')}")
        return 1

    bot = datos.get("result", {})
    print(f"OK: bot conectado (@{bot.get('username', '?')})")
    print("Si la web sigue fallando, reinicia Streamlit o agrega secrets en Streamlit Cloud.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
