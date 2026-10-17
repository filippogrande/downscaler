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
