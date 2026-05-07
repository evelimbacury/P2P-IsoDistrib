import os
from src.peer.client import format_size, format_chunks
from src.peer import network
from src.peer.network import (
    calculate_sha256,
    connect_to_tracker,
    send_register,
    send_heartbeat,
    send_list_peers,
    send_lookup,
    send_unregister,
    send_update_chunks
)
from src.common.protocol import SHARED_FOLDER


def test_format_size():
    assert format_size(500) == "500 B"
    assert format_size(1024) == "1.00 KB"
    assert format_size(1024 * 1024) == "1.00 MB"
    assert format_size(1024 * 1024 * 1024) == "1.00 GB"
    assert format_size(1500 * 1024) == "1.46 MB"


def test_format_chunks():
    assert format_chunks([]) == "none"
    assert format_chunks([1]) == "1"
    assert format_chunks([1, 2, 3]) == "1-3"
    assert format_chunks([1, 2, 4, 5, 7]) == "1-2,4-5,7"
    assert format_chunks([0, 1, 2, 10, 11, 15]) == "0-2,10-11,15"


def test_calculate_sha256(tmp_path):
    import hashlib

    f = tmp_path / "test.txt"
    content = b"P2P-IsoDistrib-Test-Content"
    f.write_bytes(content)

    expected_hash = hashlib.sha256(content).hexdigest()

    assert calculate_sha256(str(f)) == expected_hash


def test_network_connect_fail(monkeypatch):
    monkeypatch.setattr(network, "TRACKER_PORT", 9)
    sock = connect_to_tracker()
    assert sock is None


def test_network_full_flow(tracker_server):
    os.makedirs(SHARED_FOLDER, exist_ok=True)
    iso_path = os.path.join(SHARED_FOLDER, "test_logic.iso")
    txt_path = os.path.join(SHARED_FOLDER, "invalid.txt")
    sock = None

    try:
        with open(iso_path, "wb") as f:
            f.write(b"iso content" * 100)
        with open(txt_path, "w") as f:
            f.write("test")

        sock = connect_to_tracker()
        assert sock is not None

        peer_port = 7000

        assert send_register(sock, peer_port, iso_path) is True
        assert send_register(sock, peer_port, txt_path) is False
        assert send_register(sock, peer_port, "non_existent.iso") is False
        assert send_heartbeat(sock, peer_port) is True

        res = send_lookup(sock, filename="test_logic")
        assert res is not None
        assert res["status"] == "FOUND"
        assert res["file_info"]["name"] == "test_logic.iso"

        sha256 = calculate_sha256(iso_path)
        res_sha = send_lookup(sock, sha256=sha256)
        assert res_sha is not None
        assert res_sha["status"] == "FOUND"
        assert res_sha["file_info"]["sha256"] == sha256

        assert send_update_chunks(sock, peer_port, "test_logic.iso", [0, 1, 2]) is True
        res_updated = send_lookup(sock, filename="test_logic")
        assert res_updated["peers"][0]["chunks_available"] == [0, 1, 2]

        peers_snapshot = send_list_peers(sock)
        assert peers_snapshot is not None
        assert peers_snapshot["peer_count"] == 1
        assert peers_snapshot["peers"][0]["port"] == peer_port
        assert peers_snapshot["peers"][0]["files"] == ["test_logic.iso"]

        assert send_unregister(sock, peer_port) is True
        res_after = send_lookup(sock, filename="test_logic")
        assert res_after is None

    finally:
        if os.path.exists(iso_path):
            os.remove(iso_path)
        if os.path.exists(txt_path):
            os.remove(txt_path)
        if sock:
            sock.close()
