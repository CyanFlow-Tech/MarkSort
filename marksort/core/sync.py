"""图片批量同步：把 unified.json 里条目要用的封面/头像一次拉到本地缓存。

展示端仍然是懒加载（只看视口内的），但回源不在浏览时发生，而是这里一次性做完，
并且限速——B 站会封无头绪的高频请求。

状态放在进程内存里，前端轮询 /api/sync/status 拿进度。
"""

from __future__ import annotations

import json
import os
import threading
import time
from queue import Empty, Queue
from typing import Any, Dict, List, Optional, Tuple

from . import config as config_mod

# 展示端用的缩略图规则，必须和前端 dataService.ts 的 SIZE_SUFFIX 一致
SIZE_SUFFIX = {
    "cover": "@480w_360h_1c.webp",
    "avatar": "@72w_72h_1c.webp",
}

DEFAULT_DELAY_MS = 300
DEFAULT_WORKERS = 3


def _needs_suffix(url: str) -> bool:
    lowered = url.lower()
    return "hdslb.com/" in lowered and "@" not in url


def _targets() -> List[Tuple[str, str]]:
    config = config_mod.load_settings()
    output = (config.get("core") or {}).get("output") or "data/unified.json"
    path = output if os.path.isabs(output) else os.path.join(config_mod.repo_root(), output)
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as handle:
        items = json.load(handle)
    seen = set()
    targets: List[Tuple[str, str]] = []
    for item in items:
        for kind, value in (
            ("cover", item.get("cover")),
            ("avatar", ((item.get("author") or {}).get("avatar"))),
        ):
            if not value or not isinstance(value, str):
                continue
            url = value + SIZE_SUFFIX[kind] if _needs_suffix(value) else value
            if url in seen:
                continue
            seen.add(url)
            targets.append((kind, url))
    return targets


class ImageSync:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._queue: Optional[Queue] = None
        self._stop = threading.Event()
        self._state: Dict[str, Any] = {
            "running": False,
            "total": 0,
            "done": 0,
            "failed": 0,
            "skipped": 0,
            "started_at": None,
            "finished_at": None,
            "last": None,
            "errors": [],
            "delay_ms": DEFAULT_DELAY_MS,
            "workers": DEFAULT_WORKERS,
        }

    # ---- 对外 ----

    def status(self) -> Dict[str, Any]:
        with self._lock:
            snapshot = dict(self._state)
        snapshot["errors"] = list(snapshot.get("errors") or [])[-5:]
        total = snapshot.get("total") or 0
        done = snapshot.get("done") or 0
        snapshot["percent"] = round(done * 100.0 / total, 1) if total else 0.0
        started = snapshot.get("started_at")
        if started:
            end = snapshot.get("finished_at") or time.time()
            elapsed = max(end - started, 0.001)
            snapshot["elapsed_s"] = round(elapsed, 1)
            snapshot["rate"] = round(done / elapsed, 2) if done else 0.0
            remaining = total - done - snapshot.get("failed", 0)
            snapshot["eta_s"] = (
                round(remaining / (done / elapsed), 1) if done and snapshot["running"] else 0
            )
        return snapshot

    def start(
        self,
        delay_ms: int = DEFAULT_DELAY_MS,
        workers: int = DEFAULT_WORKERS,
        kinds: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            if self._state["running"]:
                return {"ok": False, "error": "同步已经在跑"}
            targets = _targets()
            if kinds:
                wanted = {k for k in kinds if k in SIZE_SUFFIX}
                if wanted:
                    targets = [t for t in targets if t[0] in wanted]
            if not targets:
                return {"ok": False, "error": "没有可同步的图片（先抓取一次）"}
            self._state = {
                "running": True,
                "total": len(targets),
                "done": 0,
                "failed": 0,
                "skipped": 0,
                "started_at": time.time(),
                "finished_at": None,
                "last": None,
                "errors": [],
                "delay_ms": max(0, int(delay_ms)),
                "workers": max(1, min(int(workers), 8)),
            }
            self._stop.clear()
            self._queue = Queue()
            for _, url in targets:
                self._queue.put(url)
        self._thread = threading.Thread(target=self._run, name="marksort-image-sync", daemon=True)
        self._thread.start()
        return {"ok": True, "total": len(targets)}

    def stop(self) -> Dict[str, Any]:
        self._stop.set()
        return {"ok": True, "stopping": True}

    # ---- 内部 ----

    def _bump(self, url: str, ok: bool, error: str = "") -> None:
        with self._lock:
            if ok:
                self._state["done"] += 1
            else:
                self._state["failed"] += 1
                if error:
                    self._state["errors"].append("%s: %s" % (url[-40:], error))
                    self._state["errors"] = self._state["errors"][-5:]
            self._state["last"] = url[-60:]

    def _run(self) -> None:
        from .server import fetch_image

        assert self._queue is not None
        delay = self._state["delay_ms"] / 1000.0
        threads = []
        for _ in range(self._state["workers"]):
            worker = threading.Thread(target=self._worker, args=(fetch_image, delay), daemon=True)
            worker.start()
            threads.append(worker)
        for worker in threads:
            worker.join()
        with self._lock:
            self._state["running"] = False
            self._state["finished_at"] = time.time()

    def _worker(self, fetch_image, delay: float) -> None:
        assert self._queue is not None
        while not self._stop.is_set():
            try:
                url = self._queue.get_nowait()
            except Empty:
                return
            try:
                fetch_image(url)
                self._bump(url, True)
            except Exception as exc:  # 单张失败不影响整体
                self._bump(url, False, "%s" % exc)
            if delay:
                # 固定间隔 + 抖动，避免整齐的机器节奏
                time.sleep(delay + (0.15 * delay))


_SYNC = ImageSync()


def get_sync() -> ImageSync:
    return _SYNC
