#!/usr/bin/env python3

from typing import Optional
from dataclasses import dataclass, asdict
import json

import os
from dotenv import load_dotenv
import requests
from urllib.parse import urlencode

@dataclass
class OutputInfo:
    text: str
    tooltip: str
    alt: Optional[str] = None
    percentage: Optional[int] = None

def format_price(n: float) -> str:
    if n < 10:
        return f"{n:.3f}"
    elif n < 100:
        return f"{n:.2f}"
    elif n < 1000:
        return f"{n:.1f}"
    else:
        return "{:,}".format(round(n))

def main() -> OutputInfo:
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))

    api_endpoint = os.getenv("API_ENDPOINT")
    api_key = os.getenv("API_KEY")
    crypto_token = os.getenv("CRYPTO_TOKEN", "btc")

    query_params = {
        "x_cg_demo_api_key": api_key
    }

    url = api_endpoint + "?" + urlencode(query_params)

    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()

        data = response.json()

        token_price_per_btc = data['rates'][crypto_token]['value']
        usd_per_btc = data['rates']['usd']['value']

        usd_price_per_token = usd_per_btc / token_price_per_btc

        return OutputInfo(
            text=format_price(usd_price_per_token) + " $",
            tooltip=f" Exchange rate: <tt>{usd_price_per_token:.3f} {crypto_token.upper()}USD</tt>",
            alt=crypto_token
        )
    except requests.exceptions.HTTPError as http_err:
        return OutputInfo(
            text="HTTP Error",
            alt="http_error",
            tooltip=f"HTTP error occurred:\n<tt>{http_err}</tt>"
        )
        # http error occurred {http_err}
    except requests.exceptions.ConnectionError:
        return OutputInfo(
            text="No service",
            alt="connection_error",
            tooltip="Unable to connect to the API"
        )
    except requests.exceptions.Timeout:
        return OutputInfo(
            text="Timeout",
            alt="timeout_error",
            tooltip="Request timed out"
        )
    except requests.exceptions.RequestException as err:
        return OutputInfo(
            text="Error",
            tooltip=f"Unexpected error:\n<tt>{err}</tt>",
            alt="unexpected_error"
        )

    return OutputInfo(text="Template", tooltip="Example custom module!")

print(json.dumps({k: v for k, v in asdict(main()).items() if v is not None}, separators=(",", ":")))
