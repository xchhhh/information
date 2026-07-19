# 部署与运维：腾讯云 + systemd + Gitee 镜像

本项目部署在腾讯云服务器，以 systemd 常驻服务方式运行，FastAPI 同源托管前后端，对外提供 8000 端口。

## 一、systemd 常驻服务

把应用注册为系统服务（rag.service），好处：

- 开机自启，服务器重启后无需人工拉起；
- 进程异常退出时 systemd 自动重启，保障可用性；
- 用 systemctl start / stop / restart / status 统一管控。

日常运维命令示例：systemctl stop rag（停服释放 Milvus 文件锁，供评估脚本使用）、systemctl start rag（恢复服务）。

## 二、同源托管前后端

FastAPI 进程同时承担三件事：

- 提供 REST API（/chat、/health、/admin/*）；
- 根路径 / 返回聊天页 index.html；
- /admin 返回后台管理页 admin.html。

无需额外的 Web 服务器或对象存储，一个进程搞定前后端，考官访问 http://公网IP:8000 即可直接使用。这也是"部署简单、故障面小"的体现。

## 三、Gitee 镜像解决国内拉取问题

开发机在国内，直连 GitHub 经常连接超时（curl 28 / fatal: expected flush），导致服务器 git pull 失败、更新卡住。解决方案：

- 代码同时推送到 GitHub（主仓库）与 Gitee（国内镜像）；
- 服务器改为从 Gitee 拉取：git fetch Gitee main:bench_tmp 然后 git reset --hard bench_tmp，再删掉临时分支；
- 这样更新稳定，不再受 GitHub 直连超时影响。

Gitee 镜像地址形如 https://gitee.com/xu-chenghe/information.git，推送时用带令牌的 URL 直推即可。

## 四、端口与进程

- 服务监听 8000 端口；
- 若端口被旧进程占用，可用 fuser -k 8000/tcp 释放后再启动；
- 上线前确保防火墙 / 安全组放通 8000 入站，考官才能从外网访问。

## 五、配置与密钥管理

- 所有超参集中在 config/settings.yaml；
- 密钥（DeepSeek Key、火山方舟 Key、API Key）写在 .env，由 python-dotenv 注入环境变量，不进版本库（.env 已被 gitignore）；
- 评估脚本需要 LLM_API_KEY 时，从 .env 读取后 export 到环境变量再运行。

## 六、依赖与环境一致性

- 服务器用独立虚拟环境（.venv），依赖与本地一致；
- 曾遇到 FastAPI 的 UploadFile 因缺 python-multipart 而启动崩溃，已在依赖清单补上并在仓库固化，避免重复踩坑。
