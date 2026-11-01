"""浏览器 → 本地 JSON 的收数通道。

浏览器里抓到的原始数据用 POST 推给这个进程，避免把 Cookie 抠出来交给 Python：
登录态留在浏览器，数据落到本地文件。

    python -m marksort ingest --port 17330 [--data-dir data]

浏览器侧（见 marksort/browser/bilibili.js）：
    fetch('http://127.0.0.1:17330/ingest', {
      method: 'POST',
      headers: {'Content-Type': 'text/plain'},
      body: JSON.stringify({platform: 'bilibili', folder: {...}, items: [...]})
    })

用 text/plain 是为了避开预检请求：CORS 简单请求不需要 OPTIONS 往返，
但私网访问（PNA）仍会带一个预检，所以 OPTIONS 分支也要回 Private-Network 允许头。
"""

from __future__ import annotations

import json
import os
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_PORT = 17330
DEFAULT_DATA_DIR = "data"
_SAFE = re.compile(r"[^a-zA-Z0-9_.-]+")


class _Store:
    """把推来的原始条目按 platform 合并进 data/raw/<platform>.json。"""

    def __init__(self, data_dir: str) -> None:
        self.root = os.path.abspath(data_dir)
        self.raw_dir = os.path.join(self.root, "raw")
        os.makedirs(self.raw_dir, exist_ok=True)

    def path_for(self, platform: str) -> str:
        return os.path.join(self.raw_dir, "%s.json" % _SAFE.sub("_", platform))

    def merge(self, platform: str, items: List[Dict[str, Any]], key: str = "bvid") -> Tuple[int, int]:
        path = self.path_for(platform)
        existing: List[Dict[str, Any]] = []
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    loaded = json.load(handle)
                if isinstance(loaded, list):
                    existing = loaded
            except (ValueError, OSError):
                existing = []
        index = {str(row.get(key) or row.get("id")): row for row in existing}
        added = 0
        for item in items:
            identity = str(item.get(key) or item.get("id") or "")
            if not identity:
                continue
            if identity in index:
                index[identity].update(item)
            else:
                index[identity] = item
                added += 1
        merged = list(index.values())
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(merged, handle, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
        return added, len(merged)


def _handler(store: _Store, verbose: bool):
    class Handler(BaseHTTPRequestHandler):
        server_version = "marksort-ingest/0.1"

        def _cors(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Access-Control-Max-Age", "600")

        def _send(self, status: int, payload: Dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler 要求的名字
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            if self.path.startswith("/health"):
                self._send(200, {"ok": True, "data_dir": store.root, "time": int(time.time())})
            else:
                self._send(404, {"ok": False, "error": "unknown path"})

        def do_POST(self) -> None:  # noqa: N802
            if not self.path.startswith("/ingest"):
                self._send(404, {"ok": False, "error": "unknown path"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b"{}"
                payload = json.loads(raw.decode("utf-8"))
            except (ValueError, OSError) as exc:
                self._send(400, {"ok": False, "error": "bad payload: %s" % exc})
                return
            platform = str(payload.get("platform") or "").strip()
            items = payload.get("items")
            if not platform or not isinstance(items, list):
                self._send(400, {"ok": False, "error": "需要 platform 与 items 数组"})
                return
            key = str(payload.get("key") or "bvid")
            raised, total = store.merge(platform, items, key)
            if verbose:
                folder = (payload.get("folder") or {}).get("title") or "-"
                print("[ingest] %s %s 收 %d 条（新增 %d，累计 %d）" % (platform, folder, len(items), raised, total))
            self._send(200, {"ok": True, "received": len(items), "added": raised, "stored": total})

        def log_message(self, fmt: str, *args: Any) -> None:  # 不要默认的 stderr 噪音
            if verbose:
                print("[http] " + fmt % args)

    return Handler


def serve(port: int = DEFAULT_PORT, data_dir: str = DEFAULT_DATA_DIR, verbose: bool = True) -> None:
    store = _Store(data_dir)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _handler(store, verbose))
    print("ingest 已启动：http://127.0.0.1:%d/ingest" % port)
    print("写入目录：%s" % store.raw_dir)
    print("Ctrl+C 结束")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        httpd.server_close()
