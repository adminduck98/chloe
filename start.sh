#!/bin/sh
# свежие настройки CHLOE_* из ~/.bashrc — даже если терминал открыт до их изменения.
# Ключи API лежат не здесь, а в ~/.config/chloe/keys.env (права 600): Chloe читает их сама.
eval "$(grep -E '^export (CHLOE_[A-Z_]+|QWEN_BASE_URL)=' "$HOME/.bashrc" 2>/dev/null)"
cd "$(dirname "$0")" && exec .venv/bin/python run.py "$@"
