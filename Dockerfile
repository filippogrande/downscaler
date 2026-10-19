FROM python:3.14-alpine

# ── Dipendenze di sistema ───────────────────────────────────────────────
# Il downscaler chiama il CLI docker (`docker ps`) E `docker compose down/up`.
#
# Trappola 1: senza docker-cli le chiamate muoiono con FileNotFoundError
#          'docker' e il container parte in restart loop (17/10/26).
# Trappola 2: `docker-cli` da solo NON include il plugin Compose: `docker compose`
#          fallisce con "unknown shorthand flag: 'f' in -f" perche' docker
#          interpreta `compose` come un comando suo (17/10/26).
#          Serve anche `docker-cli-compose`.
# bash: comodo per i test manuali (`docker compose run --rm ... sh`).
RUN apk add --no-cache docker-cli docker-cli-compose bash

# Il downscaler deve poter scrivere il log nella directory bind-mountata
# dal compose (/var/log/emergency-stop.log sull'host): gira come root.
# Nota: il socket Docker e' montato rw dal compose, quindi il processo ha
# gia' un accesso equivalente a root al daemon. Non si aggiunge superficie.
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# `downscaler/` e' il package con la logica: l'entrypoint fa
# `from downscaler import ...`, quindi il package DEVE stare in /app/downscaler.
# Trappola: `COPY <dir>/ ./` copia solo i CONTENUTI della directory, non la
# directory stessa — con `COPY emergency-stop.py entrypoint.sh downscaler/ ./`
# i moduli finivano in /app/ e `import downscaler` moriva con ModuleNotFoundError
# (restart loop). Serve un dest esplicito.
COPY emergency-stop.py entrypoint.sh ./
COPY downscaler /app/downscaler
RUN chmod +x entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
