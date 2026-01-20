#!/usr/bin/env python3
import subprocess
import sys
from pathlib import Path

BASE = ["docker", "compose", "-f", "docker-compose.yml", "-f", "docker-compose.dev.yml"]

def run(cmd: list[str]) -> int:
    result = subprocess.run(cmd)
    return result.returncode

def ensure_files_exist() -> None:
    missing = [p for p in ["docker-compose.yml", "docker-compose.dev.yml"] if not Path(p).exists()]
    if missing:
        print(f"❌ Missing compose file(s): {', '.join(missing)}", file=sys.stderr)
        sys.exit(2)

def main() -> None:
    ensure_files_exist()

    show_config = "--config" in sys.argv
    show_services = "--services" in sys.argv
    show_logs = "--logs" in sys.argv

    print("📦 Dev environment status:\n")

    rc = run(BASE + ["ps"])
    if rc != 0:
        print("\n❌ Unable to read compose status. Is Docker running?", file=sys.stderr)
        sys.exit(rc)

    if show_services:
        print("\n🧩 Services:")
        rc = run(BASE + ["config", "--services"])
        if rc != 0:
            sys.exit(rc)

    if show_config:
        print("\n🧾 Effective merged config:")
        rc = run(BASE + ["config"])
        if rc != 0:
            sys.exit(rc)

    if show_logs:
        print("\n📜 Recent logs (tail=100):")
        rc = run(BASE + ["logs", "--tail", "100"])
        if rc != 0:
            sys.exit(rc)

    print("\n✅ Status complete")

if __name__ == "__main__":
    main()
