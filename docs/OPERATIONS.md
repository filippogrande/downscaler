# OPERATIONS — operazioni ricorrenti

<!-- Tipo: HOW-TO. I passi per un obiettivo concreto. -->

## Validare la configurazione senza toccare nulla

```bash
# valida config, compose, nomi container, Glances — non tocca nulla
docker run --rm \
  -v "$PWD/config.yaml:/app/config.yaml:ro" \
  -v "$PWD/services:/app/services:ro" \
  -e DRY_RUN=true \
  filippogrande/downscaler:latest --validate

# senza Docker (solo file e nomi)
docker run --rm \
  -v "$PWD/config.yaml:/app/config.yaml:ro" \
  -v "$PWD/services:/app/services:ro" \
  filippogrande/downscaler:latest --validate --selftest
```

`--selftest` controlla solo che i path esistano: non serve il socket Docker.

## Provare cosa farebbe senza spegnere nulla

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock:rw \
  -v "$PWD/config.yaml:/app/config.yaml:ro" \
  -v "$PWD/services:/app/services:ro" \
  filippogrande/downscaler:latest --dry-run
```

`--dry-run` stampa i comandi e non scrive `state.json`. Utile anche con valori
simulati: `--simulate-iowait 96 --simulate-load 2`.

## Farlo lavorare davvero

`docker-compose.yml` ha `DRY_RUN: "true"`. Per attivarlo:

```bash
# modifica DRY_RUN: "false" nel compose, poi
docker compose up -d
```

## Comandi di tutti i giorni

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

## Aggiungere un servizio gestito

1. Crea `examples/services/<nome>.yaml` con `name`, `compose_dir` (path assoluto),
   `priority` e, se serve, `can_stop`/`can_restart`/`one_shot`.
2. Controlla che `name` corrisponda **esattamente** al nome del container:
   `docker ps --format '{{.Names}}'`.
3. Copialo nella cartella di deploy (`services/`).
4. Valida: `filippogrande/downscaler:latest --validate`.

Se un servizio deve restare escluso, usa `can_stop: false` — non un campo
`enabled: false`, che non esiste e creerebbe un buco.

## Fermare il downscaler per lavorare su un servizio

Chi spegne un servizio a mano lo vede riacceso dall'health-check entro 60s.
Per lavorare su un servizio:

```bash
docker compose stop emergency-stop
```

## Leggere uno snapshot d'incidente

```
incidents/<timestamp>/
  ├── <container>.log     <- log nella finestra dell'incidente
  ├── metrics.json        <- iowait/load all'inizio e alla fine
  └── summary.txt         <- durata, servizi fermati, ordine
```

`metrics.json` per l'andamento, `summary.txt` per il riepilogo, i `.log` per i
dettagli.
