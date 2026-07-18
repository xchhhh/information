import os                          # 处理目录与路径
from langchain_community.document_loaders import TextLoader, PyPDFLoader  # txt/md 与 pdf 加载器
from common.config import BASE_DIR  # 引入项目根目录，保证路径不依赖“当前工作目录”

def load_documents(folder=None):
    # folder 不传时，默认读项目根下的 data/raw（你的原始资料放这里）
    folder = folder or os.path.join(BASE_DIR, "data", "raw")
    docs = []                                   # 用来装加载好的文档
    for root, _, files in os.walk(folder):      # 递归遍历该目录所有文件
        for fn in files:                        # 逐个文件名
            p = os.path.join(root, fn)          # 拼出完整路径
            if fn.lower().endswith((".txt", ".md")):        # 文本 / Markdown
                docs += TextLoader(p, encoding="utf-8").load()   # 用 TextLoader 加载（utf-8 防乱码）
            elif fn.lower().endswith(".pdf"):   # PDF
                docs += PyPDFLoader(p).load()   # 每页会被拆成一个独立文档
    return docs                                 # 返回所有文档
