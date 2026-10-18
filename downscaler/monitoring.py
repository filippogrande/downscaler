"""Metriche (Glances), health check e macchina a stati monitor/recovery.

Questo modulo non importa ne `emergency-stop.py` ne i test: i nomi che i test
patchano (running_containers, get_glances_metrics, send_telegram,
save_state...) arrivano qui come callables iniettate da emergency-stop.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

import requests

from downscaler import config as config_mod
from downscaler import docker_ops, services, state as state_mod

log = config_mod.log


@dataclass(frozen=True)
class Actions:
    """Effetti collaterali del ciclo, iniettati da emergency-stop."""

    save: Callable[[dict], None]
    notify: Callable[[str, dict], None]
    stop: Callable[[dict], bool]
    start: Callable[[dict], bool]
    snapshot: Callable[..., object]
    report: Callable[..., None]
    sample: Callable[..., tuple]


def _glances_get(base_url: str, path: str) -> dict | None:
    """GET /api/<ver>/<path> su Glances. Ritorna il dict, o None se non raggiungibile."""
    url = f"{base_url.rstrip('/')}{path}"
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        return resp.json()
    except requests.HTTPError as e:
        log.warning(f"Glances risponde {e.response.status_code} su {path}")
    except config_mod.NETWORK_ERRORS as e:
        log.warning(f"Glances non raggiungibile su {path}: {e}")
    return None


def _read_glances_field(base_url: str, api_path: str, field: str) -> float | None:
    """Legge un campo numerico dalla API Glances, provando /api/4 e poi /api/3."""
    for api_version in ("4", "3"):
        data = _glances_get(base_url, f"/api/{api_version}{api_path}")
        if data is None:
            continue
        if field not in data:
            log.error(f"Glances /api/{api_version}{api_path} non contiene il campo {field!r}")
            continue
        return float(data[field])
    return None


def get_glances_metrics(
    config: dict, sim_iowait: float | None = None, sim_load: float | None = None
) -> tuple[float | None, float | None]:
    """Legge iowait e load da Glances API. Ritorna (iowait, load), None se non leggibile.

    Da Glances 4.0 l'API e' /api/4/ (la /api/3/ non esiste piu': risponde 404).
    I campi non stanno in `system`:
      - iowait -> /api/4/cpu  (campo "iowait")
      - load   -> /api/4/load (campo "min1")

    Se sim_iowait/sim_load sono forniti, li usa invece di Glances (simulazione).
    """
    base_url = config["glances"]["url"]
    iowait_val = float(sim_iowait) if sim_iowait is not None else _read_glances_field(base_url, "/cpu", "iowait")
    load_val = float(sim_load) if sim_load is not None else _read_glances_field(base_url, "/load", "min1")
    if iowait_val is not None:
        log.info(f"iowait={iowait_val:.1f}")
    if load_val is not None:
        log.info(f"load={load_val:.1f}")
    if iowait_val is None and load_val is None:
        log.error("Impossibile leggere nessuna metrica da Glances")
        return None, None
    return iowait_val, load_val


def update_window(window: deque, value: float, window_sec: int, sample_interval: int) -> float:
    """Aggiungi campione e calcola media mobile (finestra di window_sec secondi)."""
    window.append(value)
    max_samples = window_sec // sample_interval
    while len(window) > max_samples:
        window.popleft()
    return sum(window) / len(window) if window else 0.0


def fmt_metric(value: float | None) -> str:
    """Formatta una metrica per i log: 'N/A' se mancante.

    Non si puo' mettere la condizione dentro il format specifier di una
    f-string (`{v:.1f if v else 'N/A'}` solleva ValueError), e `if v` avrebbe
    trattato 0.0 come valore mancante.
    """
    return f"{value:.1f}" if value is not None else "N/A"


def health_check(
    services_list: list[dict],
    state: dict,
    running_check: Callable[[list[str]], list[str]] | None = None,
    start_fn: Callable[[dict], bool] | None = None,
) -> None:
    """Riavvia servizi down che non sono stati spenti dal sistema.

    Salta gli one-shot (batch da cron, non hanno un container residente)
    e quelli con can_restart: false.
    """
    check = running_check or docker_ops.running_containers
    start = start_fn or docker_ops.start_service
    for service in services.restartable_services(services_list, state):
        if not check(service["service_names"]):
            log.info(f"Health check: {service['name']} e' down, lo riavvio")
            start(service)


def sample_metrics(
    config: dict,
    state: dict,
    sim_iowait: float | None = None,
    sim_load: float | None = None,
) -> tuple[float | None, float | None, float | None, float | None] | None:
    """Legge le metriche e aggiorna le finestre dello stato.

    Ritorna (iowait, load, media_iowait, media_load), oppure None se Glances
    non e' leggibile: il chiamante non deve decidere nulla in quel caso.
    """
    monitor = config["monitor"]
    window_iowait = deque(state.get("metric_window", state_mod.STATE_DEFAULTS["metric_window"]))
    window_load = deque(state.get("metric_window_load", state_mod.STATE_DEFAULTS["metric_window_load"]))
    iowait_val, load_val = get_glances_metrics(config, sim_iowait, sim_load)
    if iowait_val is None and load_val is None:
        return None
    avg_iowait = (
        update_window(window_iowait, iowait_val, monitor["window_sec"], monitor["sample_interval_sec"])
        if iowait_val is not None
        else None
    )
    avg_load = (
        update_window(window_load, load_val, monitor["window_sec"], monitor["sample_interval_sec"])
        if load_val is not None
        else None
    )
    state["metric_window"] = list(window_iowait)
    state["metric_window_load"] = list(window_load)
    return iowait_val, load_val, avg_iowait, avg_load


def _above_stop(
    avg_iowait: float | None, avg_load: float | None, iowait_threshold: float, load_threshold: float
) -> bool:
    """True se UNA delle due metriche e' sopra (o uguale) la soglia di stop."""
    return (avg_iowait is not None and avg_iowait >= iowait_threshold) or (
        avg_load is not None and avg_load >= load_threshold
    )


def _below_stop(
    avg_iowait: float | None, avg_load: float | None, iowait_threshold: float, load_threshold: float
) -> bool:
    """True se ENTRAMBE le metriche sono sotto la soglia di stop."""
    return (avg_iowait is None or avg_iowait < iowait_threshold) and (
        avg_load is None or avg_load < load_threshold
    )


def _windowed_average(state: dict, key: str, value: float | None, monitor: dict) -> float | None:
    """Aggiorna la finestra `key` dello stato e ritorna la nuova media."""
    if value is None:
        return None
    window = deque(state.get(key, []))
    average = update_window(window, value, monitor["window_sec"], monitor["sample_interval_sec"])
    state[key] = list(window)
    return average


def handle_recovery(
    config: dict,
    services_list: list[dict],
    state: dict,
    avg_iowait: float | None,
    avg_load: float | None,
    now: datetime,
    actions: Actions,
) -> None:
    """Un passo della modalita' recovery: riavvia un servizio alla volta."""
    monitor = config["monitor"]
    elapsed = (now - datetime.fromisoformat(state["recovery_started_at"])).total_seconds()
    if elapsed < config["recovery"]["calm_duration_sec"]:
        remaining = config["recovery"]["calm_duration_sec"] - elapsed
        log.info(f"Recovery: ancora {remaining / 60:.0f} min prima del prossimo riavvio")
        return
    if _above_stop(avg_iowait, avg_load, monitor["stop_threshold"], monitor["load_stop_threshold"]):
        # FIX: se le metriche risalgono sopra la soglia di stop il recovery
        # non puo' riavviare niente: si torna in monitor mode.
        log.warning(
            f"Recovery: ancora sopra soglia (iowait_media={fmt_metric(avg_iowait)}, "
            f"load_media={fmt_metric(avg_load)}), torno in monitor mode"
        )
        state["mode"] = "monitor"
        actions.save(state)
        return
    iowait_ok = avg_iowait is None or avg_iowait < monitor["restart_threshold"]
    load_ok = avg_load is None or avg_load < monitor["load_restart_threshold"]
    if not (iowait_ok and load_ok):
        log.info(
            f"Recovery: ancora sopra soglia (iowait_media={fmt_metric(avg_iowait)}, "
            f"load_media={fmt_metric(avg_load)}), attendo"
        )
        return
    if state["stopped_services"]:
        _restart_next_service(config, services_list, state, actions)
    else:
        _close_incident(config, services_list, state, now, actions)


def _restart_next_service(config: dict, services_list: list[dict], state: dict, actions: Actions) -> None:
    """Riavvia il prossimo servizio fermato, rispettando can_restart."""
    service_name = state["stopped_services"][-1]
    service = next((s for s in services_list if s["name"] == service_name), None)
    if service is None:
        log.error(f"Recovery: servizio {service_name} non piu' in config, lo scarto")
        state["stopped_services"].pop()
        actions.save(state)
        return
    if not service["can_restart"]:
        # FIX: can_restart=false va rispettato anche nel recovery.
        log.info(f"Recovery: {service_name} ha can_restart=false, lo salto")
        state["stopped_services"].pop()
        actions.save(state)
        return
    restart_delay = config["recovery"]["restart_delay_sec"]
    log.info(f"Recovery: riavvio {service_name}")
    actions.notify(f"INIZIO RECOVERY\n+ {service_name}", config)
    if actions.start(service):
        state["stopped_services"].pop()
        actions.save(state)
        time.sleep(restart_delay)
        return
    log.error(f"Riavvio {service_name} fallito, riprovo dopo {restart_delay}s")
    time.sleep(restart_delay)


def _close_incident(config: dict, services_list: list[dict], state: dict, now: datetime, actions: Actions) -> None:
    """Chiude l'incidente: snapshot finale, report e ritorno al monitor."""
    incident_start = datetime.fromisoformat(state["incident_start"])
    duration_min = (now - incident_start).total_seconds() / 60
    num_services = len(state["incident_services"])
    snapshot_dir = actions.snapshot(config, services_list, state, now, "end")
    if snapshot_dir:
        actions.report(snapshot_dir, state, config)
    actions.notify(
        f"FINE INCIDENTE\ndurata: {duration_min:.0f} minuti\nservizi fermati: {num_services}",
        config,
    )
    state["mode"] = "monitor"
    state["stopped_services"] = []
    state["recovery_started_at"] = None
    state["incident_start"] = None
    state["incident_services"] = []
    actions.save(state)
    log.info("Recovery completato, tornato in monitor mode")


def handle_monitor(
    config: dict,
    services_list: list[dict],
    state: dict,
    avg_iowait: float | None,
    avg_load: float | None,
    now: datetime,
    actions: Actions,
) -> None:
    """Un passo della modalita' monitor: allarma e ferma i servizi candidati."""
    monitor = config["monitor"]
    if _above_stop(avg_iowait, avg_load, monitor["stop_threshold"], monitor["load_stop_threshold"]):
        log.warning(
            f"ALLARME: iowait_media={fmt_metric(avg_iowait)} (soglia {monitor['stop_threshold']}), "
            f"load_media={fmt_metric(avg_load)} (soglia {monitor['load_stop_threshold']})"
        )
        _start_incident(config, services_list, state, now, actions)
        _stop_candidates_services(config, services_list, state, avg_iowait, avg_load, now, actions)
    elif state["stopped_services"]:
        log.info("Metriche tornate sotto soglia, entro in recovery mode")
        state["mode"] = "recovery"
        state["recovery_started_at"] = now.isoformat()
        actions.save(state)


def _start_incident(config: dict, services_list: list[dict], state: dict, now: datetime, actions: Actions) -> None:
    """Segna l'inizio dell'incidente: snapshot iniziale e notifica."""
    if state["incident_start"]:
        return
    state["incident_start"] = now.isoformat()
    state["incident_services"] = []
    actions.notify("ALLARME: inizio downscale", config)
    actions.snapshot(config, services_list, state, now, "start")


def _stop_candidates_services(
    config: dict,
    services_list: list[dict],
    state: dict,
    avg_iowait: float | None,
    avg_load: float | None,
    now: datetime,
    actions: Actions,
) -> None:
    """Ferma i servizi candidati: due in un colpo sopra la soglia critica."""
    candidates = _stop_candidates(services_list, state)
    if not candidates:
        log.warning("Tutti i servizi candidati sono gia' spenti o falliti, niente da fare")
        return
    targets = candidates[: _super_stop_count(avg_iowait, avg_load, config["monitor"])]
    if len(targets) > 1:
        log.warning(f"SUPER-STOP: fermo {len(targets)} servizi in un colpo ({', '.join(s['name'] for s in targets)})")
    results = [_stop_one(config, state, service, now, actions) for service in targets]
    if any(results):
        _evaluate_after_stop(config, state, avg_iowait, avg_load, now, actions)


def _super_stop_count(avg_iowait: float | None, avg_load: float | None, monitor: dict) -> int:
    """Quanti servizi fermare in un colpo: 2 sopra la soglia critica, 1 altrimenti."""
    super_load = avg_load is not None and avg_load > monitor["load_super_threshold"]
    super_iowait = avg_iowait is not None and avg_iowait > monitor["iowait_super_threshold"]
    return 2 if (super_load or super_iowait) else 1


def _stop_one(config: dict, state: dict, service: dict, now: datetime, actions: Actions) -> bool:
    """Ferma un servizio. Ritorna True se il down e' andato a buon fine."""
    log.info(f"Tentativo stop: {service['name']}")
    if not actions.stop(service):
        log.error(f"Stop {service['name']} fallito, il prossimo giro provaro' il successivo")
        state.setdefault("failed_stops", []).append(service["name"])
        state["failed_stops"] = state["failed_stops"][-20:]
        actions.save(state)
        return False
    state["stopped_services"].append(service["name"])
    state["incident_services"].append(service["name"])
    state["last_alarm_time"] = now.isoformat()
    state["failed_stops"] = [n for n in state.get("failed_stops", []) if n != service["name"]]
    actions.save(state)
    actions.notify(f"- {service['name']}", config)
    return True


def _stop_candidates(services_list: list[dict], state: dict) -> list[dict]:
    """Servizi fermabili non ancora spenti (o falliti) in questo incidente."""
    stopped = set(state.get("stopped_services", []))
    failed = set(state.get("failed_stops", []))
    return [
        service
        for service in services_list
        if service["can_stop"]
        and not service["one_shot"]
        and service["name"] not in stopped
        and service["name"] not in failed
    ]


def _evaluate_after_stop(
    config: dict,
    state: dict,
    avg_iowait: float | None,
    avg_load: float | None,
    now: datetime,
    actions: Actions,
) -> None:
    """Dopo un down: ricampiona le metriche e decide se entrare in recovery."""
    monitor = config["monitor"]
    if config_mod.DRY_RUN:
        log.info("[dry-run] nessun campionamento post-stop")
        new_avg_iowait, new_avg_load = avg_iowait, avg_load
    else:
        time.sleep(30)
        new_iowait, new_load = actions.sample(config)
        if new_iowait is None and new_load is None:
            log.error("Post-stop: metriche non leggibili, valuto al prossimo giro")
            return
        new_avg_iowait = _windowed_average(state, "metric_window", new_iowait, monitor)
        new_avg_load = _windowed_average(state, "metric_window_load", new_load, monitor)
        actions.save(state)
        log.info(f"Post-stop: iowait_media={fmt_metric(new_avg_iowait)}, load_media={fmt_metric(new_avg_load)}")
    if _below_stop(new_avg_iowait, new_avg_load, monitor["stop_threshold"], monitor["load_stop_threshold"]):
        log.info("Migliorato! Entro in recovery mode")
        state["mode"] = "recovery"
        state["recovery_started_at"] = now.isoformat()
        actions.save(state)
    else:
        log.warning("Non migliora, prossimo giro provaro' un altro servizio")
