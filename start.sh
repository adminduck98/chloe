#!/bin/sh
# свежие настройки и ключи из ~/.bashrc — даже если терминал открыт до их изменения
eval "$(grep -E '^export (CHLOE_[A-Z_]+|DASHSCOPE_API_KEY|QWEN_API_KEY|QWEN_BASE_URL|DEEPSEEK_API_KEY|ANTHROPIC_API_KEY|GEMINI_API_KEY)=' "$HOME/.bashrc" 2>/dev/null)"
cd "$(dirname "$0")" && exec .venv/bin/python run.py "$@"
