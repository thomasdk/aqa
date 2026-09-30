"""Opt-in connectivity diagnostic for a local LM Studio server."""

import requests

URL = "http://localhost:1234/v1/models"


def main() -> int:
    print(f"Checking connection to {URL}...")
    try:
        response = requests.get(URL, timeout=2)
    except requests.RequestException as exc:
        print(f"CONNECTION FAILED: {exc}")
        print("Ensure LM Studio is running and its server is listening on port 1234.")
        return 1
    if response.status_code != 200:
        print(f"ERROR: LM Studio responded with status {response.status_code}")
        return 1
    print("SUCCESS: LM Studio is reachable.")
    print(f"Available models: {len(response.json().get('data', []))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
