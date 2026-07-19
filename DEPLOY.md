# 服务器部署指南（腾讯云轻量应用服务器 · Ubuntu 22.04）

目标：把后端 + 前端都跑在服务器上，考官访问 `http://公网IP:8000` 一个地址就能聊天（同源 http，浏览器不拦截）。GitHub 只保留代码仓库。

> 前置：已在腾讯云买好轻量应用服务器（2核2G 即可），镜像选 **Ubuntu 22.04**，并在控制台「防火墙」放通 **TCP 8000** 端口。

## 1. 登录服务器
控制台点「登录」用 OrcaTerm，或本地终端：`ssh root@你的公网IP`（密码在控制台重置过）。

## 2. 装基础工具
```bash
sudo apt update
sudo apt install -y git python3-venv python3-pip
```

## 3. 拉代码
```bash
git clone https://github.com/xchhhh/information.git
cd information
```

## 4. 建虚拟环境并装依赖
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-deploy.txt
```
> requirements-deploy.txt 已改为云端友好版：milvus-lite（嵌入式，免 Docker）+ 云端 doubao embedding，并去掉了 Ollama / 本地重排模型依赖。

## 5. 配置密钥
```bash
cp .env.example .env
nano .env
```
在 `.env` 里填两项真实值，并**取消注释**下面两行（切换到云端 embedding + 嵌入式 Milvus）：
```env
LLM_API_KEY=sk-你的deepseek密钥
ARK_API_KEY=你的火山方舟密钥

EMBEDDING_PROVIDER=doubao
MILVUS_MODE=lite
```
> 重排模型在 2核2G 上会自动加载失败并跳过（代码已容错），不影响问答，只是少了重排、答案质量略降。

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

## 7. 后台常驻（推荐 systemd）
新建服务文件：`sudo nano /etc/systemd/system/rag.service`
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
> 若代码在 `/home/ubuntu/information`，请把上面两处路径改成对应位置。

启用并启动：
```bash
sudo systemctl daemon-reload
sudo systemctl enable rag
sudo systemctl start rag
sudo systemctl status rag   # 看到 active(running) 即成功
```
之后看日志：`sudo journalctl -u rag -f`

## 8. 防火墙
- 腾讯云控制台「防火墙」已放通 TCP 8000（步骤前置）。
- 若服务器本身开了 `ufw`，再执行：`sudo ufw allow 8000`。

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
sudo systemctl restart rag
```
