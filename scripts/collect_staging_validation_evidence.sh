#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUTPUT_DIR="${1:-${ROOT_DIR}/.local/staging-validation/${TIMESTAMP}}"

mkdir -p "${OUTPUT_DIR}"

STATUS_RUFF="PASS"
STATUS_PYTEST="PASS"
STATUS_PIP_AUDIT="PASS"

run_check() {
  local name="$1"
  shift
  local log_file="${OUTPUT_DIR}/${name}.log"

  echo "[staging-validation] Running ${name}..."
  if "$@" >"${log_file}" 2>&1; then
    echo "[staging-validation] ${name}: PASS"
  else
    echo "[staging-validation] ${name}: FAIL (see ${log_file})" >&2
    case "${name}" in
      ruff) STATUS_RUFF="FAIL" ;;
      pytest) STATUS_PYTEST="FAIL" ;;
      pip-audit) STATUS_PIP_AUDIT="FAIL" ;;
    esac
  fi
}

run_check "ruff" env PYTHONPATH=src .venv/bin/ruff check src tests
run_check "pytest" env PYTHONPATH=src .venv/bin/pytest -q
run_check "pip-audit" env PYTHONPATH=src .venv/bin/pip-audit --progress-spinner off

SUMMARY_FILE="${OUTPUT_DIR}/summary.md"
cat >"${SUMMARY_FILE}" <<SUMMARY
# Staging Validation Evidence

- Generated at (UTC): ${TIMESTAMP}
- Workspace: ${ROOT_DIR}
- Output directory: ${OUTPUT_DIR}

## Automated Checks

| Check | Status | Log |
|-------|--------|-----|
| ruff | ${STATUS_RUFF} | ${OUTPUT_DIR}/ruff.log |
| pytest | ${STATUS_PYTEST} | ${OUTPUT_DIR}/pytest.log |
| pip-audit | ${STATUS_PIP_AUDIT} | ${OUTPUT_DIR}/pip-audit.log |

## Next Steps

1. Attach this summary and logs to the release notes or ticket.
2. Record smoke-test evidence URLs from docs/STAGING_VALIDATION.md.
SUMMARY

echo "[staging-validation] Summary written to ${SUMMARY_FILE}"

if [[ "${STATUS_RUFF}" == "FAIL" || "${STATUS_PYTEST}" == "FAIL" || "${STATUS_PIP_AUDIT}" == "FAIL" ]]; then
  exit 1
fi
