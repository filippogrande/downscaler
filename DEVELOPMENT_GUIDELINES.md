```markdown
# DEVELOPMENT_GUIDELINES

## Regole di base

- **Max 50 righe/funzione** — VINCOLANTE. Funzioni più lunghe vanno divise per coesione semantica.
- **Max 500 righe/file** — VINCOLANTE. File più lunghi vanno divisi in moduli più piccoli per coesione semantica (mai tagliare a metà per fare numero).
- **No fallback silenziati** — niente return []/{}/nil/mock per mascherare errori. Errore esplicito e visibile.
- **No file di test temporanei** — verifica sulla build reale, non su frammenti usa-e-getta.
- **Aggiornare documentazione nella stessa PR** — se cambi codice, aggiorna docs/ o README.md nello stesso branch.

## Sicurezza

- **Nessun segreto nel repo** — .env non committato, usa .env.example per i nomi delle variabili.
- **Dipendenze pinnate** — Python: `>=` o `==` (no nomi nudi). Node: package-lock.json committato. Go: go.mod + go.sum.

## Dependabot

- Ogni manifest (package.json, requirements.txt, go.mod, Dockerfile, docker-compose.yml, .github/workflows/) DEVE avere la sua voce in `.github/dependabot.yml`.
- Quando aggiungi un manifest, aggiorna dependabot.yml NELLA STESSA PR.

## Task tracking

- Task tracked in Vikunja. Chiudi solo quando il fix è mergiato E verificato.

## PR

- Una PR = un cambiamento logico. PR multi-file solo dove indicato (es. Lyrica).
- PR title in conventional commit: feat:, fix:, chore:, ci:, docs:.
```