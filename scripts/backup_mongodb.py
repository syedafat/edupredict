#!/usr/bin/env python3
"""Create a MongoDB backup without embedding credentials in source."""
import argparse
import json
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="./backups")
    args = parser.parse_args()
    uri = os.environ.get("MONGO_URI")
    if not uri:
        raise SystemExit("MONGO_URI must be set in the environment.")
    if not shutil.which("mongodump"):
        raise SystemExit("mongodump is required; install MongoDB Database Tools.")
    destination = os.path.join(args.output, datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    os.makedirs(destination, mode=0o700, exist_ok=True)
    os.chmod(destination, 0o700)
    descriptor, config_path = tempfile.mkstemp(prefix="edupredict-mongodump-", suffix=".yaml")
    try:
        os.chmod(config_path, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as config_file:
            json.dump({"uri": uri}, config_file)
        result = subprocess.run(
            ["mongodump", "--config", config_path, "--out", destination],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            raise SystemExit(f"mongodump failed with exit code {result.returncode}; details suppressed.")
    finally:
        try:
            os.remove(config_path)
        except FileNotFoundError:
            pass
    print(f"Backup written to {destination}")


if __name__ == "__main__":
    main()