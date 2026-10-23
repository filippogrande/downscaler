# REFERENCE — la mappa del codice

<!-- Tipo: REFERENCE. Rispecchia la struttura del codice, come una mappa. -->
<!-- Ogni riga: un file reale + un simbolo reale. Nessun numero di riga. -->
<!-- Si aggiorna NELLA STESSA PR che sposta qualcosa. -->

## Come si legge

Una riga per cosa che ti puo' essere chiesto di cambiare.
**Richiesta -> file -> entry point.** Se per trovare il file ti serve altro,
la riga e' sbagliata.

## Entry point

| Vuoi... | File | Entry point |
|---|---|---|
| Capire dove inizia tutto | `emergency-stop.py` | `main()` |
| Aggiungere un flag CLI | `emergency-stop.py` | `_parse_args()`, `main()` |
| Cambiare l'ordine del giro (health check, campionamento, decisione) | `emergency-stop.py` | `main()` |
| Vedere come gli effetti collaterali sono iniettati | `downscaler/monitoring.py` | `Actions`, `_build_actions()` |
| Vedere i wrapper patchabili dai test | `emergency-stop.py` | `load_services()`, `load_state()`, `save_state()`, `stop_service()`, `check_service_files()` |

## Logica di downscale

| Vuoi... | File | Entry point |
|---|---|---|
| Leggere iowait/load da Glances | `downscaler/monitoring.py` | `get_glances_metrics()`, `_read_glances_field()`, `_glances_get()` |
| Cambiare la media mobile | `downscaler/monitoring.py` | `update_window()` |
| Decidere se una metrica e' sopra/sotto soglia | `downscaler/monitoring.py` | `_above_stop()`, `_below_stop()` |
| Decidere quando il recovery puo' riavviare | `downscaler/monitoring.py` | `handle_recovery()` |
| Riavviare un servizio fermato | `downscaler/monitoring.py` | `_restart_next_service()` |
| Chiudere un incidente e tornare in monitor | `downscaler/monitoring.py` | `_close_incident()` |
| Decidere quanti servizi fermare in un colpo | `downscaler/monitoring.py` | `_super_stop_count()` |
| Scegliere i candidati allo stop | `downscaler/monitoring.py` | `_stop_candidates()` |
| Fermare un servizio e aggiornare lo stato | `downscaler/monitoring.py` | `_stop_one()` |
| Valutare le metriche dopo uno stop | `downscaler/monitoring.py` | `_evaluate_after_stop()` |
| Aggiornare la finestra dello stato | `downscaler/monitoring.py` | `_windowed_average()`, `sample_metrics()` |
| Cambiare il formato dei log delle metriche | `downscaler/monitoring.py` | `fmt_metric()` |

## Health check

| Vuoi... | File | Entry point |
|---|---|---|
| Riavviare i servizi down non spenti dal sistema | `downscaler/monitoring.py` | `health_check()` |
| Stabilire quali servizi sono riavviabili | `downscaler/services.py` | `restartable_services()` |

## File di servizio

| Vuoi... | File | Entry point |
|---|---|---|
| Leggere i file di servizio e ordinarli per priorita' | `downscaler/services.py` | `load_services()` |
| Cambiare i campi accettati in un file di servizio | `downscaler/services.py` | `load_services()` |
| Validare i file di servizio (`--validate`, `--selftest`) | `downscaler/services.py` | `check_service_files()` |
| Controllare un singolo servizio (compose_dir, compose, container) | `downscaler/services.py` | `_check_one_service()`, `_check_running()`, `_compose_is_valid()` |
| Controllare la configurazione di Glances | `downscaler/services.py` | `_check_glances()` |
| I default dei campi e la priorita' | `downscaler/config.py` | `DEFAULT_COMPOSE_FILE`, `DEFAULT_PRIORITY` |

## Operazioni Docker

