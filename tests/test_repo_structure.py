"""Test della struttura del repo: Dockerfile, compose, esempi, config.yaml."""

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent


def test_il_dockerfile_installa_il_cli_docker():
    """Il downscaler chiama il CLI docker: deve essere nell'immagine.

    Senza `apk add docker-cli` il container parte in restart loop con
    FileNotFoundError: 'docker' (verificato 17/10/26).
    """
    dockerfile = (REPO / "Dockerfile").read_text()

    assert "docker-cli" in dockerfile, "il Dockerfile deve installare docker-cli"


def test_il_dockerfile_installa_il_plugin_compose():
    """`docker compose` e' un PLUGIN: serve docker-cli-compose, non solo docker-cli.

    Regressione verificata 17/10/26: con solo docker-cli, `docker compose -f ...`
    fallisce con "unknown shorthand flag: 'f' in -f" perche' docker interpreta
    `compose` come un comando proprio.
    """
    dockerfile = (REPO / "Dockerfile").read_text()

    assert "docker-cli-compose" in dockerfile, (
        "il Dockerfile deve installare docker-cli-compose (plugin Compose)"
    )


def test_il_compose_monta_il_socket_docker():
    """Il CLI docker parla col daemon attraverso il socket montato dal compose."""
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text())
    services = compose.get("services", {})

    assert services, "il compose non definisce servizi"
    for name, service in services.items():
        mounts = service.get("volumes", []) or []
        assert any("docker.sock" in str(m) for m in mounts), (
            f"{name}: manca il mount del socket docker"
        )


def test_il_compose_monta_le_directory_dei_servizi():
    """I compose_dir dei file servizio sono path assoluti dell'HOST.

    Senza questo mount il container non vede /mnt/applicazioni e TUTTI i
    servizi risultano con compose_dir inesistente (verificato 17/10/26).
    """
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text())
    services = compose.get("services", {})

    mounts = []
    for service in services.values():
        mounts.extend(service.get("volumes", []) or [])

    assert any("/mnt/applicazioni" in str(m) for m in mounts), (
        "il compose deve montare /mnt/applicazioni: i compose_dir sono path dell'host"
    )


def test_i_file_di_esempio_sono_tutti_validi():
    """Controlla i file di servizio d'esempio.

    Non si fissa il conteggio: i servizi cambiano quando il server cambia.
    Quello che non puo' cambiare e' che la directory esista e che ogni
    file sia un servizio leggibile.
    """
    directory = REPO / "examples" / "services"
    files = sorted(directory.glob("*.yaml"))

    assert directory.is_dir(), "manca examples/services/"
    assert files, "nessun file di servizio d'esempio"

    for path in files:
        data = yaml.safe_load(path.read_text())
        assert isinstance(data, dict), f"{path.name}: non e' un mapping"
        assert data.get("name"), f"{path.name}: manca 'name'"
        assert data.get("compose_dir"), f"{path.name}: manca 'compose_dir'"
        assert isinstance(data.get("priority"), int), f"{path.name}: priority non e' un intero"
        assert str(data.get("compose_dir", "")).startswith("/"), (
            f"{path.name}: compose_dir deve essere un path assoluto"
        )


def test_config_yaml_del_repo_e_valido():
    data = yaml.safe_load((REPO / "config.yaml").read_text())

    assert data["glances"]["url"].startswith("http")
    assert data["monitor"]["metric"] in ("iowait", "load")
    assert data["monitor"]["stop_threshold"] > data["monitor"]["restart_threshold"]
    assert data["monitor"]["window_sec"] > 0
    # le chiavi nuove esistono nel config del repo (altrimenti il default le copre)
    assert "load_stop_threshold" in data["monitor"]
    assert "load_restart_threshold" in data["monitor"]


def test_config_yaml_del_repo_ha_le_soglie_super():
    """Le soglie critiche del super-stop sono documentate nel config del repo."""
    data = yaml.safe_load((REPO / "config.yaml").read_text())

    assert data["monitor"]["load_super_threshold"] == 11.0
    assert data["monitor"]["iowait_super_threshold"] == 95.0


def test_nessun_compose_con_placeholder_nella_struttura():
    """Il compose non deve usare interpolazione ne build locale.

    Si confronta la struttura YAML, non il testo: i commenti spiegano la
    regola e contengono la parola ${...} come esempio di cosa NON fare.
    """
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text())
    services = compose.get("services", {})

    assert "build" not in compose, "il compose deve solo pullare, non buildare"
    assert "env_file" not in compose, "il compose non deve usare env_file"

    for name, service in services.items():
        assert "$" not in str(service.get("environment", {})), (
            f"{name}: valori letterali, niente interpolazione"
        )
        assert "build" not in service, f"{name}: deve solo pullare"
