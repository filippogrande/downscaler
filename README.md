# Emergency Stop

Sistema di salvataggio/paracadute per il home-lab: quando il server soffre
(iowait o load troppo alti), spegne automaticamente servizi non critici in ordine
di priorità, poi li riaccende gradualmente dopo 5 min di calma.

## Installazione

```bash
# 1. Crea la cartella di deploy
mkdir -p /mnt/applicazioni/yml/docker/emergency-stop/services
cd /mnt/applicazioni/yml/docker/emergency-stop

# 2. Copia i file dal repo
cp /mnt/applicazioni/emergency-stop-repo/docker-compose.yml .
cp /mnt/applicazioni/emergency-stop-repo/config.yaml .
cp -r /mnt/applicazioni/emergency-stop-repo/examples/services/* services/

# 3. Prima avvio: DRY_RUN=true, non spegne nulla
docker compose up -d
docker logs -f emergency-stop
```

**Nessun build locale**: l'immagine la builda GitHub Actions a ogni merge su `main`
(workflow *Docker Build & Push*) e il compose fa solo **pull** da Docker Hub.

## La cartella deplo

`/mnt/applicazioni/yml/docker/emergency-stop/`:

| File | Contenuto |
|---|---|
| `docker-compose.yml` | valori letterali, niente `${}`, nessun `build:` |
| `config.yaml` | soglie, Glances, Telegram |
| `services/<nome>.yaml` | un file per servizio |

## Il primo avvio e' sicuro

`docker-compose.yml` ha `DRY_RUN: "true"` **scritto letteralmente**: il container gira,
legge la metrica, stampa cosa farebbe e **non spegne niente**.

Per farlo lavorare davvero:

```bash
# modifica DRY_RUN: "false" nel compose, poi
docker compose up -d
```

`config.yaml` e `services/` sono riletti a ogni giro (60s): modificarli **non**
richiede restart. Solo `DRY_RUN` e' una env var, quindi per cambiarlo serve
`docker compose up -d`.

## Test singoli

```bash
# valida config, compose, nomi container, Glances — non tocca nulla
docker run --rm \
  -v "$PWD/config.yaml:/app/config.yaml:ro" \
  -v "$PWD/services:/app/services:ro" \
  -e DRY_RUN=true \
  filippogrande/downscaler:latest --validate

# prova senza Docker (file e nomi, niente socket)
docker run --rm \
  -v "$PWD/config.yaml:/app/config.yaml:ro" \
  -v "$PWD/services:/app/services:ro" \
  filippogrande/downscaler:latest --validate --selftest

# esegue la logica e stampa cosa farebbe
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock:rw \
  -v "$PWD/config.yaml:/app/config.yaml:ro" \
  -v "$PWD/services:/app/services:ro" \
  filippogrande/downscaler:latest --dry-run
```

## Comandi

```bash
# log
docker logs -f emergency-stop

# stato
docker compose exec emergency-stop cat /app/state/state.json

# ricomincia (dopo un cambio a DRY_RUN)
docker compose restart emergency-stop

# aggiorna l'immagine dopo un nuovo merge su main
docker compose pull && docker compose up -d
```

## Configurazione

### config.yaml

- `glances.url`: URL dell'istanza Glances
- `monitor.metric`: `iowait` o `load`
- `monitor.sample_interval_sec`: ogni quanto campionare (30s)
- `monitor.window_sec`: finestra media mobile (120s = 2 min)
- `monitor.stop_threshold`: media iowait > 80% → ferma un servizio
- `monitor.restart_threshold`: media iowait < 60% → può riavviare
- `monitor.load_stop_threshold`: media load > 6 → ferma un servizio
- `monitor.load_restart_threshold`: media load < 4 → può riavviare
- `recovery.calm_duration_sec`: 5 min di calma prima del primo riavvio
- `recovery.restart_delay_sec`: 5 min tra un riavvio e l'altro
- `telegram`: bot_token e chat_id per notifiche

