"""Basic in-process metrics hook.

For sprint 1 we only count requests and security events in memory. The functions below are
the single place to connect a real metrics system later (Prometheus, StatsD, CloudWatch...).
"""
from collections import Counter
from threading import Lock

_lock = Lock()
_counters: Counter = Counter()


def increment(name, amount=1):
    with _lock:
        _counters[name] += amount


def record_request(method, status, duration_ms):
    increment(f"http_requests_total.{status // 100}xx")
    increment("http_request_duration_ms_sum", duration_ms)


def snapshot():
    with _lock:
        return dict(_counters)
