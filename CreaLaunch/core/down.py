"""Параллельный загрузчик с проверкой SHA-1, повторами и прогрессом."""

from __future__ import annotations

import hashlib
import os
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

USER_AGENT = "NeoForgeLauncher/1.0 (Minecraft launcher, python-urllib)"


class DownloadCancelled(Exception):
    pass


class DownloadError(Exception):
    pass


def sha1_file(path: str, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha1()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def file_ok(path: str, sha1: str = None, size: int = 0) -> bool:
    try:
        stat = os.stat(path)
    except OSError:
        return False
    if size and stat.st_size != size:
        return False
    if sha1:
        try:
            return sha1_file(path) == sha1.lower()
        except OSError:
            return False
    return True


class Task:
    __slots__ = ("url", "dest", "sha1", "size", "label")

    def __init__(self, url, dest, sha1=None, size=0, label=""):
        self.url = url
        self.dest = dest
        self.sha1 = sha1.lower() if sha1 else None
        self.size = size or 0
        self.label = label


class Downloader:
    """Очередь файлов. on_progress(done, total, bytes_done, bytes_total, label)."""

    def __init__(self, workers: int = 8, on_progress=None, on_log=None):
        self.workers = max(1, int(workers))
        self.tasks = []
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._done = 0
        self._total = 0
        self._bytes = 0
        self._bytes_total = 0
        self._stamp = 0.0
        self.on_progress = on_progress or (lambda *args: None)
        self.on_log = on_log or (lambda message: None)

    # --- наполнение очереди -------------------------------------------------
    def add(self, url, dest, sha1=None, size=0, label=""):
        if url:
            self.tasks.append(Task(url, dest, sha1, size, label))

    def pending(self):
        return [t for t in self.tasks if not file_ok(t.dest, t.sha1, t.size)]

    def missing_bytes(self) -> int:
        return sum(t.size for t in self.pending())

    def cancel(self):
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    # --- работа -------------------------------------------------------------
    def run(self):
        if self._cancel.is_set():
            raise DownloadCancelled()
        queue = self.pending()
        self._total = len(queue)
        self._done = 0
        self._bytes = 0
        self._bytes_total = sum(t.size for t in queue if t.size)
        self._stamp = 0.0
        self.on_progress(0, self._total, 0, self._bytes_total, "")
        if not queue:
            return 0
        self.on_log("Загрузка: %d файл(ов), %.1f МБ" % (len(queue), self._bytes_total / 1048576.0))
        errors = []
        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            futures = [pool.submit(self._one, task) for task in queue]
            for future in futures:
                try:
                    future.result()
                except DownloadCancelled:
                    self.cancel()
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)
        if self._cancel.is_set():
            raise DownloadCancelled()
        self._report("", force=True)
        if errors:
            raise DownloadError("Не удалось скачать %d файл(ов): %s" % (len(errors), errors[0]))
        self.tasks = []
        return len(queue)

    def _report(self, label="", force=False):
        now = time.time()
        if not force and now - self._stamp < 0.1:
            return
        self._stamp = now
        try:
            self.on_progress(self._done, self._total, min(self._bytes, self._bytes_total or self._bytes),
                             self._bytes_total, label)
        except Exception:
            pass

    def _one(self, task: Task):
        if self._cancel.is_set():
            raise DownloadCancelled()
        last = None
        for attempt in range(4):
            if self._cancel.is_set():
                raise DownloadCancelled()
            try:
                self._fetch(task)
                with self._lock:
                    self._done += 1
                self._report(task.label, force=True)
                return
            except DownloadCancelled:
                raise
            except Exception as exc:  # noqa: BLE001
                last = exc
                time.sleep(0.5 * (attempt + 1))
        raise DownloadError("%s -> %s" % (task.url, last))

    def _fetch(self, task: Task):
        dest = task.dest
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        part = dest + ".part"
        url = task.url
        if url.startswith("http://"):
            url = "https://" + url[len("http://"):]
        request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
        )
        digest = hashlib.sha1() if task.sha1 else None
        written = 0
        try:
            with urllib.request.urlopen(request, timeout=60) as response, open(part, "wb") as out:
                while True:
                    if self._cancel.is_set():
                        raise DownloadCancelled()
                    chunk = response.read(1 << 16)
                    if not chunk:
                        break
                    out.write(chunk)
                    if digest:
                        digest.update(chunk)
                    written += len(chunk)
                    with self._lock:
                        self._bytes += len(chunk)
                    self._report(task.label)
        except Exception:
            with self._lock:
                self._bytes -= written
            if os.path.exists(part):
                try:
                    os.remove(part)
                except OSError:
                    pass
            raise
        if task.size and written != task.size:
            os.remove(part)
            raise DownloadError("неверный размер (%d вместо %d)" % (written, task.size))
        if digest and digest.hexdigest() != task.sha1:
            os.remove(part)
            raise DownloadError("неверная SHA-1")
        os.replace(part, dest)
