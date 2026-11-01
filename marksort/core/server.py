"""本地服务：托管设置页、读写本地设置、跑抓取。

    python -m marksort serve --port 17331

页面与 API 同源，所以浏览器里不需要任何跨域许可；对外只监听 127.0.0.1。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Optional, Tuple

from . import config as config_mod
from .container import Container, PLUGIN_ROOT
from .pipeline import collect

# 图床按域名给对应 Referer，否则 B 站会 403（防盗链）
_IMAGE_HOSTS = (
    (".hdslb.com", "https://www.bilibili.com/"),
    (".bilibili.com", "https://www.bilibili.com/"),
    (".xhscdn.com", "https://www.xiaohongshu.com/"),
    (".xiaohongshu.com", "https://www.xiaohongshu.com/"),
)

_IMAGE_EXT = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/avif": ".avif",
}


def _image_referer(url: str) -> Optional[str]:
    host = urllib.parse.urlparse(url).hostname or ""
    for suffix, referer in _IMAGE_HOSTS:
        if host.endswith(suffix):
            return referer
    return None


def _cache_dir() -> str:
    path = os.path.join(config_mod.repo_root(), "data", "cache", "images")
    os.makedirs(path, exist_ok=True)
    return path


def fetch_image(url: str) -> Tuple[bytes, str]:
    """带 Referer 取图，成功一次就落到本地缓存。返回 (bytes, content_type)。"""
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("只代理 http(s) 图片")
    referer = _image_referer(url)
    if referer is None:
        raise ValueError("不在允许的图床白名单里")
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
    directory = _cache_dir()
    for ext in set(_IMAGE_EXT.values()):
        cached = os.path.join(directory, digest + ext)
        if os.path.isfile(cached):
            with open(cached, "rb") as handle:
                return handle.read(), next(
                    (k for k, v in _IMAGE_EXT.items() if v == ext), "image/jpeg"
                )
    request = urllib.request.Request(
        url,
        headers={
            "Referer": referer,
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
            ),
            "Accept": "image/avif,image/webp,image/png,image/*,*/*;q=0.8",
            "Accept-Encoding": "identity",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        body = response.read()
        content_type = (response.headers.get("Content-Type") or "image/jpeg").split(";")[0].strip()
    ext = _IMAGE_EXT.get(content_type, ".jpg")
    try:
        with open(os.path.join(directory, digest + ext), "wb") as handle:
            handle.write(body)
    except OSError:
        pass
    return body, content_type

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
}


def _build_container() -> Container:
    container = Container(config_mod.load())
    container.discover_plugins(PLUGIN_ROOT)
    return container


def _plugin_payload(container: Container) -> Dict[str, Any]:
    plugins = []
    for meta in sorted(container.plugins.values(), key=lambda p: (p.kind, p.name)):
        plugins.append(
            {
                "name": meta.name,
                "kind": meta.kind,
                "version": meta.version,
                "description": meta.description,
                "enabled": container.enabled(meta),
                "inject": list(meta.inject),
                "missing_services": container.missing_services(meta),
                "schema": meta.schema.to_json_schema(),
                "path": meta.path,
            }
        )
    return {"plugins": plugins}


def _settings_payload(container: Container) -> Dict[str, Any]:
    paths = config_mod.settings_paths()
    default_raw = config_mod._read_json(paths["default"])
    local_raw = config_mod._read_json(paths["local"])
    merged = config_mod.load_settings()
    payload = {
        "paths": paths,
        "default": default_raw,
        "local": local_raw,
        "merged": merged,
        "failures": container.validate_all_settings(),
    }
    payload.update(_plugin_payload(container))
    return payload


def run_fetch(names: Optional[list] = None, limit: Optional[int] = None) -> Tuple[Dict[str, Any], int]:
    container = _build_container()
    container.service("log").quiet = True
    result = asyncio.run(collect(container, names, limit))
    output = (container.config.get("core") or {}).get("output") or "data/unified.json"
    path = result.dump(output)
    counts: Dict[str, int] = {}
    for item in result.items:
        counts[item.platform] = counts.get(item.platform, 0) + 1
    payload = {
        "ok": True,
        "items": len(result.items),
        "by_platform": counts,
        "duplicates": result.duplicates,
        "warnings": result.warnings,
        "output": os.path.abspath(path),
        "elapsed_ms": 0,
    }
    return payload, 200


def _handler(verbose: bool = True):
    class Handler(BaseHTTPRequestHandler):
        server_version = "marksort-server/0.1"
        # 默认是 HTTP/1.0，每个请求都新建 TCP 连接；一屏二十几张图就是二十几次握手
        protocol_version = "HTTP/1.1"

        # ---- 工具 ----

        def _cors(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

        def _json(self, status: int, payload: Dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)

        def _file(self, path: str) -> None:
            if not os.path.isfile(path):
                self._json(404, {"ok": False, "error": "not found"})
                return
            with open(path, "rb") as handle:
                body = handle.read()
            self.send_response(200)
            self.send_header("Content-Type", _CONTENT_TYPES.get(os.path.splitext(path)[1], "application/octet-stream"))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_body(self) -> Dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            if not length:
                return {}
            raw = self.rfile.read(length).decode("utf-8")
            try:
                data = json.loads(raw)
            except ValueError as exc:
                raise ValueError("请求体不是合法 JSON：%s" % exc)
            return data if isinstance(data, dict) else {}

        # ---- 路由 ----

        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self._cors()
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            route = self.path.split("?")[0]
            if route == "/api/sync/status":
                from .sync import get_sync

                self._json(200, get_sync().status())
                return
            if route == "/api/settings":
                try:
                    self._json(200, _settings_payload(_build_container()))
                except Exception as exc:
                    self._json(500, {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)})
                return
            if route == "/api/items":
                container = _build_container()
                output = (container.config.get("core") or {}).get("output") or "data/unified.json"
                path = output if os.path.isabs(output) else os.path.join(config_mod.repo_root(), output)
                self._file(path)
                return
            if route == "/api/image":
                query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                target = (query.get("u") or [""])[0]
                try:
                    body, content_type = fetch_image(target)
                except Exception as exc:
                    self._json(502, {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)})
                    return
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "public, max-age=86400")
                self._cors()
                self.end_headers()
                self.wfile.write(body)
                return
            if route == "/api/health":
                self._json(200, {"ok": True, "time": int(time.time())})
                return
            self._json(404, {"ok": False, "error": "unknown route"})

        def do_POST(self) -> None:  # noqa: N802
            route = self.path.split("?")[0]
            try:
                body = self._read_body()
            except ValueError as exc:
                self._json(400, {"ok": False, "error": str(exc)})
                return
            if route == "/api/settings":
                patch = body.get("patch")
                if not isinstance(patch, dict):
                    self._json(400, {"ok": False, "error": "需要 patch 对象"})
                    return
                try:
                    path = config_mod.save_local(patch)
                except OSError as exc:
                    self._json(500, {"ok": False, "error": str(exc)})
                    return
                self._json(200, {"ok": True, "saved": path})
                return
            if route == "/api/fetch":
                started = time.time()
                try:
                    payload, status = run_fetch(body.get("names"), body.get("limit"))
                except Exception as exc:
                    self._json(500, {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)})
                    return
                payload["elapsed_ms"] = int((time.time() - started) * 1000)
                self._json(status, payload)
                return
            if route == "/api/sync/start":
                from .sync import get_sync

                result = get_sync().start(
                    delay_ms=int(body.get("delay_ms") or 300),
                    workers=int(body.get("workers") or 3),
                    kinds=body.get("kinds") or None,
                )
                self._json(200 if result.get("ok") else 400, result)
                return
            if route == "/api/sync/stop":
                from .sync import get_sync

                self._json(200, get_sync().stop())
                return
            self._json(404, {"ok": False, "error": "unknown route"})

        def log_message(self, fmt: str, *args: Any) -> None:
            if verbose:
                print("[http] " + fmt % args)

    return Handler


def serve(port: int = 17331, verbose: bool = True) -> None:
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _handler(verbose))
    print("MarkSort 设置页：http://127.0.0.1:%d/" % port)
    print("设置文件：%s" % config_mod.settings_paths()["local"])
    print("Ctrl+C 结束")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        httpd.server_close()
