import time
import pytest

from src.tracker import tracker


def setup_function():
    tracker.peers_dict.clear()
    tracker.heartbeat_log_counter.clear()
    tracker.peer_last_heartbeat_time.clear()
    tracker.active_connections = 0


# =========================
# REGISTER
# =========================
def test_register_success():
    data = {
        "action": "REGISTER",
        "port": 6000,
        "files": ["file.iso"],
        "size": 1000,
        "sha256": "abc"
    }

    res = tracker.handle_register(data, ("127.0.0.1", 1234))

    assert res["status"] == "OK"
    assert "127.0.0.1:6000" in tracker.peers_dict


def test_register_missing_fields():
    data = {"action": "REGISTER"}

    res = tracker.handle_register(data, ("127.0.0.1", 1234))

    assert res["status"] == "ERROR"


# =========================
# HEARTBEAT
# =========================
def test_heartbeat_success():
    peer_key = "127.0.0.1:6000"
    tracker.peers_dict[peer_key] = {
        "ip": "127.0.0.1",
        "port": 6000,
        "files": {},
        "last_heartbeat": 0,
        "heartbeat_count": 0,
    }

    data = {
        "action": "HEARTBEAT",
        "port": 6000,
    }

    res = tracker.handle_heartbeat(data, ("127.0.0.1", 1234))

    assert res["status"] == "OK"
    assert tracker.peers_dict[peer_key]["heartbeat_count"] == 1


def test_heartbeat_unregistered_peer():
    data = {
        "action": "HEARTBEAT",
        "port": 9999,
    }

    res = tracker.handle_heartbeat(data, ("127.0.0.1", 1234))

    assert res["status"] == "WARNING"


# =========================
# LOOKUP
# =========================
def test_lookup_found():
    tracker.peers_dict["127.0.0.1:6000"] = {
        "ip": "127.0.0.1",
        "port": 6000,
        "files": {
            "ubuntu.iso": {
                "size": 100,
                "sha256": "abc",
                "total_chunks": 1,
                "chunks_available": [0],
            }
        },
        "last_heartbeat": time.time(),
        "heartbeat_count": 0,
    }

    res = tracker.handle_lookup({"filename": "ubuntu"}, None)

    assert res["status"] == "FOUND"
    assert len(res["peers"]) == 1


def test_lookup_not_found():
    res = tracker.handle_lookup({"filename": "nothing"}, None)

    assert res["status"] == "NOT_FOUND"


# =========================
# UNREGISTER
# =========================
def test_unregister_success():
    tracker.peers_dict["127.0.0.1:6000"] = {}

    res = tracker.handle_unregister(
        {"port": 6000},
        ("127.0.0.1", 1234)   # ← addr real simulado
    )

    assert res["status"] == "OK"
    assert "127.0.0.1:6000" not in tracker.peers_dict


# =========================
# TIMEOUT
# =========================
def test_cleanup_timeout():
    peer_key = "127.0.0.1:6000"

    tracker.peers_dict[peer_key] = {
        "ip": "127.0.0.1",
        "port": 6000,
        "files": {},
        "last_heartbeat": time.time() - 1000,
        "heartbeat_count": 0,
    }

    tracker._do_cleanup()

    assert peer_key not in tracker.peers_dict