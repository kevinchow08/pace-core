# 基础镜像：官方 Python 3.13 精简版（slim 体积小，只含运行环境）
FROM python:3.13-slim

# 设置容器内工作目录，后续所有命令都在 /app 下执行
WORKDIR /app

# 先只复制 requirements.txt，利用 Docker 层缓存：
# requirements.txt 没变 → pip install 层直接用缓存，不重新装
# requirements.txt 变了 → 才重新执行 pip install
COPY requirements.txt .

# --no-cache-dir：禁止 pip 把下载缓存存进镜像，减小镜像体积
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目代码（放在装依赖之后，代码改动不会触发重新装依赖）
COPY . .

# 容器启动命令
# --host 0.0.0.0：监听所有网络接口，宿主机才能通过端口映射访问到容器
# --port 8000：容器内监听 8000 端口
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
