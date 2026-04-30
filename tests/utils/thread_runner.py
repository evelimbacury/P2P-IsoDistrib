import threading


def run_in_threads(target, count, args_factory):
    """
    Executa um target em múltiplas threads e propaga exceções para o teste.

    Args:
        target: função a ser executada em cada thread
        count: quantidade de threads
        args_factory: função que recebe o índice e retorna uma tupla de args
    """
    errors = []
    lock = threading.Lock()
    threads = []

    def worker(index):
        try:
            target(*args_factory(index))
        except Exception as exc:
            with lock:
                errors.append((index, exc))

    for index in range(count):
        thread = threading.Thread(target=worker, args=(index,))
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    return errors
