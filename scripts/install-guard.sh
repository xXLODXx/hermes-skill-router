#!/usr/bin/env bash
# Installiert den Privacy-Guard als pre-commit-Hook für dieses Repo.
set -euo pipefail
cd "$(dirname "$0")/.."
chmod +x .githooks/pre-commit scripts/guard.py
git config core.hooksPath .githooks
echo "Guard installiert: core.hooksPath=.githooks — Commits mit persönlichen Daten werden blockiert."
