FROM python:3.12-alpine

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
