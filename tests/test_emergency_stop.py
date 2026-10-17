"""Test di emergency-stop.py.

Coprono la logica pura (media mobile, selezione del candidato) e la
costruzione della config dei servizi, senza Docker ne file di stato reali.

I path (log/stato/config/servizi) sono in /tmp via conftest.py in root,
impostati PRIMA dell'import: emergency-stop.py chiama _setup_logging()
al caricamento del modulo.
"""

import importlib.util
import json
import logging
import sys
import tokenize
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import yaml

REPO = Path(__file__).resolve().parent.parent

SPEC = importlib.util.spec_from_file_location("emergency_stop", REPO / "emergency-stop.py")
MODULE = importlib.util.module_from_spec(SPEC)

sys.modules["emergency_stop"] = MODULE
SPEC.loader.exec_module(MODULE)


# ─── Media mobile ────────────────────────────────────────────────────────────

def test_update_window_campiona_e_limita_la_finestra():
    window = deque()
    assert MODULE.update_window(window, 10.0, 120, 30) == 10.0
    assert MODULE.update_window(window, 20.0, 120, 30) == 15.0
    assert MODULE.update_window(window, 30.0, 120, 30) == 20.0
    # il quarto campione riempie la finestra (max 120/30 = 4)
    assert MODULE.update_window(window, 40.0, 120, 30) == 25.0
    assert len(window) == 4
    # il quinto spiazza il piu' vecchio: resta [20, 30, 40, 50]
    assert MODULE.update_window(window, 50.0, 120, 30) == 35.0
    assert list(window) == [20.0, 30.0, 40.0, 50.0]

def test_update_window_vuota_non_divide_per_zero():
    assert MODULE.update_window(deque(), 5.0, 120, 30) == 5.0


# ─── Config servizi ──────────────────────────────────────────────────────────

def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body)
    return path

def test_load_services_ordina_per_priorita(tmp_path):
    _write(tmp_path, "b.yaml", "name: b\npriority: 50\ncompose_dir: /x\n")
    _write(tmp_path, "a.yaml", "name: a\npriority: 10\ncompose_dir: /x\n")
    _write(tmp_path, "c.yaml", "name: c\npriority: 30\ncompose_dir: /x\n")

    services = MODULE.load_services(tmp_path)

    assert [s["name"] for s in services] == ["a", "c", "b"]

def test_load_services_flag_default(tmp_path):
    _write(tmp_path, "a.yaml", "name: a\ncompose_dir: /x\n")

    service = MODULE.load_services(tmp_path)[0]

    assert service["can_stop"] is True
    assert service["can_restart"] is True
    assert service["one_shot"] is False
    assert service["priority"] == 100
    # service_name assente = il nome del servizio
    assert service["service_names"] == ["a"]

def test_load_services_accetta_nomi_multipli(tmp_path):
    _write(
        tmp_path,
        "a.yaml",
        "name: suwayomi\ncompose_dir: /x\nservice_name:\n  - suwayomi-sfw\n  - suwayomi-nsfw\n",
    )

    assert MODULE.load_services(tmp_path)[0]["service_names"] == [
        "suwayomi-sfw",
        "suwayomi-nsfw",
    ]

def test_load_services_scarta_file_vuoto(tmp_path):
    _write(tmp_path, "empty.yaml", "")
    _write(tmp_path, "ok.yaml", "name: ok\ncompose_dir: /x\n")

    names = [s["name"] for s in MODULE.load_services(tmp_path)]

    assert names == ["ok"]

def test_load_services_scarta_senza_nome(tmp_path):
    _write(tmp_path, "bad.yaml", "priority: 10\ncompose_dir: /x\n")

    assert MODULE.load_services(tmp_path) == []

def test_load_services_ignora_yaml_non_mapping(tmp_path):
    _write(tmp_path, "list.yaml", "- uno\n- due\n")

    assert MODULE.load_services(tmp_path) == []

def test_load_services_directory_mancante():
    assert MODULE.load_services(Path("/non-esiste")) == []


# ─── Matching dei container ───────────────────────────────────────────────────

