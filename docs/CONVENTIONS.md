# CONVENTIONS — regole di codice e di repo

<!-- Tipo: HOW-TO. Le regole da rispettare prima di scrivere codice. -->

## Regole di base

- **Max 50 righe/funzione** — VINCOLANTE. Funzioni piu' lunghe vanno divise per
  coesione semantica.
- **Max 500 righe/file** — VINCOLANTE. File piu' lunghi vanno divisi in moduli
  piu' piccoli per coesione semantica (mai tagliare a meta' per fare numero).
- **No fallback silenziati** — niente `return []`/`{}`/`nil`/`mock` per mascherare
  errori. Errore esplicito e visibile.
- **No file di test temporanei** — verifica sulla build reale, non su frammenti
  usa-e-getta.
- **Aggiornare la documentazione nella stessa PR** — se cambi codice, aggiorna
  i doc nello stesso branch.

## Convenzione del compose

- TUTTO l'`environment` sta nel `docker-compose.yml` come valori letterali:
  niente `${...}`, niente `env_file`.
- Nessun `build:`: l'immagine arriva da Docker Hub.
- I path nei file di servizio sono path **assoluti dell'host**: il compose deve
  montare `/mnt/applicazioni`.

## Convenzione dei documenti

- Ogni doc e' **uno solo** dei quattro tipi: reference, explanation, how-to,
  tutorial. Dichiarato in testa.
- `docs/REFERENCE.md` e' la mappa: richiesta -> file -> entry point. Nessun
  numero di riga, nessun elenco di directory.
- `AGENTS.md` in root e' l'unico file letto sempre: sotto le 150 righe, un link per
  il resto.
- Un doc che non descrive piu' la realta' va corretto o cancellato NELLA STESSA PR
  che lo invalida. Mai stub, mai note "in realta' ora e' diverso".

## Sicurezza

- **Nessun segreto nel repo** — usa `.env.example` per i nomi delle variabili.
- **Dipendenze pinnate** — Python: `>=` o `==` (no nomi nudi).

## Dependabot

- Ogni manifest (`requirements.txt`, `Dockerfile`, `docker-compose.yml`,
  `.github/workflows/`) DEVE avere la sua voce in `.github/dependabot.yml`.
- Quando aggiungi un manifest, aggiorna `dependabot.yml` NELLA STESSA PR.

## Task tracking

- Task tracked in Vikunja. Chiudi solo quando il fix e' mergiato E verificato.

## PR

- Una PR = un cambiamento logico.
- Titolo in conventional commit: `feat:`, `fix:`, `chore:`, `ci:`, `docs:`.
