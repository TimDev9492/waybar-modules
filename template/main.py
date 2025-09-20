#!/usr/bin/env python

from typing import Optional
from dataclasses import dataclass, asdict
import json

@dataclass
class OutputInfo:
    text: str
    tooltip: str
    alt: Optional[str] = None
    percentage: Optional[int] = None

def main() -> OutputInfo:
    return OutputInfo(text="Template", tooltip="Example custom module!")

print(json.dumps({k: v for k, v in asdict(main()).items() if v is not None}, separators=(",", ":")))
