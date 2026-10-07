# Emergency Stop

Sistema di salvataggio/paracadute per il home-lab: quando il server soffre
(iowait o load troppo alto), spegne automaticamente servizi non critici
in ordine di priorità, poi li riaccende dopo 1h di calma.

## Installazione

```bash
# 1. Clona il repo
git clone https://github.com/filippogrande/downscaler.git /opt/emergency-stop

# 2. Installa dipendenze
pip3 install pyyaml requests

# 3. Copia i file systemd
sudo cp /opt/emergency-stop/emergency-stop.service /etc/systemd/system/
sudo cp /opt/emergency-stop/emergency-stop.timer /etc/systemd/system/

# 4. Abilita e avvia
sudo systemctl daemon-reload
sudo systemctl enable --now emergency-stop.timer
```

## Configurazione

Modifica `/opt/emergency-stop/config.yaml`:
- `glances.url`: URL della tua istanza Glances
- `monitor.metric`: `iowait` o `load`
- `monitor.threshold`: soglia che scatena l'allarme
- `monitor.duration_sec`: quanto tempo deve restare sopra la soglia
- `stop_order`: lista servizi in ordine di priorità di stop
- `services`: path dei compose file per ogni servizio

## Comandi utili

```bash
# Vedi i log
journalctl -u emergency-stop.service -f

# Vedi lo stato
cat /tmp/emergency-stop-state.json

# Riavvia il timer
sudo systemctl restart emergency-stop.timer

# Prova manualmente (dry-run)
python3 /opt/emergency-stop/emergency-stop.py
```

## Come funziona

1. Ogni 60s legge iowait/load da Glances
2. Se sopra soglia per 2 min → ferma il primo servizio in lista
3. Aspetta 30s → ricontrolla. Se migliorato → recovery mode
4. Recovery: 1h senza allarme → riaccende in ordine inverso

## Servizi mai fermati

Jellyfin, Hermes, Nextcloud, Vikunja, Immich non sono in `stop_order`
quindi non verranno mai fermati.
