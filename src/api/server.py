from fastapi import FastAPI, Depends, Request, HTTPException     # FastAPI 核心
from fastapi.middleware.cors import CORSMiddleware                # 跨域中间件（前端 GitHub Pages 需要）
import os                                                          # 路径处理：定位前端页面
import traceback                                                  # 把真实异常写入日志，便于排查 500
from datetime import datetime                                    # 日志时间戳
from fastapi.responses import FileResponse                       # 返回前端 HTML 文件
from pydantic import BaseModel                                  # 请求/响应数据校验
from api.auth import get_api_key                                # 鉴权依赖
from api.rate_limit import limiter                              # 限流
from rag import answer as rag_answer                            # 顶层问答函数
from orchestrator import orchestrate                            # 多智能体 Orchestrator 总控（深度研究模式）
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

@app.post("/chat", response_model=ChatResp)
async def chat(req: ChatReq, request: Request, api_key: str = Depends(get_api_key)):
    # 1) 限流：按客户端 IP
    if not limiter.allow(request.client.host):
        raise HTTPException(status_code=429, detail="Too many requests")
    # 2) 调问答主流程；捕获意外异常，返回清晰提示而非裸 500，便于定位
    try:
        # 深度研究模式：走多智能体 Orchestrator（拆解->并行子Agent->汇总）；否则走原单链路
        # orchestrate 是 async def（内部 asyncio.gather/to_thread 并发），必须 await；否则拿到的是 coroutine，下面 result["answer"] 会抛 TypeError->500
        result = await orchestrate(req.query) if req.deep else rag_answer(req.query)
    except FileNotFoundError as e:
        _log_error("FileNotFoundError", e)
        raise HTTPException(status_code=503, detail=f"知识库尚未入库：{e}")
    except Exception as e:
        _log_error("chat 未捕获异常", e)
        raise HTTPException(status_code=503, detail=f"问答处理失败：{type(e).__name__}: {e}")
    return ChatResp(
        answer=result["answer"],
        sources=result.get("sources", []),
        sub_queries=result.get("sub_queries", []),   # 深度模式透传子问题，供前端展示思维链
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
