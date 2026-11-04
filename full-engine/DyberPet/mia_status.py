"""Reporte de estado y briefing del dia para Mia (contrato-voz-en.md punto 3-4).

- `collect_status_data`: GPU (nvidia-smi), Ollama (/api/ps), ComfyUI
  (/system_stats), Kanban (`assistant_service kanban list`). Cada fuente corre
  independiente; si falla o el comando no existe, ese campo queda en
  `None` (nunca se inventa). Pensado para correr en un hilo de fondo.
- `build_status_prompt`: el LLM solo REDACTA a partir del JSON de datos
  recolectados; nunca inventa cifras.
- `read_briefing`: lee `user-assets` (solo
  lectura, sin red) y lo parte en parrafos; si no existe, mensaje fijo.
"""
from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from typing import Callable, List, Optional


NO_BRIEFING_MESSAGE = "No briefing yet today."


# ---------------------------------------------------------------------------
# Punto 3: recoleccion de datos (cada fuente aislada, sin excepciones)
# ---------------------------------------------------------------------------

def collect_gpu_data(run_fn: Callable[..., "subprocess.CompletedProcess"] = subprocess.run) -> Optional[dict]:
    """`nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu
    --format=csv,noheader`. Devuelve dict con memory_used_mib,
    memory_total_mib, util_gpu_pct, o None si el comando falla/no existe."""
    try:
        result = run_fn(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu",
             "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    line = (result.stdout or "").strip().splitlines()[0] if result.stdout else ""
    if not line:
        return None
    parts = [p.strip() for p in line.split(",")]
    if len(parts) != 3:
        return None
    try:
        mem_used = int(parts[0].split()[0])
        mem_total = int(parts[1].split()[0])
        util = int(parts[2].split()[0])
    except (ValueError, IndexError):
        return None
    return {"memory_used_mib": mem_used, "memory_total_mib": mem_total, "util_gpu_pct": util}


def collect_ollama_data(base_url: str = "http://127.0.0.1:11434",
                         timeout_s: float = 2.0) -> Optional[dict]:
    """GET /api/ps: modelo cargado o no. None si Ollama no responde."""
    try:
        req = urllib.request.Request(base_url.rstrip("/") + "/api/ps", method="GET")
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError):
        return None
    models = data.get("models") if isinstance(data, dict) else None
    if models:
        return {"loaded": True, "model": models[0].get("name")}
    return {"loaded": False, "model": None}


def collect_comfyui_data(base_url: str = "http://127.0.0.1:8188",
                          timeout_s: float = 1.0) -> Optional[dict]:
    """GET /system_stats; arriba/abajo, timeout 1s (contrato)."""
    try:
        req = urllib.request.Request(base_url.rstrip("/") + "/system_stats", method="GET")
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            if not (200 <= resp.status < 300):
                return {"up": False}
    except (urllib.error.URLError, TimeoutError, OSError):
        return {"up": False}
    return {"up": True}


def collect_kanban_data(*args, **kwargs):
    """Personal task integration is not part of this distribution."""
    return None


def collect_status_data(
    gpu_fn: Callable[[], Optional[dict]] = collect_gpu_data,
    ollama_fn: Callable[[], Optional[dict]] = collect_ollama_data,
    comfyui_fn: Callable[[], Optional[dict]] = collect_comfyui_data,
    kanban_fn: Callable[[], Optional[dict]] = collect_kanban_data,
) -> dict:
    """Junta las 4 fuentes en un solo dict (pensado para correr en un
    hilo). Cada `*_fn` se inyecta para poder testear sin red/procesos."""
    return {
        "gpu": gpu_fn(),
        "ollama": ollama_fn(),
        "comfyui": comfyui_fn(),
        "kanban": kanban_fn(),
    }


DEFAULT_REPORTS_CONFIG = {"morning": False}


def load_reports_config(brain_path) -> dict:
    """Lee `reports` de mia_brain.json (contrato punto 3: disparo automatico
    del status report al saludar si `reports.morning` esta activo). Si el
    archivo no existe o no trae `reports`, default `{\"morning\": False}`."""
    cfg = dict(DEFAULT_REPORTS_CONFIG)
    brain_path = Path(brain_path)
    if not brain_path.is_file():
        return cfg
    try:
        data = json.loads(brain_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return cfg
    user_reports = data.get("reports") if isinstance(data, dict) else None
    if isinstance(user_reports, dict):
        cfg.update({k: user_reports[k] for k in cfg if k in user_reports})
    return cfg


def mia_greeting_flow(reports_cfg: dict) -> str:
    """Decide que debe disparar el saludo matutino (contrato punto 3): si
    `reports.morning` esta activo, el status report en vez del globo fijo
    de siempre."""
    return "status" if reports_cfg.get("morning") else "greet"


# ---------------------------------------------------------------------------
# Prompt: el LLM solo redacta, no inventa cifras (contrato punto 3)
# ---------------------------------------------------------------------------

def build_status_prompt(data: dict, language: str = "es") -> str:
    """Arma el prompt que se envia al LLM: le pasa el JSON exacto y le
    pide redactar 2-4 frases SOLO con esos datos, diciendo que un dato no
    esta disponible si es None (nunca inventar cifras)."""
    payload = json.dumps(data, ensure_ascii=False)
    if language == "en":
        instruction = (
            "Here is the current status data as JSON (null means that data "
            "point is unavailable): "
        )
        tail = (
            " Write a short status report in English, 2 to 4 sentences, using "
            "ONLY these numbers. If a field is null, say it is not available. "
            "Never invent numbers."
        )
    else:
        instruction = (
            "Estos son los datos de estado actuales en JSON (null significa "
            "que ese dato no esta disponible): "
        )
        tail = (
            " Escribe un reporte de estado breve en espanol, de 2 a 4 frases, "
            "usando SOLO estos numeros. Si un campo es null, di que no esta "
            "disponible. Nunca inventes cifras."
        )
    return f"{instruction}{payload}.{tail}"


# ---------------------------------------------------------------------------
# Punto 4: briefing del dia (solo lectura de archivo, sin red)
# ---------------------------------------------------------------------------

def briefing_path_for_today(briefing_dir, today: Optional[date] = None) -> Path:
    today = today or date.today()
    return Path(briefing_dir) / f"{today.isoformat()}.md"


def read_briefing(briefing_dir, today: Optional[date] = None) -> List[str]:
    """Lee el briefing del dia y lo divide en parrafos (separados por
    linea en blanco). Si no existe, devuelve [NO_BRIEFING_MESSAGE]."""
    path = briefing_path_for_today(briefing_dir, today)
    if not path.is_file():
        return [NO_BRIEFING_MESSAGE]
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return [NO_BRIEFING_MESSAGE]
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    return paragraphs or [NO_BRIEFING_MESSAGE]
