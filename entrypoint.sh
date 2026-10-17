#!/bin/sh
# Emergency Stop — entrypoint container.
#
# DRY_RUN=true  (default): stampa cosa farebbe, NON esegue nulla.
# DRY_RUN=false          : esegue davvero.
#
# Se passi --validate / --dry-run / --selftest come argomento:
#   esegue una corsa singola (per test con `docker compose run --rm ...`)  
# Altrimenti: loop infinito ogni INTERVAL secondi.

set -e

INTERVAL=${CHECK_INTERVAL:-60}

dry_run_info() {
    if [ "${DRY_RUN:-true}" = "true" ]; then
        echo "DRY_RUN=true (solo simulazione, nessuna azione reale)"
    else
        echo "DRY_RUN=false (esegue davvero — attenzione!)"
    fi
}

case "${1:-}" in
    --validate|--dry-run|--selftest)
        dry_run_info
        exec python3 /app/emergency-stop.py "$@"
        ;;
    *)
        dry_run_info
        ;;
esac

# Loop infinito: esegue il check, aspetta INTERVAL secondi, ricomincia.
while true; do
    python3 /app/emergency-stop.py
    echo "[loop] prossimo check tra ${INTERVAL}s (DRY_RUN=${DRY_RUN:-true})"
    sleep "${INTERVAL}"
done
