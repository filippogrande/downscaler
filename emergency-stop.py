#!/usr/bin/env python3
"""
Emergency Stop — spegne servizi non critici quando il server soffre.

Logica:
1. Health check: riavvia servizi down che non sono stati spenti dal sistema
   (salta gli one-shot e quelli con can_restart: false)
2. Media mobile: campiona ogni 30s, media su finestra 2 min
3. Isteresi: stop se media > soglia, recovery solo se media < soglia
4. Stop graduale: un servizio alla volta, poi passa al successivo
5. Recovery graduale: un servizio ogni restart_delay, solo a metrica calata
6. Notifiche Telegram: inizio downscale, inizio recovery, fine incidente

Dentro il container (mount dal compose):
  config:   /app/config.yaml
  servizi:  /app/services/<nome>.yaml
  stato:    /app/state/state.json
  log:      /app/logs/emergency-stop.log

Sulla macchina host:
  compose:  /mnt/applicazioni/yml/docker/emergency-stop/docker-compose.yml
  servizi:  /mnt/applicazioni/yml/docker/emergency-stop/services/*.yaml
  log:      /var/log/emergency-stop.log

Modalita': --validate controlla la config, --dry-run mostra cosa farebbe
senza toccare Docker ne lo stato, --selftest prova i file di servizio
senza Docker.
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import requests
import yaml

# ─── Config ───────────────────────────────────────────────────────────────────

CONFIG_PATH = Path("/app/config.yaml")
SERVICES_DIR = Path("/app/services")
STATE_PATH = Path("/app/state/state.json")
LOG_PATH = Path("/app/logs/emergency-stop.log")

DEFAULT_COMPOSE_FILE = "docker-compose.yml"
DEFAULT_PRIORITY = 100

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

# Eccezioni di rete: requests non e' importabile qui, quindi si usano le
# classi base. ConnectionError/OSError coprono la stragrande maggior parte
# dei casi (timeout, DNS, socket chiuso).
NETWORK_ERRORS = (
    requests.RequestException,
    OSError,
)


# ─── Logging ─────────────────────────────────────────────────────────────────

def _setup_logging():
    """Configura il logging su file e stdout.

    Se il file di log non esiste lo crea: con un bind-mount su un file inesistente
    Docker crea una DIRECTORY, e FileHandler fallirebbe con IsADirectoryError.
    """
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not LOG_PATH.exists():
        LOG_PATH.touch()
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

# --dry-run si puo' attivare da env (DRY_RUN=true nel compose).
DRY_RUN = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes", "on")

# ─── Config servizi ──────────────────────────────────────────────────────────


def load_services(services_dir: Path, log_missing: bool = True) -> list[dict]:
    """Legge i file di servizio e li ordina per priorità (più bassa = prima)."""
    if not services_dir.is_dir():
        if log_missing:
            log.error(f"Directory servizi non trovata: {services_dir}")
        return []

    services = []
    for path in sorted(services_dir.glob("*.yaml")):
        try:
            raw = yaml.safe_load(path.read_text())
        except YAML_ERRORS as e:
            log.error(f"Config {path.name} non leggibile: {e}")
            continue

        # Un .yaml vuoto da None: senza questo controllo il file sparirebbe
        # in silenzio e il servizio non sarebbe mai gestito.
        if raw is None:
            log.error(f"Config {path.name}: VUOTO (0 byte) — il servizio non sara' gestito")
            continue

        if not isinstance(raw, dict):
            log.error(f"Config {path.name}: atteso un mapping, trovato {type(raw).__name__}")
            continue

        if not raw.get("name"):
            log.error(f"Config {path.name}: manca 'name'")
            continue
        if not raw.get("compose_dir"):
            log.error(f"Config {path.name} ({raw['name']}): manca 'compose_dir'")
            continue

        service_names = raw.get("service_name") or [raw["name"]]
        if isinstance(service_names, str):
            service_names = [service_names]

        services.append(
            {
                "name": raw["name"],
                "compose_dir": Path(raw["compose_dir"]),
                "compose_file": raw.get("compose_file", DEFAULT_COMPOSE_FILE),
                "service_names": list(service_names),
                "can_stop": bool(raw.get("can_stop", True)),
                "can_restart": bool(raw.get("can_restart", True)),
                "one_shot": bool(raw.get("one_shot", False)),
                "priority": int(raw.get("priority", DEFAULT_PRIORITY)),
                "note": raw.get("note", ""),
            }
        )

    services.sort(key=lambda s: s["priority"])
    return services


def check_service_files(services: list[dict], config: dict) -> bool:
    """Controlla i file di servizio. Ritorna True se tutto ok.

    Modalita' --selftest: solo file e nomi, niente Docker (utile dove non
    c'e' il socket Docker, o per controllare la config senza permessi).
    """
    ok = True
    selftest = getattr(check_service_files, "selftest", False)

    if not services:
        print(f"NESSUN SERVIZIO in {SERVICES_DIR} (atteso: un file <nome>.yaml per servizio)")
        return False

    print(f"\n=== Validazione {len(services)} servizi ===")
    for s in services:
        name = s["name"]
        compose_file = s["compose_dir"] / s["compose_file"]
        if not s["compose_dir"].is_dir():
            print(f"  ✗ {name}: compose_dir non esiste ({s['compose_dir']})")
            ok = False
        elif not compose_file.is_file():
            print(f"  ✗ {name}: compose file non trovato ({compose_file})")
            ok = False
        else:
            print(f"  ✓ {name}: {s['compose_dir']} [{', '.join(s['service_names'])}] priority={s['priority']}")

        if selftest:
            # Senza Docker si controlla solo che i path esistano
            continue

        if s["compose_dir"].is_dir() and compose_file.is_file():
            check = subprocess.run(
                ["docker", "compose", "-f", str(compose_file), "config", "-q"],
                check=False, capture_output=True, text=True, timeout=60,
            )
            if check.returncode != 0:
                print(f"  ✗ {name}: compose non valido: {check.stderr.strip()[:200]}")
                ok = False

        running = running_containers(s["service_names"])
        if s["one_shot"]:
            print(f"    one_shot: non residente (container: {', '.join(running) if running else 'nessuno'})")
        elif not s["can_stop"] and not s["can_restart"]:
            print("    skip: can_stop=false can_restart=false → non gestito")
        elif not running:
            print(f"  ⚠ {name}: NESSUN container in esecuzione (atteso: {', '.join(s['service_names'])})")
            ok = False

    print("\n=== Glances ===")
    base_url = config.get("glances", {}).get("url", "")
    metric = config.get("monitor", {}).get("metric", "")
    if not base_url:
        print("  ✗ glances.url mancante")
        ok = False
    else:
        print(f"  url: {base_url}  metrica: {metric}")
        value = get_glances_metric(config)
        if value is None:
            print("  ✗ metrica non leggibile da Glances")
            ok = False
        else:
            print(f"  ✓ valore attuale: {metric}={value:.1f}")

    print(f"\n=== Esito: {'OK' if ok else 'ERRORI'} ===")
    return ok

# ─── State ───────────────────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except JSON_ERRORS as e:
            log.error(f"Stato illeggibile ({STATE_PATH}: {e}), riparto da zero")
    return {
        "mode": "monitor",  # monitor | recovery
        "stopped_services": [],  # servizi spenti, in ordine di stop
        "last_alarm_time": None,
        "recovery_started_at": None,
        "incident_start": None,
        "incident_services": [],
    }


def save_state(state: dict):
    if DRY_RUN:
        log.info("[dry-run] stato NON scritto")
        return
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))

# ─── Telegram ────────────────────────────────────────────────────────────────

def send_telegram(message: str, config: dict):
    """Invia notifica Telegram (mai in --dry-run)."""
    if DRY_RUN:
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

# ─── Glances ─────────────────────────────────────────────────────────────────

def _glances_get(base_url: str, path: str) -> dict | None:
    """GET /api/<ver>/<path> su Glances. Ritorna il dict, o None se non raggiungibile."""
    url = f"{base_url.rstrip('/')}{path}"
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        return resp.json()
    except requests.HTTPError as e:
        log.warning(f"Glances risponde {e.response.status_code} su {path}")
    except NETWORK_ERRORS as e:
        log.warning(f"Glances non raggiungibile su {path}: {e}")
    return None


def get_glances_metric(config: dict) -> float | None:
    """Legge iowait o load da Glances API. None se non leggibile.

    Da Glances 4.0 l'API è /api/4/ (la /api/3/ non esiste più: risponde
    404). I campi non stanno in `system`:
      - iowait  → /api/4/cpu  (campo "iowait")
      - load    → /api/4/load (campo "min1")
    """
    base_url = config["glances"]["url"]
    metric = config["monitor"]["metric"]

    if metric == "iowait":
        endpoint = "/cpu"
        field = "iowait"
    elif metric == "load":
        endpoint = "/load"
        field = "min1"
    else:
        log.error(f"Metrica sconosciuta: {metric} (atteso 'iowait' o 'load')")
        return None

    for api_version in ("4", "3"):
        data = _glances_get(base_url, f"/api/{api_version}{endpoint}")
        if data is None:
            continue
        if field not in data:
            log.error(f"Glances /api/{api_version}{endpoint} non contiene il campo '{field}'")
            continue
        value = float(data[field])
        log.info(f"Glances /api/{api_version}{endpoint}: {field}={value:.1f}")
        return value

    log.error(f"Impossibile leggere la metrica '{metric}' da Glances")
    return None

# ─── Docker ──────────────────────────────────────────────────────────────────

def running_containers(service_names: list[str]) -> list[str]:
    """Container in esecuzione il cui nome e' in `service_names` (confronto esatto)."""
    if not service_names:
        return []
    ps = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"],
        check=False, capture_output=True, text=True, timeout=10,
    )
    wanted = set(service_names)
    return [line.strip() for line in ps.stdout.splitlines() if line.strip() in wanted]


