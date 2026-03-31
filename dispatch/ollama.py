import heapq
import json
import threading
import time
import uuid
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional


class Priority:
    COLLAPSE   = 0
    CACHE_LOW  = 1
    NORMAL     = 2
    PREFETCH   = 3
    BACKGROUND = 4


@dataclass(order=True)
class _Request:
    priority:    int
    enqueued_at: float    = field(compare=False)
    request_id:  str      = field(compare=False)
    student_id:  str      = field(compare=False)
    prompt:      str      = field(compare=False)
    callback:    Callable = field(compare=False)
    timeout:     float    = field(compare=False, default=30.0)
    cancelled:   bool     = field(compare=False, default=False)


class OllamaDispatcher:
    MAX_DEPTH = 60

    def __init__(self, base_url: str = "http://localhost:11434",
                 model: str = "qwen3:1.5b", num_ctx: int = 2048):
        self.model     = model
        self.num_ctx   = num_ctx
        self._endpoint = f"{base_url.rstrip('/')}/api/generate"
        self._heap:    list           = []
        self._lock     = threading.Lock()
        self._event    = threading.Event()
        self._pending: Dict[str, str] = {}
        self.total_dispatched = 0
        self.total_dropped    = 0
        self.total_timeouts   = 0
        threading.Thread(target=self._run, daemon=True).start()

    def submit(self, student_id: str, prompt: str,
               callback: Callable[[Optional[str]], None],
               priority: int = Priority.NORMAL,
               timeout: float = 30.0) -> str:
        with self._lock:
            if len(self._heap) >= self.MAX_DEPTH and priority >= Priority.PREFETCH:
                self.total_dropped += 1
                callback(None)
                return ""
            if student_id in self._pending:
                old = self._pending[student_id]
                for req in self._heap:
                    if req.request_id == old:
                        req.cancelled = True
                        break
            rid = uuid.uuid4().hex[:10]
            req = _Request(priority=priority, enqueued_at=time.time(),
                           request_id=rid, student_id=student_id,
                           prompt=prompt, callback=callback, timeout=timeout)
            heapq.heappush(self._heap, req)
            self._pending[student_id] = rid
        self._event.set()
        return rid

    def cancel(self, student_id: str):
        with self._lock:
            if student_id in self._pending:
                old = self._pending.pop(student_id)
                for req in self._heap:
                    if req.request_id == old:
                        req.cancelled = True

    @property
    def metrics(self) -> Dict:
        return {
            "queue_depth":      len(self._heap),
            "dispatched":       self.total_dispatched,
            "dropped":          self.total_dropped,
            "timeouts":         self.total_timeouts,
            "pending_students": len(self._pending),
        }

    def _run(self):
        while True:
            self._event.wait()
            self._event.clear()
            while True:
                with self._lock:
                    if not self._heap:
                        break
                    req = heapq.heappop(self._heap)
                    if self._pending.get(req.student_id) == req.request_id:
                        del self._pending[req.student_id]
                if req.cancelled:
                    continue
                if time.time() - req.enqueued_at > req.timeout:
                    self.total_timeouts += 1
                    req.callback(None)
                    continue
                result = self._call(req)
                self.total_dispatched += 1
                req.callback(result)

    def _call(self, req: _Request) -> Optional[str]:
        payload = json.dumps({
            "model":   self.model,
            "prompt":  req.prompt,
            "stream":  False,
            "options": {"num_ctx": self.num_ctx, "temperature": 0.7,
                        "num_predict": 512, "stop": ["```"]},
        }).encode()
        try:
            remaining = max(1.0, req.timeout - (time.time() - req.enqueued_at))
            http_req  = urllib.request.Request(
                self._endpoint, data=payload,
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(http_req, timeout=remaining) as resp:
                return json.loads(resp.read()).get("response", "").strip()
        except Exception as e:
            print(f"[Ollama] {req.student_id}: {e}")
            return None