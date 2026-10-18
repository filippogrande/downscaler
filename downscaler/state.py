"""Stato persistente (state.json) e notifiche Telegram."""

from __future__ import annotations

import json
from pathlib import Path

import requests

from downscaler import config as config_mod
from downscaler.config import JSON_ERRORS, NETWORK_ERRORS, STATE_DEFAULTS

log = config_mod.log


def load_state(path: Path | None = None) -> dict:
    """Carica lo stato, completando le chiavi mancanti.

    Serve perche' uno stato scritto da una versione precedente (o in
    dry-run) puo' non avere tutte le chiavi: senza questo completamento
    il primo accesso solleva KeyError e il container va in loop.
    """
    state_path = path or config_mod.STATE_PATH
    state = dict(STATE_DEFAULTS)
    if state_path.exists():
        try:
            loaded = json.loads(state_path.read_text())
            if isinstance(loaded, dict):
                state.update(loaded)
            else:
                log.error(f"Stato non e' un JSON object ({state_path}), riparto da zero")
        except JSON_ERRORS as e:
            log.error(f"Stato illeggibile ({state_path}: {e}), riparto da zero")
    return state


def save_state(state: dict, path: Path | None = None) -> None:
    """Salva lo stato.

    In dry-run NON viene scritto: l'obiettivo del dry-run e' non toccare
    nulla di persistente. La finestra delle metriche viene comunque
    accumulata in memoria durante il giro, quindi la media mobile non
    riparte da zero a ogni esecuzione.
    """
    if config_mod.DRY_RUN:
        log.info("[dry-run] stato NON scritto")
        return
    state_path = path or config_mod.STATE_PATH
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2))


def send_telegram(message: str, config: dict) -> None:
    """Invia notifica Telegram (mai in --dry-run)."""
    if config_mod.DRY_RUN:
        log.info(f"[dry-run] notifica Telegram non inviata: {message[:60]!r}")
        return
    tg = config.get("telegram", {})
    if not tg.get("enabled"):
        return
    token = tg.get("bot_token", "")
    chat_id = tg.get("chat_id", "")
    if not token or not chat_id or "INSERISCI" in token:
        log.warning("Telegram non configurato, salto notifica")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(url, json={"chat_id": chat_id, "text": message}, timeout=10)
        resp.raise_for_status()
        log.info(f"Notifica Telegram inviata: {message[:50]}...")
    except NETWORK_ERRORS as e:
        log.error(f"Errore invio Telegram: {e}")