L'allarme scatta se **una** delle due metriche supera la sua soglia; il riavvio
richiede che **entrambe** siano sotto soglia. Con le soglie di default, un load
sostenuto (backup, transcode, `docker system prune`) ferma i servizi non critici
anche se la CPU è ferma: è il caso d'uso del load.

### File di servizio

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
| `compose_dir` | directory del compose | obbligatorio |
| `compose_file` | nome del compose | `docker-compose.yml` |
| `service_name` | container da considerare (uno o più) | `name` |
| `can_stop` | il downscaler può fermarlo | `true` |
| `can_restart` | il downscaler può riaccenderlo | `true` |
| `one_shot` | batch da cron, nessun container residente | `false` |
| `priority` | ordine di stop (più basso = fermato prima) | `100` |
| `note` | libera, documenta la scelta | vuota |

**`priority` decide l'ordine di stop, non l'importanza.** Più basso = fermato per
primo. Il ripristino avviene in ordine inverso (l'ultimo spento torna su per ultimo).

**`can_stop: false` esclude un servizio**, qualunque priority abbia.

**`can_stop` e `can_restart` sono separati:**

- `can_stop: false` → non lo tira giù, ma il health-check può riaccenderlo
- `can_restart: false` → può tirarlo giù, ma il health-check non lo riaccende

Un solo `enabled: false` creerebbe un buco: il servizio finirebbe in `stopped_services`
e non verrebbe mai più riacceso.

**`one_shot`** è per i servizi da cron (`recyclarr`, `cleanuparr`): non hanno un
container residente, quindi il health-check non deve riavviarli ogni 60s.

**Suwayomi** è un unico servizio: sfw, nsfw e gluetun condividono lo stesso compose
e vanno giù insieme.

## Rischio

Il container monta `/var/run/docker.sock:rw` per eseguire `docker compose ...`.
`docker.sock:rw` = accesso equivalente a root al daemon. Necessario per spegnere gli
altri servizi, va dichiarato come tale.

## Metriche Glances

Da Glances 4.0 l'API e' `/api/4/`: la vecchia `/api/3/` non esiste più
(risponde `404 {"detail":"Not Found"}`) e il plugin `system` non espone
più le metriche.

- `iowait` → `GET /api/4/cpu`, campo `iowait`
- `load` → `GET /api/4/load`, campo `min1`

Se la metrica non è leggibile il giro viene **saltato** e l'errore va in log:
non viene più usato `0.0` (= tutto ok).

## Come funziona

1. **Health check**: ogni 60s verifica i servizi residenti non spenti dal sistema e li riavvia (salta one-shot e `can_restart: false`).
2. **Media mobile**: campiona iowait e load ogni 30s, media su finestra di 2 min.
3. **Isteresi**: stop se la media di iowait **o** di load supera la soglia; il riavvio richiede entrambe sotto soglia.
4. **Stop graduale**: ferma un servizio alla volta; se il down fallisce, il giro dopo prova il successivo.
5. **Recovery**: 5 min di calma **con entrambe le medie sotto soglia** → riavvia un servizio → altri 5 min → il successivo.

**Avviso**: chi spegne un servizio a mano lo vede riacceso dal health-check entro 60s.
Per lavorare su un servizio: `docker compose stop emergency-stop`.

## Servizi mai fermati

I servizi non in `services/` non vengono toccati.

Tutti i servizi del server hanno un YAML in `services/`: il gestore toglie
quelli che non vuole gestire (es. `can_stop: false`).

Attualmente esclusi:

- **Vikunja** — sempre su per preferenza
- **`arr`** — DB condiviso degli *arr, deve restare su
- **`emergency-stop` e `hermes-agent`** — non si spengono da soli
- **`docker`/`images`/`scripts`/`services.json`/`runtipi`/`sure`/`ytdl-sub`/`domain-watchdog`** — nessun container attivo o non servizi applicativi
