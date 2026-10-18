"""Fixture condivise dai test di emergency-stop.py.

Il modulo viene caricato UNA sola volta per sessione (fixture `module`). I
path (log/stato/config/servizi) sono puntati su /tmp dal conftest.py di root,
impostati PRIMA dell'import: emergency-stop.py chiama _setup_logging() al
caricamento del modulo.
"""

import importlib.util
import json
import sys
import tokenize
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO / "emergency-stop.py"


@pytest.fixture(scope="session")
def module():
    """Il modulo emergency-stop.py caricato dal disco, condiviso dai test."""
    spec = importlib.util.spec_from_file_location("emergency_stop", MODULE_PATH)
    loaded = importlib.util.module_from_spec(spec)
    sys.modules["emergency_stop"] = loaded
    spec.loader.exec_module(loaded)
    return loaded


@pytest.fixture(autouse=True)
def _isolamento_modulo(module, monkeypatch):
    """Ogni test parte da DRY_RUN=False e senza sleep: niente attese ne stati spurii."""
    monkeypatch.setattr(module, "DRY_RUN", False)
    monkeypatch.setattr(module.time, "sleep", lambda seconds: None)
    yield
    module.DRY_RUN = False


@pytest.fixture
def servizio():
    """Costruisce un servizio gestibile (dict) con valori sensati."""

    def _make(nome, priority=60, can_restart=None, can_stop=None, one_shot=None):
        return {
            "name": nome,
            "compose_dir": Path("/x"),
            "compose_file": "docker-compose.yml",
            "service_names": [f"{nome}-app-1"],
            "can_stop": True if can_stop is None else can_stop,
            "can_restart": True if can_restart is None else can_restart,
            "one_shot": False if one_shot is None else one_shot,
            "priority": priority,
            "note": "",
        }

    return _make


@pytest.fixture
def scrivi_servizio(tmp_path):
    """Scrive un file di servizio YAML in tmp_path e ne ritorna il path."""

    def _write(nome, corpo):
        percorso = tmp_path / nome
        percorso.write_text(corpo)
        return percorso

    return _write


@pytest.fixture
def avvia_main(module, monkeypatch):
    """Prepara il giro di main() senza Docker: niente container, niente rete.

    Glances e' sostituito dai valori simulati degli argv, i container sono
    sempre assenti e i file di servizio sono forniti dal chiamante.
    """

    def _run(tmp_path, argv, state=None, services=None, running=None, config=None):
        monkeypatch.setattr(module, "CONFIG_PATH", config or (REPO / "config.yaml"))
        state_path = tmp_path / "state.json"
        if state is not None:
            state_path.write_text(json.dumps(state))
        monkeypatch.setattr(module, "STATE_PATH", state_path)
        if services is not None:
            monkeypatch.setattr(module, "load_services", lambda directory: services)
        monkeypatch.setattr(module, "running_containers", running or (lambda names: []))
        monkeypatch.setattr(sys, "argv", argv)
        return state_path

    return _run


@pytest.fixture
def cattura_stati(module, monkeypatch):
    """Intercetta save_state: i test leggono lo stato anche in dry-run."""

    def _install():
        salvati = []
        monkeypatch.setattr(module, "save_state", lambda state: salvati.append(json.loads(json.dumps(state))))
        return salvati

    return _install


@pytest.fixture
def solo_codice():
    """Contenuto del file senza commenti ne stringhe (docstring incluse)."""

    def _only_code(percorso):
        with percorso.open(encoding="utf-8") as handle:
            tokens = list(tokenize.generate_tokens(handle.readline))
        saltati = (tokenize.COMMENT, tokenize.STRING)
        return "".join(tok.string for tok in tokens if tok.type not in saltati)

    return _only_code


class FakeResponse:
    """Risposta HTTP minima per sostituire requests.get/post nei test."""

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


@pytest.fixture
def http_response():
    """La classe FakeResponse, per costruire risposte finte."""
    return FakeResponse


@pytest.fixture
def mock_docker(module, monkeypatch):
    """Nessun container in esecuzione e nessuna chiamata reale a docker."""
    comandi = []
    monkeypatch.setattr(module, "running_containers", lambda names: [])

    def fake_run(*args, **kwargs):
        comandi.append(args[0])
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    return comandi


@pytest.fixture
def mock_glances(module, monkeypatch):
    """Metriche finte: il test non dipende da un Glances reale."""
    valori = {"iowait": 1.0, "load": 1.0}
    monkeypatch.setattr(module, "get_glances_metrics", lambda config, *a, **k: (valori["iowait"], valori["load"]))
    return valori


def pytest_terminal_summary(terminalreporter):
    """DIAGNOSTICA TEMPORANEA: i test falliti come annotazioni di CI (::error::)."""
    failed = list(terminalreporter.stats.get("failed", [])) + list(terminalreporter.stats.get("error", []))
    for rep in failed[:10]:
        detail = ""
        longrepr = getattr(rep, "longrepr", None)
        if longrepr is not None:
            righe = [riga for riga in str(longrepr).splitlines() if riga.strip()]
            detail = righe[-1] if righe else ""
        print(f"::error::FAIL {rep.nodeid} - {detail}", flush=True)
