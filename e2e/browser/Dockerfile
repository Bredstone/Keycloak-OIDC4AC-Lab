FROM mcr.microsoft.com/playwright/python:v1.60.0-noble

WORKDIR /browser-e2e
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt ./
RUN pip install --no-cache-dir --disable-pip-version-check -r requirements.txt
COPY run.py ./

ENTRYPOINT ["python", "run.py"]
