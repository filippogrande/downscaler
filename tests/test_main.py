"""Test della logica principale: allarme, recovery, super-stop, ritorno a monitor."""

import logging
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Un timestamp lontano nel passato: la finestra di calma (300s) e' gia' scaduta,
# quindi il test entra nel ramo che decide cosa fare del recovery.
RECOVERY_STARTED = "2020-01-01T00:00:00"


def _stato_recovery(fermati=None):
    return {
        "mode": "recovery",
        "recovery_started_at": RECOVERY_STARTED,
        "stopped_services": list(fermati if fermati is not None else ["radarr"]),
        "incident_services": ["radarr"],
        "incident_start": RECOVERY_STARTED,
    }


def test_allarme_logga_invece_di_crasha(module, avvia_main, servizio, tmp_path, monkeypatch, caplog):
    """Il ramo di allarme deve scrivere il log, non sollevare ValueError.

    Regressione verificata 17/10/26: i log di allarme/recovery/post-stop
    contenevano la condizione dentro il format specifier (`{v:.1f if v ...}`),
    che Python rifiuta. Il crash era nel ramo di allarme, cioe' proprio quando
    il downscaler doveva spegnere un servizio.
    """
    monkeypatch.setattr(module, "load_services", lambda directory: [servizio("radarr")])
    avvia_main(
        tmp_path,
        ["emergency-stop", "--dry-run", "--simulate-iowait", "5", "--simulate-load", "430"],
    )

    with caplog.at_level(logging.INFO, logger="emergency-stop"):
        module.main()

    testo = caplog.text
    assert "ALLARME: iowait_media=5.0" in testo
    assert "load_media=430.0" in testo


def test_recovery_ancora_sopra_soglia_restart_non_riavvia(module, avvia_main, servizio, tmp_path, monkeypatch, caplog):
    """Il ramo di recovery deve loggare, non sollevare ValueError.

    Stesso difetto del ramo di allarme. Qui lo stato e' gia' in modalita'
    recovery con le metriche ancora sopra la soglia di restart: e' il caso in
    cui quel log viene emesso. Sotto la soglia di stop, cioe' il recovery puo'
    ancora aspettare.
    """
    monkeypatch.setattr(module, "load_services", lambda directory: [servizio("radarr")])
    avvia_main(
        tmp_path,
        ["emergency-stop", "--dry-run", "--simulate-iowait", "70", "--simulate-load", "2"],
        state=_stato_recovery(),
    )

    with caplog.at_level(logging.INFO, logger="emergency-stop"):
        module.main()

    testo = caplog.text
    assert "Recovery: ancora sopra soglia (iowait_media=70.0" in testo
    assert "load_media=2.0" in testo


def test_recovery_can_restart_false_non_riavvia(module, avvia_main, servizio, tmp_path, monkeypatch, caplog):
    """Un servizio con can_restart=false non deve essere riavviato dal recovery.

    Senza questo controllo il recovery riavvia servizi che il health check
    salta correttamente.
    """
    monkeypatch.setattr(module, "load_services", lambda directory: [servizio("radarr", can_restart=False)])
    avvia_main(
        tmp_path,
        ["emergency-stop", "--dry-run", "--simulate-iowait", "5", "--simulate-load", "2"],
        state=_stato_recovery(),
    )
    avvii = []
    monkeypatch.setattr(module, "start_service", lambda s: avvii.append(s["name"]) or True)
    salvati = []
    monkeypatch.setattr(module, "save_state", lambda s: salvati.append(s))

    with caplog.at_level(logging.INFO, logger="emergency-stop"):
        module.main()

    assert avvii == []
    assert salvati
    assert "radarr" not in salvati[-1]["stopped_services"]
    assert "can_restart=false" in caplog.text


def test_recovery_metriche_risalite_torna_a_monitor(module, avvia_main, servizio, tmp_path, monkeypatch, caplog):
    """Se in recovery le metriche risalgono sopra la soglia di stop, torna in monitor.

    Senza questo controllo il sistema restava bloccato a riavviare senza mai
    tornare a stoppare.
    """
    monkeypatch.setattr(module, "load_services", lambda directory: [servizio("radarr")])
    avvia_main(
        tmp_path,
        ["emergency-stop", "--dry-run", "--simulate-iowait", "90", "--simulate-load", "2"],
        state=_stato_recovery(),
    )
    avvii = []
    monkeypatch.setattr(module, "start_service", lambda s: avvii.append(s["name"]) or True)
    salvati = []
    monkeypatch.setattr(module, "save_state", lambda s: salvati.append(s))

    with caplog.at_level(logging.INFO, logger="emergency-stop"):
        module.main()

    assert avvii == []
    assert salvati[-1]["mode"] == "monitor"
    assert "torno in monitor mode" in caplog.text


def test_super_stop_load_critica_ferma_due_servizi(module, avvia_main, servizio, tmp_path, monkeypatch, caplog):
    """load oltre la soglia critica: ne ferma due invece di uno."""
    servizi = [servizio("radarr", priority=60), servizio("sonarr", priority=70)]
    avvia_main(tmp_path, ["emergency-stop", "--dry-run", "--simulate-load", "12"], services=servizi)
    fermati = []
    monkeypatch.setattr(module, "stop_service", lambda s: fermati.append(s["name"]) or True)

    with caplog.at_level(logging.INFO, logger="emergency-stop"):
        module.main()

    assert fermati == ["radarr", "sonarr"]
    assert "SUPER-STOP" in caplog.text


def test_super_stop_iowait_critico_ferma_due_servizi(module, avvia_main, servizio, tmp_path, monkeypatch, caplog):
    """iowait oltre la soglia critica: ne ferma due invece di uno."""
    servizi = [servizio("radarr", priority=60), servizio("sonarr", priority=70)]
    avvia_main(tmp_path, ["emergency-stop", "--dry-run", "--simulate-iowait", "96"], services=servizi)
    fermati = []
    monkeypatch.setattr(module, "stop_service", lambda s: fermati.append(s["name"]) or True)

    with caplog.at_level(logging.INFO, logger="emergency-stop"):
        module.main()

    assert fermati == ["radarr", "sonarr"]
    assert "SUPER-STOP" in caplog.text


def test_stop_normale_ferma_un_servizio(module, avvia_main, servizio, tmp_path, monkeypatch, caplog):
    """Sotto la soglia critica il downscale resta graduale: un servizio alla volta."""
    servizi = [servizio("radarr", priority=60), servizio("sonarr", priority=70)]
    avvia_main(tmp_path, ["emergency-stop", "--dry-run", "--simulate-iowait", "85"], services=servizi)
    fermati = []
    monkeypatch.setattr(module, "stop_service", lambda s: fermati.append(s["name"]) or True)

    with caplog.at_level(logging.INFO, logger="emergency-stop"):
        module.main()

    assert fermati == ["radarr"]
    assert "SUPER-STOP" not in caplog.text


def test_nessun_format_specifier_con_condizione(module, solo_codice):
    """Un selettore di formato non puo' contenere una condizione.

    Rete per il ramo post-stop, l'unico dei tre log che i test funzionali
    non eseguono. Si guarda il codice, non il testo: la docstring di
    fmt_metric cita il pattern per spiegarlo.
    """
    assert ".1f if " not in solo_codice(REPO / "emergency-stop.py")
