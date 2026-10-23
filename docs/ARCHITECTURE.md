# ARCHITECTURE — come funziona

<!-- Tipo: EXPLANATION. Come funziona e perche'. La mappa dei file e' in REFERENCE.md. -->

## Che cos'e'

Emergency Stop e' un paracadute per il home-lab: un processo che gira in un
container e, quando il server soffre, spegne i servizi non critici in ordine di
priorita' per ridurre il carico, poi li riaccende gradualmente.

Il container monta il socket Docker dell'host: per spegnere un servizio esegue
`docker compose -f <compose_dir>/<compose_file> down`, per riaccenderlo `up -d`.

## Componenti

| Componente | Ruolo |
|---|---|
| `emergency-stop.py` | entry point: `main()`, parsing degli argomenti, wrapper iniettati |
| `downscaler/config.py` | path, `DEFAULTS`, `STATE_DEFAULTS`, logging, `DRY_RUN` |
| `downscaler/services.py` | lettura e validazione dei file di servizio |
| `downscaler/monitoring.py` | metriche, media mobile, macchina a stati, decisioni |
| `downscaler/docker_ops.py` | comandi `docker` / `docker compose` |
| `downscaler/state.py` | `state.json` e notifiche Telegram |
| `downscaler/incidents.py` | snapshot degli incidenti (log, metriche, summary) |
| `entrypoint.sh` | avvio del container: corsa singola o loop infinito |

La logica vera vive in `downscaler/`: l'entry point contiene `main()` e i wrapper
che risolvono i nomi nel suo namespace, cosi' i test possono patcharli.

## Flusso di un giro

1. **Health check**: ogni 60s riavvia i servizi residenti non spenti dal sistema
   (salta gli `one_shot` e quelli con `can_restart: false`).
2. **Campionamento**: legge iowait e load da Glances; se nessuna e' leggibile il
   giro viene **saltato** (non si decide nulla: usare `0.0` significherebbe "tutto ok").
3. **Media mobile**: i campioni sono accumulati in una finestra (`window_sec`,
   default 2 min) e la media aggiorna lo stato.
4. **Decisione**: `handle_monitor()` se lo stato e' `monitor`, `handle_recovery()`
   se e' `recovery`.
5. **Salvataggio**: lo stato aggiornato e' scritto in `state.json` (mai in dry-run).

## Macchina a stati

Due soli stati, in `state.json` sotto la chiave `mode`:

- **monitor** — tutto normale. Sopra soglia: apre un incidente, ferma i candidati.
  Tornato sotto soglia con dei servizi fermati: passa a `recovery`.
- **recovery** — 5 minuti di calma (con entrambe le medie sotto soglia), poi
  riavvia un servizio alla volta, aspettando `restart_delay_sec` tra l'uno e
  l'altro. Se le metriche risalgono sopra la soglia di stop, torna in `monitor`.

## Isteresi

- **Stop**: basta che **una** delle due metriche superi la sua soglia.
- **Riavvio**: servono **entrambe** sotto soglia.

Con le soglie di default un load sostenuto (backup, transcode, `docker system prune`)
ferma i servizi non critici anche se la CPU e' ferma: e' il caso d'uso del load.

## Super-stop

Se una metrica supera la soglia critica (`load_super_threshold`, `iowait_super_threshold`)
il giro ferma **due** servizi invece di uno. Serve quando un carico improvviso
non da' tempo ad agire.

## Incident snapshots

A ogni incidente il downscaler salva i log di tutti i container attivi:

```
incidents/2026-10-17_22-30-15/
  ├── radarr-radarr-1.log
  ├── sonarr.log
  ├── metrics.json      <- iowait/load all'inizio e alla fine
  └── summary.txt       <- durata, servizi fermati, ordine
```

- **Finestra log**: `incident_start - log_window_min` -> `incident_end + log_window_min`
- **Limite righe**: `incidents.log_tail` per container (un servizio in loop di
  errori non deve riempire il disco)
- **Report Telegram**: alla fine dell'incidente

## Metriche Glances

Da Glances 4.0 l'API e' `/api/4/`: la vecchia `/api/3/` non esiste piu' (risponde
`404 {"detail":"Not Found"}`) e il plugin `system` non espone piu' le metriche.

- `iowait` -> `GET /api/4/cpu`, campo `iowait`
- `load`   -> `GET /api/4/load`, campo `min1`

`_read_glances_field()` prova la `/api/4` e, se il campo manca, la `/api/3`.

## Deploy

- L'immagine la builda GitHub Actions a ogni merge su `main` (`docker-push.yml`);
  il compose fa solo **pull** da Docker Hub. Nessun build locale.
- `docker-compose.yml` ha valori letterali: niente `${...}`, niente `build:`,
  niente `env_file`.
- `DRY_RUN: "true"` scritto letteralmente: il container gira, legge la metrica,
  stampa cosa farebbe e **non spegne niente**.
- `config.yaml` e `services/` sono riletti a ogni giro (60s): modificarli non
  richiede restart. Per cambiare `DRY_RUN` serve `docker compose up -d`.
- Sul master il servizio gira come container + timer systemd (`OnUnitActiveSec=1min`).

## Sicurezza

- **Socket Docker**: il container monta `/var/run/docker.sock:rw` per eseguire
  `docker compose`. E' un accesso equivalente a root al daemon: voluto per
  spegnere gli altri servizi, va dichiarato come tale.
- **Segreti**: nessun segreto nel repo. `config.yaml` contiene placeholder
  (`INSERISCI_BOT_TOKEN`); il file committato non e' la configurazione reale.
- **Dipendenze**: `requirements.txt` usa `>=` o `==` con versioni minime esplicite.
- **Confronto nomi container**: esatto, non per sottostringa: `sonarr` non deve
  mai risultare in esecuzione per colpa di `sonarr-anime`.
