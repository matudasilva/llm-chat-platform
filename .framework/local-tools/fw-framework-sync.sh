#!/usr/bin/env bash

set -euo pipefail

# Controlled Framework Sync Helper
# Automates drift detection and controlled propagation from canonical Framework repo
# Modes: check (drift detection), plan (preview changes), apply (controlled propagation)

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly CONSUMER_REPO="$(cd "$SCRIPT_DIR/../.." && pwd)"
readonly CANONICAL_REPO="/home/matias/Cursor/Framework/ai-together-framework"
readonly CANONICAL_VERSION_FILE="$CANONICAL_REPO/.framework/version.txt"
readonly CONSUMER_VERSION_FILE="$CONSUMER_REPO/.framework/framework-version"

# Propagable mappings (src:dst pairs, relative to repos)
declare -a PROPAGABLES=(
  "framework/prompts:.framework/prompts"
  "framework/templates/orq:.framework/templates/orq"
  "framework/output-contracts:.framework/output-contracts"
)

# Local-only files (never overwrite)
declare -a LOCAL_ONLY_SKIP=(
  "fw-execute.md"
  "fw-execution-review.md"
)

# Protected paths (apply mode must never touch)
declare -a PROTECTED_PATHS=(
  ".framework/context.md"
  ".framework/project-config.yml"
  ".framework/orqs/"
  "app/"
  "tests/"
  "scripts/"
  "alembic/"
  ".env"
  ".claude/settings.local.json"
)

# Helper: check if file is in skip list
is_skipped() {
  local filename="$1"
  for skip in "${LOCAL_ONLY_SKIP[@]}"; do
    if [[ "$filename" == "$skip" ]]; then
      return 0
    fi
  done
  return 1
}

# Helper: extract framework version from version file
extract_version() {
  local vfile="$1"
  if [[ ! -f "$vfile" ]]; then
    echo "ERROR"
    return 1
  fi
  grep "^framework_version=" "$vfile" | cut -d'=' -f2
}

# Helper: run safety gates
safety_gates() {
  if [[ ! -d "$CANONICAL_REPO" ]]; then
    echo "GATE_FAIL: Canonical Framework repo not found at $CANONICAL_REPO"
    return 1
  fi
  if [[ ! -f "$CANONICAL_VERSION_FILE" ]]; then
    echo "GATE_FAIL: Canonical version file not found at $CANONICAL_VERSION_FILE"
    return 1
  fi
  if [[ ! -d "$CONSUMER_REPO/.framework" ]]; then
    echo "GATE_FAIL: Consumer .framework/ directory not found"
    return 1
  fi
  for pair in "${PROPAGABLES[@]}"; do
    local src="${pair%%:*}"
    if [[ ! -d "$CANONICAL_REPO/$src" ]]; then
      echo "GATE_FAIL: Canonical propagable source $src not found"
      return 1
    fi
  done
  return 0
}

# Helper: compare two files and report result
compare_files() {
  local canonical="$1"
  local consumer="$2"
  local consumer_fname="$3"  # for skip-list check

  if is_skipped "$consumer_fname"; then
    echo "PROTECTED"
    return 0
  fi

  if [[ ! -f "$consumer" ]]; then
    echo "NEW"
    return 0
  fi

  if diff -q "$canonical" "$consumer" >/dev/null 2>&1; then
    echo "UP-TO-DATE"
  else
    echo "UPDATE"
  fi
  return 0
}

