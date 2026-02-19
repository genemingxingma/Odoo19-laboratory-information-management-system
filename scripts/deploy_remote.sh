#!/usr/bin/env bash
set -euo pipefail

# Local-only release pipeline:
# 1) package from local source
# 2) upload package
# 3) install + migrate on server
# No direct code edits on server, no manual SQL.

APP_NAME="laboratory_management"
REMOTE_HOST="${REMOTE_HOST:-192.168.10.190}"
REMOTE_USER="${REMOTE_USER:-mamingxing}"
REMOTE_PASS="${REMOTE_PASS:-}"
REMOTE_BENCH="${REMOTE_BENCH:-/home/frappe/frappe-bench}"
REMOTE_SITE="${REMOTE_SITE:-erp.imytest.com}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TMP_PKG="/tmp/${APP_NAME}.tar.gz"
REMOTE_PKG="/tmp/${APP_NAME}.tar.gz"

if [[ -z "${REMOTE_PASS}" ]]; then
  echo "ERROR: REMOTE_PASS is required (set env var)."
  echo "Example: REMOTE_PASS='***' ${SCRIPT_DIR}/deploy_remote.sh"
  exit 2
fi

echo "[1/4] Packaging local source..."
# Avoid AppleDouble (._*) and Finder metadata in the package. Those files can
# break Frappe's app auto-discovery (esbuild utils scans bench/apps).
COPYFILE_DISABLE=1 tar \
  --exclude='._*' \
  --exclude='.DS_Store' \
  -czf "${TMP_PKG}" \
  -C "$(dirname "${APP_ROOT}")" "$(basename "${APP_ROOT}")"

echo "[2/4] Uploading package to ${REMOTE_HOST}..."
sshpass -p "${REMOTE_PASS}" scp -o StrictHostKeyChecking=no "${TMP_PKG}" "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_PKG}"

echo "[3/4] Installing package on server (no remote source edits)..."
# Root step: replace app sources and clean AppleDouble metadata files.
sshpass -p "${REMOTE_PASS}" ssh -o StrictHostKeyChecking=no "${REMOTE_USER}@${REMOTE_HOST}" "sudo -S -p '' -k bash -s" <<EOF
${REMOTE_PASS}
set -e
rm -rf ${REMOTE_BENCH}/apps/${APP_NAME}
tar -xzf ${REMOTE_PKG} -C ${REMOTE_BENCH}/apps
chown -R frappe:frappe ${REMOTE_BENCH}/apps/${APP_NAME}
# Clean up AppleDouble files that may have been created by macOS packaging.
find ${REMOTE_BENCH}/apps -maxdepth 1 -type f -name '._*' -delete || true
find ${REMOTE_BENCH}/apps/${APP_NAME} -type f -name '._*' -delete || true
find ${REMOTE_BENCH}/apps/${APP_NAME} -type f -name '.DS_Store' -delete || true
EOF

# Frappe step: install, ensure apps.txt + install-app, build, migrate, clear cache.
sshpass -p "${REMOTE_PASS}" ssh -o StrictHostKeyChecking=no "${REMOTE_USER}@${REMOTE_HOST}" "sudo -S -p '' -k -u frappe bash -s" <<EOF
${REMOTE_PASS}
set -e
cd ${REMOTE_BENCH}
./env/bin/pip install -e apps/${APP_NAME}

cd ${REMOTE_BENCH}/sites
grep -qx ${APP_NAME} apps.txt || echo ${APP_NAME} >> apps.txt

cd ${REMOTE_BENCH}
bench --site ${REMOTE_SITE} list-apps | grep -q '^${APP_NAME}[[:space:]]' || bench --site ${REMOTE_SITE} install-app ${APP_NAME}
bench build --app ${APP_NAME}

LOCK=${REMOTE_BENCH}/sites/${REMOTE_SITE}/locks/bench_migrate.lock
if [ -f "\${LOCK}" ]; then
  if ps aux | grep -F "frappe --site ${REMOTE_SITE} migrate" | grep -v grep >/dev/null 2>&1; then
    echo "ERROR: migrate already running on server; refusing to proceed."
    exit 3
  fi
  echo "Stale migrate lock found; removing \${LOCK}"
  rm -f "\${LOCK}"
fi

bench --site ${REMOTE_SITE} migrate
bench --site ${REMOTE_SITE} clear-cache
EOF

echo "[4/4] Restarting bench services..."
restart_ok=0
for attempt in 1 2 3; do
  if sshpass -p "${REMOTE_PASS}" ssh -o StrictHostKeyChecking=no "${REMOTE_USER}@${REMOTE_HOST}" \
    "sudo -S -p '' -k supervisorctl restart frappe-bench-redis:* frappe-bench-web:* frappe-bench-workers:* >/dev/null" <<<"${REMOTE_PASS}"; then
    restart_ok=1
    break
  fi
  echo "WARN: restart attempt ${attempt} failed; retrying..."
  sleep 2
done
if [[ "${restart_ok}" != "1" ]]; then
  echo "ERROR: failed to restart services after retries"
  exit 4
fi

echo "Done."
echo "Verify: https://${REMOTE_SITE}"
