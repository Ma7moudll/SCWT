"""AI-service test setup: pin classifier mode + ensure app modules import
with a clean (uncached) settings object. Env vars must be set before any
`app.config` import."""
from __future__ import annotations

import os
import sys

os.environ["AI_SERVICE_CLASSIFIER"] = "development"
os.environ.pop("DEVELOPMENT_FORCE_CLASS", None)
os.environ.pop("DEVELOPMENT_FORCE_CONFIDENCE", None)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
