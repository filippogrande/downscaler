"""Configurazione di emergency-stop: path, default e logging.

Modulo base del package: tutti gli altri moduli di `downscaler` importano da
qui, cosi' i default e i path restano in un unico posto.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import sys
from pathlib import Path

import requests
import yaml

# ─── Path ──────────────────────────────────────────────────────────────
#
# I path si leggono da env perche' _setup_logging() gira a import: i test
# impostano EMERGENCY_STOP_LOG_PATH prima di caricare questo modulo.
CONFIG_PATH = Path(os.environ.get("EMERGENCY_STOP_CONFIG", "/app/config.yaml"))
SERVICES_DIR = Path(os.environ.get("EMERGENCY_STOP_SERVICES", "/app/services"))
STATE_PATH = Path(os.environ.get("EMERGENCY_STOP_STATE", "/app/state/state.json"))
LOG_PATH = Path(os.environ.get("EMERGENCY_STOP_LOG", "/app/logs/emergency-stop.log"))

DEFAULT_COMPOSE_FILE = "docker-compose.yml"
DEFAULT_PRIORITY = 100

# ─── Default di configurazione ─────────────────────────────────────────
#
# Un config vecchio (manca una chiave aggiunta dopo) non deve far crashare
# il container: le chiavi assenti prendono questi valori.
# Fonte dell'errore che questo risolve: KeyError: 'load_stop_threshold'
# e KeyError: 'stopped_services' (stato parziale scritto in dry-run).
DEFAULTS = {
    "monitor": {
        "metric": "iowait",
        "sample_interval_sec": 30,
        "window_sec": 120,
        "stop_threshold": 80.0,
        "restart_threshold": 60.0,
        "load_stop_threshold": 6.0,
        "load_restart_threshold": 4.0,
        # Super-stop: sopra queste soglie l'emergency stop ferma 2 servizi.
        "load_super_threshold": 11.0,
        "iowait_super_threshold": 95.0,
        "check_interval_sec": 60,
    },
    "recovery": {
        "calm_duration_sec": 300,
        "restart_delay_sec": 300,
    },
    "telegram": {
        "enabled": False,
        "bot_token": "",
        "chat_id": "",
    },
    "glances": {
        "url": "",
    },
    "incidents": {
        "enabled": True,
        "dir": "/mnt/applicazioni/yml/docker/emergency-stop/incidents",
        "telegram_report": True,
        "log_tail": 20000,
        "log_window_min": 15,
    },
}

# Chiavi dello stato con il loro valore iniziale: uno stato parziale
# (es. scritto in dry-run prima di questa regola) viene completato.
STATE_DEFAULTS = {
    "mode": "monitor",
    "stopped_services": [],
    "last_alarm_time": None,
    "recovery_started_at": None,
    "incident_start": None,
    "incident_services": [],
    "failed_stops": [],
    "metric_window": [],
    "metric_window_load": [],
}

# Eccezioni del parsing YAML: safe_load alza queste (o una sottoclasse).
# Catturarle esplicitamente invece di 'except Exception' evita di ingoiare
# errori che non sono di parsing (es. un PermissionError sul file).
YAML_ERRORS = (
    yaml.YAMLError,
    UnicodeDecodeError,
    OSError,
)

# Eccezioni della lettura/scrittura JSON di stato.
JSON_ERRORS = (
    json.JSONDecodeError,
    OSError,
)

# Eccezioni di rete: ConnectionError/OSError coprono la stragrande
# maggior parte dei casi (timeout, DNS, socket chiuso).
NETWORK_ERRORS = (
    requests.RequestException,
    OSError,
)


def _merge_defaults(config: dict) -> dict:
    """Rende il config tollerante alle chiavi mancanti (unione con DEFAULTS)."""
    merged = {section: dict(values) for section, values in DEFAULTS.items()}
    for section, values in config.items():
        if isinstance(values, dict) and section in merged:
            merged[section].update(values)
        else:
            merged[section] = values
    return merged


def _normalize_state(state: dict) -> dict:
    """Completa uno stato parziale con le chiavi mancanti (STATE_DEFAULTS).

    I default sono copiati in profondita': contengono liste, e un
    `dict(STATE_DEFAULTS)` le condividerebbe con lo stato caricato. Un
    append su `state["stopped_services"]` scriverebbe allora sui default
    del modulo, contaminando ogni stato caricato dopo.
    """
    normalized = copy.deepcopy(STATE_DEFAULTS)
    normalized.update(state)
    return normalized


# ─── Logging ──────────────────────────────────────────────────────────

def _setup_logging() -> None:
    """Configura il logging su file e stdout.

    Se il file di log non esiste lo crea: con un bind-mount su un file inesistente
    Docker crea una DIRECTORY, e FileHandler fallirebbe con IsADirectoryError.

    Il log e' un dettaglio secondario: se la directory non e' scrivibile (es.
    l'utente root in CI, dove /app non esiste) si logga su stdout e basta,
    invece di far fallire l'import del modulo.
    """
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        if not LOG_PATH.exists():
            LOG_PATH.touch()
    except OSError as e:
        print(f"ATTENZIONE: impossibile creare il file di log {LOG_PATH}: {e}", file=sys.stderr)

    handlers = [logging.StreamHandler(sys.stdout)]
    try:
        handlers.append(logging.FileHandler(LOG_PATH))
    except OSError as e:
        # Meglio loggare su stdout che non partire affatto: il container
        # ripartirebbe in loop con un traceback, come e' successo.
        print(f"ATTENZIONE: impossibile scrivere il log su {LOG_PATH}: {e}", file=sys.stderr)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=handlers,
    )


_setup_logging()
log = logging.getLogger("emergency-stop")

# --dry-run si puo' attivare da env (DRY_RUN=true nel compose). I flag
# --dry-run/--no-dry-run lo aggiornano a runtime: i moduli lo rileggono da qui.
DRY_RUN = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes", "on")
