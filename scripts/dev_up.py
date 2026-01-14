#!/usr/bin/env python3
import subprocess
import sys

CMD = [
    "docker", "compose",
    "-f", "docker-compose.yml",
    "-f", "docker-compose.dev.yml",
    "up", "-d"
]

def main():
    print("🔧 Starting development environment...")
    result = subprocess.run(CMD)

    if result.returncode != 0:
        print("❌ Failed to start dev environment", file=sys.stderr)
        sys.exit(result.returncode)

    print("✅ Dev environment is up")

if __name__ == "__main__":
    main()
