"""WS smoke test: proves the console's real-time data path works.

Connects to /ws/events exactly like the React console, triggers a full
project execution, and counts the events received live.

Run:  .venv/Scripts/python scripts/ws_smoke.py   (backend must be running)
"""
from __future__ import annotations

import asyncio
import sys

import httpx
from websockets.client import connect

BASE = "http://127.0.0.1:8000"
SPEC = (
    "Machine de transport 300 kg a 15 m/min sous 400 V triphase avec arret d'urgence "
    "et capteurs de position."
)


async def main() -> int:
    received: list[str] = []

    async with httpx.AsyncClient(timeout=60) as client:
        project = (await client.post(f"{BASE}/projects", json={"name": "WS smoke", "description": ""})).json()
        pid = project["id"]

        async with connect("ws://127.0.0.1:8000/ws/events") as ws:
            async def run_exec() -> None:
                await client.post(f"{BASE}/projects/{pid}/execute", json={"cahier_des_charges": SPEC})

            exec_task = asyncio.create_task(run_exec())
            try:
                while len(received) < 8:
                    event = await asyncio.wait_for(ws.recv(), timeout=30)
                    received.append(event[:80])
            except asyncio.TimeoutError:
                pass
            await exec_task

    print(f"Events received live over WebSocket: {len(received)}")
    for r in received:
        print("  ", r)
    return 0 if len(received) >= 8 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
