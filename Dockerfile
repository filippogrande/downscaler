FROM python:3.12-alpine

# Il downscaler gira come utente non-root; ha solo bisogno del socket Docker
# (montato rw dal compose) e di scrivere stato/log su un volume.
RUN adduser -D -u 1000 emergency

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY emergency-stop.py entrypoint.sh ./
RUN chmod +x entrypoint.sh

USER emergency
ENTRYPOINT ["/app/entrypoint.sh"]
