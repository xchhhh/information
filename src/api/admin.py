# src/api/admin.py
# 后台管理接口：检测系统状态 + 上传资料 + 重新入库
# 三个接口全部挂在 /admin 下，并复用 /chat 的同一套 X-API-Key 鉴权
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException  # FastAPI 核心与上传类型
import os            # 处理文件路径
import pickle        # 仅用于判断 BM25 语料文件是否存在（可选）
from api.auth import get_api_key                    # 复用 /chat 的鉴权依赖
from common.config import BASE_DIR, settings       # 项目根目录、全局配置
from ingestion.milvus_client import get_client, ensure_collection  # Milvus 连接/建表

# 创建带前缀 /admin 的路由，并统一要求请求携带合法的 X-API-Key
router = APIRouter(prefix="/admin", dependencies=[Depends(get_api_key)])

# 资料原始目录：上传的文件落在这里，run.py 入库时会读取它
RAW_DIR = os.path.join(BASE_DIR, "data", "raw")
# BM25 稀疏检索语料路径：入库时生成，用来判断"是否已入库"
BM25_PATH = os.path.join(BASE_DIR, "data", "processed", "bm25_corpus.pkl")
# 允许上传的文件类型（与 ingestion/loaders.py 支持的格式保持一致）
ALLOWED_EXT = {".txt", ".md", ".pdf", ".doc", ".docx", ".png", ".jpg", ".jpeg"}
# 单个文件大小上限 20MB，防止有人传超大文件把内存打爆
MAX_SIZE = 20 * 1024 * 1024


@router.get("/status")
async def status():
    # —— 1) 列出 data/raw 下已有的资料文件（带大小） ——
    raw_files = []
    if os.path.isdir(RAW_DIR):
        for fn in sorted(os.listdir(RAW_DIR)):
            fp = os.path.join(RAW_DIR, fn)
            if os.path.isfile(fp):                      # 只统计文件，跳过子目录
                raw_files.append({"name": fn, "size": os.path.getsize(fp)})

    # —— 2) 统计向量库里已写入的条目数（milvus-lite 需先 load 才能查） ——
    vector_count = 0
    try:
        client = get_client()
        ensure_collection(client)                       # 没有集合就先建一个空的
        name = settings["milvus"]["collection"]
        client.load_collection(collection_name=name)    # milvus-lite 必须先 load 才能 query
        rows = client.query(collection_name=name, output_fields=["id"], limit=100000)
        vector_count = len(rows)                        # 条数即向量条数
    except Exception:
        vector_count = -1                              # -1 表示查询失败（如未入库/文件被占用）

    # —— 3) 组装检测报告返回给前端 ——
    return {
        "backend": "ok",                                       # 后端活着
        "embedding_provider": settings["embedding"]["provider"],   # 当前 embedding 后端
        "milvus_mode": settings["milvus"]["mode"],                # lite / docker
        "llm_key_set": bool(os.getenv("LLM_API_KEY")),         # DeepSeek Key 是否配置
        "ark_key_set": bool(os.getenv("ARK_API_KEY")),         # 火山方舟 Key 是否配置
        "raw_files": raw_files,                                # 原始资料清单
        "raw_count": len(raw_files),                           # 资料数量
        "vector_count": vector_count,                          # 向量条数（-1=查询失败）
        "bm25_ready": os.path.exists(BM25_PATH),              # BM25 语料是否已生成
    }


@router.post("/upload")
async def upload(files: list[UploadFile] = File(...)):
    os.makedirs(RAW_DIR, exist_ok=True)    # 确保资料目录存在
    saved = []                             # 收集成功保存的文件名，返回给前端展示
    for f in files:
        # 安全：只取文件名最后一段，剥掉路径分隔符与 ".."，防止目录穿越攻击
        name = os.path.basename(f.filename or "")
        if not name:
            raise HTTPException(status_code=400, detail="文件名不能为空")
        ext = os.path.splitext(name)[1].lower()       # 取扩展名（小写）用于校验
        if ext not in ALLOWED_EXT:
            raise HTTPException(status_code=400,
                               detail=f"不支持的类型 {ext}，仅允许 {sorted(ALLOWED_EXT)}")
        safe = name.replace(" ", "_")                  # 空格转下划线，避免路径/命令行麻烦
        data = await f.read()                          # 读取上传内容到内存
        if len(data) > MAX_SIZE:
            raise HTTPException(status_code=413, detail=f"文件过大：{safe}（上限 20MB）")
        dest = os.path.join(RAW_DIR, safe)
        with open(dest, "wb") as out:
            out.write(data)                           # 写入资料目录
        saved.append(safe)
    return {"saved": saved, "count": len(saved)}


@router.post("/ingest")
async def ingest(reset: bool = False):
    # reset=true 时先清空旧集合，避免重复入库导致向量翻倍、检索质量下降
    if reset:
        client = get_client()
        name = settings["milvus"]["collection"]
        if client.has_collection(name):
            client.drop_collection(collection_name=name)   # 删掉后下次入库会自动重建

    # 直接复用 run.py 的入库主流程：加载->切分->向量化->写 Milvus->存 BM25
    from ingestion.run import main as ingest_main
    ingest_main()

    # 让正在运行的服务刷新内存中的检索索引（BM25 语料已更新、含新 chunk_id），
    # 否则下次 /chat 会因内存索引与 Milvus 不一致而 KeyError -> HTTP 500
    try:
        from rag import reset_retriever
        reset_retriever()
    except Exception:
        pass   # 即使刷新失败，hybrid 也会在下一次 retrieve 时按文件 mtime 自动重载

    # 重新统计入库后的向量条数返回
    vector_count = 0
    try:
        client = get_client()
        ensure_collection(client)
        name = settings["milvus"]["collection"]
        client.load_collection(collection_name=name)
        rows = client.query(collection_name=name, output_fields=["id"], limit=100000)
        vector_count = len(rows)
    except Exception:
        vector_count = -1
    return {"ok": True, "vector_count": vector_count}
