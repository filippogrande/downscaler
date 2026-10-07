#!/usr/bin/env python3
"""
Emergency Stop — spegne servizi non critici quando il server soffre.

Logica:
1. Monitora Glances API (iowait o load)
2. Se sopra soglia per duration_sec → stoppa il primo servizio in lista
3. Aspetta 30s → ricontrolla. Se migliorato → recovery mode
4. Recovery: 1h senza allarme → riaccende in ordine inverso

State: /tmp/emergency-stop-state.json
"""

import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests
import yaml

# ─── Config ───────────────────────────────────────────────────────────────────

CONFIG_PATH = Path("/opt/emergency-stop/config.yaml")
STATE_PATH = Path("/tmp/emergency-stop-state.json")
LOG_PATH = Path("/var/log/emergency-stop.log")

# ─── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("emergency-stop")

# ─── State ───────────────────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {
        "mode": "monitor",  # monitor | recovery
        "stopped_services": [],  # servizi spenti, in ordine di stop
        "last_alarm_time": None,
        "recovery_started_at": None,
    }


def save_state(state: dict):
    STATE_PATH.write_text(json.dumps(state, indent=2))

# ─── Glances ─────────────────────────────────────────────────────────────────

def get_glances_metric(config: dict) -> float:
    """Legge iowait o load da Glances API."""
    url = f"{config['glances']['url']}/api/3/system"
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        metric = config["monitor"]["metric"]
        if metric == "iowait":
            return float(data.get("iowait", 0))
        elif metric == "load":
            return float(data.get("load1", 0))
        else:
            log.error(f"Metrica sconosciuta: {metric}")
            return 0.0
    except Exception as e:
        log.warning(f"Glances non raggiungibile: {e}")
        return 0.0

# ─── Docker ──────────────────────────────────────────────────────────────────

def stop_service(service: str, config: dict):
    """Ferma un servizio con docker compose down."""
    compose_dir = Path(config["services"][service]["compose_dir"])
    compose_file = config["services"][service].get("compose_file", "compose.yml")
    cmd = ["docker", "compose", "-f", str(compose_dir / compose_file), "down"]
    log.info(f"STOP: {service} → {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        log.error(f"Errore stop {service}: {result.stderr}")
        return False
    # Verifica che sia davvero spento
    time.sleep(5)
    ps = subprocess.run(
        ["docker", "ps", "--filter", f"name={service}", "--format", "{{.Names}}"],
        capture_output=True, text=True, timeout=10,
    )
    if service in ps.stdout:
        log.error(f"{service} ancora attivo dopo down!")
        return False
    log.info(f"✓ {service} spento correttamente")
    return True


def start_service(service: str, config: dict):
    """Riaccende un servizio con docker compose up -d."""
    compose_dir = Path(config["services"][service]["compose_dir"])
    compose_file = config["services"][service].get("compose_file", "compose.yml")
    cmd = ["docker", "compose", "-f", str(compose_dir / compose_file), "up", "-d"]
    log.info(f"START: {service} → {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        log.error(f"Errore start {service}: {result.stderr}")
        return False
    log.info(f"✓ {service} riavviato")
    return True

# ─── Main loop ───────────────────────────────────────────────────────────────

def main():
    if not CONFIG_PATH.exists():
        log.error(f"Config non trovato: {CONFIG_PATH}")
        sys.exit(1)

    config = yaml.safe_load(CONFIG_PATH.read_text())
    state = load_state()

    metric_value = get_glances_metric(config)
    threshold = config["monitor"]["threshold"]
    duration_sec = config["monitor"]["duration_sec"]
    check_interval = config["monitor"].get("check_interval_sec", 60)
    recovery_wait = config["recovery"]["calm_duration_sec"]
    restart_delay = config["recovery"]["restart_delay_sec"]

    now = datetime.now()
    log.info(f"Check: {config['monitor']['metric']}={metric_value:.1f} (soglia={threshold})")

    # ── Recovery mode ────────────────────────────────────────────────────
    if state["mode"] == "recovery":
        elapsed = (now - datetime.fromisoformat(state["recovery_started_at"])).total_seconds()
        if elapsed >= recovery_wait:
            log.info("Recovery: 1h di calma raggiunto, riaccendo i servizi in ordine inverso")
            for service in reversed(state["stopped_services"]):
                start_service(service, config)
                time.sleep(restart_delay)
            state["mode"] = "monitor"
            state["stopped_services"] = []
            state["recovery_started_at"] = None
            save_state(state)
            log.info("Recovery completato, tornato in monitor mode")
        else:
            remaining = recovery_wait - elapsed
            log.info(f"Recovery: ancora {remaining/60:.0f} min prima del riavvio")
        return

    # ── Monitor mode ──────────────────────────────────────────────────────
    if metric_value >= threshold:
        log.warning(f"ALLARME: {config['monitor']['metric']}={metric_value:.1f} >= {threshold}")

        # Trova il primo servizio non ancora spento
        stopped = set(state["stopped_services"])
        candidates = [s for s in config["stop_order"] if s not in stopped]

        if not candidates:
            log.warning("Tutti i servizi candidati sono già spenti, niente da fare")
            return

        service = candidates[0]
        log.info(f"Tentativo stop: {service}")

        if stop_service(service, config):
            state["stopped_services"].append(service)
            state["last_alarm_time"] = now.isoformat()
            save_state(state)

            # Aspetta e verifica miglioramento
            time.sleep(30)
            new_value = get_glances_metric(config)
            log.info(f"Post-stop {service}: {config['monitor']['metric']}={new_value:.1f}")

            if new_value < threshold:
                log.info(f"✓ Migliorato! Entro in recovery mode")
                state["mode"] = "recovery"
                state["recovery_started_at"] = now.isoformat()
                save_state(state)
            else:
                log.warning(f"Non migliora, prossimo giro proverà un altro servizio")
        else:
            log.error(f"Stop {service} fallito, riprovo al prossimo giro")
    else:
        # Tutto ok — se eravamo in allarme ma ora è calato, reset
        if state["stopped_services"]:
            log.info("Metrica tornata sotto soglia, entro in recovery mode")
            state["mode"] = "recovery"
            state["recovery_started_at"] = now.isoformat()
            save_state(state)


if __name__ == "__main__":
    main()
