#!/usr/bin/env python3
"""Create a MongoDB backup without embedding credentials in source."""
import argparse
import os
import shutil
import subprocess
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
    subprocess.run(["mongodump", "--uri", uri, "--out", destination], check=True)
    print(f"Backup written to {destination}")


if __name__ == "__main__":
    main()