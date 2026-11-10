"""Curated snippets, one per interesting path through the system."""

EXAMPLES: list[dict[str, object]] = [
    {
        "id": "success",
        "title": "Compute something",
        "expect": "succeeded",
        "blurb": "A normal run: fresh microVM, real exit code 0.",
        "code": (
            "import math, platform\n\n"
            'print(f"20! = {math.factorial(20):,}")\n'
            'print(f"Running on {platform.system()} {platform.machine()}, '
            'Python {platform.python_version()}")\n'
        ),
        "timeout_seconds": 10,
    },
    {
        "id": "stream",
        "title": "Stream output live",
        "expect": "succeeded",
        "blurb": "Output streams to the terminal chunk by chunk as the sandbox produces it.",
        "code": (
            "import time\n\n"
            "for i in range(1, 9):\n"
            '    print(f"step {i}/8 " + "#" * i, flush=True)\n'
            "    time.sleep(0.4)\n"
            'print("done")\n'
        ),
        "timeout_seconds": 10,
    },
    {
        "id": "runtime_error",
        "title": "Runtime error",
        "expect": "failed",
        "blurb": "User-code failure: classified as user_code_error, exception type parsed.",
        "code": (
            'orders = {"alice": 3, "bob": 5}\n\n'
            "def total(names):\n"
            "    return sum(orders[n] for n in names)\n\n"
            'print(total(["alice", "carol"]))\n'
        ),
        "timeout_seconds": 10,
    },
    {
        "id": "syntax_error",
        "title": "Syntax error",
        "expect": "failed",
        "blurb": "Never runs; the interpreter rejects it inside the sandbox.",
        "code": 'def greet(name:\n    print(f"hello {name}")\n',
        "timeout_seconds": 10,
    },
    {
        "id": "timeout",
        "title": "Infinite loop",
        "expect": "timed_out",
        "blurb": "Runs until the 5 s timeout. The sandbox is killed; partial output is kept.",
        "code": (
            "import itertools\n\n"
            "for i in itertools.count():\n"
            "    if i % 5_000_000 == 0:\n"
            '        print(f"still going... {i:,}", flush=True)\n'
        ),
        "timeout_seconds": 5,
    },
    {
        "id": "flood",
        "title": "Output flood",
        "expect": "succeeded",
        "blurb": "Prints ~5 MB. The server keeps 64 KB and flags it as truncated.",
        "code": 'for i in range(100_000):\n    print(f"line {i:06d} " + "x" * 40)\n',
        "timeout_seconds": 10,
    },
    {
        "id": "network",
        "title": "Reach the internet",
        "expect": "timed_out",
        "blurb": "Egress is blocked. DNS hangs until the timeout: the request never leaves.",
        "code": (
            "import urllib.request\n\n"
            'print("trying https://example.com ...", flush=True)\n'
            'r = urllib.request.urlopen("https://example.com", timeout=5)\n'
            'print("reached it:", r.status)\n'
        ),
        "timeout_seconds": 8,
    },
    {
        "id": "secrets",
        "title": "Look for secrets",
        "expect": "succeeded",
        "blurb": "The sandbox environment contains no server keys: nothing to steal.",
        "code": (
            "import os\n\n"
            "suspicious = [k for k in os.environ if any(w in k for w in "
            '("KEY", "TOKEN", "SECRET"))]\n'
            'print("secret-looking env vars:", suspicious or "none")\n'
        ),
        "timeout_seconds": 10,
    },
]

AGENT_EXAMPLES: list[str] = [
    "What is the 30th Fibonacci number? Compute it.",
    "How many prime numbers are there below 100,000?",
    "What day of the week was 1 January 2000?",
    "Estimate pi with a Monte Carlo simulation of 200,000 points.",
]
