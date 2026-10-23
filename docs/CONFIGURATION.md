# CONFIGURATION — soglie e servizi gestiti

<!-- Tipo: REFERENCE. I fatti: cosa si configura e cosa significa. -->

## Dove vivono le configurazioni

| Cosa | Dove | Riletta |
|---|---|---|
| Soglie, Glances, Telegram, incidenti | `config.yaml` | a ogni giro (60s) |
| Servizi gestiti | `services/<nome>.yaml` (nel deploy) / `examples/services/` (nel repo) | a ogni giro |
| Flag `DRY_RUN` | `docker-compose.yml` -> `environment.DRY_RUN` | solo all'avvio |

Il file `config.yaml` nel repo contiene i placeholder (`INSERISCI_BOT_TOKEN`):
non e' la configurazione reale del server.

## config.yaml

### `glances`

- `url`: URL dell'istanza Glances.

### `monitor`

| Chiave | Significato | Default |
|---|---|---|
| `metric` | `iowait` o `load` (compatibilita', log) | `iowait` |
| `sample_interval_sec` | ogni quanto campionare | `30` |
| `window_sec` | finestra della media mobile | `120` |
| `stop_threshold` | iowait oltre -> ferma un servizio | `80.0` |
| `restart_threshold` | iowait sotto -> puo' riavviare | `60.0` |
| `load_stop_threshold` | load oltre -> ferma un servizio | `6.0` |
| `load_restart_threshold` | load sotto -> puo' riavviare | `4.0` |
| `load_super_threshold` | load oltre -> **super-stop** (2 servizi) | `11.0` |
| `iowait_super_threshold` | iowait oltre -> **super-stop** (2 servizi) | `95.0` |
| `check_interval_sec` | loop di controllo (letto da `entrypoint.sh`) | `60` |

### `recovery`

| Chiave | Significato | Default |
|---|---|---|
| `calm_duration_sec` | calma prima del primo riavvio | `300` |
| `restart_delay_sec` | attesa tra un riavvio e l'altro | `300` |

### `telegram`

- `enabled`: attiva le notifiche.
- `bot_token`, `chat_id`: credenziali del bot.

### `incidents`

| Chiave | Significato | Default |
|---|---|---|
| `enabled` | raccogli log e metriche | `true` |
| `dir` | cartella degli snapshot | `/mnt/applicazioni/yml/docker/emergency-stop/incidents` |
| `telegram_report` | report finale via Telegram | `true` |
| `log_tail` | max righe di log per container | `20000` |
| `log_window_min` | finestra log prima/dopo | `15` |

Le chiavi assenti in un config vecchio prendono i `DEFAULTS` di
`downscaler/config.py`: un config scritto da una versione precedente non fa
crashare il container.

## File di servizio

Un file per servizio in `services/<nome>.yaml`:

```yaml
name: radarr
compose_dir: /mnt/applicazioni/yml/docker/radarr
compose_file: docker-compose.yml
service_name:
  - radarr-radarr-1
can_stop: true
can_restart: true
one_shot: false
priority: 60
note: "il DB e' nel compose condiviso postgres-arr, deve restare su"
```

| Campo | Significato | Default |
|---|---|---|
| `name` | nome del servizio. Deve corrispondere al **nome esatto** del container | obbligatorio |
| `compose_dir` | directory del compose (path assoluto dell'host) | obbligatorio |
| `compose_file` | nome del compose | `docker-compose.yml` |
| `service_name` | container da considerare (uno o piu') | `name` |
| `can_stop` | il downscaler puo' fermarlo | `true` |
| `can_restart` | il downscaler puo' riaccenderlo | `true` |
| `one_shot` | batch da cron, nessun container residente | `false` |
| `priority` | ordine di stop (piu' basso = fermato prima) | `100` |
| `note` | libera, documenta la scelta | vuota |

### Regole sui campi

- **`priority` decide l'ordine di stop, non l'importanza.** Piu' basso = fermato
  per primo. Il ripristino avviene in ordine inverso.
- **`can_stop: false` esclude un servizio**, qualunque priority abbia.
- **`can_stop` e `can_restart` sono separati:**
  - `can_stop: false` -> non lo tira giu', ma l'health-check puo' riaccenderlo;
  - `can_restart: false` -> puo' tirarlo giu', ma l'health-check non lo riaccende.
  - Un solo `enabled: false` creerebbe un buco: il servizio finirebbe in
    `stopped_services` e non verrebbe mai piu' riacceso.
- **`one_shot`** e' per i servizi da cron (`recyclarr`, `cleanuparr`): non hanno un
  container residente, quindi l'health-check non deve riavviarli ogni 60s.

## Servizi esclusi

I servizi non in `services/` non vengono toccati. Attualmente esclusi:

- **Vikunja** — sempre su per preferenza
- **`arr`** — DB condiviso degli *arr, deve restare su
- **`emergency-stop` e `hermes-agent`** — non si spengono da soli
- **`docker`/`images`/`scripts`/`services.json`/`runtipi`/`sure`/`ytdl-sub`/`domain-watchdog`** — nessun container attivo o non servizi applicativi

**Suwayomi** e' un unico servizio: sfw, nsfw e gluetun condividono lo stesso compose
e vanno giu' insieme.
