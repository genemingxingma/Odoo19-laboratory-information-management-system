#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${PROJECT_DIR}/.remote_server.env"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing ${ENV_FILE}" >&2
  exit 1
fi

set -a
source "${ENV_FILE}"
set +a

exec sshpass -p "${REMOTE_PASSWORD}" ssh -p "${REMOTE_PORT}" -o StrictHostKeyChecking=no "${REMOTE_USER}@${REMOTE_HOST}" "$@"
