#!/bin/sh
# Deterministic engine tests only: an isolated network namespace, empty environment.
set -eu
cd "$(dirname "$0")"
recovery_dir=$(pwd)
repo_dir=$(git rev-parse --show-toplevel)
mkdir -p evidence
exec unshare -rn env -i PATH=/usr/bin:/bin HOME=/tmp \
  AWS_CONFIG_FILE=/nonexistent AWS_SHARED_CREDENTIALS_FILE=/nonexistent \
  AWS_EC2_METADATA_DISABLED=true APP_SETTINGS_ENV_FILE= \
  PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
  "$repo_dir/.venv/bin/python" -m pytest -q -c /dev/null -p no:cacheprovider \
  --confcutdir="$recovery_dir" "$recovery_dir/test_admin_recovery.py" \
  --junitxml="$recovery_dir/evidence/focused-final.xml"
