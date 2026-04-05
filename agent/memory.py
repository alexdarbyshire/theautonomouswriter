from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.types import WriterMemory

MEMORY_PATH = Path(__file__).resolve().parent.parent / "system" / "memory.json"


def load_memory(path: Path = MEMORY_PATH) -> WriterMemory:
    with open(path) as f:
        return json.load(f)


def save_memory(memory: WriterMemory, path: Path = MEMORY_PATH) -> None:
    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "w") as f:
        json.dump(memory, f, indent=2, default=str)
        f.write("\n")
    os.replace(tmp_path, path)