# Mode: check (read-only drift detection)
mode_check() {
  local gate_result
  gate_result=$(safety_gates 2>&1) || {
    cat <<EOF
# Framework Sync Check Report

- framework_version_local: [ERROR]
- framework_version_canonical: [ERROR]
- mode: check
- sync_status: Needs Review
- drift_detected: unknown
- files_checked: 0
- files_to_update: 0
- files_skipped_protected: 0
- local_only_allowed: [fw-execute.md, fw-execution-review.md]
- conflicts_requiring_review: 1
- suggested_next_action: Verify canonical Framework repo path is correct

**Gate Failure:** $gate_result
EOF
    return 1
  }

  local local_version
  local_version=$(extract_version "$CONSUMER_VERSION_FILE") || local_version="[ERROR]"

  local canonical_version
  canonical_version=$(extract_version "$CANONICAL_VERSION_FILE") || canonical_version="[ERROR]"

  local files_checked=0
  local files_drifted=0
  local skipped_protected=0
  local report=""

  for pair in "${PROPAGABLES[@]}"; do
    local canonical_dir="${pair%%:*}"
    local consumer_dir="${pair##*:}"

    if [[ -d "$CANONICAL_REPO/$canonical_dir" ]]; then
      while IFS= read -r canonical_file; do
        files_checked=$((files_checked + 1))
        local fname
        fname=$(basename "$canonical_file")

        local consumer_file="$CONSUMER_REPO/$consumer_dir/$fname"
        local status
        status=$(compare_files "$canonical_file" "$consumer_file" "$fname")

        if [[ "$status" == "PROTECTED" ]]; then
          skipped_protected=$((skipped_protected + 1))
        elif [[ "$status" != "UP-TO-DATE" ]]; then
          files_drifted=$((files_drifted + 1))
          report+="  - $consumer_dir/$fname: [$status]"$'\n'
        fi
      done < <(find "$CANONICAL_REPO/$canonical_dir" -maxdepth 1 -type f)
    fi
  done

  local sync_status="Aligned"
  local drift_detected="false"
  if [[ $files_drifted -gt 0 || "$local_version" != "$canonical_version" ]]; then
    sync_status="Drifted"
    drift_detected="true"
  fi

  cat <<EOF
# Framework Sync Check Report

- framework_version_local: $local_version
- framework_version_canonical: $canonical_version
- mode: check
- sync_status: $sync_status
- drift_detected: $drift_detected
- files_checked: $files_checked
- files_to_update: $files_drifted
- files_skipped_protected: $skipped_protected
- local_only_allowed: [fw-execute.md, fw-execution-review.md]
- conflicts_requiring_review: 0
- suggested_next_action: $(if [[ "$sync_status" == "Aligned" ]]; then echo "None - framework is aligned"; else echo "Run 'fw-framework-sync.sh plan' to preview changes"; fi)

EOF
  if [[ -n "$report" ]]; then
    cat <<EOF
## Files with differences

$report
EOF
  fi
}

