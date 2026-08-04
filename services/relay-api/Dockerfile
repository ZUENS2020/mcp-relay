FROM python:3.12-slim
WORKDIR /app
ENV PIP_DEFAULT_TIMEOUT=300
COPY requirements.txt requirements-mcp.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && (pip install --no-cache-dir -r requirements-mcp.txt \
        || pip install --no-cache-dir -r requirements-mcp.txt -i https://pypi.tuna.tsinghua.edu.cn/simple \
        || echo "optional mcp install skipped")
COPY app ./app
ENV RELAY_DATA=/data
ENV RELAY_CONFIG_REPO=/config-repo
ENV SKILLS_ROOT=/data/skills-repo
EXPOSE 8740
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8740"]
