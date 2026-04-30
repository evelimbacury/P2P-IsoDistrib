import threading
import socket
import json
import time
import traceback

from src.tracker.tracker import main, stop_event


def start_tracker():
    thread = threading.Thread(target=main, daemon=True)
    thread.start()
    time.sleep(1)
    return thread


if __name__ == "__main__":
    start_tracker()
    s = socket.socket()
    try:
        s.connect(("127.0.0.1", 5000))
        s.sendall((json.dumps({
            "action": "REGISTER",
            "peer_ip": "127.0.0.1",
            "port": 6000,
            "files": ["file.iso"],
            "size": 1000,
            "sha256": "abc"
        }) + "\n").encode())
        print("sent")
        print("recv", s.recv(4096))
    except Exception:
        traceback.print_exc()
    finally:
        s.close()
        stop_event.set()
        time.sleep(0.5)
