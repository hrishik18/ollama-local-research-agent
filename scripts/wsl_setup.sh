#!/usr/bin/env bash
# WSL2 / fresh-Ubuntu bootstrap for the autonomous research agent.
#
# Run this INSIDE WSL2 (or any fresh Ubuntu 22.04 / Debian 12 box):
#
#   curl -fsSL https://raw.githubusercontent.com/hsancheti_microsoft/ollama-local-research-agent/main/scripts/wsl_setup.sh | bash
#   # or, if you've already cloned:
#   bash scripts/wsl_setup.sh
#
# Cap WSL2 memory to mimic the 4 GB target laptop by putting this in
# %USERPROFILE%\.wslconfig on the Windows host, then `wsl --shutdown`:
#
#   [wsl2]
#   memory=4GB
#   processors=2
#
# What this does:
#   1. apt install python3 + venv + build essentials + curl
#   2. install Ollama (idempotent)
#   3. pull qwen2.5:1.5b + nomic-embed-text (≈1.8 GB download)
#   4. clone the repo if not already in it
#   5. create venv + pip install (prefers requirements.lock.txt over requirements.txt)
#   6. run pytest tests/ to verify (no Ollama required for tests)
#   7. print next steps

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/hsancheti_microsoft/ollama-local-research-agent.git}"
REPO_DIR="${REPO_DIR:-$HOME/ollama-local-research-agent}"
MODEL="${MODEL:-qwen2.5:1.5b}"
EMBED_MODEL="${EMBED_MODEL:-nomic-embed-text}"

say() { printf "\n\033[1;36m==>\033[0m %s\n" "$*"; }
ok()  { printf "  \033[1;32m✓\033[0m %s\n" "$*"; }
warn(){ printf "  \033[1;33m!\033[0m %s\n" "$*" >&2; }

say "Checking OS"
if ! grep -qiE "(ubuntu|debian)" /etc/os-release; then
  warn "Not Ubuntu/Debian — script may need tweaks for your distro."
fi
ok "$(awk -F= '/^PRETTY_NAME/ {gsub(/"/,"",$2); print $2}' /etc/os-release)"

say "Installing system packages"
sudo apt-get update -qq
sudo apt-get install -y -qq \
  python3 python3-venv python3-pip python3-dev \
  build-essential git curl ca-certificates \
  libnotify-bin   # for notify-send (desktop notifications, if running with display)
ok "apt deps installed"

say "Installing Ollama (if missing)"
if ! command -v ollama >/dev/null 2>&1; then
  curl -fsSL https://ollama.com/install.sh | sh
  ok "ollama installed"
else
  ok "ollama already installed: $(ollama --version 2>&1 | head -1)"
fi

say "Starting ollama serve in the background"
if ! pgrep -x ollama >/dev/null; then
  nohup ollama serve >/tmp/ollama.log 2>&1 &
  sleep 3
fi
ok "ollama daemon up"

say "Pulling models (this is the big download — ≈1.8 GB)"
ollama pull "$MODEL"
ollama pull "$EMBED_MODEL"
ok "models pulled"

say "Cloning repo (or updating if present)"
if [[ -d "$REPO_DIR/.git" ]]; then
  git -C "$REPO_DIR" pull --ff-only
  ok "$REPO_DIR up to date"
else
  git clone "$REPO_URL" "$REPO_DIR"
  ok "cloned to $REPO_DIR"
fi
cd "$REPO_DIR"

say "Creating venv + installing requirements"
if [[ ! -d venv ]]; then
  python3 -m venv venv
fi
# shellcheck disable=SC1091
source venv/bin/activate
pip install --quiet --upgrade pip
# Prefer the pinned lockfile (reproducible: tested exact versions, ~134 deps).
# Fall back to requirements.txt if the lockfile isn't present (older clones).
if [[ -f requirements.lock.txt ]]; then
  echo "  using requirements.lock.txt (pinned versions)"
  pip install --quiet -r requirements.lock.txt
else
  echo "  using requirements.txt (loose >= constraints)"
  pip install --quiet -r requirements.txt
fi
ok "venv ready"

say "Running smoke tests (no Ollama needed for tests)"
if pytest tests/ -q; then
  ok "tests passed"
else
  warn "some tests failed — check output above before proceeding"
fi

cat <<EOF

\033[1;32m=== Setup complete ===\033[0m

Next steps (still inside the venv):

  cd $REPO_DIR
  source venv/bin/activate

  # Edit your goal
  \$EDITOR prompt.md

  # Sanity-check Ollama is reachable
  curl -s http://localhost:11434/api/tags | head -c 200

  # Run one iteration (a short one to start — say 10 min)
  python main.py --hours 0.2

  # Or seed demo data + launch the dashboard
  python scripts/seed_demo_history.py --force
  ./dashboard/run.sh --host 0.0.0.0

Resource notes for WSL2 / 4 GB cap:
  - Cap RAM via %USERPROFILE%\\.wslconfig on Windows (see top of this script).
  - WSL2 does NOT expose /sys/class/thermal — thermal abort won't trigger here.
    Test it on the real Linux laptop for full validation.
  - notify-send needs a display server; in headless WSL use ntfy.sh instead
    (see config.yaml notifications.ntfy_topic).

EOF
