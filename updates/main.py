#!/usr/bin/env python3

from typing import Optional
from dataclasses import dataclass, asdict
import json

import subprocess

@dataclass
class OutputInfo:
    text: str
    tooltip: Optional[str] = None
    alt: Optional[str] = None
    percentage: Optional[int] = None

def main() -> OutputInfo:
    result = subprocess.run(
        ["artix-checkupdates", "-fu"],
        capture_output=True,
        text=True,
        check=True
    )

    update_count = len(result.stdout.splitlines()) - 2 # remove 2 line header

    return OutputInfo(text=f"{update_count}", alt=("updates_available" if update_count > 0 else "no_updates_available"))

print(json.dumps({k: v for k, v in asdict(main()).items() if v is not None}, separators=(",", ":")))
