"""Snapshot degli incidenti: log dei container, metriche e report finale."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from downscaler import config as config_mod
from downscaler.monitoring import get_glances_metrics
from downscaler.state import send_telegram

log = config_mod.log


def collect_incident_snapshot(
    config: dict,
    services: list[dict],
    state: dict,
    now: datetime,
    phase: str,
    metrics_fn: Callable[[dict], tuple[float | None, float | None]] | None = None,
) -> Path | None:
    """Raccoglie log e metriche dell'incidente e li salva su disco.

    phase: "start" (prima del primo stop) o "end" (fine recovery).
    Ritorna il path della cartella snapshot, o None se disabilitato.
    `metrics_fn` e' iniettato: i test patchano il nome a livello di modulo
    di emergency-stop, non questa funzione.
    """
    read_metrics = metrics_fn or get_glances_metrics
    incidents_config = config.get("incidents", {})
    if not incidents_config.get("enabled", True):
        return None
    if config_mod.DRY_RUN:
        log.info("[dry-run] snapshot incidente non scritto")
        return None

    log_dir = Path(incidents_config.get("dir", "/app/incidents"))
    log_tail = incidents_config.get("log_tail", 20000)
    log_window = incidents_config.get("log_window_min", 15)

    timestamp = now.strftime("%Y-%m-%d_%H-%M-%S")
    snapshot_dir = log_dir / timestamp
    try:
        snapshot_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        log.error(f"Impossibile creare la cartella incidenti {log_dir}: {e} - snapshot saltato")
        return None

    window_start = (now - timedelta(minutes=log_window)).isoformat()
    window_end = now.isoformat()
    all_containers = sorted({name for service in services for name in service["service_names"]})

    for container in all_containers:
        _dump_container_log(snapshot_dir, container, window_start, window_end, log_tail)

    _write_metrics(snapshot_dir, read_metrics(config), state, now, phase)
    summary = "\n".join(
        [
            f"Incidente {phase}",
            f"Timestamp: {now.isoformat()}",
            f"Finestra log: {window_start} -> {window_end}",
            f"Servizi fermati: {', '.join(state.get('incident_services', []))}",
            f"Container: {', '.join(all_containers)}",
        ]
    )
    (snapshot_dir / "summary.txt").write_text(summary)

    log.info(f"Snapshot incidente salvato in {snapshot_dir}")
    return snapshot_dir


def _dump_container_log(snapshot_dir: Path, container: str, window_start: str, window_end: str, log_tail: int) -> None:
    """Salva le righe di log di un container nella finestra dell'incidente."""
    log_file = snapshot_dir / f"{container}.log"
    try:
        result = subprocess.run(
            ["docker", "logs", "--since", window_start, "--until", window_end, "--tail", str(log_tail), container],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        log_file.write_text(result.stdout if result.returncode == 0 else f"[errore: {result.stderr.strip()}]")
    except (subprocess.TimeoutExpired, OSError) as e:
        log_file.write_text(f"[errore: {e}]")


def _write_metrics(snapshot_dir: Path, metrics: tuple, state: dict, now: datetime, phase: str) -> None:
    """Salva il JSON con le metriche al momento dell'incidente."""
    iowait_val, load_val = metrics
    payload = {
        "timestamp": now.isoformat(),
        "phase": phase,
        "iowait": iowait_val,
        "load": load_val,
        "stopped_services": list(state.get("incident_services", [])),
    }
    (snapshot_dir / "metrics.json").write_text(json.dumps(payload, indent=2))


def send_incident_report(
    snapshot_dir: Path,
    state: dict,
    config: dict,
    notify_fn: Callable[[str, dict], None] | None = None,
) -> None:
    """Invia report Telegram con riepilogo e path dei log."""
    notify = notify_fn or send_telegram
    incidents_config = config.get("incidents", {})
    if not incidents_config.get("telegram_report", True):
        return
    duration_min = (datetime.now() - datetime.fromisoformat(state["incident_start"])).total_seconds() / 60
    fermati = sorted(set(state.get("incident_services", [])))
    message = (
        f"✅ Incidente risolto - {duration_min:.0f} minuti\n"
        f"Servizi fermati: {len(fermati)} ({', '.join(fermati)})\n"
        f"Log: {snapshot_dir}"
    )
    notify(message, config)
