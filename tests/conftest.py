"""Configurazione di pytest per Emergency Stop.

I path del modulo si leggono da env (EMERGENCY_STOP_*): senza questo,
_setup_logging() tenta /app/logs al caricamento e fallisce in CI, dove /app
non esiste e non si hanno i permessi di root.
"""

import os
import tempfile

_TMP = tempfile.gettempdir()

os.environ.setdefault("EMERGENCY_STOP_LOG", f"{_TMP}/emergency-stop-test.log")
os.environ.setdefault("EMERGENCY_STOP_STATE", f"{_TMP}/emergency-stop-test-state.json")
os.environ.setdefault("EMERGENCY_STOP_CONFIG", "/non-esiste-config-test.yaml")
os.environ.setdefault("EMERGENCY_STOP_SERVICES", "/non-esiste-services-test")
