import threading


def parked_in_a_worker_thread(release: threading.Event) -> None:
    release.wait()


def waiting_in_the_test_itself() -> None:
    threading.Event().wait()


def test_stuck_with_a_worker_thread() -> None:
    release = threading.Event()
    worker = threading.Thread(target=parked_in_a_worker_thread, args=(release,))
    worker.start()
    try:
        waiting_in_the_test_itself()
    finally:
        release.set()
        worker.join()
