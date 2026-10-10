"""Generate a hash-pinned Linux production dependency lock for the Docker build."""
import platform
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main():
    if platform.system() != "Linux":
        raise SystemExit("Run this on the Linux/Python 3.12 production build platform.")
    if sys.version_info[:2] != (3, 12):
        raise SystemExit("Use Python 3.12 to match the production Docker runtime.")
    if shutil.which("pip-compile") is None:
        raise SystemExit("Install pip-tools from requirements-dev.txt, then rerun this script.")

    subprocess.run(
        [
            "pip-compile",
            "--generate-hashes",
            "--resolver=backtracking",
            "--output-file=requirements-prod.lock",
            "requirements.txt",
        ],
        cwd=ROOT,
        check=True,
    )


if __name__ == "__main__":
    main()
