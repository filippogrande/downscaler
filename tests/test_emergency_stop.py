"""Test di emergency-stop.py.

Coprono la logica pura (media mobile, selezione del candidato) e la
costruzione della config dei servizi, senza Docker ne file di stato reali.

I path (log/stato/config/servizi) sono in /tmp via conftest.py, impostati
PRIMA dell'import: emergency-stop.py chiama _setup_logging() al caricamento.
"""

import importlib.util
import sys
from collections import deque
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
    assert MODULE.update_window(window, 40.0, 120, 30) == 30.0
    # la finestra tiene al massimo 120/30 = 4 campioni
    assert len(window) == 4


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
    monkeypatch.setattr(
        MODULE.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(
            returncode=0,
            stdout="sonarr\nsonarr-anime\nprowlarr\nprowlarr_flaresolverr\n",
            stderr="",
        ),
    )

    assert MODULE.running_containers(["sonarr"]) == ["sonarr"]
    assert MODULE.running_containers(["prowlarr"]) == ["prowlarr"]
    assert MODULE.running_containers(["suwayomi-nsfw"]) == ["suwayomi-nsfw"]


def test_is_service_running_true_con_un_container():
    service = {"name": "x", "service_names": ["x-app-1"]}

    class FakeContainers:
        def __call__(self, names):
            return ["x-app-1"] if "x-app-1" in names else []

    MODULE.running_containers = FakeContainers()
    assert MODULE.is_service_running(service) is True


# ─── Config d'esempio del repo ───────────────────────────────────────────────


def test_i_18_file_di_esempio_sono_tutti_validi():
    directory = REPO / "examples" / "services"
    files = sorted(directory.glob("*.yaml"))

    assert len(files) == 18, f"attesi 18 file di servizio, trovati {len(files)}"

    for path in files:
        data = yaml.safe_load(path.read_text())
        assert isinstance(data, dict), f"{path.name}: non e' un mapping"
        assert data.get("name"), f"{path.name}: manca 'name'"
        assert data.get("compose_dir"), f"{path.name}: manca 'compose_dir'"
        assert isinstance(data.get("priority"), int), f"{path.name}: priority non e' un intero"


def test_config_yaml_del_repo_e_valido():
    data = yaml.safe_load((REPO / "config.yaml").read_text())

    assert data["glances"]["url"].startswith("http")
    assert data["monitor"]["metric"] in ("iowait", "load")
    assert data["monitor"]["stop_threshold"] > data["monitor"]["restart_threshold"]
    assert data["monitor"]["window_sec"] > 0


def test_nessun_compose_con_placeholder():
    # La regola e' valori letterali: nessun ${} o build: nei compose.
    text = (REPO / "docker-compose.yml").read_text()

    assert "${" not in text, "il compose non deve usare interpolazione"
    assert "build:" not in text, "il compose deve solo pullare, non buildare"
