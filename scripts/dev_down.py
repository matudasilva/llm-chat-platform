#!/usr/bin/env python3
import subprocess
import sys

CMD = [
    "docker", "compose",
    "-f", "docker-compose.yml",
    "-f", "docker-compose.dev.yml",
    "down"
]

def main():
    print("🛑 Stopping development environment...")
    result = subprocess.run(CMD)

    if result.returncode != 0:
        print("❌ Failed to stop dev environment", file=sys.stderr)
        sys.exit(result.returncode)

    print("✅ Dev environment stopped")

if __name__ == "__main__":
    main()
