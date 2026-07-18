from common.config import settings  # 读 langfuse 配置

# 是否启用可观测；默认 false（关），开启需在 .env 配好 Langfuse key 并 pip 装 langfuse
_enabled = settings.get("langfuse", {}).get("enabled", False)

def trace_step(name):
    # 装饰器：给某一步打追踪点。关闭时原样返回函数（零开销）；开启时包 Langfuse 的 observe
    def decorator(func):
        if not _enabled:
            return func
        import functools
        from langfuse import observe   # 仅启用时才导入，避免无谓依赖
        return observe(name=name)(func)
    return decorator
