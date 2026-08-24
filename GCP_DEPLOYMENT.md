# This branch: hosting on Google Cloud Run

The `gcp-deploy` branch adds a second hosting target for the Clara
competitor-intelligence application: **Google Cloud Run, with continuous
deployment from GitHub Actions**. The application itself is unchanged — this
branch only adds files; nothing in `clara_monitor/` or the existing hosts was
modified.

## What is live

| | |
| --- | --- |
| Service URL | https://clara-monitor-z3uic3jqlq-uc.a.run.app |
| GCP project | `clara-warehouse` (280470997380) |
| Region / service | `us-central1` / `clara-monitor` |
| Bundle bucket | `gs://clara-warehouse-monitor-bundle` |
| Deploys on | every push to `main` or `gcp-deploy` |

Sign-in is required; accounts live in the collection bundle (see below).
Credentials are never committed — ask whoever runs collections.

## How it works

**One application, three hosts.** The local server (`serve.py`), the Vercel
host (`deploy/api/index.py`) and this one all serve the same modules through
the same router. The Cloud Run entrypoint, [deploy/gcp/main.py](deploy/gcp/main.py),
does not reimplement anything: it imports the handler from
`deploy/api/index.py` and serves it with a plain `ThreadingHTTPServer` on the
`PORT` Cloud Run injects. Everything that host was designed around — ephemeral
independent instances, stateless HMAC-signed session cookies, operational
writes to Postgres via `DATABASE_URL`, the read-only bundled snapshot — is
exactly the Cloud Run execution model too.

**The collection bundle arrives by bucket, not by git.**
`data/monitor.sqlite3` holds the scan results *and every account's password
hash*, so it is gitignored and never reaches CI or the container image.
Instead the deploy mounts the bundle bucket read-only at `deploy/data`
(Cloud Storage FUSE, gen2 execution environment). Consequences worth knowing:

- Uploading a fresh snapshot to the bucket **updates the live site without a
  redeploy** — the handler re-copies the bundle whenever its mtime changes.
- If the bucket is empty, the service does not crash-loop: it serves a 503
  setup page naming the missing file, and swaps the real application in on
  the next request once the file appears.

**The pipeline.** [.github/workflows/deploy-gcp.yml](.github/workflows/deploy-gcp.yml)
authenticates with a service-account key, then runs `gcloud run deploy
--source .`, which has Cloud Build build the root [Dockerfile](Dockerfile)
(the image contains only `deploy/`) and rolls the service. The final step
prints the service URL. Runs serialize under a concurrency group, and the
workflow can also be triggered manually from the Actions tab.

## Configuration (already set)

| Where | Name | Holds |
| --- | --- | --- |
| GitHub secret | `GCP_SA_KEY` | key for `github-deployer@clara-warehouse.iam.gserviceaccount.com` |
| GitHub variable | `GCP_PROJECT_ID` | `clara-warehouse` |
| GitHub variable | `GCP_BUNDLE_BUCKET` | `clara-warehouse-monitor-bundle` |
| GitHub variable | `GCP_REGION`, `GCP_SERVICE` | optional overrides (default `us-central1`, `clara-monitor`) |
| GitHub secret | `DATABASE_URL` | **not set yet** — see below |
| GitHub secret | `CLARA_SESSION_SECRET` | optional; pins the session HMAC key across bundle changes |

`DATABASE_URL` is the one that matters operationally: section 9 of the price
addendum requires operational writes (resolutions, requests, audit) to survive
instance recycling, which needs managed Postgres. Until the secret is set, the
site serves fine but says on every page that storage is not durable. Add the
secret and push to fix that.

## Routine operations

Publish a fresh scan (from a machine that has run a collection):

```bash
python sync_deploy.py
gcloud storage cp deploy/data/monitor.sqlite3 deploy/data/intel.json gs://clara-warehouse-monitor-bundle/
```

Deploy a code change: push to `main` or `gcp-deploy`. That is the whole step.

Tail the service logs:

```bash
gcloud run services logs read clara-monitor --project clara-warehouse --region us-central1
```

Roll back: re-run an older green "Deploy to Cloud Run" workflow run, or shift
traffic to a previous revision with `gcloud run services update-traffic`.

Manage accounts: on the local server only (`python serve.py` → `/admin`);
the hosted host is read-only for accounts by design. After changing users,
re-upload the bundle.

## Files this branch adds

- `deploy/gcp/main.py` — Cloud Run entrypoint (serves the existing handler)
- `deploy/gcp/README.md` — one-time GCP/GitHub setup, kept as the record of
  what was provisioned
- `Dockerfile`, `.dockerignore` — the image Cloud Build builds
- `.github/workflows/deploy-gcp.yml` — the deploy pipeline
- `GCP_DEPLOYMENT.md` — this file
