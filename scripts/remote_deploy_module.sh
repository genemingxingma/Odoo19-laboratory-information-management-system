#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
MODULE_NAME="$(basename "${PROJECT_DIR}")"
TAR_PATH="/tmp/${MODULE_NAME}_deploy.tar.gz"
REMOTE_TMP_DIR="/tmp/${MODULE_NAME}_deploy"
MODULE_TECHNICAL_NAME="laboratory_management"

if [[ ! -x "${SCRIPT_DIR}/remote_ssh.sh" ]]; then
  echo "Missing or non-executable ${SCRIPT_DIR}/remote_ssh.sh" >&2
  exit 1
fi

if [[ ! -f "${PROJECT_DIR}/.remote_server.env" ]]; then
  echo "Missing ${PROJECT_DIR}/.remote_server.env (copy from .remote_server.env.example first)" >&2
  exit 1
fi

set -a
source "${PROJECT_DIR}/.remote_server.env"
set +a

echo "[1/4] Packing ${MODULE_NAME}..."
STAGE_DIR="$(mktemp -d)"
trap 'rm -rf "${STAGE_DIR}"' EXIT
mkdir -p "${STAGE_DIR}/${MODULE_TECHNICAL_NAME}"
cp -a "${PROJECT_DIR}/." "${STAGE_DIR}/${MODULE_TECHNICAL_NAME}/"
rm -rf "${STAGE_DIR}/${MODULE_TECHNICAL_NAME}/.git"
(
  cd "${STAGE_DIR}"
  COPYFILE_DISABLE=1 tar --exclude='__pycache__' --exclude='*.pyc' -czf "${TAR_PATH}" "${MODULE_TECHNICAL_NAME}"
)

echo "[2/4] Uploading package..."
sshpass -p "${REMOTE_PASSWORD}" scp -P "${REMOTE_PORT}" -o StrictHostKeyChecking=no "${TAR_PATH}" "${REMOTE_USER}@${REMOTE_HOST}:${TAR_PATH}"

echo "[3/4] Sync module files on remote..."
"${SCRIPT_DIR}/remote_ssh.sh" 'bash -s' <<EOF
set -e
printf '%s\n' '${REMOTE_PASSWORD}' | sudo -S -k bash -lc '
  rm -rf ${REMOTE_TMP_DIR}
  mkdir -p ${REMOTE_TMP_DIR}
  tar -xzf ${TAR_PATH} -C ${REMOTE_TMP_DIR}
  rm -rf /opt/odoo/custom_addons/${MODULE_TECHNICAL_NAME}
  cp -a ${REMOTE_TMP_DIR}/${MODULE_TECHNICAL_NAME} /opt/odoo/custom_addons/${MODULE_TECHNICAL_NAME}
  chown -R odoo:odoo /opt/odoo/custom_addons/${MODULE_TECHNICAL_NAME}
'
EOF

echo "[4/5] Upgrading module in Odoo DB..."
"${SCRIPT_DIR}/remote_ssh.sh" 'bash -s' <<EOF
set -e
printf '%s\n' '${REMOTE_PASSWORD}' | sudo -S -k -u odoo /opt/odoo/venv/bin/python3 /opt/odoo/odoo19/odoo-bin -c /opt/odoo/config/odoo.conf -d odoo-26-1-16 -u ${MODULE_TECHNICAL_NAME} --stop-after-init --http-port=39569 --gevent-port=39572
EOF

echo "[5/5] Restarting Odoo service..."
"${SCRIPT_DIR}/remote_ssh.sh" 'bash -s' <<EOF
set -e
printf '%s\n' '${REMOTE_PASSWORD}' | sudo -S -k systemctl restart odoo
printf '%s\n' '${REMOTE_PASSWORD}' | sudo -S -k systemctl is-active odoo
EOF

echo "Deploy finished: ${MODULE_TECHNICAL_NAME}"
