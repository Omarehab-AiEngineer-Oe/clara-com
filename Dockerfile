# Container image for the hosted Clara application on Google Cloud Run.
#
# Only `deploy/` goes in: it is the self-contained bundle `sync_deploy.py`
# derives (the same one Vercel serves), and the Cloud Run entrypoint in
# deploy/gcp/main.py serves the same handler as deploy/api/index.py.
#
# The collection snapshot (deploy/data/monitor.sqlite3) is gitignored — it
# holds password hashes — so a CI-built image does not contain it. The deploy
# workflow mounts a Cloud Storage bucket at /app/deploy/data instead; an image
# built on a machine that has the snapshot locally will bake it in, which is
# fine for a quick manual test but the bucket mount hides it in production.

FROM python:3.12-slim

WORKDIR /app

COPY deploy/requirements.txt deploy/requirements.txt
RUN pip install --no-cache-dir -r deploy/requirements.txt

COPY deploy/ deploy/

ENV PYTHONUNBUFFERED=1
EXPOSE 8080

CMD ["python", "deploy/gcp/main.py"]
