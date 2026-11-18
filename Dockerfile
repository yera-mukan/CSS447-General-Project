FROM denoland/deno:alpine

RUN apk add --no-cache \
    tini \
    tesseract-ocr \
    tesseract-ocr-data-eng

WORKDIR /app

COPY deno.json deno.lock* ./
RUN deno install

COPY ./public/ ./public/
COPY ./src/ ./src/
COPY build.json* ./

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/docker-entrypoint.sh \
    && chmod 755 /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["tini", "--", "docker-entrypoint.sh"]
CMD ["deno", "run", "--allow-net", "--allow-read", "--allow-write", "--allow-run", "--allow-env", "--allow-sys", "src/index.ts"]
EXPOSE 8884