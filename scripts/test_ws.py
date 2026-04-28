import asyncio
import json
import sys

import websockets


async def chat_session(token: str, session_id: str):
    ws_url = f"ws://localhost/api/v1/chat/ws/{session_id}?token={token}"
    print(f"\nConnecting through Nginx: {ws_url}")

    try:
        async with websockets.connect(ws_url) as websocket:
            print("Connected. Type 'exit' to leave.\n")

            while True:
                message = input("[You]> ")
                if message.lower() == "exit":
                    break
                if not message.strip():
                    continue

                await websocket.send(json.dumps({"message": message}))

                print("[Copilot]> ", end="", flush=True)

                while True:
                    response = await websocket.recv()
                    data = json.loads(response)

                    if data["type"] == "chunk":
                        print(data["content"], end="", flush=True)
                    elif data["type"] == "done":
                        print()
                        break

    except Exception as exc:  # noqa: BLE001
        print(f"Connection closed or failed: {exc}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python scripts/test_ws.py <YOUR_JWT_TOKEN> <YOUR_SESSION_ID>")
        sys.exit(1)

    asyncio.run(chat_session(sys.argv[1], sys.argv[2]))
