# Emergency Stop

Sistema di salvataggio/paracadute per il home-lab: quando il server soffre
(iowait o load troppo alti), spegne automaticamente i servizi non critici in
ordine di priorita', poi li riaccende gradualmente dopo 5 minuti di calma.

- Stack: Python 3.12+, PyYAML, requests; container Alpine
- Immagine: `filippogrande/downscaler:latest` (buildata da GitHub Actions)
- Test: `pytest --tb=short -q`

## Avvio

```bash
docker compose up -d
docker logs -f emergency-stop
```

Il primo avvio e' sicuro: `DRY_RUN: "true"` nel compose, non spegne nulla.
Installazione completa: `docs/DEPLOY.md`.

## Struttura

| Cartella | Contenuto |
|---|---|
| `emergency-stop.py` | entry point: `main()`, argomenti, wrapper |
| `downscaler/` | la logica: config, servizi, monitoring, docker, stato, incidenti |
| `tests/` | test, un file per modulo |
| `examples/services/` | un file di servizio d'esempio per servizio del server |
| `docs/` | la documentazione (mappa, architettura, operazioni) |

## Indice

| Vuoi... | Apri |
|---|---|
| Trovare una funzione o un file | `docs/REFERENCE.md` |
| Capire come funziona | `docs/ARCHITECTURE.md` |
| Conoscere le regole | `docs/CONVENTIONS.md` |
| Configurare soglie o servizi | `docs/CONFIGURATION.md` |
| Validare, aggiornare, aggiungere un servizio | `docs/OPERATIONS.md` |
| Risolvere un problema noto | `docs/TROUBLESHOOTING.md` |
| Installare o aggiornare | `docs/DEPLOY.md` |