# Mode: plan (preview changes without modifying)
mode_plan() {
  local gate_result
  gate_result=$(safety_gates 2>&1) || {
    cat <<EOF
# Framework Sync Plan Report

**Error:** Cannot plan due to safety gate failure: $gate_result
EOF
    return 1
  }

  local local_version
  local_version=$(extract_version "$CONSUMER_VERSION_FILE") || local_version="[ERROR]"

  local canonical_version
  canonical_version=$(extract_version "$CANONICAL_VERSION_FILE") || canonical_version="[ERROR]"

  local plan_report=""
  local updates_needed=0

  for pair in "${PROPAGABLES[@]}"; do
    local canonical_dir="${pair%%:*}"
    local consumer_dir="${pair##*:}"

    plan_report+=$'\n'"## Sync actions for \`$consumer_dir\`"$'\n'

    if [[ -d "$CANONICAL_REPO/$canonical_dir" ]]; then
      while IFS= read -r canonical_file; do
        local fname
        fname=$(basename "$canonical_file")

        local consumer_file="$CONSUMER_REPO/$consumer_dir/$fname"
        local status
        status=$(compare_files "$canonical_file" "$consumer_file" "$fname")

        if [[ "$status" == "PROTECTED" ]]; then
          plan_report+="- \`$fname\` [PROTECTED - LOCAL-ONLY, will skip]"$'\n'
        elif [[ "$status" == "NEW" ]]; then
          plan_report+="- \`$fname\` [NEW - will copy]"$'\n'
          updates_needed=$((updates_needed + 1))
        elif [[ "$status" == "UPDATE" ]]; then
          plan_report+="- \`$fname\` [MODIFIED - will overwrite]"$'\n'
          updates_needed=$((updates_needed + 1))
        else
          plan_report+="- \`$fname\` [UP-TO-DATE]"$'\n'
        fi
      done < <(find "$CANONICAL_REPO/$canonical_dir" -maxdepth 1 -type f)
    fi
  done

  cat <<EOF
# Framework Sync Plan Report

- framework_version_local: $local_version
- framework_version_canonical: $canonical_version
- mode: plan
- files_to_update: $updates_needed

## Protected Paths (apply will never touch)

- \`.framework/context.md\`
- \`.framework/project-config.yml\`
- \`.framework/orqs/**\`
- \`app/\`, \`tests/\`, \`scripts/\`, \`alembic/\`, \`.env*\`, \`.claude/settings.local.json\`

## Version Update

If applied: \`.framework/framework-version\` will be updated from \`$local_version\` to \`$canonical_version\`
$plan_report
## Next Action

Run \`fw-framework-sync.sh apply\` to execute these changes (if any).
EOF
}

# Mode: apply (controlled propagation)
mode_apply() {
  local gate_result
  gate_result=$(safety_gates 2>&1) || {
    cat <<EOF
# Framework Sync Apply Report

- mode: apply
- sync_status: Needs Review
- suggested_next_action: Fix safety gate failure before applying

**Gate Failure:** $gate_result
EOF
    return 1
  }

  local local_version
  local_version=$(extract_version "$CONSUMER_VERSION_FILE") || local_version="[ERROR]"

  local canonical_version
  canonical_version=$(extract_version "$CANONICAL_VERSION_FILE") || canonical_version="[ERROR]"

  local files_copied=0
  local files_skipped=0

  for pair in "${PROPAGABLES[@]}"; do
    local canonical_dir="${pair%%:*}"
    local consumer_dir="${pair##*:}"

    if [[ -d "$CANONICAL_REPO/$canonical_dir" ]]; then
      while IFS= read -r canonical_file; do
        local fname
        fname=$(basename "$canonical_file")

        if is_skipped "$fname"; then
          files_skipped=$((files_skipped + 1))
        else
          local consumer_file="$CONSUMER_REPO/$consumer_dir/$fname"
          mkdir -p "$CONSUMER_REPO/$consumer_dir"
          cp "$canonical_file" "$consumer_file"
          files_copied=$((files_copied + 1))
        fi
      done < <(find "$CANONICAL_REPO/$canonical_dir" -maxdepth 1 -type f)
    fi
  done

  # Update version file
  cat > "$CONSUMER_VERSION_FILE" <<EOF
AI Together Framework V2
framework_version=$canonical_version
contract=framework-v2
EOF

  cat <<EOF
# Framework Sync Apply Report

- framework_version_local: $local_version
- framework_version_canonical: $canonical_version
- mode: apply
- files_copied: $files_copied
- files_skipped_protected: $files_skipped

## Changes Applied

- Updated \`.framework/framework-version\` to \`$canonical_version\`
- Copied $files_copied framework propagables
- Skipped $files_skipped protected (local-only) files

## Post-apply Verification

Running check to verify alignment...

EOF

  # Run check to verify
  mode_check
}

# Main entry point
main() {
  if [[ $# -lt 1 ]]; then
    cat >&2 <<'EOF'
Usage: fw-framework-sync.sh <mode>

Modes:
  check   - Detect drift between canonical and consumer repos (read-only)
  plan    - Preview changes that would be applied (read-only)
  apply   - Copy propagables from canonical to consumer (controlled write)

Examples:
  fw-framework-sync.sh check
  fw-framework-sync.sh plan
  fw-framework-sync.sh apply
EOF
    exit 1
  fi

  local mode="$1"

  case "$mode" in
    check)
      mode_check
      ;;
    plan)
      mode_plan
      ;;
    apply)
      mode_apply
      ;;
    *)
      echo "ERROR: Unknown mode '$mode'. Use 'check', 'plan', or 'apply'." >&2
      exit 1
      ;;
  esac
}

main "$@"
