"""Evaluation 层 — 统一指标收集器 (Layer 1 性能基准)。

所属层级: Evaluation / Infra

设计要点:
- 纯 stdlib, 零内部依赖 —— 供 llm/factory、mcp_sdk/manager、harness/supervisor
  安全 import, 不产生循环依赖。
- 有界环形缓冲: 每条 (kind, tags) 序列独立 ring (maxlen=ring_size),
  内存占用恒定, 应用运行期间始终采集真实流量延迟。
- 两种记录语义:
  * value    —— 标量采样 (延迟等), snapshot 出 min/mean/max/分位数;
  * count    —— 增量计数器 (token 用量等), snapshot 出窗口内累计 total。
- 线程安全 (threading.Lock): FastAPI 单事件循环内 record 高频调用, 开销极小。
- 可选持久化 sink: set_sink(callable) 后每条记录触发; 默认 None。
"""
import statistics
import threading
import time
from collections import deque
from typing import Any, Callable, Optional

RecordEvent = dict[str, Any]
SinkFn = Callable[[RecordEvent], None]


def percentile(sorted_values: list[float], p: float) -> float:
    """最近秩法分位数 (0 < p <= 100), 输入需已升序。空列表返回 0.0。"""
    if not sorted_values:
        return 0.0
    n = len(sorted_values)
    if p >= 100:
        return sorted_values[-1]
    rank = max(1, round(p / 100.0 * n))
    return sorted_values[rank - 1]


def _key(kind: str, tags: dict[str, Any]) -> tuple[str, tuple]:
    return (kind, tuple(sorted(tags.items())))


class _Counter:
    """增量计数器: 记录每次增量 (供窗口统计) + 累计总量。"""

    __slots__ = ("deltas", "total")

    def __init__(self, ring: int) -> None:
        self.deltas: deque = deque(maxlen=ring)
        self.total: int = 0


class MetricsCollector:
    """统一指标收集器 (内存 + 可选 sink 持久化)。"""

    def __init__(self, ring_size: int = 2000) -> None:
        self._ring_size = ring_size
        self._samples: dict[tuple, deque] = {}   # key -> deque[(ts, value)]
        self._counters: dict[tuple, _Counter] = {}
        self._sink: Optional[SinkFn] = None
        self._lock = threading.Lock()

    # ---------- 写入 ----------
    def record(self, kind: str, value: Optional[float] = None,
               count: Optional[int] = None, **tags: Any) -> None:
        """记录一条采样。

        传 count 走计数器累加; 否则按 value 采样值入库。
        """
        ts = time.monotonic()
        if count is not None:
            self._incr_at(kind, ts, count, tags)
        else:
            k = _key(kind, tags)
            with self._lock:
                series = self._samples.get(k)
                if series is None:
                    series = deque(maxlen=self._ring_size)
                    self._samples[k] = series
                series.append((ts, float(value if value is not None else 0.0)))
        self._emit(kind, tags, value=value, count=count)

    def incr(self, kind: str, amount: int = 1, **tags: Any) -> None:
        """计数器 +amount (便捷)。"""
        self.record(kind, count=amount, **tags)

    def _incr_at(self, kind: str, ts: float, amount: int, tags: dict) -> None:
        k = _key(kind, tags)
        with self._lock:
            counter = self._counters.get(k)
            if counter is None:
                counter = _Counter(self._ring_size)
                self._counters[k] = counter
            counter.total += amount
            counter.deltas.append((ts, amount))

    def _emit(self, kind: str, tags: dict, **payload: Any) -> None:
        if self._sink is not None:
            try:
                self._sink({"kind": kind, "tags": tags, **payload})
            except Exception:  # noqa: BLE001 — sink 异常不得影响采集
                pass

    # ---------- 读取 ----------
    def snapshot(self, window_s: Optional[float] = None,
                 kinds: Optional[list[str]] = None) -> list[dict[str, Any]]:
        """统计窗口内指标。window_s=None 表示不按时间过滤 (统计全部保留记录)。"""
        now = time.monotonic()
        out: list[dict[str, Any]] = []
        with self._lock:
            for k, series in self._samples.items():
                kind, tags_items = k
                if kinds and kind not in kinds:
                    continue
                tags = dict(tags_items)
                vals = [v for ts, v in series
                        if window_s is None or now - ts <= window_s]
                if not vals:
                    continue
                srt = sorted(vals)
                span = window_s if window_s is not None else max(now - series[0][0], 1e-9)
                entry = {
                    "kind": kind,
                    "tags": tags,
                    "count": len(vals),
                    "min": round(min(vals), 3),
                    "mean": round(statistics.fmean(vals), 3),
                    "max": round(max(vals), 3),
                    "p50": round(percentile(srt, 50), 3),
                    "p95": round(percentile(srt, 95), 3),
                    "p99": round(percentile(srt, 99), 3),
                    "per_second": round(len(vals) / span, 3) if window_s is not None else None,
                }
                out.append(entry)
            for k, counter in self._counters.items():
                kind, tags_items = k
                if kinds and kind not in kinds:
                    continue
                tags = dict(tags_items)
                deltas = [(ts, a) for ts, a in counter.deltas
                          if window_s is None or now - ts <= window_s]
                total = sum(a for _, a in deltas)
                span = window_s if window_s is not None else 1e-9
                entry = {
                    "kind": kind,
                    "tags": tags,
                    "count": len(deltas),
                    "total": total,
                    "per_second": round(total / span, 3) if window_s is not None else None,
                }
                out.append(entry)
        return out

    # ---------- 生命周期 ----------
    def reset(self) -> None:
        """清空所有已采集指标 (测试 / dry_run 隔离用)。"""
        with self._lock:
            self._samples.clear()
            self._counters.clear()

    def set_sink(self, sink: Optional[SinkFn]) -> None:
        """设置持久化 sink (可选); None 关闭。"""
        self._sink = sink

    @property
    def series_count(self) -> int:
        return len(self._samples) + len(self._counters)


# 全局单例
_collector = MetricsCollector()


def get_metrics_collector() -> MetricsCollector:
    """获取全局 MetricsCollector 单例。"""
    return _collector
