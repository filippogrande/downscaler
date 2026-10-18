"""Test delle operazioni Docker: running_containers, is_service_running, stop_service, start_service."""

from types import SimpleNamespace


def test_running_containers_confronto_esatto(module, monkeypatch):
    """Il vecchio 'name=X' matchava per sottostringa: sonarr matchava anche sonarr-anime.

    Nota: prowlarr e prowlarr_flaresolverr sono nello STESSO compose, quindi
    'docker compose down' li ferma insieme (comportamento voluto). Il matching
    dei nomi resta esatto: flaresolverr non si ferma da solo.
    """
    nomi = "sonarr\nsonarr-anime\nprowlarr\nprowlarr_flaresolverr\nsuwayomi-nsfw\n"

    def fake_run(*args, **kwargs):
        return SimpleNamespace(returncode=0, stdout=nomi, stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    assert module.running_containers(["sonarr"]) == ["sonarr"]
    assert module.running_containers(["prowlarr"]) == ["prowlarr"]
    assert module.running_containers(["suwayomi-nsfw"]) == ["suwayomi-nsfw"]
    assert module.running_containers(["assente"]) == []
    assert module.running_containers([]) == []


def test_running_containers_non_crasha_senza_cli_docker(module, monkeypatch):
    """Senza il binario docker nel PATH il modulo non deve crashare.

    Regressione verificata 17/10/26: l'immagine non aveva docker-cli, quindi
    `docker ps` sollevava FileNotFoundError e il container ripartiva in loop.
    """

    def fake_run(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    assert module.running_containers(["sonarr"]) == []


def test_is_service_running_false_senza_cli_docker(module, monkeypatch):
    """Senza CLI docker il servizio non e' 'in esecuzione': meglio non riavviarlo."""

    def fake_run(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    servizio = {"name": "x", "service_names": ["x-app-1"]}
    assert module.is_service_running(servizio) is False


def test_is_service_running_true_con_un_container(module, monkeypatch):
    def fake_running(names):
        return ["x-app-1"] if "x-app-1" in names else []

    monkeypatch.setattr(module, "running_containers", fake_running)

    servizio = {"name": "x", "service_names": ["x-app-1"]}
    assert module.is_service_running(servizio) is True


def test_which_trova_eseguibile(module, monkeypatch, tmp_path):
    eseguibile = tmp_path / "docker"
    eseguibile.write_text("#!/bin/sh\n")
    monkeypatch.setenv("PATH", str(tmp_path))

    assert module._which("docker") == str(eseguibile)


def test_which_non_trova_eseguibile(module, monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))

    assert module._which("docker") is None


def test_stop_service_dry_run_non_chiama_docker(module, monkeypatch, servizio):
    monkeypatch.setattr(module, "DRY_RUN", True)
    comandi = []
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: comandi.append(args[0]))

    assert module.stop_service(servizio("radarr")) is True

    assert comandi == []


def test_stop_service_ok(module, monkeypatch, servizio):
    monkeypatch.setattr(module, "DRY_RUN", False)
    comandi = []
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: comandi.append(args[0])
        or SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    monkeypatch.setattr(module, "is_service_running", lambda s: False)

    assert module.stop_service(servizio("radarr")) is True

    assert comandi[0][:4] == ["docker", "compose", "-f", "/x/docker-compose.yml"]
    assert comandi[0][-1] == "down"


def test_stop_service_errore_restituisce_false(module, monkeypatch, servizio):
    monkeypatch.setattr(module, "DRY_RUN", False)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="boom"),
    )

    assert module.stop_service(servizio("radarr")) is False


def test_stop_service_ancora_attivo_restituisce_false(module, monkeypatch, servizio):
    monkeypatch.setattr(module, "DRY_RUN", False)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    monkeypatch.setattr(module, "is_service_running", lambda s: True)

    assert module.stop_service(servizio("radarr")) is False


def test_start_service_dry_run_non_chiama_docker(module, monkeypatch, servizio):
    monkeypatch.setattr(module, "DRY_RUN", True)
    comandi = []
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: comandi.append(args[0]))

    assert module.start_service(servizio("radarr")) is True

    assert comandi == []


def test_start_service_ok(module, monkeypatch, servizio):
    monkeypatch.setattr(module, "DRY_RUN", False)
    comandi = []
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: comandi.append(args[0])
        or SimpleNamespace(returncode=0, stdout="", stderr=""),
    )

    assert module.start_service(servizio("radarr")) is True

    assert comandi[0][-2:] == ["up", "-d"]


def test_start_service_errore_restituisce_false(module, monkeypatch, servizio):
    monkeypatch.setattr(module, "DRY_RUN", False)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="boom"),
    )

    assert module.start_service(servizio("radarr")) is False
