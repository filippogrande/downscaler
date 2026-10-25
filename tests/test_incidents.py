"""Test degli snapshot d'incidente: collect_incident_snapshot, send_incident_report."""

from datetime import datetime, timezone
from types import SimpleNamespace


def test_collect_incident_snapshot_salva_log_e_metriche(module, monkeypatch, tmp_path):
    """collect_incident_snapshot salva log, metrics e summary."""
    services = [
        {"name": "radarr", "service_names": ["radarr-radarr-1"]},
        {"name": "sonarr", "service_names": ["sonarr"]},
    ]

    log_calls = []

    def fake_run(*args, **kwargs):
        log_calls.append(args[0])
        return SimpleNamespace(returncode=0, stdout="log line", stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module, "get_glances_metrics", lambda config: (5.0, 430.0))

    config = {
        "incidents": {
            "dir": str(tmp_path / "incidents"),
            "log_tail": 20000,
            "log_window_min": 15,
        },
        "glances": {"url": "http://x"},
    }

    state = {"mode": "monitor", "incident_services": ["radarr"]}

    now = datetime(2026, 10, 17, 22, 30, 15, tzinfo=timezone.utc)
    result = module.collect_incident_snapshot(config, services, state, now, "start")

    expected = tmp_path / "incidents" / "2026-10-17_22-30-15"
    assert result == expected
    assert (expected / "radarr-radarr-1.log").exists()
    assert (expected / "sonarr.log").exists()
    assert (expected / "metrics.json").exists()
    assert (expected / "summary.txt").exists()
    # 2 container, 2 chiamate a docker logs
    assert len(log_calls) == 2


def test_collect_incident_snapshot_disabilitato_non_fa_nulla(module, tmp_path):
    """Con incidents.enabled false, non salva nulla."""
    config = {"incidents": {"enabled": False, "dir": str(tmp_path)}}

    result = module.collect_incident_snapshot(config, [], {}, datetime(2026, 1, 1, tzinfo=timezone.utc), "start")

    assert result is None
    assert not (tmp_path / "2026-01-01_00-00-00").exists()


def test_collect_incident_snapshot_cartella_non_scrivibile_non_crasha(module, tmp_path):
    """Cartella non scrivibile: lo snapshot si salta, il loop non deve morire."""
    blocker = tmp_path / "blocker"
    blocker.write_text("sono un file, non una directory")
    config = {
        "incidents": {
            "dir": str(blocker / "incidents"),
            "log_tail": 100,
            "log_window_min": 15,
        }
    }

    result = module.collect_incident_snapshot(
        config, [], {}, datetime(2026, 10, 24, 22, 0, 0, tzinfo=timezone.utc), "start"
    )

    assert result is None


def test_collect_incident_snapshot_specifica_la_fase_nel_summary(module, monkeypatch, tmp_path):
    services = [{"name": "radarr", "service_names": ["radarr-radarr-1"]}]
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    monkeypatch.setattr(module, "get_glances_metrics", lambda config: (1.0, 1.0))
    config = {"incidents": {"dir": str(tmp_path / "incidents"), "log_tail": 100, "log_window_min": 15}}

    result = module.collect_incident_snapshot(
        config,
        services,
        {"incident_services": ["radarr"]},
        datetime(2026, 10, 17, 22, 30, 15, tzinfo=timezone.utc),
        "end",
    )

    summary = (result / "summary.txt").read_text()
    assert "Incidente end" in summary


def test_send_incident_report_manda_telegram(module, tmp_path, monkeypatch):
    """send_incident_report invia il report con path e durata."""
    calls = []
    monkeypatch.setattr(module, "send_telegram", lambda msg, config: calls.append(msg))

    snapshot_dir = tmp_path / "incidents" / "2026-10-17_22-30-15"
    state = {
        "incident_start": "2026-10-17T22:00:00",
        "incident_services": ["radarr", "sonarr"],
    }
    config = {"incidents": {"telegram_report": True}}

    module.send_incident_report(snapshot_dir, state, config)

    assert len(calls) == 1
    assert "Incidente risolto" in calls[0]
    assert "radarr" in calls[0]
    assert "sonarr" in calls[0]
    assert str(snapshot_dir) in calls[0]


def test_send_incident_report_disabilitato_non_manda_nulla(module, tmp_path, monkeypatch):
    """Con incidents.telegram_report false, non invia nulla."""
    calls = []
    monkeypatch.setattr(module, "send_telegram", lambda msg, config: calls.append(msg))

    config = {"incidents": {"telegram_report": False}}
    module.send_incident_report(tmp_path, {}, config)

    assert calls == []


def test_send_incident_report_conta_servizi_distinti(module, tmp_path, monkeypatch):
    """Nomi duplicati nello stato: il report elenca e conta i servizi distinti."""
    calls = []
    monkeypatch.setattr(module, "send_telegram", lambda msg, config: calls.append(msg))

    state = {
        "incident_start": "2026-10-25T09:00:00",
        "incident_services": ["radarr", "sonarr", "radarr", "radarr", "sonarr"],
    }
    config = {"incidents": {"telegram_report": True}}

    module.send_incident_report(tmp_path, state, config)

    assert "Servizi fermati: 2 (radarr, sonarr)" in calls[0]


def test_stop_one_non_duplica_i_servizi_fermati(module):
    """Un servizio fermato due volte compare una sola volta in incident_services."""
    salvati = []

    def salva(state):
        salvati.append(list(state["incident_services"]))

    actions = module.monitoring.Actions(
        save=salva,
        notify=lambda msg, config: None,
        stop=lambda service: True,
        start=lambda service: True,
        snapshot=lambda *a, **k: None,
        report=lambda *a, **k: None,
        sample=lambda *a, **k: (1.0, 1.0),
    )
    state = {"stopped_services": [], "incident_services": [], "failed_stops": []}
    service = {"name": "radarr", "service_names": ["radarr-radarr-1"]}
    now = datetime(2026, 10, 25, 10, 0, 0, tzinfo=timezone.utc)

    module.monitoring._stop_one({}, state, service, now, actions)
    state["stopped_services"] = []  # il recovery lo riaccende e lo toglie dai fermati
    module.monitoring._stop_one({}, state, service, now, actions)

    assert state["incident_services"] == ["radarr"]
