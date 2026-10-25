# DEPLOY — installazione e aggiornamento

<!-- Tipo: HOW-TO. Installare e aggiornare sul master. -->

## Installazione sul master

```bash
mkdir -p /mnt/applicazioni/yml/docker/emergency-stop/services
cd /mnt/applicazioni/yml/docker/emergency-stop

cp /mnt/applicazioni/emergency-stop-repo/docker-compose.yml .
cp /mnt/applicazioni/emergency-stop-repo/config.yaml .
cp -r /mnt/applicazioni/emergency-stop-repo/examples/services/* services/
```

**Nessun build locale**: l'immagine la builda GitHub Actions a ogni merge su `main`
(workflow *Docker Build & Push*) e il compose fa solo **pull** da Docker Hub.

### La cartella di deploy

`/mnt/applicazioni/yml/docker/emergency-stop/`:

| File | Contenuto |
|---|---|
| `docker-compose.yml` | valori letterali, niente `${}`, nessun `build:` |
| `config.yaml` | soglie, Glances, Telegram |
| `services/<nome>.yaml` | un file per servizio |

## Primo avvio

`docker-compose.yml` ha `DRY_RUN: "true"` scritto letteralmente: il container
gira, legge la metrica, stampa cosa farebbe e **non spegne niente**.

```bash
docker compose up -d
docker logs -f emergency-stop
```

Per farlo lavorare davvero:

```bash
# modifica DRY_RUN: "false" nel compose, poi
docker compose up -d
```

`config.yaml` e `services/` sono riletti a ogni giro (60s): modificarli **non**
richiede restart. Solo `DRY_RUN` e' una env var, quindi per cambiarlo serve
`docker compose up -d`.

## Aggiornare l'immagine

```bash
docker compose pull && docker compose up -d
```

## Variante systemd (alternativa al compose)

Il repo contiene anche `emergency-stop.service` e `emergency-stop.timer`
(unita' one-shot chiamata ogni 60s) e `install.sh`, che crea un venv fuori dal
repo, installa le dipendenze e valida. `install.sh` **non** abilita il timer:
quello e' un passo separato, dopo aver visto un `--dry-run` pulito.

## Dove vivono i dati

| Cosa | Path |
|---|---|
| Compose (host) | `/mnt/applicazioni/yml/docker/emergency-stop/docker-compose.yml` |
| Servizi (host) | `/mnt/applicazioni/yml/docker/emergency-stop/services/*.yaml` |
| Log (host) | `/var/log/emergency-stop.log` |
| Incidenti (host) | `/mnt/applicazioni/yml/docker/emergency-stop/incidents/<timestamp>/` |
| Stato (container) | `/app/state/state.json` |
