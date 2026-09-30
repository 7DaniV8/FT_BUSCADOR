#!/usr/bin/env python3
"""Compatibilidad: ahora es scripts/sacar_claves.py (FanDuel y BetMGM)."""
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).with_name("sacar_claves.py")), run_name="__main__")