def test_running_containers_confronto_esatto(monkeypatch):
    # Il vecchio 'name=X' matchava per sottostringa: sonarr matchava anche
    # sonarr-anime. Questo test blocca la regressione.
    #
    # Nota: prowlarr e prowlarr_flaresolverr sono nello STESSO compose, quindi
    # 'docker compose down' li ferma insieme (comportamento voluto). Il matching
    # dei nomi resta esatto: flaresolverr non si ferma da solo.
    nomi = "sonarr\nsonarr-anime\nprowlarr\nprowlarr_flaresolverr\nsuwayomi-nsfw\n"

    def fake_run(*args, **kwargs):
        return SimpleNamespace(returncode=0, stdout=nomi, stderr="")

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)

    assert MODULE.running_containers(["sonarr"]) == ["sonarr"]
    assert MODULE.running_containers(["prowlarr"]) == ["prowlarr"]
    assert MODULE.running_containers(["suwayomi-nsfw"]) == ["suwayomi-nsfw"]
    # un nome non presente non viene inventato
    assert MODULE.running_containers(["assente"]) == []
    # senza nomi non si chiama nemmeno docker
    assert MODULE.running_containers([]) == []

def test_running_containers_non_crasha_senza_cli_docker(monkeypatch):
    """Senza il binario docker nel PATH il modulo non deve crashare.

    Regressione verificata 17/10/26: l'immagine non aveva docker-cli, quindi
    `docker ps` sollevava FileNotFoundError e il container ripartiva in loop.
    Il health check deve saltare il servizio, non portare giu' tutto.
    """
    err_msg = "[Errno 2] No such file or directory: 'docker'"

    def fake_run(*args, **kwargs):
        raise FileNotFoundError(err_msg)

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)

    assert MODULE.running_containers(["sonarr"]) == []

def test_is_service_running_false_senza_cli_docker(monkeypatch):
    """Senza CLI docker il servizio non e' 'in esecuzione': meglio non riavviarlo."""
    err_msg = "[Errno 2] No such file or directory: 'docker'"

    def fake_run(*args, **kwargs):
        raise FileNotFoundError(err_msg)

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)

    service = {"name": "x", "service_names": ["x-app-1"]}
    assert MODULE.is_service_running(service) is False

def test_is_service_running_true_con_un_container():
    service = {"name": "x", "service_names": ["x-app-1"]}

    class FakeContainers:
        def __call__(self, names):
            return ["x-app-1"] if "x-app-1" in names else []

    MODULE.running_containers = FakeContainers()
    assert MODULE.is_service_running(service) is True


# ─── Default per chiavi mancanti ─────────────────────────────────────────────

def test_config_vecchio_senza_chiavi_nuove():
    """Un config senza le chiavi aggiunte dopo non deve sollevare KeyError.

    Regressione verificata 17/10/26: il config locale non aveva
    load_stop_threshold e il container partiva in restart loop.
    """
    config_vecchio = {
        "glances": {"url": "http://10.0.0.5:61208"},
        "monitor": {
            "metric": "iowait",
            "sample_interval_sec": 30,
            "window_sec": 120,
            "stop_threshold": 80.0,
            "restart_threshold": 60.0,
        },
    }

    merged = MODULE._merge_defaults(config_vecchio)

    # le chiavi nuove prendono il default, non sollevano KeyError
    assert merged["monitor"]["load_stop_threshold"] == 6.0
    assert merged["monitor"]["load_restart_threshold"] == 4.0
    # le chiavi presenti non vengono toccate
    assert merged["monitor"]["stop_threshold"] == 80.0

def test_config_con_incidents_default():
    """Un config senza la sezione incidents usa i valori di default."""
    config_vecchio = {"glances": {"url": "http://x"}}

    merged = MODULE._merge_defaults(config_vecchio)

    assert merged["incidents"]["enabled"] is True
    assert merged["incidents"]["log_tail"] == 20000
    assert merged["incidents"]["log_window_min"] == 15

def test_stato_parziale_non_crasha():
    """Uno stato scritto da una versione precedente non deve rompere il health check.

    Regressione verificata 17/10/26: lo stato in dry-run aveva solo
    metric_window, quindi mancava stopped_services.
    """
    stato_parziale = {"metric_window": [1.0, 2.0]}

    normalized = MODULE._normalize_state(stato_parziale)

    assert normalized["stopped_services"] == []
    assert normalized["metric_window"] == [1.0, 2.0]
    # il health check deve poterlo leggere senza KeyError
    assert set(normalized["stopped_services"]) == set()

def test_load_state_con_file_illeggibile(tmp_path, monkeypatch):
    """Uno stato corrotto non deve bloccare il container."""
    state_path = tmp_path / "state.json"
    state_path.write_text("{ non e' json")
    monkeypatch.setattr(MODULE, "STATE_PATH", state_path)

    state = MODULE.load_state()

    assert state["mode"] == "monitor"
    assert state["stopped_services"] == []

