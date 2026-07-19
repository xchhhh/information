# 服务器部署指南（腾讯云轻量应用服务器 · TencentOS Server 4）

目标：把后端 + 前端都跑在服务器上，考官访问 `http://公网IP:8000` 一个地址就能聊天（同源 http，浏览器不拦截）。GitHub 只保留代码仓库。

> 前置：已在腾讯云买好轻量应用服务器（2核2G 即可），镜像为 **TencentOS Server 4 for x86_64**，并在控制台「防火墙」放通 **TCP 8000** 端口。
>
> TencentOS 是类 RHEL9 系统，包管理用 `dnf`（不是 `apt`），Python 默认 3.11（代码兼容 3.11+，无需另装 3.12）。

## 1. 登录服务器
控制台点「登录」用 OrcaTerm，或本地终端：`ssh root@你的公网IP`（密码在控制台重置过）。

## 2. 装基础工具
```bash
dnf install -y git python3 python3-devel python3-pip gcc make
python3 --version   # 确认输出 3.11.x 左右即可
```
> 说明：RHEL 系没有 `python3-venv` 这个独立包，`venv` 模块已包含在 `python3` 里；`python3-devel` + `gcc make` 用于个别包需要本地编译时保底。

## 3. 拉代码
```bash
git clone https://github.com/xchhhh/information.git
cd information
```
> 国内服务器直连 `github.com` 常被重置（报错 `Failure when receiving data from the peer`）。若 clone 失败，改用 Gitee 镜像：先把 GitHub 仓库导入 Gitee（`https://gitee.com` → 右上角「+」→ 导入仓库），再：
> ```bash
> git clone https://gitee.com/你的用户名/information.git
> cd information
> git remote set-url origin https://gitee.com/你的用户名/information.git   # 以后 pull 也走镜像
> ```
> （ghproxy.com / gitclone.com 等公共镜像经常超时或 502，不如 Gitee 稳。）

## 4. 建虚拟环境并装依赖
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-deploy.txt
```
> requirements-deploy.txt 已改为云端友好版：milvus-lite（嵌入式，免 Docker）+ 云端 doubao embedding，并去掉了 Ollama / 本地重排模型依赖。
>
> 若 `python3 -m venv .venv` 报错提示缺少模块，先 `dnf install -y python3-devel` 后重试。

## 5. 配置密钥
```bash
cp .env.example .env
vi .env        # 或 nano .env（nano 可能需 dnf install -y nano）
```
在 `.env` 里填两项真实值，并**取消注释**下面两行（切换到云端 embedding + 嵌入式 Milvus）：
```env
LLM_API_KEY=sk-你的deepseek密钥
ARK_API_KEY=你的火山方舟密钥

EMBEDDING_PROVIDER=doubao
MILVUS_MODE=lite
```
> 重排模型在 2核2G 上会自动加载失败并跳过（代码已容错），不影响问答，只是少了重排、答案质量略降。

## 5.5 上传资料并入库（首次部署必做）

代码仓库**不含**你的原始资料（`data/` 被 `.gitignore` 忽略），服务器 clone 下来 `data/raw` 是空的。不入库直接调 `/chat` 会报 `未找到 BM25 语料`，必须先把资料传上去并跑一次入库脚本。

1) 把本机资料传到服务器项目目录 `data/raw`（支持 `.txt` / `.md` / `.pdf`）：
   - 本机 PowerShell（推荐）：
     ```powershell
     ssh root@公网IP "mkdir -p /root/information/data/raw"
     scp -r "本机资料目录\*" root@公网IP:/root/information/data/raw/
     ```
   - 或腾讯云控制台 OrcaTerm「文件上传」拖到 `/root/information/data/raw`。
   > 注意：资料要放到**项目目录**下的 `data/raw`，不是系统根目录 `/data/raw`；若 `run.py` 输出 `inserted 0 chunks`，先 `ls data/raw` 确认文件在正确位置、且格式为 txt|md|pdf。

2) 服务器上入库（用 doubao 向量化 + 写 milvus-lite，消耗少量 ARK 额度）：
   ```bash
   cd /root/information
   source .venv/bin/activate
   python src/ingestion/run.py
   # 看到 inserted N chunks; BM25 corpus saved to ... 即成功（N>0）
   ```
   > 入库只需做一次；以后换资料重跑即可。milvus-lite 的固定数据库文件 `milvus_lite.db` 会生成在项目根目录，已被 `.gitignore` 忽略，勿提交。

## 6. 先前台试跑
```bash
source .venv/bin/activate
python app.py
```
浏览器开 `http://公网IP:8000` 应看到聊天界面；另开终端验证：
```bash
curl http://localhost:8000/health
# 应返回 {"status":"ok"}

curl -X POST http://localhost:8000/chat \
  -H "X-API-Key: change_me" -H "Content-Type: application/json" \
  -d '{"query":"你做过哪些项目"}'
# 应返回带 answer 和 sources 的 JSON
```
确认无误后 `Ctrl+C` 停掉前台进程。

## 7. 后台常驻（systemd）
新建服务文件：`vi /etc/systemd/system/rag.service`
```ini
[Unit]
Description=Personal RAG API
After=network.target

[Service]
WorkingDirectory=/root/information
ExecStart=/root/information/.venv/bin/python /root/information/app.py
Restart=always
User=root

[Install]
WantedBy=multi-user.target
```
> 若代码在别处（如 `/home/xxx/information`），请把上面两处路径改成对应位置。

启用并启动：
```bash
systemctl daemon-reload
systemctl enable rag
systemctl start rag
systemctl status rag   # 看到 active(running) 即成功
```
之后看日志：`journalctl -u rag -f`

## 8. 防火墙
- 腾讯云控制台「防火墙」已放通 TCP 8000（步骤前置，最重要）。
- 若服务器本身开了 `firewalld`，再执行：
  ```bash
  firewall-cmd --zone=public --add-port=8000/tcp --permanent
  firewall-cmd --reload
  ```
  > 查看是否运行：`systemctl is-active firewalld`。若显示 `inactive`，说明系统层防火墙没开，跳过即可（只看控制台防火墙）。

## 9. 给考官的地址
直接给：`http://你的公网IP:8000`
（http 非 https，演示够用；若要 https 需另购域名 + 证书，本方案为免域名最简版。）

## 10. 安全提醒（演示前建议做）
- 公网暴露后，把 `.env` 里 `auth.api_keys` 的 `change_me` 改成强随机值（或用环境变量 `AUTH_API_KEYS` 覆盖），并更新前端设置面板的 API Key。
- 2核2G 内存紧，不要同时跑 Docker / Ollama 等重负载。

## 11. 更新代码
以后改了代码，服务器上拉取并重启：
```bash
cd /root/information
git pull
source .venv/bin/activate
pip install -r requirements-deploy.txt   # 依赖有变动时
systemctl restart rag
```
