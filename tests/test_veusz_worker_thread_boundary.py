from concurrent.futures import ThreadPoolExecutor

from sciplot_core.veusz_runtime import needs_veusz_worker_process


def test_background_operations_use_a_worker_even_with_ready_qt_runtime(monkeypatch):
    monkeypatch.setenv("SCIPLOT_STUDIO_QT_RUNTIME", "1")
    assert needs_veusz_worker_process() is False
    with ThreadPoolExecutor(max_workers=1) as executor:
        assert executor.submit(needs_veusz_worker_process).result() is True