def test_load_state_con_json_non_dict(tmp_path, monkeypatch):
    """Un JSON valido ma non un object (es. una lista) non deve bloccare."""
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps([1, 2, 3]))
    monkeypatch.setattr(MODULE, "STATE_PATH", state_path)

    state = MODULE.load_state()

    assert state["mode"] == "monitor"


# ─── Immagine: dipendenze di sistema ─────────────────────────────────────────

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


# ─── Config d'esempio del repo ───────────────────────────────────────────────

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
        # i compose_dir devono essere path assoluti: sono letti dall'host,
        # non dal container
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

def test_nessun_compose_con_placeholder_nella_struttura():
    """Il compose non deve usare interpolazione ne build locale.

    Si confronta la struttura YAML, non il testo: i commenti spiegano la
    regola e contengono la parola ${...} come esempio di cosa NON fare.
    """
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text())
    services = compose.get("services", {})

    assert "build" not in compose, "il compose deve solo pullare, non buildare"
    assert "env_file" not in compose, "il compose non deve usare env_file"

    # nessun servizio usa interpolazione ${...} nei valori
    for name, service in services.items():
        assert "$" not in str(service.get("environment", {})), f"{name}: valori letterali, niente interpolazione"
        assert "build" not in service, f"{name}: deve solo pullare"


# ─── Formattazione delle metriche nei log ───────────────────────────────────

def test_fmt_metric_formatta_e_gestisce_il_mancante():
    """0.0 e' un valore valido: non deve diventare 'N/A'."""
    assert MODULE.fmt_metric(20.1) == "20.1"
    assert MODULE.fmt_metric(0.0) == "0.0"
    assert MODULE.fmt_metric(None) == "N/A"


def _avvia_main(monkeypatch, argv, state_path):
    """Prepara il giro di main() senza Docker: niente container, niente rete.

    Glances e' sostituito dai valori simulati degli argv, i container sono
    sempre assenti e i file di servizio sono forniti dal chiamante: cosi' i
    test non dipendono da examples/ ne dal socket Docker.
    """
    monkeypatch.setattr(MODULE, "CONFIG_PATH", REPO / "config.yaml")
    monkeypatch.setattr(MODULE, "STATE_PATH", state_path)
    monkeypatch.setattr(MODULE, "running_containers", lambda names: [])
    monkeypatch.setattr(sys, "argv", argv)


def test_allarme_logga_invece_di_crasha(tmp_path, monkeypatch, caplog):
    """Il ramo di allarme deve scrivere il log, non sollevare ValueError.

    Regressione verificata 17/10/26: i log di allarme/recovery/post-stop
    contenevano la condizione dentro il format specifier (`{v:.1f if v ...}`),
    che Python rifiuta. Il crash era nel ramo di allarme, cioe' proprio quando
    il downscaler doveva spegnere un servizio.
    """
    servizio = {
        "name": "radarr",
        "compose_dir": Path("/x"),
        "compose_file": "docker-compose.yml",
        "service_names": ["radarr-radarr-1"],
        "can_stop": True,
        "can_restart": True,
        "one_shot": False,
        "priority": 60,
        "note": "",
    }
    monkeypatch.setattr(MODULE, "load_services", lambda directory: [servizio])
    _avvia_main(
        monkeypatch,
        ["emergency-stop", "--dry-run", "--simulate-iowait", "5", "--simulate-load", "430"],
        tmp_path / "state.json",
    )

    with caplog.at_level(logging.INFO, logger="emergency-stop"):
        MODULE.main()  # non deve sollevare

    testo = caplog.text
    assert "ALLARME: iowait_media=5.0" in testo
    assert "load_media=430.0" in testo

def test_recovery_logga_invece_di_crasha(tmp_path, monkeypatch, caplog):
    """Anche il ramo di recovery deve loggare, non sollevare ValueError.

    Stesso difetto del ramo di allarme. Qui lo stato e' gia' in modalita'
    recovery con le metriche ancora sopra soglia: e' il caso in cui quel
    log viene emesso. Il ramo post-stop invece e' nel cammino NON dry-run
    (c'e' il campionamento reale dopo il down) e non si puo' eseguire qui.
    """
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({
        "mode": "recovery",
        "recovery_started_at": "2020-01-01T00:00:00",
    }))
    monkeypatch.setattr(MODULE, "load_services", lambda directory: [])
    _avvia_main(
        monkeypatch,
        ["emergency-stop", "--dry-run", "--simulate-iowait", "430", "--simulate-load", "5"],
        state_path,
    )

    with caplog.at_level(logging.INFO, logger="emergency-stop"):
        MODULE.main()  # non deve sollevare

    testo = caplog.text
    assert "Recovery: ancora sopra soglia (iowait_media=430.0" in testo
    assert "load_media=5.0" in testo


