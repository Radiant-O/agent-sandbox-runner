"""Exercise every outcome the API can produce against a running server.

BASE_URL=http://localhost:8000 API_KEY=... python examples/run_examples.py
python examples/run_examples.py --agent   # also runs one agent task (uses LLM credit)
"""

import json
import os
import sys

import httpx

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")
API_KEY = os.environ.get("API_KEY", "")

CASES: list[tuple[str, dict[str, object]]] = [
    ("success", {"code": "import math\nprint(math.factorial(20))"}),
    ("runtime error", {"code": "data = {'a': 1}\nprint(data['missing'])"}),
    ("syntax error", {"code": "def broken(:\n    pass"}),
    ("timeout", {"code": "while True:\n    pass", "timeout_seconds": 3}),
    (
        "internet blocked",
        {"code": "import urllib.request\nurllib.request.urlopen('https://example.com', timeout=5)"},
    ),
    ("huge output (capped)", {"code": "print('x' * 1_000_000)"}),
    ("policy violation", {"code": "print(1)", "timeout_seconds": 9999}),
]


def show(label: str, r: httpx.Response) -> None:
    body = r.json()
    if "error" in body and "status" not in body:
        print(f"[{label}] HTTP {r.status_code} error={body['error']['code']}")
        return
    print(
        f"[{label}] HTTP {r.status_code} status={body['status']} "
        f"category={body['error_category']} exit={body['exit_code']} "
        f"exception={body['exception_type']} duration_ms={body['duration_ms']} "
        f"stdout_truncated={body['stdout_truncated']}"
    )
    if body["stdout"]:
        print("   stdout:", body["stdout"][:120].rstrip())
    if body["stderr"]:
        print("   stderr:", body["stderr"].strip().splitlines()[-1][:120])


def main() -> None:
    if not API_KEY:
        sys.exit("Set API_KEY to one of the server's API_KEYS.")
    headers = {"X-API-Key": API_KEY}
    with httpx.Client(base_url=BASE_URL, headers=headers, timeout=180) as c:
        for label, payload in CASES:
            show(label, c.post("/api/v1/executions", params={"wait": "true"}, json=payload))

        if "--agent" in sys.argv:
            task = "What is the 20th Fibonacci number (F1=F2=1)? Compute it with code."
            r = c.post("/api/v1/agent/run", json={"task": task})
            body = r.json()
            print(f"\n[agent] HTTP {r.status_code} stop_reason={body.get('stop_reason')}")
            print("   answer:", body.get("answer"))
            print("   executions:", [e["status"] for e in body.get("executions", [])])

        print("\nmetrics:", json.dumps(c.get("/metrics").json(), indent=2))


if __name__ == "__main__":
    main()
