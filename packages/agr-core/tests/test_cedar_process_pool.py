import io
import json
import queue
import threading
import time

from policy_engine import CedarProcessPool


class _FakeStdout:
    def __init__(self) -> None:
        self._lines: queue.Queue[str] = queue.Queue()

    def push(self, payload: dict[str, object]) -> None:
        self._lines.put(json.dumps(payload) + "\n")

    def readline(self) -> str:
        return self._lines.get(timeout=1.0)


class _FakeStdin:
    def __init__(self, process: "_FakeProcess") -> None:
        self._process = process
        self._buffer = ""

    def write(self, data: str) -> int:
        self._buffer = data
        return len(data)

    def flush(self) -> None:
        payload = json.loads(self._buffer.strip())
        self._process.handle_payload(payload)


class _FakeProcess:
    def __init__(self, factory: "_FakeProcessFactory") -> None:
        self.factory = factory
        self.returncode: int | None = None
        self.stdout = _FakeStdout()
        self.stdin = _FakeStdin(self)
        self.stderr = io.StringIO("")
        self.call_count = 0

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.returncode = 0

    def kill(self) -> None:
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode or 0

    def handle_payload(self, payload: dict[str, object]) -> None:
        self.call_count += 1
        self.factory.on_start()
        try:
            if self.factory.block_event is not None:
                self.factory.block_event.wait(timeout=1.0)
            self.stdout.push({"ok": True, "decision": str(payload.get("decision", "ALLOW"))})
        finally:
            self.factory.on_end()


class _FakeProcessFactory:
    def __init__(self, block_event: threading.Event | None = None) -> None:
        self.block_event = block_event
        self.processes: list[_FakeProcess] = []
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def __call__(self, *args: object, **kwargs: object) -> _FakeProcess:
        process = _FakeProcess(self)
        self.processes.append(process)
        return process

    def on_start(self) -> None:
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)

    def on_end(self) -> None:
        with self.lock:
            self.active -= 1


def test_cedar_pool_reuses_workers_across_sequential_calls(monkeypatch) -> None:
    factory = _FakeProcessFactory()
    monkeypatch.setattr("policy_engine.subprocess.Popen", factory)

    pool = CedarProcessPool("cedar", size=2)
    try:
        for _ in range(10):
            response = pool.execute({"command": "authorize"})
            assert response["decision"] == "ALLOW"
    finally:
        pool.close()

    assert len(factory.processes) == 2
    assert sum(process.call_count for process in factory.processes[:2]) == 10


def test_cedar_pool_replaces_dead_worker_on_next_call(monkeypatch) -> None:
    factory = _FakeProcessFactory()
    monkeypatch.setattr("policy_engine.subprocess.Popen", factory)

    pool = CedarProcessPool("cedar", size=1)
    try:
        factory.processes[0].returncode = 1
        response = pool.execute({"command": "authorize"})
        assert response["decision"] == "ALLOW"
    finally:
        pool.close()

    assert len(factory.processes) == 2
    assert factory.processes[1].call_count == 1


def test_cedar_pool_respects_semaphore_concurrency_limit(monkeypatch) -> None:
    block_event = threading.Event()
    factory = _FakeProcessFactory(block_event=block_event)
    monkeypatch.setattr("policy_engine.subprocess.Popen", factory)

    pool = CedarProcessPool("cedar", size=2)
    results: list[str] = []

    def worker() -> None:
        response = pool.execute({"command": "authorize"})
        results.append(str(response["decision"]))

    threads = [threading.Thread(target=worker) for _ in range(5)]
    try:
        for thread in threads:
            thread.start()
        time.sleep(0.1)
        assert factory.max_active == 2
        block_event.set()
        for thread in threads:
            thread.join(timeout=1.0)
    finally:
        pool.close()

    assert results == ["ALLOW"] * 5
