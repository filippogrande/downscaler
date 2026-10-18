"""Test del monitoraggio: get_glances_metrics, update_window, health_check, fmt_metric."""

from collections import deque


def test_update_window_campiona_e_limita_la_finestra(module):
    window = deque()
    assert module.update_window(window, 10.0, 120, 30) == 10.0
    assert module.update_window(window, 20.0, 120, 30) == 15.0
    assert module.update_window(window, 30.0, 120, 30) == 20.0
    # il quarto campione riempie la finestra (max 120/30 = 4)
    assert module.update_window(window, 40.0, 120, 30) == 25.0
    assert len(window) == 4
    # il quinto spiazza il piu' vecchio: resta [20, 30, 40, 50]
    assert module.update_window(window, 50.0, 120, 30) == 35.0
    assert list(window) == [20.0, 30.0, 40.0, 50.0]


def test_update_window_vuota_non_divide_per_zero(module):
    assert module.update_window(deque(), 5.0, 120, 30) == 5.0


def test_update_window_finestra_piu_piccola_del_campione(module):
    window = deque()
    assert module.update_window(window, 10.0, 30, 30) == 10.0
    assert module.update_window(window, 20.0, 30, 30) == 20.0
    assert list(window) == [20.0]


def test_fmt_metric_formatta_e_gestisce_il_mancante(module):
    """0.0 e' un valore valido: non deve diventare 'N/A'."""
    assert module.fmt_metric(20.1) == "20.1"
    assert module.fmt_metric(0.0) == "0.0"
    assert module.fmt_metric(None) == "N/A"


def test_get_glances_metrics_simulazione(module):
    config = {"glances": {"url": "http://x"}}

    assert module.get_glances_metrics(config, sim_iowait=10, sim_load=2) == (10.0, 2.0)


def test_get_glances_metrics_api_v4(module, monkeypatch, http_response):
    risposte = {"/api/4/cpu": {"iowait": 12.5}, "/api/4/load": {"min1": 3.5}}

    def fake_get(url, timeout):
        return http_response(risposte[url.replace("http://x", "")])

    monkeypatch.setattr(module.requests, "get", fake_get)

    config = {"glances": {"url": "http://x"}}
    assert module.get_glances_metrics(config) == (12.5, 3.5)


def test_get_glances_metrics_fallback_api_v3(module, monkeypatch, http_response):
    """Se la v4 non espone il campo, il modulo prova la v3."""
    risposte = {
        "/api/4/cpu": {},
        "/api/3/cpu": {"iowait": 7.0},
        "/api/4/load": {"min1": 2.0},
        "/api/3/load": {"min1": 9.0},
    }

    def fake_get(url, timeout):
        return http_response(risposte[url.replace("http://x", "")])

    monkeypatch.setattr(module.requests, "get", fake_get)

    config = {"glances": {"url": "http://x"}}
    assert module.get_glances_metrics(config) == (7.0, 2.0)


def test_get_glances_metrics_nessuna_metrica_leggibile(module, monkeypatch):
    monkeypatch.setattr(module, "_glances_get", lambda url, path: None)

    config = {"glances": {"url": "http://x"}}
    assert module.get_glances_metrics(config) == (None, None)


def test_get_glances_metrics_errore_rete_ritorna_none(module, monkeypatch):
    def fake_get(url, timeout):
        raise ConnectionError

    monkeypatch.setattr(module.requests, "get", fake_get)

    config = {"glances": {"url": "http://x"}}
    assert module.get_glances_metrics(config) == (None, None)


def test_health_check_riavvia_solo_chi_puo_ripartire(module, monkeypatch):
    chiamate = []
    monkeypatch.setattr(module, "start_service", lambda s: chiamate.append(s["name"]) or True)
    monkeypatch.setattr(module, "is_service_running", lambda s: False)
    servizi = [
        {"name": "a", "one_shot": False, "can_restart": True},
        {"name": "b", "one_shot": False, "can_restart": False},
        {"name": "c", "one_shot": True, "can_restart": True},
    ]

    module.health_check(servizi, {"stopped_services": []})

    assert chiamate == ["a"]


def test_health_check_salta_servizi_fermi_dal_sistema(module, monkeypatch):
    chiamate = []
    monkeypatch.setattr(module, "start_service", lambda s: chiamate.append(s["name"]) or True)
    monkeypatch.setattr(module, "is_service_running", lambda s: False)
    servizi = [{"name": "a", "one_shot": False, "can_restart": True}]

    module.health_check(servizi, {"stopped_services": ["a"]})

    assert chiamate == []


def test_health_check_non_riavvia_servizi_gia_attivi(module, monkeypatch):
    chiamate = []
    monkeypatch.setattr(module, "start_service", lambda s: chiamate.append(s["name"]) or True)
    monkeypatch.setattr(module, "is_service_running", lambda s: True)
    servizi = [{"name": "a", "one_shot": False, "can_restart": True}]

    module.health_check(servizi, {"stopped_services": []})

    assert chiamate == []
