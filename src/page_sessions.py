"""Track live browser streams without relying on background JavaScript timers."""
import threading
import time


class PageSessions:
    def __init__(self, shutdown, grace=120, clock=time.monotonic):
        self.shutdown, self.grace, self.clock = shutdown, grace, clock
        self._lock = threading.RLock()
        self._pages = set()
        self._deadline = None
        self._closing = False

    def opened(self, token):
        with self._lock:
            if self._closing:
                return False
            self._pages.add(token)
            self._deadline = None
            return True

    def closed(self, token):
        with self._lock:
            if token not in self._pages:
                return
            self._pages.remove(token)
            if not self._pages:
                self._deadline = self.clock() + self.grace

    def poll(self):
        with self._lock:
            if self._closing or self._pages or self._deadline is None or self.clock() < self._deadline:
                return False
            self._closing = True
        try:
            self.shutdown()
        except Exception:
            with self._lock:
                self._closing = False
                self._deadline = self.clock() + self.grace
            raise
        return True

    def watch(self, logger):
        def run():
            while True:
                threading.Event().wait(.5)
                try:
                    self.poll()
                except Exception:
                    logger.exception('Automatic exit cleanup failed; will retry after grace period')
        threading.Thread(target=run, name='GeoPort-page-exit', daemon=True).start()
