# 向量数据库：Milvus-Lite 嵌入式方案

本项目选用 Milvus-Lite 作为向量存储，而不是独立部署的 Milvus 集群或外部向量服务。下面说明选型理由与关键使用细节。

## 一、什么是 Milvus-Lite

Milvus-Lite 是 Milvus 的嵌入式版本，以单个文件（milvus_lite.db）形式落盘，无需启动独立的数据库服务进程，直接随应用进程内嵌运行。对个人项目、单机部署、资源受限的云服务器来说，它把"向量数据库"的运维成本降到几乎为零。

## 二、为什么不用独立 Milvus / 外部向量库

- 个人作品集问答的语料规模小（几十到几百个段落），远未到需要分布式向量库的程度；
- 独立 Milvus 需要 Docker 或独立进程，占用内存与运维精力；
- 嵌入式方案让"FastAPI 进程 + 向量库"同进程托管，部署最简单，也最契合腾讯云小机型。

配置项 milvus.mode 在本地开发可设为 standalone（Docker），生产部署设为 lite，二者 schema 通用（稠密字段 dense_vec、维度 1024、度量 L2）。

## 三、集合（Collection）与字段

- 集合名：personal_rag（相当于一张表）；
- 稠密向量字段：dense_vec，1024 维；
- 距离度量：L2（欧氏距离）；
- 每条记录除向量外，还存原文 text、来源 source、chunk_id 等标量字段，供检索召回后定位出处。

## 四、必须注意的加载机制

Milvus-Lite（以及 Milvus 通用）有个容易踩坑的点：集合必须先 load_collection 之后才能 query / search。本项目在 /admin/status 状态检测、入库后的计数、以及 benchmark 的向量检索阶段，都会先显式 load_collection，否则会查不到数据或报错。

## 五、文件锁与单进程约束

Milvus-Lite 基于本地文件，同一时刻只允许一个进程持有写锁。这也是本项目运维上的一条铁律：

- 运行中的 rag 服务进程持有该锁，负责日常检索与入库；
- 任何另起进程直接操作同一个 milvus_lite.db（例如跑评估 benchmark、或离线脚本）都会因锁冲突报 DataDirLockedError；
- 因此跑评估前必须先 systemctl stop rag 释放锁，跑完再 start。

这条约束是排查"评估脚本连不上向量库"类问题的第一抓手。

## 六、入库与重建

入库主流程（ingestion.run）连接 Milvus、确保集合存在、加载并切分资料、向量化、写入，并把 BM25 语料落盘。需要全量重建时，先 drop_collection 再重新入库，避免向量重复导致检索质量下降。后台 /admin/ingest 接口带 reset 参数，就是用来做"清空重建"。
