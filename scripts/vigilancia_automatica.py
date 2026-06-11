"""Vigilancia automatica Chile — ejecutar en cron o GitHub Actions."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import nazca_alertas as alertas
import nazca_vigilancia_core as vigilancia


def main() -> int:
    parser = argparse.ArgumentParser(description="NAZCA vigilancia automatica Chile")
    parser.add_argument("--dry-run", action="store_true", help="Evalua sin enviar Telegram")
    parser.add_argument("--ttl-horas", type=int, default=6, help="TTL cache APIs (horas)")
    args = parser.parse_args()

    secrets = alertas.leer_secrets_toml()
    token = alertas.obtener_secret("TELEGRAM_TOKEN", secrets)
    chat_id = alertas.obtener_secret("TELEGRAM_CHAT_ID", secrets)
    if not token:
        print("FALTA: TELEGRAM_TOKEN")
        print("GitHub Actions: Settings > Secrets and variables > Actions > TELEGRAM_TOKEN")
        print("Local: .streamlit/secrets.toml o variable de entorno TELEGRAM_TOKEN")
        return 1
    if not args.dry_run and not chat_id:
        print("FALTA: TELEGRAM_CHAT_ID")
        print("GitHub Actions: agrega secret TELEGRAM_CHAT_ID (tu chat ID numerico)")
        return 1

    ttl_seg = max(3600, args.ttl_horas * 3600)
    try:
        resumen = vigilancia.ejecutar_vigilancia(secrets=secrets, ttl_seg=ttl_seg, dry_run=args.dry_run)
    except Exception as exc:
        print(f"ERROR ejecutando vigilancia: {exc}")
        return 1

    print(f"Vigilancia Chile | estaciones: {resumen['estaciones']} | alertas: {resumen['alertas_enviadas']}")
    print(f"USGS: {resumen['consultado_usgs']}")
    for ev in resumen["resultados"]:
        marca = "ALERTA" if ev.get("disparar") else "ok"
        print(
            f"  [{marca}] {ev['estacion']} | indice {ev['puntaje']:.1f}% | "
            f"b={ev['b_val']} | sismos={ev['total_sismos']} | {ev.get('motivo', '')}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
