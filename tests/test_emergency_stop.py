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
