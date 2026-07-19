from fastapi import FastAPI, Depends, Request, HTTPException     # FastAPI 核心
from fastapi.middleware.cors import CORSMiddleware                # 跨域中间件（前端 GitHub Pages 需要）
import os                                                          # 路径处理：定位前端页面
from fastapi.responses import FileResponse                       # 返回前端 HTML 文件
from pydantic import BaseModel                                  # 请求/响应数据校验
from api.auth import get_api_key                                # 鉴权依赖
from api.rate_limit import limiter                              # 限流
from rag import answer as rag_answer                            # 顶层问答函数
from common.config import settings                             # 配置
from api.admin import router as admin_router                  # 后台管理路由（检测/上传/入库）

app = FastAPI(title="Personal RAG API")   # 创建 FastAPI 应用
app.include_router(admin_router)         # 挂载后台路由：/admin/status、/admin/upload、/admin/ingest

# 允许前端（GitHub Pages 等）跨域调用本接口
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],     # 生产环境应改成你的前端域名
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatReq(BaseModel):    # 请求体：用户问题
    query: str

class ChatResp(BaseModel):   # 响应体：答案 + 来源
    answer: str
    sources: list

@app.post("/chat", response_model=ChatResp)
async def chat(req: ChatReq, request: Request, api_key: str = Depends(get_api_key)):
    # 1) 限流：按客户端 IP
    if not limiter.allow(request.client.host):
        raise HTTPException(status_code=429, detail="Too many requests")
    # 2) 调问答主流程
    result = rag_answer(req.query)
    return ChatResp(answer=result["answer"], sources=result["sources"])

@app.get("/health")    # 健康检查，部署/探活用
async def health():
    return {"status": "ok"}

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
