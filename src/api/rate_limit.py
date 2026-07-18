import time                         # 计时
from collections import defaultdict  # 按 key 存命中时间

class RateLimiter:
    # 极简内存限流：每个 key（这里用 IP）在时间窗内最多调用 N 次
    def __init__(self, max_calls=30, window=60):
        self.max_calls = max_calls    # 时间窗内最大次数
        self.window = window          # 时间窗长度（秒）
        self.hits = defaultdict(list) # key -> [时间戳, ...]

    def allow(self, key):
        now = time.time()
        # 只保留时间窗内的记录
        self.hits[key] = [t for t in self.hits[key] if now - t < self.window]
        if len(self.hits[key]) >= self.max_calls:
            return False              # 超了，拒绝
        self.hits[key].append(now)
        return True                   # 放行

limiter = RateLimiter(max_calls=30, window=60)  # 单 IP 每分钟最多 30 次
