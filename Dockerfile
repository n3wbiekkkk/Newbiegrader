FROM python:3.11-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends gcc g++ \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY grader.py server.py judge_runner.py worker.py container_entrypoint.py ./
COPY problems ./problems
COPY static ./static

# Sandbox needs this: the judge child drops to `nobody` (see build_limits in
# grader.py), so tests must not be world-readable — otherwise submissions can
# `open('/app/problems/...')` and cheat. Backend stays root ONLY to allow the
# setuid drop; the child itself never runs as root and gets RLIMITs + (if the
# host allows) its own network namespace. Keep .env OUT of the image: secrets
# come from host env vars, never from files.
RUN chmod -R go-rwx ./problems

EXPOSE 8000
CMD ["python", "container_entrypoint.py"]
