FROM python:3.13.3-slim-bookworm

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt ./
RUN pip install --no-cache-dir --disable-pip-version-check -r requirements.txt
COPY app.py ./
COPY templates ./templates
COPY static ./static

EXPOSE 5000
CMD ["python", "app.py"]
