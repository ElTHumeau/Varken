FROM python:3.9.1-alpine

ENV DEBUG="True" \
    DATA_FOLDER="/config" \
    VERSION="0.0.0" \
    BRANCH="edge" \
    BUILD_DATE="1/1/1970"

LABEL maintainer="ElTHumeau" \
  org.opencontainers.image.created=$BUILD_DATE \
  org.opencontainers.image.url="https://github.com/ElTHumeau/Varken" \
  org.opencontainers.image.source="https://github.com/ElTHumeau/Varken" \
  org.opencontainers.image.version=$VERSION \
  org.opencontainers.image.vendor="ElTHumeau" \
  org.opencontainers.image.title="varken" \
  org.opencontainers.image.description="Varken with API v3 support - aggregate data from Plex ecosystem into InfluxDB using Grafana" \
  org.opencontainers.image.licenses="MIT"

WORKDIR /app

COPY /requirements.txt /Varken.py /app/

COPY /varken /app/varken

COPY /data /app/data

COPY /utilities /app/data/utilities

RUN \
  apk add --no-cache tzdata gcc musl-dev python3-dev \
  && pip install --upgrade pip \
  && pip install --no-cache-dir -r /app/requirements.txt \
  && apk del gcc musl-dev python3-dev \
  && sed -i "s/0.0.0/${VERSION}/;s/develop/${BRANCH}/;s/1\/1\/1970/${BUILD_DATE//\//\\/}/" varken/__init__.py

CMD cp /app/data/varken.example.ini /config/varken.example.ini && python3 /app/Varken.py
