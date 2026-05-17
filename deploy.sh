#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ROOT_DIR}/.env"
EXAMPLE_ENV_FILE="${ROOT_DIR}/.env.example"

log() {
  printf '[deploy] %s\n' "$*"
}

need_command() {
  command -v "$1" >/dev/null 2>&1
}

install_docker_ubuntu() {
  if need_command docker && docker compose version >/dev/null 2>&1; then
    return
  fi

  if ! need_command apt-get; then
    log "Docker is not installed and this host does not look like Ubuntu/Debian."
    log "Install Docker Engine and the Compose plugin, then rerun ./deploy.sh."
    exit 1
  fi

  log "Installing Docker Engine and Compose plugin via apt."
  sudo apt-get update
  sudo apt-get install -y ca-certificates curl gnupg
  sudo install -m 0755 -d /etc/apt/keyrings
  if [ ! -f /etc/apt/keyrings/docker.gpg ]; then
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg
  fi
  . /etc/os-release
  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
  sudo apt-get update
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
}

ensure_env_file() {
  if [ -f "${ENV_FILE}" ]; then
    return
  fi
  if [ ! -f "${EXAMPLE_ENV_FILE}" ]; then
    log "Missing .env and .env.example."
    exit 1
  fi
  cp "${EXAMPLE_ENV_FILE}" "${ENV_FILE}"
  log "Created .env from .env.example. Edit secrets before exposing this stack publicly."
}

load_env() {
  set -a
  # shellcheck disable=SC1090
  . "${ENV_FILE}"
  set +a
}

build_profiles() {
  local profiles="${COMPOSE_PROFILES:-}"

  export DB_HOST="${DB_HOST:-db}"

  if [ "${ENABLE_N8N:-false}" = "true" ]; then
    profiles="${profiles:+${profiles},}n8n"
  fi

  if [ "${ENABLE_SCRAPY:-false}" = "true" ]; then
    profiles="${profiles:+${profiles},}scrapy"
  fi

  export COMPOSE_PROFILES="${profiles}"
}

wait_for_local_postgres() {
  log "Waiting for local Postgres health check."
  for _ in $(seq 1 30); do
    if docker compose --env-file "${ENV_FILE}" ps --format json db 2>/dev/null | grep -q '"Health":"healthy"'; then
      return
    fi
    sleep 2
  done

  log "Postgres did not report healthy in time. Showing db logs."
  docker compose --env-file "${ENV_FILE}" logs --tail=80 db
  exit 1
}

main() {
  cd "${ROOT_DIR}"
  ensure_env_file
  load_env
  build_profiles
  install_docker_ubuntu

  log "Using COMPOSE_PROFILES=${COMPOSE_PROFILES:-<none>}"
  log "Building images."
  docker compose --env-file "${ENV_FILE}" build

  log "Starting stack."
  docker compose --env-file "${ENV_FILE}" up -d
  wait_for_local_postgres

  log "Stack is running."
  docker compose --env-file "${ENV_FILE}" ps
  log "API: http://${API_HOST_PORT:-127.0.0.1:8000}"
  log "Dashboard: http://${DASHBOARD_HOST_PORT:-127.0.0.1:3000}"
}

main "$@"
