#!/bin/sh
# Emergency Stop — entrypoint container.
#
# DRY_RUN=true  (default): stampa cosa farebbe, NON esegue nulla.
# DRY_RUN=false          : esegue davvero.
#
# Argomenti singoli (per test con `docker compose run --rm ...`):
#   --validate | --dry-run | --selftest
#   -> esegue una corsa singola e esce.
# Senza argomenti: loop infinito ogni CHECK_INTERVAL secondi.

set -e

INTERVAL=${CHECK_INTERVAL:-60}

case "${1:-}" in
    --validate|--dry-run|--selftest)
        if [ "${DRY_RUN:-true}" = "true" ]; then
            echo "DRY_RUN=true (solo simulazione, nessuna azione reale)"
        else
            echo "DRY_RUN=false (esegue davvero)"
        fi
        exec python3 /app/emergency-stop.py "$@"
        ;;
    *)
        if [ "${DRY_RUN:-true}" = "true" ]; then
            echo "DRY_RUN=true (solo simulazione, nessuna azione reale)"
        else
            echo "DRY_RUN=false (esegue davvero)"
        fi
        ;;
esac

# Loop infinito: esegue il check, aspetta INTERVAL secondi, ricomincia.
while true; do
    python3 /app/emergency-stop.py
    echo "[loop] prossimo check tra ${INTERVAL}s (DRY_RUN=${DRY_RUN:-true})"
    sleep "${INTERVAL}"
done
