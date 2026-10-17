#!/bin/sh
# Emergency Stop — entrypoint container.
#
# DRY_RUN=true  (default): stampa cosa farebbe, NON esegue nulla.
# DRY_RUN=false          : esegue davvero.
# L'intervallo del loop e' check_interval_sec in config.yaml (una sola fonte).
#
# Argomenti singoli (per test con `docker run --rm ...`):
#   --validate | --dry-run | --selftest
#   -> esegue una corsa singola e esce.
# Senza argomenti: loop infinito.

set -e

# Il log e' bind-mountato dall'host (vedi compose): se l'host non ha il file,
# Docker crea una DIRECTORY e il log handler fallisce con IsADirectoryError.
# Lo creiamo qui, prima di avviare Python.
mkdir -p /app/logs
touch /app/logs/emergency-stop.log

if [ "${DRY_RUN:-true}" = "true" ]; then
    echo "DRY_RUN=true (solo simulazione, nessuna azione reale)"
else
    echo "DRY_RUN=false (esegue davvero)"
fi

case "${1:-}" in
    --validate|--dry-run|--selftest)
        exec python3 /app/emergency-stop.py "$@"
        ;;
esac

# Loop infinito: esegue il check, aspetta, ricomincia.
# L'intervallo lo decide config.yaml (check_interval_sec), qui non c'e' nulla da duplicare.
while true; do
    python3 /app/emergency-stop.py
    sleep 60
    echo "[loop] prossimo check tra 60s (DRY_RUN=${DRY_RUN:-true})"
done
