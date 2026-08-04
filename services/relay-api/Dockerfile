FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
ENV RELAY_DATA=/data
ENV RELAY_CONFIG_REPO=/config-repo
ENV SKILLS_ROOT=/data/skills-repo
EXPOSE 8740
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8740"]
