from tests.utils.peer_simulator import simulate_peer
from tests.utils.thread_runner import run_in_threads
from tests.utils.peer_simulator import simulate_lookup


def test_multiple_peers_concurrent(tracker_server):
    query = "concurrent_peer"
    errors = run_in_threads(
        target=simulate_peer,
        count=20,
        args_factory=lambda i: (i, True, 10, query, 6000, "shared_hash"),
    )

    assert not errors

    response = simulate_lookup(query)
    assert response["status"] == "FOUND"
    assert len(response["peers"]) == 20