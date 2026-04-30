from tests.utils.peer_simulator import simulate_peer, simulate_lookup
from tests.utils.thread_runner import run_in_threads


def test_extreme(tracker_server):
    query = "extreme_peer"
    errors = run_in_threads(
        target=simulate_peer,
        count=200,
        args_factory=lambda i: (i, True, 10, query, 8000, "shared_hash"),
    )

    assert not errors

    response = simulate_lookup(query)
    assert response["status"] == "FOUND"
    assert len(response["peers"]) == 200