import os                      # 处理文件路径
import yaml                     # 读取 yaml 格式的配置
from dotenv import load_dotenv # 把 .env 里的密钥读进环境变量

load_dotenv()                  # 执行加载：LLM_API_KEY / ARK_API_KEY 等进入 os.environ

# 项目根目录：本文件位于 src/common/config.py，向上两级（common -> src -> 根）即项目根
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 读取 config/settings.yaml，解析成 Python 字典，全局可用
with open(os.path.join(BASE_DIR, "config", "settings.yaml"), "r", encoding="utf-8") as f:
    settings = yaml.safe_load(f)   # settings["embedding"] / settings["milvus"] ... 这样取用

# 环境变量覆盖：部署到服务器时，在 .env 里设 EMBEDDING_PROVIDER=doubao / MILVUS_MODE=lite，
# 即可切换到「云端 embedding + 嵌入式 Milvus」，本地开发不设则保持 settings.yaml 默认值
if os.getenv("EMBEDDING_PROVIDER"):
    settings["embedding"]["provider"] = os.getenv("EMBEDDING_PROVIDER")
if os.getenv("MILVUS_MODE"):
    settings["milvus"]["mode"] = os.getenv("MILVUS_MODE")
