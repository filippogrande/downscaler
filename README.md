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

## Note di deploy

Tre cose che bloccano il servizio se non sono rispettate (verificate 24/10/26):

1. **`/mnt/applicazioni` va montato `rw`** - la cartella degli incidenti
   (`incidents.dir` in `config.yaml`) sta sotto quel mount. Con `:ro` lo
   snapshot d'incidente muore con `EROFS` dentro `_close_incident` e il
   container parte in restart loop.
2. **`/var/log/emergency-stop.log` deve essere un FILE** - se non esiste, Docker
   lo crea come *directory* e il log handler fallisce. Se e' una directory:
   `sudo rm -rf /var/log/emergency-stop.log && sudo touch /var/log/emergency-stop.log`.
3. **Dopo aver editato il compose serve `docker compose down && docker compose up -d`** -
   `up -d` da solo stampa `Started` e riusa il container vecchio con la vecchia
   configurazione.

`docker-compose.yml` nel repo e' il template; quello in
`/mnt/applicazioni/yml/docker/emergency-stop/` e' quello reale ed e' tenuto a
mano (`DRY_RUN=false`). Ogni modifica va fatta su entrambi.

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
