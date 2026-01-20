#!/usr/bin/env python3
import subprocess
import sys
from pathlib import Path

BASE = ["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.dev.yml"]

def run(cmd: list[str]) -> None:
    result = subprocess.run(cmd)
    if result.returncode != 0:
        sys.exit(result.returncode)

def ensure_files_exist() -> None:
    missing = [p for p in ["docker-compose.yml", "docker-compose.dev.yml"] if not Path(p).exists()]
    if missing:
        print(f"❌ Missing compose file(s): {', '.join(missing)}", file=sys.stderr)
        sys.exit(2)

def main() -> None:
    ensure_files_exist()

    with_volumes = "--volumes" in sys.argv or "-v" in sys.argv
    remove_orphans = "--remove-orphans" in sys.argv

    print("🛑 Stopping development environment...")

    down_cmd = BASE + ["down"]
    if with_volumes:
        down_cmd.append("-v")
    if remove_orphans:
        down_cmd.append("--remove-orphans")

    run(down_cmd)

    print("✅ Dev environment stopped")

if __name__ == "__main__":
    main()
