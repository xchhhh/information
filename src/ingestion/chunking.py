from langchain_text_splitters import RecursiveCharacterTextSplitter  # 按字符递归切分器
from common.config import settings  # 读取切分参数

def chunk_documents(docs):
    c = settings["chunking"]    # 取 chunking 段：chunk_size / chunk_overlap
    # 创建切分器：按字符数切（中文没有空格，用字符数最自然）
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=c["chunk_size"],          # 每块最大字符数（你配的 500）
        chunk_overlap=c["chunk_overlap"],    # 相邻块重叠字符（你配的 80），保上下文连贯
        length_function=len,                 # 用 len() 算长度（按字符）
        separators=["\n\n", "\n", "。", "！", "？", "；", "，", " "],  # 优先在这些标点处断开，切得更自然
    )
    chunks = splitter.split_documents(docs)  # 执行切分，得到一堆小块
    # 给每个块挂上元数据 chunk_id = “来源-序号”，方便后面检索回来定位出处
    for i, ch in enumerate(chunks):
        src = ch.metadata.get("source", "doc")
        ch.metadata["chunk_id"] = f"{src}-{i}"
    return chunks                            # 返回切好的块
