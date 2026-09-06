# Hosting on Google Cloud Run

The hosted application is the same one Vercel serves: `deploy/gcp/main.py`
loads the handler from `deploy/api/index.py` and serves it directly, so every
route, the stateless sessions, the read-only accounts rule and the durability
banner are unchanged. Cloud Run fits that design for the same reasons the
serverless host did — ephemeral, independent instances with Postgres
(`DATABASE_URL`) as the only durable store.

Continuous deployment is `.github/workflows/deploy-gcp.yml`: **every push to
`main` or `gcp-deploy` rebuilds the image with Cloud Build and rolls the Cloud
Run service**. For what is currently live and how to operate it day to day,
see [GCP_DEPLOYMENT.md](../../GCP_DEPLOYMENT.md) at the repository root.

What follows is the one-time setup the workflow needs. **This was completed on
2026-08-24 for project `clara-warehouse`** (bucket
`clara-warehouse-monitor-bundle`, deployer SA `github-deployer@`, GitHub
secret/variables set) — it is kept both as the record of what was provisioned
and as the recipe for standing the service up in another project.

## 1. Project and APIs

```bash
gcloud config set project YOUR_PROJECT_ID
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
    artifactregistry.googleapis.com storage.googleapis.com
```

## 2. The bundle bucket

`data/monitor.sqlite3` carries password hashes, so it is gitignored and never
reaches CI. The service reads it (plus `intel.json`) from a Cloud Storage
bucket mounted read-only at `deploy/data`.

```bash
gcloud storage buckets create gs://YOUR_BUNDLE_BUCKET --location=us-central1 \
    --uniform-bucket-level-access
```

Upload from a machine that has run a collection:

```bash
python sync_deploy.py
gcloud storage cp deploy/data/monitor.sqlite3 deploy/data/intel.json gs://YOUR_BUNDLE_BUCKET/
```

Because the handler re-copies the bundle whenever its mtime changes, uploading
a fresh snapshot **refreshes the live site without a redeploy** — that upload
is the whole "publish a new scan" step.

The Cloud Run runtime service account (by default
`PROJECT_NUMBER-compute@developer.gserviceaccount.com`) must be able to read
the bucket:

```bash
gcloud storage buckets add-iam-policy-binding gs://YOUR_BUNDLE_BUCKET \
    --member serviceAccount:PROJECT_NUMBER-compute@developer.gserviceaccount.com \
    --role roles/storage.objectViewer
```

## 3. The deploy service account

```bash
gcloud iam service-accounts create github-deployer \
    --display-name "GitHub Actions deployer"

SA=github-deployer@YOUR_PROJECT_ID.iam.gserviceaccount.com
for ROLE in roles/run.admin roles/cloudbuild.builds.editor \
            roles/artifactregistry.admin roles/storage.admin \
            roles/iam.serviceAccountUser roles/serviceusage.serviceUsageConsumer; do
  gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
      --member serviceAccount:$SA --role $ROLE
done

gcloud iam service-accounts keys create key.json --iam-account $SA
```

(`storage.admin` and `artifactregistry.admin` are what `gcloud run deploy
--source` needs to stage sources and store the built image; narrow them later
if you prefer. If your organisation forbids SA keys, switch the `auth` step in
the workflow to Workload Identity Federation — everything else stays the same.)

## 4. GitHub configuration

In the repository settings:

| Kind | Name | Value |
| --- | --- | --- |
| Secret | `GCP_SA_KEY` | contents of `key.json` (then delete the local file) |
| Variable | `GCP_PROJECT_ID` | your project id |
| Variable | `GCP_REGION` | optional, default `us-central1` |
| Variable | `GCP_SERVICE` | optional, default `clara-monitor` |
| Variable | `GCP_BUNDLE_BUCKET` | the bucket from step 2 (no `gs://`) |
| Secret | `DATABASE_URL` | managed Postgres connection string (section 9) |
| Secret | `CLARA_SESSION_SECRET` | optional; pins the session HMAC key |

Without `DATABASE_URL` the site still serves, and says on every page that
operational storage is not durable — exactly as on any other host. Without
`GCP_BUNDLE_BUCKET` (or before the first upload) the service answers every
request with a setup page naming the missing file rather than crash-looping;
it picks the bundle up on the next request once it appears.

## 5. Deploy

Push to `main` or `gcp-deploy` (or run the workflow manually from the Actions
tab). The final workflow step prints the service URL.

## Local smoke test

```bash
python sync_deploy.py                       # builds deploy/data/monitor.sqlite3
PORT=8080 python deploy/gcp/main.py         # http://127.0.0.1:8080/login
```

or the container:

```bash
docker build -t clara-hosted .
docker run --rm -p 8080:8080 clara-hosted
```
