FROM python:3.13.3-slim-bookworm

WORKDIR /e2e
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt ./
RUN pip install --no-cache-dir --disable-pip-version-check -r requirements.txt
COPY run.py ./

ENTRYPOINT ["python", "run.py"]
