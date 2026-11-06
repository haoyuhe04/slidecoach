"""Run with the service stopped to keep uploaded files and DB in one snapshot."""
import argparse
import sqlite3
import shutil
from datetime import datetime, timezone
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--data", required=True)
parser.add_argument("--output", required=True)
args = parser.parse_args()
source = Path(args.data)
target = Path(args.output) / datetime.now(timezone.utc).strftime("slidecoach-%Y%m%dT%H%M%SZ")
target.mkdir(parents=True, mode=0o700)
with sqlite3.connect(source / "slidecoach.sqlite3") as src, sqlite3.connect(target / "slidecoach.sqlite3") as dst:
    src.backup(dst)
shutil.copytree(source / "uploads", target / "uploads")
print(target)
