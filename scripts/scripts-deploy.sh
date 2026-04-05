scripts/deploy.sh

#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════════
# FOTNSSJ Production Deployment Script
# Usage: bash scripts/deploy.sh [school|cloud|both]
# ════════════════════════════════════════════════════════════════════════
set -euo pipefail

MODE=${1:-school}
COMPOSE_FILE="docker-compose.yml"
CLOUD_COMPOSE="docker-compose.cloud.yml"

RED='\033[0;31m'
GRN='\033[0;32m'
YLW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GRN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YLW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ── Pre-flight checks ─────────────────────────────────────────────────

check_deps() {
    for cmd in docker docker-compose curl; do
        command -v "$cmd" &>/dev/null || error "Missing dependency: $cmd"
    done
    info "Dependencies: OK"
}

check_env() {
    if [[ ! -f .env ]]; then
        warn ".env not found — copying from .env.example"
        cp .env.example .env
        error "Please edit .env and set SECRET_KEY and ADMIN_PASS, then re-run."
    fi

    # shellcheck disable=SC1091
    source .env

    [[ "${SECRET_KEY:-changeme}" == "replace_with_strong_random_hex_64_chars" ]] && \
        error "SECRET_KEY is still the placeholder. Generate one with:\n  python3 -c \"import secrets; print(secrets.token_hex(32))\""

    [[ "${ADMIN_PASS:-changeme}" == "replace_with_strong_password" ]] && \
        error "ADMIN_PASS is still the placeholder."

    info "Environment: OK"
}

check_ollama() {
    if [[ "$MODE" == "school" || "$MODE" == "both" ]]; then
        if curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; then
            info "Ollama: running"

            MODEL=${LLM_MODEL:-qwen3:1.5b}
            if ! curl -sf http://localhost:11434/api/tags | grep -q "$MODEL"; then
                warn "Model '$MODEL' not found — pulling now (this may take a while)..."
                ollama pull "$MODEL"
            else
                info "Model '$MODEL': available"
            fi
        else
            warn "Ollama not running on localhost:11434"
            warn "Questions will fall back to hardcoded set until Ollama starts."
            warn "Start Ollama with: ollama serve"
        fi
    fi
}

# ── Deployment ────────────────────────────────────────────────────────

deploy_school() {
    info "Building school node..."
    docker-compose -f "$COMPOSE_FILE" build --pull

    info "Starting containers..."
    docker-compose -f "$COMPOSE_FILE" up -d

    info "Waiting for student container to be healthy..."
    ATTEMPTS=0
    until curl -sf http://localhost:5000/health > /dev/null 2>&1; do
        ATTEMPTS=$((ATTEMPTS + 1))
        [[ $ATTEMPTS -gt 30 ]] && error "Student container did not become healthy after 30s"
        sleep 1
    done

    info "School node healthy"
    print_school_urls
}

deploy_cloud() {
    info "Building cloud receiver..."
    docker-compose -f "$CLOUD_COMPOSE" build --pull

    info "Starting receiver..."
    docker-compose -f "$CLOUD_COMPOSE" up -d

    info "Waiting for receiver to be healthy..."
    ATTEMPTS=0
    until curl -sf http://localhost:8080/health > /dev/null 2>&1; do
        ATTEMPTS=$((ATTEMPTS + 1))
        [[ $ATTEMPTS -gt 20 ]] && error "Receiver did not become healthy after 20s"
        sleep 1
    done

    info "Cloud receiver healthy"
    print_cloud_urls
}

print_school_urls() {
    echo ""
    echo "═══════════════════════════════════════"
    echo "  School Node"
    echo "═══════════════════════════════════════"
    echo "  Student  → http://localhost:5000"
    echo "  Viewer   → http://localhost:5001"
    echo "  Teacher  → http://localhost:5002"
    echo "  Admin    → http://localhost:5003/admin/login"
    echo "  Geometry → http://localhost:5003/admin/geometry"
    echo "  Health   → http://localhost:5000/health"
    echo "═══════════════════════════════════════"
}

print_cloud_urls() {
    echo ""
    echo "═══════════════════════════════════════"
    echo "  Cloud Receiver"
    echo "═══════════════════════════════════════"
    echo "  Health     → http://localhost:8080/health"
    echo "  Summary    → http://localhost:8080/graph/summary"
    echo "  Positions  → http://localhost:8080/graph/positions"
    echo "  Struggles  → http://localhost:8080/graph/struggles"
    echo "  Heatmap    → http://localhost:8080/graph/heatmap"
    echo "═══════════════════════════════════════"
}

# ── Main ──────────────────────────────────────────────────────────────

check_deps
check_env
check_ollama

case "$MODE" in
    school) deploy_school ;;
    cloud)  deploy_cloud  ;;
    both)   deploy_school; deploy_cloud ;;
    *)      error "Unknown mode: $MODE. Use: school | cloud | both" ;;
esac

info "Deployment complete."