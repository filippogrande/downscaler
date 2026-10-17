# Emergency Stop

Sistema di salvataggio/paracadute per il home-lab: quando il server soffre
(iowait troppo alto), spegne automaticamente servizi non critici in ordine di priorità,
poi li riaccende gradualmente dopo 5 min di calma.

## Installazione

```bash
# 0. Clona il repo (solo codice; stesso posto degli altri servizi)
git clone https://github.com/filippogrande/downscaler.git /mnt/applicazioni/emergency-stop

# 1. Dipendenze
sudo apt install -y python3-pip
pip3 install pyyaml requests

# 2. Configura (FUORI dal repo: un git pull non la sovrascrive)
sudo mkdir -p /etc/emergency-stop/services
sudo cp /mnt/applicazioni/emergency-stop/config.yaml /etc/emergency-stop/
sudo cp /mnt/applicazioni/emergency-stop/examples/services/*.yaml /etc/emergency-stop/services/

# 3. Valida la configurazione (dir, compose, nomi container, Glances)
python3 /mnt/applicazioni/emergency-stop/emergency-stop.py --validate

# 4. Prova senza fare nulla: mostra cosa farebbe
python3 /mnt/applicazioni/emergency-stop/emergency-stop.py --dry-run

# 5. Copia i file systemd e avvia
sudo cp /mnt/applicazioni/emergency-stop/emergency-stop.service /etc/systemd/system/
sudo cp /mnt/applicazioni/emergency-stop/emergency-stop.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now emergency-stop.timer
```

**Ordine obbligato: `--validate`, poi `--dry-run`, poi il timer.**
Mai abilitare il timer prima di aver visto un `--dry-run` pulito.

### Se manca pip3

```bash
sudo apt install -y python3-pip
```

Il repo NON va in `/opt` (di root, non scrivibile senza sudo): sta in
`/mnt/applicazioni/emergency-stop`, come tutti gli altri servizi.

## Le due modalita' di verifica

```bash
# Controlla config, compose, nomi container, Glances. Non tocca nulla.
python3 /mnt/applicazioni/emergency-stop/emergency-stop.py --validate

# Esegue la logica completa MA senza toccare Docker ne lo stato:
# stampa '[dry-run] STOP: <servizio>' invece di fermarlo.
python3 /mnt/applicazioni/emergency-stop/emergency-stop.py --dry-run
```

`--dry-run` legge lo stato esistente (quindi vede i servizi gia' fermati) ma **non lo
riscrive**: il file di stato resta pulito e il timer puo' essere abilitato dopo.

Esempio di output:

```
=== DRY-RUN: nessuna azione reale verra' eseguita ===
Check: iowait=2.1 media=1.8 (stop>80.0, restart<60.0)
Health check: radarr è down, lo riavvio
[dry-run] START: radarr → docker compose -f /mnt/applicazioni/yml/docker/radarr/docker-compose.yml up -d
```

## Configurazione

Due livelli, apposta separati:

| File | Cosa contiene | Dove |
|---|---|---|
| `config.yaml` | soglie, Glances, Telegram, recovery | `/etc/emergency-stop/config.yaml` |
| `services/<nome>.yaml` | un file per servizio | `/etc/emergency-stop/services/` |

### config.yaml

- `glances.url`: URL della tua istanza Glances
- `monitor.metric`: `iowait` o `load`
- `monitor.sample_interval_sec`: ogni quanto campionare (30s)
- `monitor.window_sec`: finestra media mobile (120s = 2 min)
- `monitor.stop_threshold`: media > 80% → ferma un servizio
- `monitor.restart_threshold`: media < 60% → può riavviare
- `recovery.calm_duration_sec`: 5 min di calma prima del primo riavvio
- `recovery.restart_delay_sec`: 5 min tra un riavvio e l'altro
- `telegram`: bot_token e chat_id per notifiche

### File di servizio

Un file per servizio, `/etc/emergency-stop/services/<nome>.yaml`:

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
| `name` | nome del servizio (usato in stato e notifiche). Deve corrispondere al **nome esatto** del container | obbligatorio |
| `compose_dir` | directory del compose | obbligatorio |
| `compose_file` | nome del compose | `docker-compose.yml` |
| `service_name` | container da considerare (uno o più) | `app` |
| `can_stop` | il downscaler può fermarlo | `true` |
| `can_restart` | il downscaler può riaccenderlo | `true` |
| `one_shot` | batch da cron, nessun container residente | `false` |
| `priority` | ordine di stop (più basso = prima) | `100` |
| `note` | libera, documenta la scelta | vuota |

**Perché `can_stop` e `can_restart` sono separati:**

- `can_stop: false` → non lo tira giù, ma il health-check può riaccenderlo
- `can_restart: false` → può tirarlo giù, ma il health-check non lo riaccende

Un solo `enabled: false` creerebbe un buco: il servizio finirebbe in `stopped_services`
e non verrebbe mai più riacceso.

**`one_shot`** è per i servizi da cron (`recyclarr`, `cleanuparr`): non hanno un
container residente, quindi il health-check non deve riavviarli ogni 60s.

**Suwayomi** è un unico servizio (`suwayomi`): sfw, nsfw e gluetun condividono
lo stesso compose e vanno giù insieme.

## Comandi utili

```bash
# Valida config, compose e nomi container
python3 /mnt/applicazioni/emergency-stop/emergency-stop.py --validate

# Mostra cosa farebbe, senza eseguire nulla
python3 /mnt/applicazioni/emergency-stop/emergency-stop.py --dry-run

# Vedi i log
journalctl -u emergency-stop.service -f

# Vedi lo stato
cat /var/lib/emergency-stop/state.json

# Riavvia il timer
sudo systemctl restart emergency-stop.timer

# Prova manualmente (esegue davvero)
python3 /mnt/applicazioni/emergency-stop/emergency-stop.py
```

## Stato

`/var/lib/emergency-stop/state.json` — **non** in `/tmp`, che si svuota al reboot.
Se lo stato sparisce si perdono `recovery_started_at` e `incident_start`, quindi
la durata dell'incidente e il primo riavvio dopo un riavvio del server.

In `--dry-run` lo stato **non viene scritto**.

## Metriche Glances

Da Glances 4.0 l'API è `/api/4/`: la vecchia `/api/3/` non esiste più
(risponde `404 {"detail":"Not Found"}`) e il plugin `system` non espone
più le metriche.

- `iowait` → `GET /api/4/cpu`, campo `iowait`
- `load` → `GET /api/4/load`, campo `min1`

Il programma prova prima `/api/4/` e poi `/api/3/` (per Glances più vecchi).
Se la metrica non è leggibile il giro viene **saltato** e l'errore va in log:
non viene più usato `0.0` (= tutto ok).

## Come funziona

1. **Health check**: ogni 60s verifica i servizi residenti non spenti dal sistema e li riavvia (salta one-shot e `can_restart: false`).
2. **Media mobile**: campiona iowait ogni 30s, media su finestra di 2 min.
3. **Isteresi**: stop se media > 80%.
4. **Stop graduale**: ferma un servizio alla volta; se il down fallisce, il giro dopo prova il successivo.
5. **Recovery**: 5 min di calma **con media < restart_threshold** → riavvia un servizio → altri 5 min → il successivo.

**Avviso**: chi spegne un servizio a mano lo vede riacceso dal health-check entro 60s.
Prima di lavorare su un servizio: `systemctl stop emergency-stop.timer`.

## Servizi mai fermati

I servizi non in `services/` non vengono toccati.
Attualmente esclusi: Nextcloud, Vikunja, Immich, Hermes, Glances, Uptime Kuma, ecc.
