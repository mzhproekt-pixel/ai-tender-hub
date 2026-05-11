"""
Фоновый запуск пайплайна из веб-интерфейса.

Простая модель: один процесс на тип задачи, статус и хвост лога — в памяти.
Логи пишутся в файл, чтобы выживали между перезапусками сервера.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "task_logs"
LOG_DIR.mkdir(exist_ok=True)

# task_name → {"proc": Popen, "started_at": iso, "tail": deque, "finished_at": iso|None, "rc": int|None}
_TASKS: dict[str, dict] = {}
_LOCK = threading.Lock()

VALID_TASKS = {
    "fetch": "fetch.py",
    "analyze": "analyze.py",
    "match": "match.py",
    "report": "report.py",
}


def status(name: str) -> dict:
    with _LOCK:
        t = _TASKS.get(name)
        if not t:
            return {"name": name, "running": False, "started_at": None,
                    "finished_at": None, "rc": None, "tail": []}
        running = t["proc"].poll() is None
        if not running and t["finished_at"] is None:
            t["finished_at"] = datetime.now(timezone.utc).isoformat()
            t["rc"] = t["proc"].returncode
        return {
            "name": name,
            "running": running,
            "started_at": t["started_at"],
            "finished_at": t["finished_at"],
            "rc": t["rc"],
            "tail": list(t["tail"]),
        }


def all_status() -> dict[str, dict]:
    return {name: status(name) for name in VALID_TASKS}


def start(name: str) -> dict:
    """Запускает задачу name в фоне. Если уже бежит — возвращает текущий статус."""
    if name not in VALID_TASKS:
        raise ValueError(f"Неизвестная задача: {name}")

    with _LOCK:
        existing = _TASKS.get(name)
        if existing and existing["proc"].poll() is None:
            return status(name)

        script = VALID_TASKS[name]
        log_path = LOG_DIR / f"{name}.log"
        log_file = open(log_path, "w", encoding="utf-8", buffering=1)

        # Унаследуем env, добавим текущий PYTHONPATH для удобства
        env = os.environ.copy()

        proc = subprocess.Popen(
            [sys.executable, "-u", script],
            cwd=str(ROOT),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=env,
        )
        tail: deque[str] = deque(maxlen=200)

        _TASKS[name] = {
            "proc": proc,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
            "rc": None,
            "tail": tail,
            "log_path": str(log_path),
            "log_file": log_file,
        }

    # Параллельно стримим хвост лога в память
    threading.Thread(target=_tail_log, args=(name,), daemon=True).start()
    return status(name)


def _tail_log(name: str) -> None:
    info = _TASKS.get(name)
    if not info:
        return
    path = info["log_path"]
    proc = info["proc"]
    tail = info["tail"]
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            while True:
                line = f.readline()
                if line:
                    tail.append(line.rstrip("\n"))
                    continue
                if proc.poll() is not None:
                    # Дочитываем остатки и выходим
                    rest = f.read()
                    if rest:
                        for ln in rest.splitlines():
                            tail.append(ln)
                    break
                threading.Event().wait(0.5)
    finally:
        try:
            info["log_file"].close()
        except Exception:
            pass