def _solo_codice(percorso: Path) -> str:
    """Contenuto del file senza commenti ne stringhe (docstring incluse).

    Il pattern vietato va cercato nel codice vero: la docstring di fmt_metric
    lo cita per spiegare cosa NON fare, e sul testo grezzo farebbe scattare
    un falso positivo.
    """
    with percorso.open(encoding="utf-8") as handle:
        tokens = list(tokenize.generate_tokens(handle.readline))
    saltati = (tokenize.COMMENT, tokenize.STRING)
    return "".join(tok.string for tok in tokens if tok.type not in saltati)

def test_nessun_format_specifier_con_condizione():
    """Un selettore di formato non puo' contenere una condizione.

    Rete per il ramo post-stop, l'unico dei tre log che i test funzionali
    non eseguono. Si guarda il codice, non il testo: la docstring di
    fmt_metric cita il pattern per spiegarlo.
    """
    assert ".1f if " not in _solo_codice(REPO / "emergency-stop.py")


# ─── Incident snapshots ─────────────────────────────────────────────────────

def test_collect_incident_snapshot_salva_log_e_metriche(tmp_path, monkeypatch):
    """collect_incident_snapshot salva log, metrics e summary."""
    services = [
        {"name": "radarr", "service_names": ["radarr-radarr-1"]},
        {"name": "sonarr", "service_names": ["sonarr"]},
    ]

    log_calls = []
    def fake_run(*args, **kwargs):
        log_calls.append(args[0])
        return SimpleNamespace(returncode=0, stdout="log line", stderr="")

    monkeypatch.setattr(MODULE.subprocess, "run", fake_run)
    monkeypatch.setattr(MODULE, "get_glances_metrics", lambda config: (5.0, 430.0))

    config = {
        "incidents": {
            "dir": str(tmp_path / "incidents"),
            "log_tail": 20000,
            "log_window_min": 15,
        },
        "glances": {"url": "http://x"},
    }

    state = {
        "mode": "monitor",
        "incident_services": ["radarr"],
    }

    now = datetime(2026, 10, 17, 22, 30, 15, tzinfo=timezone.utc)
    result = MODULE.collect_incident_snapshot(config, services, state, now, "start")

    expected = tmp_path / "incidents" / "2026-10-17_22-30-15"
    assert result == expected
    assert (expected / "radarr-radarr-1.log").exists()
    assert (expected / "sonarr.log").exists()
    assert (expected / "metrics.json").exists()
    assert (expected / "summary.txt").exists()
    # 2 container, 2 chiamate a docker logs
    assert len(log_calls) == 2


def test_collect_incident_snapshot_disabilitato_non_fa_nulla(tmp_path, monkeypatch):
    """Con incidents.enabled false, non salva nulla."""
    config = {"incidents": {"enabled": False, "dir": str(tmp_path)}}
    result = MODULE.collect_incident_snapshot(config, [], {}, datetime(2026, 1, 1, tzinfo=timezone.utc), "start")
    assert result is None
    assert not (tmp_path / "2026-01-01_00-00-00").exists()


def test_send_incident_report_manda_telegram(tmp_path, monkeypatch):
    """send_incident_report invia il report con path e durata."""
    calls = []
    monkeypatch.setattr(MODULE, "send_telegram", lambda msg, config: calls.append(msg))

    snapshot_dir = tmp_path / "incidents" / "2026-10-17_22-30-15"
    state = {
        "incident_start": "2026-10-17T22:00:00",
        "incident_services": ["radarr", "sonarr"],
    }
    config = {"incidents": {"telegram_report": True}}

    MODULE.send_incident_report(snapshot_dir, state, config)

    assert len(calls) == 1
    assert "Incidente risolto" in calls[0]
    assert "radarr" in calls[0]
    assert "sonarr" in calls[0]
    assert str(snapshot_dir) in calls[0]


def test_send_incident_report_disabilitato_non_manda_nulla(tmp_path, monkeypatch):
    """Con incidents.telegram_report false, non invia nulla."""
    calls = []
    monkeypatch.setattr(MODULE, "send_telegram", lambda msg, config: calls.append(msg))

    config = {"incidents": {"telegram_report": False}}
    MODULE.send_incident_report(tmp_path, {}, config)

    assert calls == []