def is_service_running(service: dict) -> bool:
    """True se almeno un container del servizio è in esecuzione."""
    return bool(running_containers(service["service_names"]))


def _compose_cmd(service: dict) -> list[str]:
    return [
        "docker", "compose", "-f", str(service["compose_dir"] / service["compose_file"]),
    ]


def stop_service(service: dict) -> bool:
    """Ferma un servizio con docker compose down (mai in --dry-run)."""
    cmd = _compose_cmd(service) + ["down"]
    if DRY_RUN:
        log.info(f"[dry-run] STOP: {service['name']} → {' '.join(cmd)}")
        return True
    log.info(f"STOP: {service['name']} → {' '.join(cmd)}")
    result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        log.error(f"Errore stop {service['name']}: {result.stderr}")
        return False
    time.sleep(5)
    if is_service_running(service):
        log.error(f"{service['name']} ancora attivo dopo down!")
        return False
    log.info(f"✓ {service['name']} spento correttamente")
    return True


def start_service(service: dict) -> bool:
    """Riaccende un servizio con docker compose up -d (mai in --dry-run)."""
    cmd = _compose_cmd(service) + ["up", "-d"]
    if DRY_RUN:
        log.info(f"[dry-run] START: {service['name']} → {' '.join(cmd)}")
        return True
    log.info(f"START: {service['name']} → {' '.join(cmd)}")
    result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        log.error(f"Errore start {service['name']}: {result.stderr}")
        return False
    log.info(f"✓ {service['name']} riavviato")
    return True

