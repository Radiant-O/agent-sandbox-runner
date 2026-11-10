"""Record real runs for the console's budget-exhausted replay mode.

Runs every demo example (and a couple of agent tasks) against a live server with
DEMO_ENABLED=true, captures the exact SSE event streams, and writes them to
app/demo/recordings.json. Uses real E2B (and LLM) credit: ~10 runs, 2 agent runs.

    python scripts/record_demo.py --base http://localhost:8000
"""

import argparse
import json
from pathlib import Path
from typing import Any

import httpx

OUT = Path(__file__).resolve().parents[1] / "app" / "demo" / "recordings.json"
AGENT_TASKS = [
    "What is the 30th Fibonacci number? Compute it.",
    "How many prime numbers are there below 100,000?",
]


def read_sse(client: httpx.Client, url: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    fields: dict[str, str] = {}
    with client.stream("GET", url, timeout=180) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if line == "":
                if "event" in fields:
                    payload = json.loads(fields["data"])
                    events.append(
                        {
                            "seq": int(fields.get("id", "0")),
                            "type": fields["event"],
                            "ts": payload["ts"],
                            "data": payload["data"],
                        }
                    )
                    if fields["event"] in ("finished", "failed"):
                        break
                fields = {}
            elif not line.startswith(":") and ": " in line:
                k, v = line.split(": ", 1)
                fields[k] = v
    return events


def anonymise(events: list[dict[str, Any]], prefix: str) -> list[dict[str, Any]]:
    """Mark ids as recordings so the UI never confuses them with live runs."""
    text = json.dumps(events)
    for e in events:
        for key in ("execution_id", "run_id"):
            v = e["data"].get(key)
            if isinstance(v, str) and not v.startswith("rec_"):
                text = text.replace(v, f"rec_{prefix}_{v[-8:]}")
    for e in json.loads(text):
        run = e["data"].get("run") or {}
        rid = run.get("id")
        if isinstance(rid, str) and not rid.startswith("rec_"):
            text = text.replace(rid, f"rec_{prefix}_{rid[-8:]}")
    out: list[dict[str, Any]] = json.loads(text)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--skip-agent", action="store_true")
    args = ap.parse_args()

    recordings: dict[str, Any] = {"executions": {}, "agent_runs": []}
    with httpx.Client(base_url=args.base, timeout=60) as c:
        for ex in c.get("/demo/examples").json():
            r = c.post(
                "/demo/executions",
                json={"code": ex["code"], "timeout_seconds": ex["timeout_seconds"]},
            )
            r.raise_for_status()
            exec_id = r.json()["id"]
            events = read_sse(c, f"/demo/executions/{exec_id}/events")
            status = events[-1]["data"]["execution"]["status"]
            recordings["executions"][ex["id"]] = {"events": anonymise(events, ex["id"])}
            print(f"{ex['id']:<14} {status:<10} {len(events)} events")

        if not args.skip_agent:
            for task in AGENT_TASKS:
                r = c.post("/demo/agent/runs", json={"task": task})
                r.raise_for_status()
                events = read_sse(c, f"/demo/agent/runs/{r.json()['run_id']}/events")
                stop = events[-1]["data"].get("run", {}).get("stop_reason")
                recordings["agent_runs"].append(
                    {"task": task, "events": anonymise(events, "agent")}
                )
                print(f"agent: {task[:40]:<40} {stop}")

    OUT.write_text(json.dumps(recordings, indent=1), encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