| Vuoi... | File | Entry point |
|---|---|---|
| Fermare un servizio | `downscaler/docker_ops.py` | `stop_service()` |
| Riaccendere un servizio | `downscaler/docker_ops.py` | `start_service()` |
| Vedere quali container girano | `downscaler/docker_ops.py` | `running_containers()` |
| Sapere se un servizio e' attivo | `downscaler/docker_ops.py` | `is_service_running()` |
| Cambiare il comando `docker compose` | `downscaler/docker_ops.py` | `_compose_cmd()` |
| Gestire il dry-run dentro le operazioni | `downscaler/config.py` | `DRY_RUN` |

## Stato e notifiche

| Vuoi... | File | Entry point |
|---|---|---|
| Leggere `state.json` | `downscaler/state.py` | `load_state()` |
| Scrivere `state.json` | `downscaler/state.py` | `save_state()` |
| Inviare una notifica Telegram | `downscaler/state.py` | `send_telegram()` |
| Le chiavi dello stato e il loro valore iniziale | `downscaler/config.py` | `STATE_DEFAULTS` |

## Incidenti

| Vuoi... | File | Entry point |
|---|---|---|
| Raccogliere lo snapshot (log + metriche + summary) | `downscaler/incidents.py` | `collect_incident_snapshot()` |
| Salvare i log di un container nella finestra | `downscaler/incidents.py` | `_dump_container_log()` |
| Scrivere `metrics.json` | `downscaler/incidents.py` | `_write_metrics()` |
| Inviare il report finale | `downscaler/incidents.py` | `send_incident_report()` |

## Configurazione e tolleranza ai vecchi valori

| Vuoi... | File | Entry point |
|---|---|---|
| Cambiare le soglie di default | `downscaler/config.py` | `DEFAULTS` |
| Far tollerare una chiave nuova a un config vecchio | `downscaler/config.py` | `_merge_defaults()` |
| Completare uno stato parziale | `downscaler/config.py` | `_normalize_state()` |
| Cambiare i path dentro il container | `downscaler/config.py` | `CONFIG_PATH`, `SERVICES_DIR`, `STATE_PATH`, `LOG_PATH` |
| Cambiare il setup del logging | `downscaler/config.py` | `_setup_logging()` |
| Le eccezioni catturate (YAML, JSON, rete) | `downscaler/config.py` | `YAML_ERRORS`, `JSON_ERRORS`, `NETWORK_ERRORS` |

## Deploy e container

| Vuoi... | Dove |
|---|---|
| Cambiare l'immagine o DRY_RUN | `docker-compose.yml` -> `services.emergency-stop` |
| Cambiare i mount | `docker-compose.yml` -> `services.emergency-stop.volumes` |
| Cambiare il loop di avvio del container | `entrypoint.sh` |
| Cambiare come si installa il venv | `install.sh` |
| Cambiare unita' e timer systemd | `emergency-stop.service`, `emergency-stop.timer` |
| Cambiare le soglie in produzione | `config.yaml` -> `monitor.*`, `recovery.*` |
| Gestire le dipendenze | `.github/dependabot.yml` |
| Cosa la CI esegue | `.github/workflows/ci.yml` |

## Test

| Modulo | File |
|---|---|
| `emergency-stop.py` (entry point) | `tests/test_main.py` |
| `downscaler/config.py` | `tests/test_config.py` |
| `downscaler/monitoring.py` | `tests/test_monitoring.py` |
| `downscaler/services.py` | `tests/test_services.py` |
| `downscaler/docker_ops.py` | `tests/test_docker_ops.py` |
| `downscaler/state.py` | `tests/test_state.py` |
| `downscaler/incidents.py` | `tests/test_incidents.py` |
| Struttura del repo (Dockerfile, compose, esempi, config) | `tests/test_repo_structure.py` |
| Fixture condivise | `tests/conftest.py` |

## Limiti noti (dove la mappa e' sottile)

- `emergency-stop.py` e' un file di adattamento per i test: wrappa i nomi dei
  moduli perche' i test possano patcharli. Se cresce, il confine da' fastidio.
- `downscaler/monitoring.py` concentra metriche, macchina a stati e decisioni:
  e' il file piu' grande del package. Se cresce, separa la macchina a stati.
