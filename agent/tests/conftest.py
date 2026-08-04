"""Make `nova_agent` importable when tests run from the repo root, and pin a
dummy env so importing config never fails on a machine without .env. Real
integration is exercised by eval_scenarios.py, not these unit tests.
"""
import os
import sys
from pathlib import Path

AGENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT))

# config._get() raises without MONGODB_URI; unit tests never open a connection.
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017/")
os.environ.setdefault("MONGODB_DB", "nova_rca_test")
