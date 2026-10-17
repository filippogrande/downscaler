"""Garante di root: punta i path del modulo su /tmp PRIMA di qualsiasi import.

Perche' serve anche qui e non solo in tests/: la CI lancia
`pytest --tb=short -q` dalla root del repo, quindi conftest.py in tests/
potrebbe non essere caricato (tests/ non e' un package). Questo file in
root e' caricato sempre.
"""

import os
import tempfile

_TMP = tempfile.gettempdir()

os.environ.setdefault("EMERGENCY_STOP_LOG", f"{_TMP}/emergency-stop-test.log")
os.environ.setdefault("EMERGENCY_STOP_STATE", f"{_TMP}/emergency-stop-test-state.json")
os.environ.setdefault("EMERGENCY_STOP_CONFIG", "/non-esiste-config-test.yaml")
os.environ.setdefault("EMERGENCY_STOP_SERVICES", "/non-esiste-services-test")
