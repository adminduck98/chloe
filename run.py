#!/usr/bin/env python3
"""Запуск Chloe.

    python run.py               # окно с мозгом + голос
    python run.py --fullscreen  # мозг на весь экран
    python run.py --no-window   # только голос, без окна
    python run.py --text        # без микрофона: команды с клавиатуры, ответы текстом
"""
from chloe.app import main

if __name__ == "__main__":
    main()
