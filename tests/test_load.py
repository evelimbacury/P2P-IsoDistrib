from tests.utils.peer_simulator import simulate_peer, simulate_lookup
from tests.utils.thread_runner import run_in_threads


def test_high_load(tracker_server):
    query = "load_peer"
    errors = run_in_threads(
        target=simulate_peer,
        count=100,
        args_factory=lambda i: (i, True, 10, query, 7000, "shared_hash"),
    )

    assert not errors

    response = simulate_lookup(query)
    assert response["status"] == "FOUND"
    assert len(response["peers"]) == 100