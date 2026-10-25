# TROUBLESHOOTING — problemi noti e sintomi

<!-- Tipo: HOW-TO. Un sintomo, la causa, la verifica. -->

## Il container parte in restart loop

**Sintomo**: log con traceback, il container riparte continuamente.

**Cause verificate**:

1. **`docker-cli` mancante** — `FileNotFoundError: 'docker'`. Il Dockerfile deve
   fare `apk add docker-cli`. Verifica: `docker run --rm --entrypoint python3
   downscaler -c "import shutil; print(shutil.which('docker'))"`.
2. **`docker-cli-compose` mancante** — con solo `docker-cli`, `docker compose -f ...`
   fallisce con `unknown shorthand flag: 'f' in -f` perche' docker interpreta
   `compose` come un comando suo. Serve anche `docker-cli-compose`.
3. **`ModuleNotFoundError: downscaler`** — il Dockerfile ha copiato i moduli in
   `/app/` invece di `/app/downscaler/`. `COPY downscaler/ ./` copia solo i
   **contenuti**: serve `COPY downscaler /app/downscaler`.

La CI verifica il punto 3 con lo step "Docker image imports downscaler".

## Tutte le `compose_dir` risultano inesistenti

**Sintomo**: `--validate` segnala ogni servizio con compose_dir inesistente.

**Causa**: i `compose_dir` nei file di servizio sono path **assoluti dell'host**;
il compose deve montare `/mnt/applicazioni`. Senza il mount il container non li
vede.

## `IsADirectoryError` sul file di log

**Sintomo**: il log handler non si apre.

**Causa**: il log e' bind-mountato dall'host. Se il file non esiste sull'host,
Docker crea una **directory**. `entrypoint.sh` crea il file prima di avviare
Python; `config.py` degrada a stdout se la directory non e' scrivibile.

## Le metriche non si leggono

**Sintomo**: il giro viene saltato con un errore in log.

- Da Glances 4.0 l'API e' `/api/4/`; `/api/3/` risponde `404`. `_read_glances_field()`
  prova la 4 e poi la 3.
- `iowait` e' in `/api/4/cpu`, non nel plugin `system`.
- **Non usare `0.0` come valore mancante**: significherebbe "tutto ok" e impedirebbe
  lo stop proprio quando serve. Il codice salta il giro.

## Il recovery non riavvia niente

**Verifiche in ordine**:

1. Le metriche sono **entrambe** sotto soglia (il riavvio richiede entrambe).
2. Sono passati 5 minuti di calma (`recovery.calm_duration_sec`).
3. I servizi fermati non hanno `can_restart: false`.
4. Se le metriche risalgono sopra la soglia di stop, il sistema torna in `monitor`:
   e' il comportamento voluto.

## Il downscaler riaccende un servizio spento a mano

E' il comportamento voluto (health-check). Per lavorare sul servizio:
`docker compose stop emergency-stop`.

## `sonarr` risulta in esecuzione per colpa di `sonarr-anime`

Il confronto dei nomi container e' **esatto**, non per sottostringa. Se vedi
questo sintoma e' tornato il bug: controlla `running_containers()`.

Nota: `prowlarr` e `prowlarr_flaresolverr` sono nello STESSO compose, quindi
`down` li ferma insieme (voluto). Il matching resta esatto: flaresolverr non si
ferma da solo.

## Un log di allarme solleva `ValueError`

**Sintomo**: `{v:.1f if v ...}` nei log.

Un selettore di formato non puo' contenere una condizione. La regola e' in
`fmt_metric()`: la condizione sta fuori, il formato dentro.

## Lo stato in `state.json` e' parziale

Uno stato scritto da una versione precedente (o in dry-run) puo' non avere tutte
le chiavi. `_normalize_state()` le completa; senza quel completamento il primo
accesso solleva `KeyError` e il container va in loop.

## `KeyError: 'load_stop_threshold'` all'avvio

Il config locale non aveva le chiavi aggiunte dopo. `_merge_defaults()` le
aggiunge dai `DEFAULTS`: aggiorna `config.yaml` o lascia fare ai default.
