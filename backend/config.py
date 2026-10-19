"""Central paths and tunable constants. Override paths with environment variables."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv('SKYCONTROL_DATA_DIR', str(ROOT / 'data')))
CACHE_DIR = Path(os.getenv('SKYCONTROL_CACHE_DIR', str(DATA_DIR / 'cache')))
FRONTEND_DIR = ROOT / 'frontend'

RECORDING_FILE = DATA_DIR / 'london_amsterdam_opensky.json.gz'
REFERENCE_FILE = DATA_DIR / 'reference' / 'london_reference.json'
INDIA_SNAPSHOT_FILE = DATA_DIR / 'opensky_india_snapshot.json'

APP_NAME = 'SkyControl'
APP_VERSION = '6.0.0'

# Bump when analytics code changes so cached results are rebuilt.
ANALYTICS_VERSION = 10

# Screening thresholds used by the analytics. They are teaching parameters,
# not a statement of the separation minima applicable in a given airspace.
TMA_SEPARATION_NM = 3.0          # terminal radar separation used in the London TMA
ENROUTE_SEPARATION_NM = 5.0      # en-route radar separation
VERTICAL_SEPARATION_FT = 1000.0
# Mode C/S altitude is reported in 25 ft steps, so two aircraft level 1,000 ft
# apart can appear 975 ft apart. A 100 ft tolerance avoids that artefact.
VERTICAL_TOLERANCE_FT = 100.0
MIN_CONTROLLED_ALT_FT = 3000.0   # below this, VFR/helicopter traffic dominates the recording

LOGIN_LOCKOUT_FAILURES = 7
LOGIN_IP_LIMIT = 40
LOGIN_WINDOW_MINUTES = 15
SESSION_HOURS = 12
