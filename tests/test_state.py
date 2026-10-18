"""Test dello stato e delle notifiche: load_state, save_state, send_telegram."""

import json


def test_load_state_con_file_illeggibile(module, tmp_path, monkeypatch):
    """Uno stato corrotto non deve bloccare il container."""
    state_path = tmp_path / "state.json"
    state_path.write_text("{ non e' json")
    monkeypatch.setattr(module, "STATE_PATH", state_path)

    state = module.load_state()

    assert state["mode"] == "monitor"
    assert state["stopped_services"] == []


def test_load_state_con_json_non_dict(module, tmp_path, monkeypatch):
    """Un JSON valido ma non un object (es. una lista) non deve bloccare."""
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps([1, 2, 3]))
    monkeypatch.setattr(module, "STATE_PATH", state_path)

    state = module.load_state()

    assert state["mode"] == "monitor"


def test_load_state_file_assente_usa_i_default(module, tmp_path, monkeypatch):
    monkeypatch.setattr(module, "STATE_PATH", tmp_path / "inesistente.json")

    state = module.load_state()

    assert state["mode"] == "monitor"
    assert state["stopped_services"] == []


def test_load_state_legge_lo_stato_escritto(module, tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"mode": "recovery", "stopped_services": ["radarr"]}))
    monkeypatch.setattr(module, "STATE_PATH", state_path)

    state = module.load_state()

    assert state["mode"] == "recovery"
    assert state["stopped_services"] == ["radarr"]


def test_save_state_dry_run_non_scrive(module, tmp_path, monkeypatch):
    monkeypatch.setattr(module, "DRY_RUN", True)
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(module, "STATE_PATH", state_path)

    module.save_state({"mode": "monitor"})

    assert not state_path.exists()


def test_save_state_scrive_il_file(module, tmp_path, monkeypatch):
    monkeypatch.setattr(module, "DRY_RUN", False)
    state_path = tmp_path / "state.json"
    monkeypatch.setattr(module, "STATE_PATH", state_path)

    module.save_state({"mode": "monitor", "stopped_services": ["radarr"]})

    assert json.loads(state_path.read_text()) == {"mode": "monitor", "stopped_services": ["radarr"]}


def test_send_telegram_disabilitato_non_invia(module, monkeypatch):
    invii = []
    monkeypatch.setattr(module.requests, "post", lambda *args, **kwargs: invii.append((args, kwargs)))

    module.send_telegram("ciao", {"telegram": {"enabled": False}})

    assert invii == []


def test_send_telegram_dry_run_non_invia(module, monkeypatch):
    monkeypatch.setattr(module, "DRY_RUN", True)
    invii = []
    monkeypatch.setattr(module.requests, "post", lambda *args, **kwargs: invii.append((args, kwargs)))

    module.send_telegram("ciao", {"telegram": {"enabled": True, "bot_token": "T", "chat_id": "C"}})

    assert invii == []


def test_send_telegram_token_placeholder_non_invia(module, monkeypatch):
    invii = []
    monkeypatch.setattr(module.requests, "post", lambda *args, **kwargs: invii.append((args, kwargs)))

    module.send_telegram("ciao", {"telegram": {"enabled": True, "bot_token": "INSERISCI_BOT_TOKEN", "chat_id": "42"}})

    assert invii == []


def test_send_telegram_invia_il_messaggio(module, monkeypatch, http_response):
    monkeypatch.setattr(module, "DRY_RUN", False)
    invii = []
    # Il fake deve restituire una risposta vera: send_telegram chiama
    # raise_for_status() sul valore di ritorno di requests.post.
    monkeypatch.setattr(
        module.requests,
        "post",
        lambda url, json, timeout: invii.append((url, json, timeout)) or http_response({}),
    )

    module.send_telegram("ciao", {"telegram": {"enabled": True, "bot_token": "TOKEN", "chat_id": "42"}})

    assert len(invii) == 1
    url, corpo, timeout = invii[0]
    assert url == "https://api.telegram.org/botTOKEN/sendMessage"
    assert corpo == {"chat_id": "42", "text": "ciao"}
    assert timeout == 10


def test_send_telegram_errore_rete_logga_e_non_crasha(module, monkeypatch, caplog):
    def fake_post(url, json, timeout):
        raise ConnectionError

    monkeypatch.setattr(module.requests, "post", fake_post)

    with caplog.at_level("ERROR", logger="emergency-stop"):
        module.send_telegram("ciao", {"telegram": {"enabled": True, "bot_token": "T", "chat_id": "C"}})

    assert "Errore invio Telegram" in caplog.text