# ─── Health Check ────────────────────────────────────────────────────────────

def health_check(services: list[dict], state: dict):
    """Riavvia servizi down che non sono stati spenti dal sistema.

    Salta gli one-shot (batch da cron, non hanno un container residente)
    e quelli con can_restart: false.
    """
    stopped = set(state["stopped_services"])
    for service in services:
        if service["one_shot"] or not service["can_restart"]:
            continue
        if service["name"] in stopped:
            continue
        if not is_service_running(service):
            log.info(f"Health check: {service['name']} è down, lo riavvio")
            start_service(service)

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
    global DRY_RUN

    parser = argparse.ArgumentParser(description="Emergency Stop")
    parser.add_argument("--validate", action="store_true", help="valida la configurazione e esci")
    parser.add_argument("--selftest", action="store_true",
                        help="valida i file di servizio senza Docker (utile dove manca il socket)")
    parser.add_argument("--dry-run", action="store_true",
                        help="mostra cosa farebbe, senza toccare Docker ne lo stato")
    parser.add_argument("--no-dry-run", action="store_true",
                        help="esegue davvero (annulla DRY_RUN=true del compose)")
    args = parser.parse_args()

    if not CONFIG_PATH.exists():
        log.error(f"Config non trovato: {CONFIG_PATH}")
        sys.exit(1)

    if args.dry_run:
        DRY_RUN = True
    if args.no_dry_run:
        DRY_RUN = False

    config = yaml.safe_load(CONFIG_PATH.read_text())
    services = load_services(SERVICES_DIR)

    if args.selftest:
        check_service_files.selftest = True
        sys.exit(0 if check_service_files(services, config) else 1)

    if args.validate:
        sys.exit(0 if check_service_files(services, config) else 1)

    state = load_state()

    if DRY_RUN:
        log.info("=== DRY-RUN: nessuna azione reale verra' eseguita ===")

    # ── Health check ────────────────────────────────────────────────────
    health_check(services, state)

    # ── Campionamento ───────────────────────────────────────────────────
    sample_interval = config["monitor"]["sample_interval_sec"]
    window_sec = config["monitor"]["window_sec"]
    stop_threshold = config["monitor"]["stop_threshold"]
    restart_threshold = config["monitor"]["restart_threshold"]
    recovery_wait = config["recovery"]["calm_duration_sec"]
    restart_delay = config["recovery"]["restart_delay_sec"]

    if "metric_window" not in state:
        state["metric_window"] = []
    window = deque(state["metric_window"])

    metric_value = get_glances_metric(config)
    if metric_value is None:
        # Metrica non leggibile: non decidere nulla. Tornare 0.0 qui
        # significherebbe "tutto ok", che era il bug originale.
        log.error("Salto questo giro: metrica non leggibile")
        return

    avg = update_window(window, metric_value, window_sec, sample_interval)
    state["metric_window"] = list(window)
    save_state(state)

    now = datetime.now()
    log.info(f"Check: {config['monitor']['metric']}={metric_value:.1f} media={avg:.1f} (stop>{stop_threshold}, restart<{restart_threshold})")

    # ── Recovery mode ────────────────────────────────────────────────────
    if state["mode"] == "recovery":
        elapsed = (now - datetime.fromisoformat(state["recovery_started_at"])).total_seconds()
        if elapsed >= recovery_wait:
            if avg >= restart_threshold:
                log.info(f"Recovery: ancora sopra la soglia ({avg:.1f}), attendo")
                return
            if state["stopped_services"]:
                service_name = state["stopped_services"][-1]
                service = next((s for s in services if s["name"] == service_name), None)
                if service is None:
                    log.error(f"Recovery: servizio {service_name} non più in config, lo scarto")
                    state["stopped_services"].pop()
                    save_state(state)
                    return
                log.info(f"Recovery: riavvio {service_name}")
                send_telegram(f"🔄 inizio recovery\n+ {service_name}", config)
                if start_service(service):
                    state["stopped_services"].pop()
                    save_state(state)
                    time.sleep(restart_delay)
                else:
                    log.error(f"Riavvio {service_name} fallito, riprovo dopo {restart_delay}s")
                    time.sleep(restart_delay)
            else:
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
        failed = set(state.get("failed_stops", []))
        candidates = [
            s for s in services
            if s["can_stop"] and not s["one_shot"]
            and s["name"] not in stopped and s["name"] not in failed
        ]

        if not candidates:
            log.warning("Tutti i servizi candidati sono già spenti o falliti, niente da fare")
            return

        service = candidates[0]
        log.info(f"Tentativo stop: {service['name']}")

        if stop_service(service):
            if not state["stopped_services"]:
                state["incident_start"] = now.isoformat()
                state["incident_services"] = []
                send_telegram("🚨 inizio downscale", config)

            state["stopped_services"].append(service["name"])
            state["incident_services"].append(service["name"])
            state["last_alarm_time"] = now.isoformat()
            state["failed_stops"] = [n for n in state.get("failed_stops", []) if n != service["name"]]
            save_state(state)

            send_telegram(f"- {service['name']}", config)

            new_avg = None
            if DRY_RUN:
                # Senza un down reale non c'e' nulla da misurare: si usa la
                # media corrente invece di riempire la finestra con un campione
                # inventato (e di crashare se il down fosse fallito).
                log.info("[dry-run] nessun campionamento post-stop")
                new_avg = avg
            else:
                time.sleep(30)
                new_value = get_glances_metric(config)
                if new_value is None:
                    log.error("Post-stop: metrica non leggibile, valuto al prossimo giro")
                    return
                new_avg = update_window(window, new_value, window_sec, sample_interval)
                state["metric_window"] = list(window)
                save_state(state)
                log.info(f"Post-stop {service['name']}: media={new_avg:.1f}")

            if new_avg < stop_threshold:
                log.info("✓ Migliorato! Entro in recovery mode")
                state["mode"] = "recovery"
                state["recovery_started_at"] = now.isoformat()
                save_state(state)
            else:
                log.warning("Non migliora, prossimo giro proverò un altro servizio")
        else:
            # Il down fallisce: segna il servizio come fallito e al giro dopo
            # prova il successivo, invece di bloccare l'intera lista.
            log.error(f"Stop {service['name']} fallito, il prossimo giro proverà il successivo")
            state.setdefault("failed_stops", []).append(service["name"])
            state["failed_stops"] = state["failed_stops"][-20:]
            save_state(state)
    else:
        if state["stopped_services"]:
            log.info("Media tornata sotto soglia, entro in recovery mode")
            state["mode"] = "recovery"
            state["recovery_started_at"] = now.isoformat()
            save_state(state)


if __name__ == "__main__":
    main()
