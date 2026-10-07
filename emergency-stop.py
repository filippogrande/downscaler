#!/usr/bin/env python3
"""
Emergency Stop — spegne servizi non critici quando il server soffre.

Logica:
1. Health check: riavvia servizi down che non sono stati spenti dal sistema
2. Media mobile: campiona ogni 30s, media su finestra 2 min
3. Isteresi: stop > 80%, restart < 60%
4. Recovery graduale: 5 min calma tra un riavvio e l'altro
5. Notifiche Telegram: inizio downscale, inizio recovery, fine incidente

State: /tmp/emergency-stop-state.json
"""

import json
import logging
import os
import subprocess
import sys
import time
from collections import deque
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
        "incident_start": None,
        "incident_services": [],
    }


def save_state(state: dict):
    STATE_PATH.write_text(json.dumps(state, indent=2))

# ─── Telegram ────────────────────────────────────────────────────────────────

def send_telegram(message: str, config: dict):
    """Invia notifica Telegram."""
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
    except Exception as e:
        log.error(f"Errore invio Telegram: {e}")

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

def is_service_running(service: str) -> bool:
    """Controlla se un servizio è attivo."""
    ps = subprocess.run(
        ["docker", "ps", "--filter", f"name={service}", "--format", "{{.Names}}"],
        capture_output=True, text=True, timeout=10,
    )
    return service in ps.stdout


