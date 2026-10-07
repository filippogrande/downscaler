# Emergency Stop

Sistema di salvataggio/paracadute per il home-lab: quando il server soffre
(iowait troppo alto), spegne automaticamente servizi non critici in ordine di priorità,
poi li riaccende gradualmente dopo 5 min di calma.

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
- `monitor.sample_interval_sec`: ogni quanto campionare (30s)
- `monitor.window_sec`: finestra media mobile (120s = 2 min)
- `monitor.stop_threshold`: media > 80% → ferma un servizio
- `monitor.restart_threshold`: media < 60% → può riavviare
- `stop_order`: lista servizi in ordine di priorità di stop
- `services`: path dei compose file per ogni servizio
- `recovery.calm_duration_sec`: 5 min di calma prima di riavviare
- `recovery.restart_delay_sec`: 5 min tra un riavvio e l'altro
- `telegram`: bot_token e chat_id per notifiche

## Notifiche Telegram

Il sistema invia notifiche precise:

```
🚨 inizio downscale
- jellyseer
- lidarr
- sonarr

🔄 inizio recovery
+ sonarr
+ lidarr
+ jellyseer

✅ fine incidente
durata: 23 minuti
servizi fermati: 3
```

## Comandi utili

```bash
# Vedi i log
journalctl -u emergency-stop.service -f

# Vedi lo stato
cat /tmp/emergency-stop-state.json

# Riavvia il timer
sudo systemctl restart emergency-stop.timer

# Prova manualmente
python3 /opt/emergency-stop/emergency-stop.py
```

## Come funziona

1. **Health check**: ogni 60s verifica che tutti i servizi in `stop_order` siano attivi. Se uno è down e non è stato spento dal sistema, lo riavvia.
2. **Media mobile**: campiona iowait ogni 30s, calcola la media su finestra di 2 min.
3. **Isteresi**: stop se media > 80%, restart se media < 60%.
4. **Stop graduale**: ferma un servizio alla volta, aspetta 30s, verifica miglioramento.
5. **Recovery graduale**: 5 min di calma (media < 60%) → riavvia un servizio → altri 5 min → riavvia il successivo.

## Servizi mai fermati

I servizi non in `stop_order` non vengono mai toccati.
Attualmente esclusi: Nextcloud, Vikunja, Immich, Hermes, Glances, Uptime Kuma, ecc.
