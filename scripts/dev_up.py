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

    no_build = "--no-build" in sys.argv
    show_logs = "--logs" in sys.argv

    print("🔧 Starting development environment...")

    up_cmd = BASE + ["up", "-d"]
    if not no_build:
        up_cmd.append("--build")

    run(up_cmd)

    # Quick health/status view
    print("\n📦 Current containers:")
    run(BASE + ["ps"])

    if show_logs:
        print("\n📜 Tailing logs (Ctrl+C to stop):")
        run(BASE + ["logs", "-f", "--tail", "100"])

    print("\n✅ Dev environment is up")

if __name__ == "__main__":
    main()
