from tests.utils.peer_simulator import simulate_churn, simulate_lookup
from tests.utils.thread_runner import run_in_threads


def test_churn(tracker_server):
    query = "churn_peer"
    errors = run_in_threads(
        target=simulate_churn,
        count=50,
        args_factory=lambda i: (i, query, 9000),
    )

    assert not errors

    response = simulate_lookup(query)
    assert response["status"] == "NOT_FOUND"
