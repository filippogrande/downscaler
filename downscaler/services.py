"""Lettura e validazione dei file di servizio (services/<nome>.yaml)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

from downscaler.config import DEFAULT_COMPOSE_FILE, DEFAULT_PRIORITY, SERVICES_DIR, YAML_ERRORS, log


def load_services(services_dir: Path, log_missing: bool = True) -> list[dict]:
    """Legge i file di servizio e li ordina per priorita' (piu' bassa = prima)."""
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


def restartable_services(services: list[dict], state: dict) -> list[dict]:
    """Servizi che il health check puo' riavviare.

    Esclude gli one-shot (batch da cron, nessun container residente), quelli
    con can_restart=false e quelli gia' spenti dal sistema.
    """
    stopped = set(state.get("stopped_services", []))
    return [
        service
        for service in services
        if not service["one_shot"]
        and service["can_restart"]
        and service["name"] not in stopped
    ]


def check_service_files(services: list[dict], config: dict) -> bool:
    """Controlla i file di servizio. Ritorna True se tutto ok.

    Modalita' --selftest: solo file e nomi, niente Docker (utile dove non
    c'e' il socket Docker, o per controllare la config senza permessi).
    """
    # Import locali: monitoring importa questo modulo, quindi in testa si
    # creerebbe un ciclo (services -> monitoring -> services).
    from downscaler import docker_ops, monitoring

    selftest = getattr(check_service_files, "selftest", False)
    if not services:
        print(f"NESSUN SERVIZIO in {SERVICES_DIR} (atteso: un file <nome>.yaml per servizio)")
        return False

    print(f"\n=== Validazione {len(services)} servizi ===")
    ok = True
    for service in services:
        ok = _check_one_service(service, selftest, docker_ops.running_containers) and ok

    print("\n=== Glances ===")
    ok = ok and _check_glances(config, monitoring.get_glances_metrics)
    print(f"\n=== Esito: {'OK' if ok else 'ERRORI'} ===")
    return ok


def _check_one_service(service: dict, selftest: bool, running_check) -> bool:
    """Validazione di un servizio: compose_dir, compose file e container."""
    name = service["name"]
    compose_file = service["compose_dir"] / service["compose_file"]
    if not service["compose_dir"].is_dir():
        print(f"  X {name}: compose_dir non esiste ({service['compose_dir']})")
        return False
    if not compose_file.is_file():
        print(f"  X {name}: compose file non trovato ({compose_file})")
        return False
    names = ", ".join(service["service_names"])
    print(f"  OK {name}: {service['compose_dir']} [{names}] priority={service['priority']}")
    if selftest:
        # Senza Docker si controlla solo che i path esistano
        return True
    if not _compose_is_valid(compose_file):
        return False
    return _check_running(service, running_check)


def _compose_is_valid(compose_file: Path) -> bool:
    """`docker compose config -q` sul file del servizio."""
    check = subprocess.run(
        ["docker", "compose", "-f", str(compose_file), "config", "-q"],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if check.returncode != 0:
        print(f"  X {compose_file.parent.name}: compose non valido: {check.stderr.strip()[:200]}")
        return False
    return True


def _check_running(service: dict, running_check) -> bool:
    """Controlla che il servizio abbia un container in esecuzione."""
    name = service["name"]
    running = running_check(service["service_names"])
    if service["one_shot"]:
        print(f"    one_shot: non residente (container: {', '.join(running) if running else 'nessuno'})")
        return True
    if not service["can_stop"] and not service["can_restart"]:
        print("    skip: can_stop=false can_restart=false → non gestito")
        return True
    if running:
        return True
    expected = ", ".join(service["service_names"])
    print(f"  ! {name}: NESSUN container in esecuzione (atteso: {expected})")
    return False


def _check_glances(config: dict, read_metrics) -> bool:
    """Controlla la configurazione di Glances e la lettura delle metriche."""
    base_url = config["glances"]["url"]
    if not base_url:
        print("  X glances.url mancante")
        return False
    print(f"  url: {base_url}  metrica: {config['monitor']['metric']}")
    iowait_val, load_val = read_metrics(config)
    if iowait_val is None and load_val is None:
        print("  X metriche non leggibili da Glances")
        return False
    if iowait_val is not None:
        print(f"  OK iowait={iowait_val:.1f}")
    if load_val is not None:
        print(f"  OK load={load_val:.1f}")
    return True
