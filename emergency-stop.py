#!/usr/bin/env python3
"""Emergency Stop — spegne servizi non critici quando il server soffre.

Questo file e' l'entrypoint: contiene main() e i wrapper che risolvono i
nomi nel namespace di questo modulo. La logica vera vive nei moduli di
`downscaler/` (config, services, monitoring, docker_ops, state, incidents).

Logica:
1. Health check: riavvia servizi down che non sono stati spenti dal sistema
   (salta gli one-shot e quelli con can_restart: false)
2. Media mobile: campiona ogni 30s, media su finestra 2 min
3. Isteresi: stop se iowait > soglia_iowait OPPURE load > soglia_load,
   recovery solo se ENTRAMBE < soglie
4. Stop graduale: un servizio alla volta (due sopra la soglia critica),
   poi passa al successivo
5. Recovery graduale: un servizio ogni restart_delay, solo a metriche calate
6. Notifiche Telegram: inizio downscale, inizio recovery, fine incidente
7. Snapshot incidente: log e metriche salvati su disco per analisi post-incidente

Dentro il container (mount dal compose):
  config:   /app/config.yaml
  servizi:  /app/services/<nome>.yaml
  stato:    /app/state/state.json
  log:      /app/logs/emergency-stop.log

Sulla macchina host:
  compose:  /mnt/applicazioni/yml/docker/emergency-stop/docker-compose.yml
  servizi:  /mnt/applicazioni/yml/docker/emergency-stop/services/*.yaml
  log:      /var/log/emergency-stop.log
  incidenti: /mnt/applicazioni/yml/docker/emergency-stop/incidents/<timestamp>/

Modalita': --validate controlla la config, --dry-run mostra cosa farebbe
senza toccare Docker ne lo stato, --selftest prova i file di servizio
senza Docker.

Simulazione: --simulate-iowait VAL e --simulate-load VAL sovrascrivono
le metriche lette da Glances (utili per test senza carico reale).
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from pathlib import Path

# I test patchano MODULE.subprocess.run e MODULE.time.sleep (oggetti stdlib
# condivisi): i nomi devono esistere in questo modulo anche se il codice non
# li usa piu'.
import subprocess  # noqa: F401
import time  # noqa: F401
import types

# I test patchano MODULE.requests (modulo condiviso, come subprocess e time):
# il nome deve esistere in questo modulo anche se il codice non lo usa.
import requests  # noqa: F401

from downscaler import config as config_mod
from downscaler import docker_ops, monitoring, services
from downscaler.config import CONFIG_PATH, SERVICES_DIR, STATE_PATH, _merge_defaults, _normalize_state
# I test leggono module.DEFAULTS: il nome deve esistere in questo modulo.
from downscaler.config import DEFAULTS  # noqa: F401
from downscaler.docker_ops import is_service_running as _docker_is_service_running
from downscaler.docker_ops import start_service, stop_service as _docker_stop_service
# I test chiamano module._which: il nome deve esistere in questo modulo.
from downscaler.docker_ops import _which  # noqa: F401
from downscaler.incidents import (
    collect_incident_snapshot as _collect_incident_snapshot,
    send_incident_report as _send_incident_report,
)
from downscaler.monitoring import (
    Actions,
    fmt_metric,
    get_glances_metrics,
    health_check as _monitoring_health_check,
)
# I test chiamano module.update_window: il nome deve esistere nel namespace di
# questo modulo anche se il codice non lo usa.
from downscaler.monitoring import update_window  # noqa: F401
# I test patchano module._glances_get: il nome deve esistere in questo modulo.
from downscaler.monitoring import _glances_get  # noqa: F401
from downscaler.services import check_service_files as _services_check_service_files
from downscaler.state import load_state as _load_state
from downscaler.state import save_state as _save_state, send_telegram

log = config_mod.log
running_containers = docker_ops.running_containers


# DRY_RUN e' un alias VIVO di config_mod.DRY_RUN: i flag --dry-run/--no-dry-run
# scrivono config_mod.DRY_RUN e i test scrivono module.DRY_RUN. Un semplice
# `from downscaler.config import DRY_RUN` congelerebbe il valore all'import,
# quindi le due scritture non si vedrebbero piu'.
# La property deve vivere sul TIPO del modulo. `__class__ = X` come nome
# globale non basta: __class__ e' un descrittore dati (ha la precedenza sul
# __dict__ del modulo), quindi l'assegnazione finirebbe in __dict__ e il tipo
# dell'oggetto resterebbe ModuleType. Serve assegnare l'attributo sull'oggetto
# modulo, che durante l'esecuzione del modulo e' sempre in sys.modules.
# N802: il nome della property DEVE restare DRY_RUN (e' l'alias del nome di
# config_mod), quindi il metodo non si puo' rinominare in minuscolo.
class _EmergencyModule(types.ModuleType):
    @property
    def DRY_RUN(self) -> bool:  # noqa: N802
        return config_mod.DRY_RUN

    @DRY_RUN.setter
    def DRY_RUN(self, value: bool) -> None:  # noqa: N802
        config_mod.DRY_RUN = value


sys.modules[__name__].__class__ = _EmergencyModule


def _parse_args() -> argparse.Namespace:
    """Argomenti da riga di comando."""
    parser = argparse.ArgumentParser(description="Emergency Stop")
    parser.add_argument("--validate", action="store_true", help="valida la configurazione e esci")
    parser.add_argument("--selftest", action="store_true", help="valida i file di servizio senza Docker")
    parser.add_argument("--dry-run", action="store_true", help="mostra cosa farebbe, senza toccare Docker ne lo stato")
    parser.add_argument("--no-dry-run", action="store_true", help="esegue davvero (annulla DRY_RUN=true del compose)")
    parser.add_argument("--simulate-iowait", type=float, help="simula un valore iowait (sovrascrive Glances)")
    parser.add_argument("--simulate-load", type=float, help="simula un valore load (sovrascrive Glances)")
    return parser.parse_args()


def load_services(services_dir: Path | None = None, log_missing: bool = True) -> list[dict]:
    """Legge i file di servizio dal namespace di questo modulo."""
    return services.load_services(services_dir or SERVICES_DIR, log_missing=log_missing)


def load_state() -> dict:
    """Carica lo stato da STATE_PATH di questo modulo (patchabile dai test)."""
    return _load_state(STATE_PATH)


def save_state(state: dict) -> None:
    """Salva lo stato su STATE_PATH di questo modulo (patchabile dai test)."""
    _save_state(state, STATE_PATH)


def health_check(services_list: list[dict], state: dict) -> None:
    """Riavvia i servizi down non spenti dal sistema (wrapper iniettato)."""
    _monitoring_health_check(services_list, state, running_check=running_containers, start_fn=start_service)


def is_service_running(service: dict) -> bool:
    """True se almeno un container del servizio e' in esecuzione."""
    return _docker_is_service_running(service, running_check=running_containers)


