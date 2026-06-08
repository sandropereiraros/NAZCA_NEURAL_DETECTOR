"""Lista suscriptores en Google Sheet y archivo local."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
SECRETS = ROOT / ".streamlit" / "secrets.toml"
LOCAL = ROOT / "nazca_suscriptores_telegram.json"


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
    url = secrets.get("SUBSCRIBERS_WEBAPP_URL", "")
    key = secrets.get("SUBSCRIBERS_API_KEY", "")

    if url and key:
        try:
            res = requests.post(url, json={"api_key": key, "action": "list"}, timeout=20)
            datos = res.json()
            if datos.get("ok"):
                subs = datos.get("subscribers", [])
                print(f"Google Sheet: {len(subs)} suscriptor(es)")
                for s in subs:
                    print(
                        f"  - {s.get('nombre')} | chat_id: {s.get('chat_id')} | "
                        f"activo: {s.get('activo')} | estacion: {s.get('estacion')}"
                    )
            else:
                print(f"Google Sheet: error ({datos.get('error', 'sin detalle')})")
        except (requests.RequestException, ValueError) as exc:
            print(f"Google Sheet: no se pudo consultar ({exc})")
    else:
        print("Google Sheet: no configurado en secrets")

    if LOCAL.exists():
        try:
            local = json.loads(LOCAL.read_text(encoding="utf-8"))
            if isinstance(local, list):
                print(f"Archivo local: {len(local)} suscriptor(es)")
                for s in local:
                    print(f"  - {s.get('nombre')} | chat_id: {s.get('chat_id')}")
            else:
                print("Archivo local: formato no reconocido")
        except (json.JSONDecodeError, OSError) as exc:
            print(f"Archivo local: error ({exc})")
    else:
        print("Archivo local: no existe")

    return 0


if __name__ == "__main__":
    sys.exit(main())
