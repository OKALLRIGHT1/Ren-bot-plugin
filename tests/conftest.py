"""Plugin integration tests use the public Ren-bot host contracts."""
import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
host = os.environ.get("REN_BOT_ROOT")
if host:
    sys.path.insert(0, str(Path(host).resolve()))
