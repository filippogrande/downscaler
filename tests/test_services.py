"""Test dei file di servizio: load_services e check_service_files."""

from pathlib import Path
from types import SimpleNamespace


def test_load_services_ordina_per_priorita(module, scrivi_servizio, tmp_path):
    scrivi_servizio("b.yaml", "name: b\npriority: 50\ncompose_dir: /x\n")
    scrivi_servizio("a.yaml", "name: a\npriority: 10\ncompose_dir: /x\n")
    scrivi_servizio("c.yaml", "name: c\npriority: 30\ncompose_dir: /x\n")

    servizi = module.load_services(tmp_path)

    assert [s["name"] for s in servizi] == ["a", "c", "b"]


def test_load_services_flag_default(module, scrivi_servizio, tmp_path):
    scrivi_servizio("a.yaml", "name: a\ncompose_dir: /x\n")

    servizio = module.load_services(tmp_path)[0]

    assert servizio["can_stop"] is True
    assert servizio["can_restart"] is True
    assert servizio["one_shot"] is False
    assert servizio["priority"] == 100
    assert servizio["service_names"] == ["a"]


def test_load_services_accetta_nomi_multipli(module, scrivi_servizio, tmp_path):
    scrivi_servizio(
        "a.yaml",
        "name: suwayomi\ncompose_dir: /x\nservice_name:\n  - suwayomi-sfw\n  - suwayomi-nsfw\n",
    )

    assert module.load_services(tmp_path)[0]["service_names"] == ["suwayomi-sfw", "suwayomi-nsfw"]


def test_load_services_accetta_nome_singolo_stringa(module, scrivi_servizio, tmp_path):
    scrivi_servizio("a.yaml", "name: a\ncompose_dir: /x\nservice_name: a-app-1\n")

    assert module.load_services(tmp_path)[0]["service_names"] == ["a-app-1"]


def test_load_services_can_restart_false_viene_lettura(module, scrivi_servizio, tmp_path):
    scrivi_servizio("a.yaml", "name: a\ncompose_dir: /x\ncan_restart: false\ncan_stop: false\n")

    servizio = module.load_services(tmp_path)[0]

    assert servizio["can_restart"] is False
    assert servizio["can_stop"] is False


def test_load_services_scarta_file_vuoto(module, scrivi_servizio, tmp_path):
    scrivi_servizio("empty.yaml", "")
    scrivi_servizio("ok.yaml", "name: ok\ncompose_dir: /x\n")

    assert [s["name"] for s in module.load_services(tmp_path)] == ["ok"]


def test_load_services_scarta_senza_nome(module, scrivi_servizio, tmp_path):
    scrivi_servizio("bad.yaml", "priority: 10\ncompose_dir: /x\n")

    assert module.load_services(tmp_path) == []


def test_load_services_scarta_senza_compose_dir(module, scrivi_servizio, tmp_path):
    scrivi_servizio("bad.yaml", "name: a\n")

    assert module.load_services(tmp_path) == []


def test_load_services_ignora_yaml_non_mapping(module, scrivi_servizio, tmp_path):
    scrivi_servizio("list.yaml", "- uno\n- due\n")

    assert module.load_services(tmp_path) == []


def test_load_services_ignora_yaml_non_leggibile(module, scrivi_servizio, tmp_path):
    scrivi_servizio("rotto.yaml", "name: a\ncompose_dir: [non chiuso\n")

    assert module.load_services(tmp_path) == []


def test_load_services_directory_mancante(module):
    assert module.load_services(Path("/non-esiste")) == []


def test_load_services_directory_mancante_silenzioso(module, caplog):
    caplog.set_level("ERROR", logger="emergency-stop")

    module.load_services(Path("/non-esiste"), log_missing=False)

    assert "Directory servizi non trovata" not in caplog.text


def _compose_dir(tmp_path, nome="radarr"):
    directory = tmp_path / nome
    directory.mkdir()
    (directory / "docker-compose.yml").write_text("services:\n  radarr:\n    image: x\n")
    return directory


def _servizio_con_dir(modulo_servizio, directory):
    servizio = modulo_servizio("radarr", priority=60)
    servizio["compose_dir"] = directory
    return servizio


def test_check_service_files_selftest_ok(module, monkeypatch, tmp_path, servizio, mock_glances):
    directory = _compose_dir(tmp_path)
    servizi = [_servizio_con_dir(servizio, directory)]
    monkeypatch.setattr(module, "running_containers", lambda names: ["radarr-app-1"])
    config = {"glances": {"url": "http://x"}, "monitor": {"metric": "iowait"}}

    module.check_service_files.selftest = True
    try:
        assert module.check_service_files(servizi, config) is True
    finally:
        module.check_service_files.selftest = False


def test_check_service_files_selftest_segnala_compose_mancante(module, monkeypatch, tmp_path, servizio, mock_glances):
    servizi = [_servizio_con_dir(servizio, tmp_path / "inesistente")]
    monkeypatch.setattr(module, "running_containers", lambda names: [])
    config = {"glances": {"url": "http://x"}, "monitor": {"metric": "iowait"}}

    module.check_service_files.selftest = True
    try:
        assert module.check_service_files(servizi, config) is False
    finally:
        module.check_service_files.selftest = False


def test_check_service_files_senza_servizi(module):
    assert module.check_service_files([], {}) is False


def test_check_service_files_chiama_docker_senza_selftest(module, monkeypatch, tmp_path, servizio, mock_glances):
    directory = _compose_dir(tmp_path)
    servizi = [_servizio_con_dir(servizio, directory)]
    comandi = []
    monkeypatch.setattr(module, "running_containers", lambda names: ["radarr-app-1"])
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: comandi.append(args[0])
        or SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    config = {"glances": {"url": "http://x"}, "monitor": {"metric": "iowait"}}

    assert module.check_service_files(servizi, config) is True

    assert comandi
    assert comandi[0][:3] == ["docker", "compose", "-f"]
    assert comandi[0][-2:] == ["config", "-q"]
