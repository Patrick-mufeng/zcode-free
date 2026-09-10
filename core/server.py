"""本地 HTTP 服务:Web 面板页面 + RPC + SSE 事件流。

浏览器面板与后端之间只有这一条链路:
- GET  /          面板页面(ui/index.html)
- GET  /assets/*  静态资源
- POST /api       {method, args} → {result} / {error}
- GET  /events    SSE 事件流(状态/日志/截图事件实时推送)
"""
from __future__ import annotations

import json
import mimetypes
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from loguru import logger

from core.config import UI_DIR
from core.events import EventBus


class Bridge:
    def __init__(self, api, bus: EventBus, ui_dir: Path = UI_DIR):
        self.api = api
        self.bus = bus
        self.ui_dir = Path(ui_dir)

    def dispatch(self, method: str, args: list):
        if not method or method.startswith("_") or not hasattr(self.api, method):
            raise ValueError(f"未知方法:{method}")
        fn = getattr(self.api, method)
        if not callable(fn):
            raise ValueError(f"未知方法:{method}")
        payload = args[0] if args else None
        return fn(payload)


def make_handler(bridge: Bridge):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ZcodeWelfare/1.0"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):  # 静默访问日志
            pass

        # ---------- 工具 ----------

        def _send(self, code: int, body: bytes, content_type: str):
            try:
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                pass

        def _json(self, obj, code: int = 200):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")

        # ---------- GET ----------

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/events":
                return self._sse()
            rel = "index.html" if path in ("/", "/index.html") else path.lstrip("/")
            return self._static(rel)

        def _static(self, rel: str):
            root = bridge.ui_dir.resolve()
            target = (root / rel).resolve()
            if not str(target).startswith(str(root)) or not target.is_file():
                return self._json({"error": "not found"}, 404)
            mime, _ = mimetypes.guess_type(str(target))
            self._send(200, target.read_bytes(), mime or "application/octet-stream")

        def _sse(self):
            # SSE 为不定长流:声明 close 语义,避免 HTTP/1.1 keep-alive 下客户端等待长度
            self.close_connection = True
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.end_headers()

            events: queue.Queue = queue.Queue()

            def on_event(event_type, payload):
                events.put({"type": event_type, "payload": payload})

            unsubscribe = bridge.bus.subscribe(on_event)
            try:
                while True:
                    try:
                        item = events.get(timeout=15)
                        data = json.dumps(item, ensure_ascii=False)
                        self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError, OSError):
                pass
            finally:
                unsubscribe()

        # ---------- POST ----------

        def do_POST(self):
            if self.path.split("?")[0] != "/api":
                return self._json({"error": "not found"}, 404)
            try:
                length = int(self.headers.get("Content-Length") or 0)
                request = json.loads(self.rfile.read(length) or b"{}")
                result = bridge.dispatch(request.get("method") or "", request.get("args") or [])
                self._json({"result": result})
            except Exception as exc:
                self._json({"error": str(exc)})

    return Handler


class BridgeServer:
    """持有本地服务的句柄(地址 + 关闭方法)。"""

    def __init__(self, url: str, httpd: ThreadingHTTPServer):
        self.url = url
        self.httpd = httpd

    def shutdown(self) -> None:
        try:
            self.httpd.shutdown()
            self.httpd.server_close()
        except Exception:
            pass


def serve(api, bus: EventBus, host: str = "127.0.0.1", port: int = 8760,
          ui_dir: Path = UI_DIR) -> BridgeServer:
    """启动本地服务(端口占用时自动向后尝试)。"""
    handler = make_handler(Bridge(api, bus, ui_dir))
    last_error: Exception | None = None
    for candidate in range(port, port + 11):
        try:
            httpd = ThreadingHTTPServer((host, candidate), handler)
        except OSError as exc:
            last_error = exc
            continue
        threading.Thread(target=httpd.serve_forever, daemon=True, name="http-bridge").start()
        url = f"http://{host}:{candidate}/"
        logger.info(f"面板服务已启动:{url}")
        return BridgeServer(url, httpd)
    raise RuntimeError(f"无法启动本地服务(端口 {port} 起均被占用):{last_error}")
