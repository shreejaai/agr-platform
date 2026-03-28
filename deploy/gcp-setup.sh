#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="/opt/agr-platform"
COMPOSE="docker compose -f ${REPO_DIR}/docker-compose.yml -f ${REPO_DIR}/deploy/docker-compose.gcp.yml"

step()  { echo -e "\n\033[1;34m▶ $1\033[0m"; }
ok()    { echo -e "\033[1;32m✓ $1\033[0m"; }
warn()  { echo -e "\033[1;33m⚠ $1\033[0m"; }
fatal() { echo -e "\033[1;31m✗ $1\033[0m"; exit 1; }

step "Updating system packages"
apt-get update -qq
apt-get install -y -qq git curl ca-certificates gnupg lsb-release ufw
ok "System packages ready"

step "Installing Docker Engine"
if docker --version &>/dev/null; then
  ok "Docker already installed: $(docker --version)"
else
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -qq
  apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable docker
  systemctl start docker
  ok "Docker installed: $(docker --version)"
fi
usermod -aG docker "${SUDO_USER:-$USER}" 2>/dev/null || true

step "Fetching AGR platform source"
if [ -d "${REPO_DIR}/.git" ]; then
  git -C "${REPO_DIR}" pull --ff-only
  ok "Repo updated"
else
  git clone https://github.com/shreejaai/agr-platform.git "${REPO_DIR}"
  ok "Repo cloned to ${REPO_DIR}"
fi

step "Checking .env configuration"
if [ ! -f "${REPO_DIR}/.env" ]; then
  cp "${REPO_DIR}/deploy/.env.production.template" "${REPO_DIR}/.env"
  warn ".env created from template. You MUST configure it before continuing."
  echo ""
  echo "  Required fields to fill in:"
  echo "    POSTGRES_PASSWORD   — use a strong random password"
  echo "    SECRET_KEY          — run: openssl rand -hex 32"
  echo "    CLERK_SECRET_KEY    — from clerk.com dashboard"
  echo "    CLERK_WEBHOOK_SECRET"
  echo "    RESEND_API_KEY      — from resend.com dashboard"
  echo "    API_BASE_URL        — http://<this-vm-external-ip>:8000"
  echo "    DASHBOARD_BASE_URL  — http://<this-vm-external-ip>:4200"
  echo "    GHCR_TOKEN          — GitHub PAT (if packages are private)"
  echo ""
  echo "  Edit: nano ${REPO_DIR}/.env"
  echo "  Then re-run: bash ${REPO_DIR}/deploy/gcp-setup.sh"
  exit 1
else
  ok ".env found — using existing configuration"
fi

set -a
source "${REPO_DIR}/.env"
set +a

step "GitHub Container Registry authentication"
if [ -n "${GHCR_TOKEN:-}" ]; then
  echo "${GHCR_TOKEN}" | docker login ghcr.io -u shreejaai --password-stdin
  ok "Authenticated with ghcr.io"
else
  warn "GHCR_TOKEN not set — assuming packages are public. Skipping login."
fi

step "Configuring firewall"
if command -v ufw &>/dev/null; then
  ufw allow 22/tcp comment 'SSH' 2>/dev/null || true
  ufw allow 8000/tcp comment 'AGR API' 2>/dev/null || true
  ufw allow 4200/tcp comment 'AGR Dashboard' 2>/dev/null || true
  ufw allow 8080/tcp comment 'Temporal UI' 2>/dev/null || true
  ufw --force enable 2>/dev/null || true
  ok "Firewall rules applied"
else
  warn "ufw not available — configure GCP firewall rules manually if needed"
fi

step "Pulling images from ghcr.io (no build required)"
cd "${REPO_DIR}"
${COMPOSE} --profile temporal pull agr-api agr-dashboard temporal-worker
ok "Application images pulled"

step "Pulling infrastructure images"
${COMPOSE} --profile temporal pull postgres redis temporal temporal-ui
ok "Infrastructure images pulled"

step "Starting AGR platform (full stack with Temporal)"
${COMPOSE} --profile temporal up -d
ok "All services started"

step "Waiting for services to become healthy"
ATTEMPTS=0
MAX_ATTEMPTS=36
until [ "$(${COMPOSE} --profile temporal ps --status running --quiet | wc -l)" -ge 7 ] || [ "${ATTEMPTS}" -ge "${MAX_ATTEMPTS}" ]; do
  sleep 5
  ATTEMPTS=$((ATTEMPTS + 1))
  echo -n "."
done
echo ""
if [ "${ATTEMPTS}" -ge "${MAX_ATTEMPTS}" ]; then
  warn "Some services may still be starting."
  warn "Check status: cd ${REPO_DIR} && ${COMPOSE} --profile temporal ps"
else
  ok "All services running"
fi

EXTERNAL_IP=$(curl -s -m 5 https://api.ipify.org 2>/dev/null || echo "YOUR_VM_IP")
echo ""
echo -e "\033[1;32m══════════════════════════════════════════════════════\033[0m"
echo -e "\033[1;32m  AGR Platform — Successfully Deployed\033[0m"
echo -e "\033[1;32m══════════════════════════════════════════════════════\033[0m"
echo "  AGR API:        http://${EXTERNAL_IP}:8000"
echo "  API Docs:       http://${EXTERNAL_IP}:8000/docs"
echo "  AGR Dashboard:  http://${EXTERNAL_IP}:4200"
echo "  Temporal UI:    http://${EXTERNAL_IP}:8080"
echo ""
echo "  Useful commands (run from ${REPO_DIR}):"
echo "    ${COMPOSE} --profile temporal ps"
echo "    ${COMPOSE} --profile temporal logs -f agr-api"
echo "    ${COMPOSE} --profile temporal logs -f temporal-worker"
echo "    ${COMPOSE} --profile temporal down"
echo "    ${COMPOSE} --profile temporal pull && ${COMPOSE} --profile temporal up -d  # update"
echo -e "\033[1;32m══════════════════════════════════════════════════════\033[0m"
