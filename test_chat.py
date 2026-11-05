"""Quick test: send a text command via Socket.IO and check for response."""
import socketio
import time

sio = socketio.Client()
response_received = [False]
response_text = [""]

@sio.on("connect")
def on_connect():
    print("[TEST] Connected to server")

@sio.on("state")
def on_state(data):
    print(f"[TEST] State: {data}")

@sio.on("response")
def on_response(data):
    print(f"[TEST] RESPONSE: {data}")
    response_received[0] = True
    response_text[0] = data.get("text", "")

sio.connect("http://localhost:5000", transports=["websocket"])
time.sleep(1)

print("[TEST] Sending command: Hello Jarvis")
sio.emit("command", {"text": "Hello Jarvis, are you working?"})

for i in range(40):
    time.sleep(0.5)
    if response_received[0]:
        break

if response_received[0]:
    print(f"[TEST] SUCCESS! Response: {response_text[0][:200]}")
else:
    print("[TEST] FAIL - No response in 20s")

sio.disconnect()
