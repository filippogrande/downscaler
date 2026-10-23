# Emergency Stop (repo `downscaler`)

<!-- Radice della mappa: leggi QUESTO file per primo, sempre. -->
<!-- Tutto cio' che non serve ad OGNI task e' a un link di distanza. -->

Sistema di salvataggio/paracadute per il home-lab: quando il server soffre
(iowait o load troppo alti) spegne servizi non critici in ordine di priorita',
poi li riaccende gradualmente dopo 5 minuti di calma.

- Stack: Python 3.12+, PyYAML, requests; container Alpine
- Deploy: immagine `filippogrande/downscaler:latest` (buildata da GitHub Actions), compose locale
- Mappa del codice: `docs/REFERENCE.md`

## Comandi

| Azione | Comando |
|---|---|
| Test | `pytest --tb=short -q` |
| Lint | `ruff check emergency-stop.py tests/` |
| Security scan | `bandit -r emergency-stop.py -ll` |
| Valida senza toccare nulla | `docker run --rm -v "$PWD/config.yaml:/app/config.yaml:ro" -v "$PWD/services:/app/services:ro" -e DRY_RUN=true filippogrande/downscaler:latest --validate` |
| Valida senza Docker | come sopra, con `--validate --selftest` |
| Dry-run (stampa cosa farebbe) | come sopra, con `--dry-run` |
| Build immagine | `docker build -t downscaler .` |
| Installa sul master | `bash install.sh` |

## Indice — richiesta -> dove

| Vuoi... | Apri |
|---|---|
| Trovare una funzione o un file | `docs/REFERENCE.md` |
| Capire come funziona o perche' una scelta | `docs/ARCHITECTURE.md` |
| Conoscere le regole prima di scrivere codice | `docs/CONVENTIONS.md` |
| Configurare soglie o servizi gestiti | `docs/CONFIGURATION.md` |
| Aggiungere un servizio, aggiornare, validare | `docs/OPERATIONS.md` |
| Risolvere un problema noto | `docs/TROUBLESHOOTING.md` |
| Installare o aggiornare sul master | `docs/DEPLOY.md` |

## Documenti

| Doc | Tipo | Stato | A cosa serve |
|---|---|---|---|
| `docs/REFERENCE.md` | reference | ACTIVE 2026-10-23 | la mappa: richiesta -> file -> entry point |
| `docs/ARCHITECTURE.md` | explanation | ACTIVE 2026-10-23 | componenti, flusso di un giro, deploy, sicurezza |
| `docs/CONVENTIONS.md` | how-to | ACTIVE 2026-10-23 | regole di codice e di repo |
| `docs/CONFIGURATION.md` | reference | ACTIVE 2026-10-23 | `config.yaml` e i file di servizio |
| `docs/OPERATIONS.md` | how-to | ACTIVE 2026-10-23 | operazioni ricorrenti |
| `docs/TROUBLESHOOTING.md` | how-to | ACTIVE 2026-10-23 | problemi noti e sintomi |
| `docs/DEPLOY.md` | how-to | ACTIVE 2026-10-23 | installazione e aggiornamento |

## Regole

- Branch + PR, mai push su `main`.
- I doc — incluse le voci di questo indice — si aggiornano NELLA STESSA PR che li invalida.
- Limiti: 50 righe/funzione, 500 righe/file, niente fallback silenziosi, niente file di test usa-e-getta.
- Il compose ha valori letterali: niente `${...}`, niente `build:`, niente `env_file`.
- Mappa onesta: una riga che indica un path sbagliato si corregge subito, non si annota.
