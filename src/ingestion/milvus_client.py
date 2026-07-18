from pymilvus import MilvusClient, FieldSchema, CollectionSchema, DataType  # Milvus 客户端与建表类型
from common.config import settings  # 引入全局配置

def get_client():
    # 根据配置建立 Milvus 连接；本地用 Docker standalone，部署用嵌入式 milvus-lite
    m = settings["milvus"]
    if m.get("mode") == "lite":
        return MilvusClient(uri=m["lite_path"])               # 嵌入式，免 Docker
    return MilvusClient(uri=f"http://{m['host']}:{m['port']}") # 连 Docker 里的 standalone

def ensure_collection(client):
    # 确保集合存在：不存在就按 schema 新建，存在则直接复用（避免重复建表）
    m = settings["milvus"]
    dim = settings["embedding"]["dim"]   # 向量维度（你的 mxbai / doubao 都是 1024）
    name = m["collection"]
    if client.has_collection(name):     # 已存在
        return name
    schema = CollectionSchema(
        fields=[
            FieldSchema("id", DataType.INT64, is_primary=True, auto_id=True),       # 主键，自动生成
            FieldSchema("dense_vec", DataType.FLOAT_VECTOR, dim=dim),               # 稠密向量，维度=1024
            FieldSchema("text", DataType.VARCHAR, max_length=8000),                # 原文
            FieldSchema("source", DataType.VARCHAR, max_length=512),               # 来源文件名
            FieldSchema("chunk_id", DataType.VARCHAR, max_length=128),             # 切片编号
        ],
        enable_dynamic_field=True,        # 允许动态字段，以后加元数据不报错
    )
    idx = client.prepare_index_params()  # 准备索引参数
    idx.add_index(field_name="dense_vec", metric_type=m["metric_type"], index_type="AUTOINDEX")  # 向量索引
    client.create_collection(collection_name=name, schema=schema, index_params=idx)  # 真正建集合
    return name

def insert_chunks(client, chunks, vectors):
    # 把切好的块 + 对应向量批量写入 Milvus
    name = settings["milvus"]["collection"]
    data = [                                    # 每条 = 一个 Milvus 实体
        {"dense_vec": v,
         "text": c.page_content,
         "source": c.metadata.get("source", ""),
         "chunk_id": c.metadata.get("chunk_id", "")}
        for c, v in zip(chunks, vectors)
    ]
    client.insert(collection_name=name, data=data)
    return len(data)                           # 返回写入条数
