import time

from src.tracker import tracker


def test_peer_timeout_cleanup_removes_stale_peer(monkeypatch):
    monkeypatch.setattr(tracker, "PEER_TIMEOUT", 1)

    response = tracker.handle_register(
        {
            "action": "REGISTER",
            "peer_ip": "127.0.0.1",
            "port": 10001,
            "files": ["timeout_peer.iso"],
            "size": 10_000_000,
            "sha256": "timeout-hash",
        },
        ("127.0.0.1", 1234),
    )
    assert response["status"] == "OK"

    lookup = tracker.handle_lookup({"filename": "timeout_peer"}, None)
    assert lookup["status"] == "FOUND"
    assert len(lookup["peers"]) == 1

    peer_key = "127.0.0.1:10001"
    tracker.peers_dict[peer_key]["last_heartbeat"] = time.time() - 2

    tracker._do_cleanup()

    lookup = tracker.handle_lookup({"filename": "timeout_peer"}, None)
    assert lookup["status"] == "NOT_FOUND"
