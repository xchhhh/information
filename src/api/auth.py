from fastapi import Security, HTTPException, status       # FastAPI 安全相关
from fastapi.security.api_key import APIKeyHeader          # 从请求头取 API Key
from common.config import settings                         # 读 auth.api_keys

API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)  # 从 header 读 key

async def get_api_key(api_key: str = Security(api_key_header)):
    # 校验请求带的 key 是否在配置的白名单里；不在就返回 401
    valid = settings["auth"]["api_keys"]
    if api_key in valid:
        return api_key
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API Key")
