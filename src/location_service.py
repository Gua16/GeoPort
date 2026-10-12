"""One device, one retained DVT session, and one acknowledged update per request."""
import asyncio
from concurrent.futures import Future
from contextlib import contextmanager
import copy
import queue
import threading

from location_math import coordinates


class LocationError(RuntimeError):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


class LocationService:
    def __init__(self, session_factory):
        self._session_factory = session_factory
        self._operation = threading.Lock()
        self._state_lock = threading.RLock()
        self._thread = None
        self._commands = None
        self._device = None
        self._status = "idle"
        self._current = None
        self._error = None
        self._needs_clear = False

    def state(self):
        with self._state_lock:
            return {"device_connection": copy.deepcopy(self._device), "location_status": self._status,
                    "current_location": copy.deepcopy(self._current), "error": self._error}

    def _state(self, status, current=None, error=None):
        with self._state_lock:
            self._status, self._error = status, error
            if status != "processing":
                self._current = copy.deepcopy(current)

    @contextmanager
    def operation(self):
        if not self._operation.acquire(blocking=False):
            raise LocationError("Another device or location operation is in progress")
        try:
            yield
        finally:
            self._operation.release()

    @contextmanager
    def connection_change(self):
        with self.operation():
            self._stop_session()
            with self._state_lock:
                self._device = None
            self._state("processing")
            try:
                yield
            except Exception as exc:
                self._state("failed", error=str(exc))
                raise
            finally:
                if self.state()["location_status"] == "processing":
                    self._state("idle")

    def connected(self, device):
        with self._state_lock:
            self._device = copy.deepcopy(device)
            # A reconnected phone may still have a simulation from an earlier
            # process. Do not infer that it is cleared just because RAM is empty.
            self._needs_clear = True
        self._state("idle")

    def _worker(self, commands):
        async def run():
            pending = None
            try:
                async with self._session_factory() as simulation:
                    while True:
                        try:
                            pending = commands.get_nowait()
                        except queue.Empty:
                            await asyncio.sleep(0.05)
                            continue
                        action, point, future = pending
                        if action == "stop":
                            simulation.clear()
                            break
                        simulation.set(point["lat"], point["lng"])
                        self._state("simulating", current=point)
                        future.set_result(point)
                        pending = None
                # Finish a stop only after both DVT and RSD contexts are closed.
                if pending:
                    with self._state_lock:
                        self._needs_clear = False
                    self._state("idle")
                    pending[2].set_result(None)
            except Exception as exc:
                self._state("failed", error=str(exc))
                # Keep the queue open while draining under the state lock so a
                # caller cannot enqueue onto a worker which has already failed.
                with self._state_lock:
                    self._device = None
                    self._commands = None
                    if pending and not pending[2].done():
                        pending[2].set_exception(exc)
                    while not commands.empty():
                        commands.get_nowait()[2].set_exception(exc)
        asyncio.run(run())

    def _submit(self, action, point=None):
        future = Future()
        with self._state_lock:
            if self._commands is None:
                raise LocationError(self._error or "The location session is unavailable", 502)
            self._commands.put((action, point, future))
        try:
            return future.result()
        except Exception as exc:
            if self._thread:
                self._thread.join()
            raise LocationError(f"Device location operation failed: {exc}", 502) from exc

    def apply(self, point):
        point = coordinates(point["lat"], point["lng"])
        with self.operation():
            if not self.state()["device_connection"]:
                raise LocationError("Connect a device before applying a location")
            self._state("processing")
            with self._state_lock:
                self._needs_clear = True
            self._ensure_worker()
            return self._submit("set", point)

    def _ensure_worker(self):
        if self._thread is None or not self._thread.is_alive():
            with self._state_lock:
                self._commands = queue.Queue()
                self._thread = threading.Thread(target=self._worker, args=(self._commands,),
                                                name="GeoPort-location", daemon=True)
                self._thread.start()

    def _stop_session(self):
        if self._needs_clear and self.state()['device_connection']:
            self._ensure_worker()
        if self._thread and self._thread.is_alive():
            try:
                self._submit("stop")
            finally:
                self._thread.join()
        self._thread = None
        self._commands = None
        self._state("idle")

    def stop(self):
        with self.operation():
            # A reconnected device is explicitly cleared even if this process
            # has not applied a coordinate. Confirmed repeated stops are idle.
            self._stop_session()
            return self.state()
