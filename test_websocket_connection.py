#!/usr/bin/env python3
"""Test WebSocket connectivity to the dashboard backend."""

import asyncio
import json
import websockets
import time


async def test_websocket():
    """Test WebSocket connection and messaging."""
    uri = "ws://localhost:8000/ws"

    try:
        print(f"[TEST] Connecting to {uri}...")
        async with websockets.connect(uri) as websocket:
            print("[TEST] WebSocket connected successfully!")

            # Test 1: Send ping
            ping_message = json.dumps({"type": "ping"})
            await websocket.send(ping_message)
            print(f"[TEST] Sent: {ping_message}")

            # Wait for pong response
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=5)
                print(f"[TEST] Received: {response}")
            except asyncio.TimeoutError:
                print("[TEST] No pong response received (timeout)")

            # Test 2: Subscribe to all updates
            subscribe_all = json.dumps({
                "type": "subscribe",
                "target": "all"
            })
            await websocket.send(subscribe_all)
            print(f"[TEST] Sent: {subscribe_all}")

            # Wait for confirmation
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=5)
                print(f"[TEST] Received: {response}")
            except asyncio.TimeoutError:
                print("[TEST] No subscription confirmation (timeout)")

            # Test 3: Subscribe to a specific task
            task_id = "TASK-20260104-141158-50c60706"
            subscribe_task = json.dumps({
                "type": "subscribe",
                "target": "task",
                "id": task_id
            })
            await websocket.send(subscribe_task)
            print(f"[TEST] Sent: {subscribe_task}")

            # Wait for confirmation
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=5)
                print(f"[TEST] Received: {response}")
            except asyncio.TimeoutError:
                print("[TEST] No task subscription confirmation (timeout)")

            # Test 4: Request stats
            stats_request = json.dumps({"type": "get_stats"})
            await websocket.send(stats_request)
            print(f"[TEST] Sent: {stats_request}")

            # Wait for stats response
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=5)
                print(f"[TEST] Received stats: {response}")
            except asyncio.TimeoutError:
                print("[TEST] No stats response (timeout)")

            # Test 5: Listen for any updates for a few seconds
            print("\n[TEST] Listening for real-time updates for 10 seconds...")
            start_time = time.time()
            while time.time() - start_time < 10:
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=1)
                    print(f"[TEST] Update received: {message}")
                except asyncio.TimeoutError:
                    continue  # No message within timeout, continue listening

            print("\n[TEST] WebSocket test completed successfully!")

    except websockets.exceptions.WebSocketException as e:
        print(f"[TEST] WebSocket error: {e}")
    except Exception as e:
        print(f"[TEST] Unexpected error: {e}")


if __name__ == "__main__":
    print("=== WebSocket Connection Test ===")
    asyncio.run(test_websocket())