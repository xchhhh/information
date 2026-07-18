import os            # 路径
import sys           # 模块搜索路径
# 把 src 加入搜索路径，这样无需手动设 PYTHONPATH 也能 import api / rag
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from api.server import app   # 引入 FastAPI 应用

if __name__ == "__main__":
    import uvicorn
    # 启动后端服务：http://localhost:8000 ，/chat 提供问答，/docs 是自带接口文档
    uvicorn.run(app, host="0.0.0.0", port=8000)
