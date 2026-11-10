#!/bin/sh
# свежие настройки CHLOE_* из ~/.bashrc — даже если терминал открыт до их изменения.
# Ключи API лежат не здесь, а в ~/.config/chloe/keys.env (права 600): Chloe читает их сама.
eval "$(grep -E '^export (CHLOE_[A-Z_]+|QWEN_BASE_URL)=' "$HOME/.bashrc" 2>/dev/null)"
# --log (автозапуск: окна терминала нет) — вывод в ~/.chloe/chloe.log, прошлый запуск — chloe.log.1
if [ "$1" = "--log" ]; then
    shift
    mkdir -p "$HOME/.chloe"
    mv -f "$HOME/.chloe/chloe.log" "$HOME/.chloe/chloe.log.1" 2>/dev/null
    exec > "$HOME/.chloe/chloe.log" 2>&1
    export PYTHONUNBUFFERED=1
fi
cd "$(dirname "$0")" && exec .venv/bin/python run.py "$@"
