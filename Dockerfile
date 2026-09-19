FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r backend/requirements.txt
ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn","backend.api:app","--host","0.0.0.0","--port","8000"]