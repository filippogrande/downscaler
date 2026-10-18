"""Comandi docker: disponibilita' del CLI, stato dei container, stop e start."""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from downscaler import config as config_mod

log = config_mod.log


def _docker_available() -> bool:
    """True se il CLI docker e' raggiungibile.

    L'immagine deve installarlo (`apk add docker-cli`): senza il binario ogni
    chiamata solleva FileNotFoundError e il container riparte in loop.
    """
    return Path("/usr/bin/docker").exists() or _which("docker") is not None


def _which(program: str) -> str | None:
    """Percorso dell'eseguibile in PATH, o None se assente."""
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(directory) / program
        if candidate.is_file():
            return str(candidate)
    return None


def running_containers(service_names: list[str]) -> list[str]:
    """Container in esecuzione il cui nome e' in `service_names` (confronto esatto).

    Senza CLI docker ritorna [] e lo segnala una volta: non e' un crash,
    e' l'immagine sbagliata (manca docker-cli).
    """
    if not service_names:
        return []
    try:
        ps = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except FileNotFoundError:
        log.error("CLI docker non trovata nel container: serve `apk add docker-cli`")
        return []
    wanted = set(service_names)
    return [line.strip() for line in ps.stdout.splitlines() if line.strip() in wanted]


def is_service_running(service: dict, running_check: Callable[[list[str]], list[str]] | None = None) -> bool:
    """True se almeno un container del servizio e' in esecuzione.

    `running_check` e' iniettato: i test patchano il nome a livello di modulo
    di emergency-stop, non questa funzione.
    """
    check = running_check or running_containers
    return bool(check(service["service_names"]))


def _compose_cmd(service: dict) -> list[str]:
    """Comando `docker compose -f <file>` per il servizio."""
    return ["docker", "compose", "-f", str(service["compose_dir"] / service["compose_file"])]


def stop_service(service: dict) -> bool:
    """Ferma un servizio con docker compose down (mai in --dry-run)."""
    cmd = _compose_cmd(service) + ["down"]
    if config_mod.DRY_RUN:
        log.info(f"[dry-run] STOP: {service['name']} -> {' '.join(cmd)}")
        return True
    log.info(f"STOP: {service['name']} -> {' '.join(cmd)}")
    result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        log.error(f"Errore stop {service['name']}: {result.stderr}")
        return False
    time.sleep(5)
    if is_service_running(service):
        log.error(f"{service['name']} ancora attivo dopo down!")
        return False
    log.info(f"OK {service['name']} spento correttamente")
    return True


def start_service(service: dict) -> bool:
    """Riaccende un servizio con docker compose up -d (mai in --dry-run)."""
    cmd = _compose_cmd(service) + ["up", "-d"]
    if config_mod.DRY_RUN:
        log.info(f"[dry-run] START: {service['name']} -> {' '.join(cmd)}")
        return True
    log.info(f"START: {service['name']} -> {' '.join(cmd)}")
    result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        log.error(f"Errore start {service['name']}: {result.stderr}")
        return False
    log.info(f"OK {service['name']} riavviato")
    return True
