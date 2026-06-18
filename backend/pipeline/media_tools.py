"""Resolve ffmpeg/ffprobe binaries for subprocess calls."""

from __future__ import annotations

import os
import shutil
from functools import lru_cache


def _resolve_binary(name: str, env_var: str) -> str:
    candidates = [
        os.environ.get(env_var, "").strip(),
        shutil.which(name),
        f"/opt/homebrew/bin/{name}",
        f"/usr/local/bin/{name}",
    ]
    for path in candidates:
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return name


@lru_cache
def ffmpeg_bin() -> str:
    return _resolve_binary("ffmpeg", "FFMPEG_PATH")


@lru_cache
def ffprobe_bin() -> str:
    return _resolve_binary("ffprobe", "FFPROBE_PATH")
