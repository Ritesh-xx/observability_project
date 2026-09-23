FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN opentelemetry-bootstrap -a install
COPY app.py .
EXPOSE 8000
CMD ["opentelemetry-instrument", "python", "app.py"]