def stop_service(service: str, config: dict):
    """Ferma un servizio con docker compose down."""
    compose_dir = Path(config["services"][service]["compose_dir"])
    compose_file = config["services"][service].get("compose_file", "docker-compose.yml")
    cmd = ["docker", "compose", "-f", str(compose_dir / compose_file), "down"]
    log.info(f"STOP: {service} → {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        log.error(f"Errore stop {service}: {result.stderr}")
        return False
    time.sleep(5)
    if is_service_running(service):
        log.error(f"{service} ancora attivo dopo down!")
        return False
    log.info(f"✓ {service} spento correttamente")
    return True


def start_service(service: str, config: dict):
    """Riaccende un servizio con docker compose up -d."""
    compose_dir = Path(config["services"][service]["compose_dir"])
    compose_file = config["services"][service].get("compose_file", "docker-compose.yml")
    cmd = ["docker", "compose", "-f", str(compose_dir / compose_file), "up", "-d"]
    log.info(f"START: {service} → {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        log.error(f"Errore start {service}: {result.stderr}")
        return False
    log.info(f"✓ {service} riavviato")
    return True

# ─── Health Check ────────────────────────────────────────────────────────────

def health_check(config: dict, state: dict):
    """Riavvia servizi down che non sono stati spenti dal sistema."""
    stopped = set(state["stopped_services"])
    for service in config["stop_order"]:
        if service in stopped:
            continue
        if not is_service_running(service):
            log.info(f"Health check: {service} è down, lo riavvio")
            start_service(service, config)

# ─── Media mobile ────────────────────────────────────────────────────────────

def update_window(window: deque, value: float, window_sec: int, sample_interval: int) -> float:
    """Aggiungi campione e calcola media mobile."""
    window.append(value)
    max_samples = window_sec // sample_interval
    while len(window) > max_samples:
        window.popleft()
    return sum(window) / len(window) if window else 0.0

# ─── Main loop ───────────────────────────────────────────────────────────────

def main():
    if not CONFIG_PATH.exists():
        log.error(f"Config non trovato: {CONFIG_PATH}")
        sys.exit(1)

    config = yaml.safe_load(CONFIG_PATH.read_text())
    state = load_state()

    # ── Health check ────────────────────────────────────────────────────
    health_check(config, state)

    # ── Campionamento ───────────────────────────────────────────────────
    sample_interval = config["monitor"]["sample_interval_sec"]
    window_sec = config["monitor"]["window_sec"]
    stop_threshold = config["monitor"]["stop_threshold"]
    restart_threshold = config["monitor"]["restart_threshold"]
    check_interval = config["monitor"]["check_interval_sec"]
    recovery_wait = config["recovery"]["calm_duration_sec"]
    restart_delay = config["recovery"]["restart_delay_sec"]

    # Inizializza finestra se non esiste
    if "metric_window" not in state:
        state["metric_window"] = []
    window = deque(state["metric_window"])

    metric_value = get_glances_metric(config)
    avg = update_window(window, metric_value, window_sec, sample_interval)
    state["metric_window"] = list(window)
    save_state(state)

    now = datetime.now()
    log.info(f"Check: {config['monitor']['metric']}={metric_value:.1f} media={avg:.1f} (stop>{stop_threshold}, restart<{restart_threshold})")

    # ── Recovery mode ────────────────────────────────────────────────────
    if state["mode"] == "recovery":
        elapsed = (now - datetime.fromisoformat(state["recovery_started_at"])).total_seconds()
        if elapsed >= recovery_wait:
            # Riavvia il prossizio servizio in ordine inverso
            if state["stopped_services"]:
                service = state["stopped_services"][-1]  # ultimo spento
                log.info(f"Recovery: riavvio {service}")
                send_telegram(f"🔄 inizio recovery\n+ {service}", config)
                if start_service(service, config):
                    state["stopped_services"].pop()
                    save_state(state)
                    # Aspetta restart_delay prima del prossimo
                    time.sleep(restart_delay)
                else:
                    log.error(f"Riavvio {service} fallito, riprovo dopo {restart_delay}s")
                    time.sleep(restart_delay)
            else:
                # Tutti riavviati, fine incidente
                incident_end = now
                incident_start = datetime.fromisoformat(state["incident_start"])
                duration_min = (incident_end - incident_start).total_seconds() / 60
                num_services = len(state["incident_services"])
                send_telegram(
                    f"✅ fine incidente\n"
                    f"durata: {duration_min:.0f} minuti\n"
                    f"servizi fermati: {num_services}",
                    config
                )
                state["mode"] = "monitor"
                state["stopped_services"] = []
                state["recovery_started_at"] = None
                state["incident_start"] = None
                state["incident_services"] = []
                save_state(state)
                log.info("Recovery completato, tornato in monitor mode")
        else:
            remaining = recovery_wait - elapsed
            log.info(f"Recovery: ancora {remaining/60:.0f} min prima del prossimo riavvio")
        return

    # ── Monitor mode ──────────────────────────────────────────────────────
    if avg >= stop_threshold:
        log.warning(f"ALLARME: media {avg:.1f} >= {stop_threshold}")

        stopped = set(state["stopped_services"])
        candidates = [s for s in config["stop_order"] if s not in stopped]

        if not candidates:
            log.warning("Tutti i servizi candidati sono già spenti, niente da fare")
            return

        service = candidates[0]
        log.info(f"Tentativo stop: {service}")

        if stop_service(service, config):
            # Se è il primo servizio fermato, inizia incidente
            if not state["stopped_services"]:
                state["incident_start"] = now.isoformat()
                state["incident_services"] = []
                send_telegram("🚨 inizio downscale", config)

            state["stopped_services"].append(service)
            state["incident_services"].append(service)
            state["last_alarm_time"] = now.isoformat()
            save_state(state)

            # Notifica servizio fermato
            send_telegram(f"- {service}", config)

            # Aspetta e verifica miglioramento
            time.sleep(30)
            new_value = get_glances_metric(config)
            new_avg = update_window(window, new_value, window_sec, sample_interval)
            state["metric_window"] = list(window)
            save_state(state)
            log.info(f"Post-stop {service}: media={new_avg:.1f}")

            if new_avg < stop_threshold:
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
            log.info("Media tornata sotto soglia, entro in recovery mode")
            state["mode"] = "recovery"
            state["recovery_started_at"] = now.isoformat()
            save_state(state)


if __name__ == "__main__":
    main()
