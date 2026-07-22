from fastapi import FastAPI, Depends, Request, HTTPException     # FastAPI 核心
from fastapi.middleware.cors import CORSMiddleware                # 跨域中间件（前端 GitHub Pages 需要）
import os                                                          # 路径处理：定位前端页面
import json                                                         # SSE 流式响应里序列化每个 chunk
import traceback                                                  # 把真实异常写入日志，便于排查 500
from datetime import datetime                                    # 日志时间戳
from fastapi.responses import FileResponse, StreamingResponse    # 返回前端 HTML / 流式 SSE 响应
from pydantic import BaseModel                                  # 请求/响应数据校验
from api.auth import get_api_key                                # 鉴权依赖
from api.rate_limit import limiter                              # 限流
from rag import stream_answer                                  # 流式问答（SSE 接口用）
from orchestrator import stream_orchestrate                     # 多智能体 Orchestrator 流式（SSE 接口用）
from common.config import settings                             # 配置
from api.admin import router as admin_router                  # 后台管理路由（检测/上传/入库）

app = FastAPI(title="Personal RAG API")   # 创建 FastAPI 应用
app.include_router(admin_router)         # 挂载后台路由：/admin/status、/admin/upload、/admin/ingest

# 版本标记：用于确认服务器跑的是不是最新代码（curl /health 看 version 字段）
APP_VERSION = "2026-07-20-orchestrator-v1"

# 允许前端（GitHub Pages 等）跨域调用本接口
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],     # 生产环境应改成你的前端域名
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatReq(BaseModel):    # 请求体：用户问题
    query: str
    deep: bool = False       # 是否走多智能体 Orchestrator 深度研究；默认关，走原单链路

class ChatResp(BaseModel):   # 响应体：答案 + 来源 + （深度模式时的子问题思维链）
    answer: str
    sources: list
    sub_queries: list = []   # Orchestrator 拆解出的子问题列表；单链路时为空

@app.post("/chat")
async def chat(req: ChatReq, request: Request, api_key: str = Depends(get_api_key)):
    # 1) 限流：按客户端 IP；超限直接 429（此时尚未开始流式，HTTP 状态码有效）
    if not limiter.allow(request.client.host):
        raise HTTPException(status_code=429, detail="Too many requests")

    # 2) SSE 流式：把问答主流程包成异步生成器，逐块以 `data: {json}\n\n` 推给前端。
    #    前端据此实现“逐字显示”（DeepSeek 那种边想边出字的体验）。
    async def event_generator():
        try:
            # 深度研究模式：走多智能体 Orchestrator 流式（拆解->并行子Agent->汇总）；否则走原单链路流式
            gen = stream_orchestrate(req.query) if req.deep else stream_answer(req.query)
            async for chunk in gen:
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        except Exception as e:
            _log_error("chat stream", e)
            # 流式已开始（连接已返回 200），无法再改 HTTP 状态码，改用 SSE error 事件通知前端
            yield f"data: {json.dumps({'type': 'error', 'data': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},  # 关代理缓冲，保证逐字推送
    )

def _log_error(where, exc):
    # 把真实报错连同完整 traceback 写入 data/server.log，服务器上 `cat data/server.log` 即可看到根因
    try:
        log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "server.log")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n[{datetime.now().isoformat()}] {where}\n")
            f.write(traceback.format_exc())
    except Exception:
        pass   # 写日志失败也不影响主流程

@app.get("/health")    # 健康检查，部署/探活用
async def health():
    return {"status": "ok", "version": APP_VERSION}

# 同源部署：根路径直接返回前端聊天页面，考官访问 http://公网IP:8000 即可使用
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # src/api -> 项目根
_FRONTEND_DIR = os.path.join(_ROOT, "frontend")               # 前端目录（下面两个页面都在这里）
_FRONTEND = os.path.join(_FRONTEND_DIR, "index.html")        # 聊天页

@app.get("/")
async def index():
    return FileResponse(_FRONTEND)

@app.get("/admin")      # 后台管理页（纯静态 HTML，无需鉴权；接口才要 X-API-Key）
async def admin_page():
    return FileResponse(os.path.join(_FRONTEND_DIR, "admin.html"))
