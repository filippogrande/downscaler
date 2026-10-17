#!/usr/bin/env bash
# Installa Emergency Stop sul master.
#
# Crea un venv (Debian blocca pip globale con PEP 668), copia la config fuori
# dal repo e valida. NON abilita il timer: quello e' un passo separato, dopo
# aver visto un --dry-run pulito.

set -euo pipefail

REPO_DIR="/mnt/applicazioni/emergency-stop"
CONF_DIR="/etc/emergency-stop"
SERVICES_DIR="${CONF_DIR}/services"
VENV="${REPO_DIR}/venv"

if [ ! -d "${REPO_DIR}" ]; then
    echo "ERRORE: ${REPO_DIR} non esiste. Clona prima il repo:"
    echo "  git clone https://github.com/filippogrande/downscaler.git ${REPO_DIR}"
    exit 1
fi

echo "=== 1/4 venv ==="
if [ ! -x "${VENV}/bin/python" ]; then
    python3 -m venv "${VENV}"
fi
"${VENV}/bin/pip" install --quiet --upgrade pip
"${VENV}/bin/pip" install --quiet pyyaml requests

echo "=== 2/4 dipendenze di sistema ==="
for bin in docker; do
    if ! command -v "${bin}" >/dev/null 2>&1; then
        echo "ERRORE: ${bin} non trovato"
        exit 1
    fi
done

echo "=== 3/4 config fuori dal repo ==="
install -d -m 755 "${SERVICES_DIR}"
install -m 644 "${REPO_DIR}/config.yaml" "${CONF_DIR}/config.yaml"
install -m 644 "${REPO_DIR}"/examples/services/*.yaml "${SERVICES_DIR}/"
echo "  installati $(ls -1 "${SERVICES_DIR}" | wc -l) file di servizio"

echo "=== 4/4 validazione ==="
set +e
"${VENV}/bin/python" "${REPO_DIR}/emergency-stop.py" --validate
RC=$?
set -e

if [ "${RC}" -ne 0 ]; then
    echo ""
    echo "VALIDAZIONE FALLITA: correggi gli errori sopra prima di continuare."
    exit 1
fi

echo ""
echo "=== Setup completato. PROSSIMO PASSO (fai tu): ==="
echo ""
echo "  # vedi cosa farebbe, senza eseguire nulla"
echo "  ${VENV}/bin/python ${REPO_DIR}/emergency-stop.py --dry-run"
echo ""
echo "  # solo dopo un dry-run pulito:"
echo "  sudo install -m 644 ${REPO_DIR}/emergency-stop.service /etc/systemd/system/"
echo "  sudo install -m 644 ${REPO_DIR}/emergency-stop.timer /etc/systemd/system/"
echo "  sudo systemctl daemon-reload"
echo "  sudo systemctl enable --now emergency-stop.timer"
