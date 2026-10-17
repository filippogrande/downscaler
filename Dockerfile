FROM python:3.14-alpine

# ── Dipendenze di sistema ───────────────────────────────────────────────
# Il downscaler chiama il CLI docker (`docker ps`, `docker compose down/up`).
# Senza il binario nel PATH ogni chiamata muore con
# FileNotFoundError: [Errno 2] No such file or directory: 'docker'
# e il container parte in restart loop (verificato 17/10/26).
# bash: comodo per i test manuali (`docker compose run --rm ... sh`).
RUN apk add --no-cache docker-cli bash

# Il downscaler deve poter scrivere il log nella directory bind-mountata
# dal compose (/var/log/emergency-stop.log sull'host): gira come root.
# Nota: il socket Docker e' montato rw dal compose, quindi il processo ha
# gia' un accesso equivalente a root al daemon. Non si aggiunge superficie.
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY emergency-stop.py entrypoint.sh ./
RUN chmod +x entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
