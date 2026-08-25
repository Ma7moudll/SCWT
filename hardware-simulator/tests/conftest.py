"""Puts the `hardware-simulator` dir on sys.path so tests can import the
simulator modules (the directory name contains a hyphen, so it cannot be a
normal package)."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
