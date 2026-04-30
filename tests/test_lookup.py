import threading

from tests.utils.peer_simulator import simulate_peer, simulate_lookup
from tests.utils.thread_runner import run_in_threads


def test_lookup_under_load(tracker_server):
    query = "lookup_peer"
    # primeiro cria peers (todos com o mesmo hash)
    peer_errors = run_in_threads(
        target=simulate_peer,
        count=20,
        args_factory=lambda i: (i, True, 10, query, 11000, "shared_hash"),
    )
    assert not peer_errors

    # agora faz LOOKUP concorrente
    results = []
    lookup_errors = []
    lock = threading.Lock()

    def lookup_worker(_):
        try:
            response = simulate_lookup(query)
            with lock:
                results.append(response)
        except Exception as exc:
            with lock:
                lookup_errors.append(exc)

    threads = []
    for index in range(30):
        thread = threading.Thread(target=lookup_worker, args=(index,))
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    assert not lookup_errors
    assert len(results) == 30
    assert all(response["status"] == "FOUND" for response in results)
    assert all(len(response["peers"]) == 20 for response in results)
    assert all(response["file_info"]["name"].startswith(query) for response in results)