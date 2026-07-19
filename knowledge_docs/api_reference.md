# 接口参考（API Reference）

后端基于 FastAPI，对外暴露若干 REST 接口与静态页面路由。所有业务 / 管理接口均需 X-API-Key 鉴权。

## 一、核心问答接口

### POST /chat
- 功能：接收用户问题，返回基于检索资料的答案与引用来源。
- 请求体：{"query": "你做过什么项目？"}
- 响应体：{"answer": "...", "sources": [...]}
- 入口先做按 IP 限流（超限 429），再调 RAG 主流程。

### GET /health
- 功能：健康检查，部署探活、监控用。
- 响应：{"status": "ok"}

## 二、后台管理接口（/admin，均需 X-API-Key）

### GET /admin/status
- 功能：系统状态检测。
- 返回：后端是否存活、当前 embedding 后端、milvus 模式、LLM / 火山方舟 Key 是否配置、data/raw 已有资料清单与数量、向量库条数、BM25 语料是否就绪。
- 用途：一眼看清"资料有没有、向量写没写、Key 配没配"。

### POST /admin/upload
- 功能：上传资料文件到 data/raw。
- 参数：multipart 多文件（files）。
- 防护：类型白名单（.txt/.md/.pdf）、单文件 20MB、路径穿越防护。
- 返回：{"saved": [...], "count": N}

### POST /admin/ingest
- 功能：触发重新入库（加载 -> 切分 -> 向量化 -> 写 Milvus -> 存 BM25）。
- 参数：reset（bool，true 表示先清空旧集合再重建）。
- 返回：{"ok": true, "vector_count": N}

## 三、静态页面路由（无需鉴权）

### GET /
- 返回聊天页 index.html。

### GET /admin
- 返回后台管理页 admin.html。

## 四、接口数量与口径说明

后端真正承担业务逻辑 / 管理的 REST 接口为 5 个：/chat、/health、/admin/status、/admin/upload、/admin/ingest；另有 / 与 /admin 两个静态页面路由。项目经历文档里提到的"6 个接口"是把 /health 与某一路由合并计数的口径差异，此处以代码实际路由为准。

## 五、调用示例（后台入库）

先停服释放 Milvus 锁不是必须（入库由运行中的服务进程持有锁执行）；重建语料时：

curl -X POST "http://localhost:8000/admin/ingest?reset=true" \
  -H "X-API-Key: <你的KEY>"

该调用会在服务进程内 drop 旧集合并重新入库，完成后返回新的向量条数。
