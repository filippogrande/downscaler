"""Test della configurazione: DEFAULTS, _merge_defaults, _normalize_state."""


def test_merge_defaults_aggiunge_le_chiavi_nuove(module):
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

    merged = module._merge_defaults(config_vecchio)

    assert merged["monitor"]["load_stop_threshold"] == 6.0
    assert merged["monitor"]["load_restart_threshold"] == 4.0
    assert merged["monitor"]["stop_threshold"] == 80.0


def test_merge_defaults_incidents_di_default(module):
    """Un config senza la sezione incidents usa i valori di default."""
    merged = module._merge_defaults({"glances": {"url": "http://x"}})

    assert merged["incidents"]["enabled"] is True
    assert merged["incidents"]["log_tail"] == 20000
    assert merged["incidents"]["log_window_min"] == 15


def test_merge_defaults_non_tocca_le_chiavi_presenti(module):
    merged = module._merge_defaults({"monitor": {"stop_threshold": 99.0}})

    assert merged["monitor"]["stop_threshold"] == 99.0


def test_defaults_definiscono_le_soglie_super(module):
    """Le soglie critiche del super-stop esistono e sono piu' alte di quelle normali."""
    soglie = module.DEFAULTS["monitor"]

    assert soglie["load_super_threshold"] == 11.0
    assert soglie["iowait_super_threshold"] == 95.0
    assert soglie["load_super_threshold"] > soglie["load_stop_threshold"]
    assert soglie["iowait_super_threshold"] > soglie["stop_threshold"]


def test_merge_defaults_espone_le_soglie_super(module):
    merged = module._merge_defaults({})

    assert merged["monitor"]["load_super_threshold"] == 11.0
    assert merged["monitor"]["iowait_super_threshold"] == 95.0


def test_normalize_state_completa_lo_stato_parziale(module):
    """Uno stato scritto da una versione precedente non deve rompere il health check.

    Regressione verificata 17/10/26: lo stato in dry-run aveva solo
    metric_window, quindi mancava stopped_services.
    """
    normalized = module._normalize_state({"metric_window": [1.0, 2.0]})

    assert normalized["stopped_services"] == []
    assert normalized["metric_window"] == [1.0, 2.0]
    assert normalized["mode"] == "monitor"


def test_normalize_state_preserva_lo_stato_letto(module):
    state = {"mode": "recovery", "stopped_services": ["radarr"]}

    normalized = module._normalize_state(state)

    assert normalized["mode"] == "recovery"
    assert normalized["stopped_services"] == ["radarr"]
