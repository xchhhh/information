# 部署与验证手册（DEPLOY.md）

> 适用范围：基于 FastAPI + Milvus-Lite 的个人 RAG 知识库问答系统（含多智能体 Orchestrator 深度研究模式）。
> 本文档沉淀了从「本地改代码」到「腾讯云服务器上线验证」的完整流程，以及实操中踩过的坑。

---

## 1. 架构与代码流向

```
本地开发机 (Windows + PyCharm)
   │  git commit
   ├─▶ GitHub  (origin，主远端，仅存档)
   └─▶ Gitee   (国内镜像，服务器从这里拉；GitHub 直连超时)
            │  git pull
            ▼
   腾讯云服务器 (TencentOS)
   systemd 服务 `rag`  →  uvicorn 监听 0.0.0.0:8000
   前端聊天页 http://<公网IP>:8000  /  后台页 http://<公网IP>:8000/admin
```

**关键约定**
- 主远端 `origin` = GitHub；镜像 = Gitee（`https://gitee.com/xu-chenghe/information.git`）。
- **服务器永远从 Gitee 拉取**（GitHub 在国内直连超时）。
- 推送 Gitee 偶发 SSL 握手失败，用重试循环兜底（见下文）。

---

## 2. 服务器首次部署（或全新 clone）

> 适用：服务器上还没有项目，或目录被清掉后重新拉。

```bash
# ① 从 Gitee 克隆（私仓用带令牌的地址；公仓可省略账号）
cd /root
git clone https://gitee.com/xu-chenghe/information.git
cd information

# ② 建虚拟环境并装依赖（.venv 不进 git，必须重建）
python3 -m venv /root/information/.venv
/root/information/.venv/bin/pip install --upgrade pip
/root/information/.venv/bin/pip install -r /root/information/requirements.txt
# TencentOS/CentOS 若报缺 venv 模块：先 yum install -y python3-venv 再重试

# ③ 配置鉴权 key（重要！见第 4 节坑位说明）
#   编辑 config/settings.yaml 里 auth.api_keys，改成你自己的 key（默认是 change_me）

# ④ 安装并启用 systemd 服务（服务名是 rag，不是 information）
cp /root/information/deploy/rag.service /etc/systemd/system/rag.service
systemctl daemon-reload
systemctl enable rag
systemctl start rag
```

---

## 3. 日常更新流程（改完代码上线）

本地改完 → 提交 → 推双远端 → 服务器拉取 → 重启 → 验证。

**本地（Windows）**
```bash
cd "C:/Users/30794/Desktop/personal information"
git add -A
git commit -m "你的提交说明"
git push origin main                                  # GitHub
GITEE="https://xu-chenghe:<你的Gitee令牌>@gitee.com/xu-chenghe/information.git"
for i in 1 2 3; do git push --force "$GITEE" HEAD:main && break || sleep 2; done   # Gitee（重试兜底）
```

**服务器**
```bash
cd /root/information
git pull                        # 从 Gitee 拉最新
sudo systemctl restart rag      # 重载新代码（进程内存里的旧代码不会自动更新！）
sleep 3
curl -s http://127.0.0.1:8000/health
```

> ⚠️ **`git clone` / `git pull` 只更新磁盘文件，正在跑的进程仍加载旧代码于内存。任何代码改动都必须 `restart rag` 才生效。**

---

## 4. 坑位速查（都是实测踩过的）

| 现象 | 根因 | 解决办法 |
|------|------|----------|
| `git pull` → `fatal: not a git repository` | 在 `~` 家目录执行，那里不是仓库 | `cd /root/information` 再操作；若从未 clone 过，先按第 2 节克隆 |
| `systemctl restart information` → `Unit information.service not found` | **服务名是 `rag`，不是 `information`**（见 `deploy/rag.service`） | 改用 `systemctl restart rag` |
| 重启后服务秒退 / 起不来 | `.venv` 不存在（全新 clone 不带 venv；或 `rm -rf` 后克隆把 venv 一起删了） | 先 `ls /root/information/.venv/bin/python` 确认；缺失则按第 2 节 ② 重建 |
| 重启后前端集体 `Invalid API Key` | `git clone`/`pull` 覆盖了 `config/settings.yaml`，把你自定义的 `auth.api_keys` 冲回默认 `change_me` | 重启前把真实 key 写回 `config/settings.yaml` 的 `auth.api_keys`（或统一用 `change_me` 并改前端） |
| `/chat` 深度研究返回 `Internal Server Error` 500 | `server.py` 调用 `orchestrate()` 漏写 `await`（`orchestrate` 是 async def），拿到 coroutine 后对 `result["answer"]` 下标访问抛 `TypeError`，且该访问在 try 块外未被捕获（已修复于 commit `83399e3`） | 拉取最新代码并 `restart rag`；经验：在 async 端点里调 async 函数务必 `await` |
| `/health` 版本号不是最新的 | 服务没重启，跑的还是旧代码 | `sudo systemctl restart rag` 后复测 |

---

## 5. 验证命令

**① 健康检查（确认版本）**
```bash
curl -s http://127.0.0.1:8000/health
# Orchestrator 上线后应返回：{"status":"ok","version":"2026-07-20-orchestrator-v1"}
```

**② 单链路问答（基础 RAG）**
```bash
curl -s -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -H "X-API-Key: change_me" \
  -d '{"query":"你的技术栈是什么？","deep":false}'
```

**③ 深度研究（多智能体 Orchestrator）**
```bash
curl -s -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -H "X-API-Key: change_me" \
  -d '{"query":"介绍你整个项目","deep":true}'
```
期望返回含三个字段：
- `sub_queries`：Planner 拆出的子问题列表（思维链数据源）
- `answer`：Synthesizer 汇总后的答案，带 `[来源：<文件名>]` 引用
- `sources`：合并去重后的源文件路径列表

> 深度模式要跑「Planner → 并行子 Agent 检索生成 → Synthesizer 汇总」，会调多次 LLM，**耗时约 10–30 秒**，curl 等待属正常。

**④ 看服务端真实异常（出问题先查这里）**
```bash
tail -n 50 /root/information/data/server.log     # /chat 未捕获异常会写 traceback 到这里
journalctl -u rag -n 50 --no-pager               # systemd 服务日志
```

---

## 6. 已知结论（实测验证）

- **milvus-lite 并行检索安全**：深度研究模式 3 个并行子 Agent 同时检索无报错。原因——子 Agent 只做**检索（读）**，milvus-lite 的锁是**写锁**，仅后台 `/admin/ingest` 入库时触发，读操作之间不互斥。实现时为保并行未加锁是合理取舍。
- **优雅降级已具备**：单个子 Agent 超时/失败会跳过；全部失败回退单链路；Synthesizer 失败用规则拼接兜底。
- **确定性质量数据**：混合检索相关段落覆盖率 `top_k=4` 38.0% → `top_k=8` 65.0%（+71.1%），10 条真实问答对实测。

---

## 7. 目录与服务速记

- 服务名：`rag`｜单元文件：`deploy/rag.service`
- 工作目录：`/root/information`｜入口：`app.py`（uvicorn 监听 `0.0.0.0:8000`）
- Python 解释器：`/root/information/.venv/bin/python`
- 配置：`config/settings.yaml`（含 `auth.api_keys`、`orchestrator.*`）
- 知识库原始文件：`data/raw/`｜入库后向量：`data/`（Milvus-Lite 嵌入式）
- 服务端日志：`data/server.log`
