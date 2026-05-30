FROM python:3.11-slim
WORKDIR /app
RUN mkdir -p logs
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 9700
CMD ["gunicorn", "-c", "gunicorn.conf.py", "server:app"]
