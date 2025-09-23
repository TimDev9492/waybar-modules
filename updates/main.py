#!/usr/bin/env python3

from typing import Optional
from dataclasses import dataclass, asdict
import json

import subprocess
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sockets.client.client import UnixSocketClient

@dataclass
class OutputInfo:
    text: str
    tooltip: Optional[str] = None
    alt: Optional[str] = None
    percentage: Optional[int] = None

def main() -> OutputInfo:
    client = UnixSocketClient(socket_path=os.getenv("SOCKET_FILE", "/tmp/waybard.socket"))
    try:
        client.connect()
        result = client.call_method("list_updates")
        update_count = len(result.splitlines())
        return OutputInfo(text=f"{update_count}", alt=("updates_available" if update_count > 0 else "no_updates_available"))
    except Exception as e:
        return OutputInfo(
            text="Error",
            alt="error",
            tooltip=f"<tt>{e}</tt>"
        )

print(json.dumps({k: v for k, v in asdict(main()).items() if v is not None}, separators=(",", ":")))