def stop_service(service: dict) -> bool:
    """Ferma un servizio (wrapper iniettato: is_running di questo modulo)."""
    return _docker_stop_service(service, is_running=is_service_running)


def collect_incident_snapshot(
    config: dict, services_list: list[dict], state: dict, now: datetime, phase: str
) -> Path | None:
    """Snapshot dell'incidente: inietta get_glances_metrics di questo modulo."""
    return _collect_incident_snapshot(config, services_list, state, now, phase, metrics_fn=get_glances_metrics)


def send_incident_report(snapshot_dir: Path, state: dict, config: dict) -> None:
    """Report finale dell'incidente: inietta send_telegram di questo modulo."""
    _send_incident_report(snapshot_dir, state, config, notify_fn=send_telegram)


def check_service_files(services_list: list[dict], config: dict) -> bool:
    """Valida i file di servizio (wrapper iniettato: running_check e metrics_fn).

    Il flag `selftest` vive su questa funzione (lo alza main con --selftest e
    i test per simulare la modalita' senza Docker): lo ritrasmette.
    """
    return _services_check_service_files(
        services_list,
        config,
        running_check=running_containers,
        metrics_fn=get_glances_metrics,
        selftest=check_service_files.selftest,
    )


# Default del flag --selftest: main lo alza per la modalita' senza Docker.
check_service_files.selftest = False


def _build_actions() -> Actions:
    """Effetti collaterali del ciclo, risolti nel namespace di questo modulo."""
    return Actions(
        save=save_state,
        notify=send_telegram,
        stop=stop_service,
        start=start_service,
        snapshot=collect_incident_snapshot,
        report=send_incident_report,
        sample=get_glances_metrics,
    )


def _log_metrics(
    config: dict,
    iowait_val: float | None,
    avg_iowait: float | None,
    load_val: float | None,
    avg_load: float | None,
) -> None:
    """Logga valore corrente e media mobile delle due metriche."""
    monitor = config["monitor"]
    parts = []
    if iowait_val is not None:
        parts.append(f"iowait={fmt_metric(iowait_val)}" + (f" media={fmt_metric(avg_iowait)}" if avg_iowait is not None else ""))
    if load_val is not None:
        parts.append(f"load={fmt_metric(load_val)}" + (f" media={fmt_metric(avg_load)}" if avg_load is not None else ""))
    log.info(
        f"Check: {' | '.join(parts)} "
        f"(stop>iowait:{monitor['stop_threshold']} load:{monitor['load_stop_threshold']}, "
        f"restart<iowait:{monitor['restart_threshold']} load:{monitor['load_restart_threshold']})"
    )


def main() -> None:
    """Un giro del downscaler: health check, campionamento, monitor/recovery."""
    args = _parse_args()
    if not CONFIG_PATH.exists():
        log.error(f"Config non trovato: {CONFIG_PATH}")
        sys.exit(1)
    if args.no_dry_run:
        config_mod.DRY_RUN = False
    elif args.dry_run:
        config_mod.DRY_RUN = True

    config = _merge_defaults(yaml.safe_load(CONFIG_PATH.read_text()))
    services_list = load_services(SERVICES_DIR)

    if args.selftest:
        check_service_files.selftest = True
        sys.exit(0 if check_service_files(services_list, config) else 1)
    if args.validate:
        sys.exit(0 if check_service_files(services_list, config) else 1)

    state = _normalize_state(load_state())
    if config_mod.DRY_RUN:
        log.info("=== DRY-RUN: nessuna azione reale verra' eseguita ===")

    health_check(services_list, state)
    actions = _build_actions()
    sampled = monitoring.sample_metrics(config, state, args.simulate_iowait, args.simulate_load)
    if sampled is None:
        # Metriche non leggibili: non decidere nulla. Tornare 0.0 qui
        # significherebbe "tutto ok", che era il bug originale.
        log.error("Salto questo giro: metriche non leggibili")
        return
    iowait_val, load_val, avg_iowait, avg_load = sampled
    actions.save(state)
    _log_metrics(config, iowait_val, avg_iowait, load_val, avg_load)

    now = datetime.now()
    if state["mode"] == "recovery":
        monitoring.handle_recovery(config, services_list, state, avg_iowait, avg_load, now, actions)
    else:
        monitoring.handle_monitor(config, services_list, state, avg_iowait, avg_load, now, actions)


if __name__ == "__main__":
    main()
