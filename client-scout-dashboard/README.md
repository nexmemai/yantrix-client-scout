# Dashboard/API connectivity architecture

The Dockerized dashboard is a React SPA served by Nginx on port `3000`.
Browser API calls must stay same-origin:

```text
Browser -> http://<vm-ip>:3000/api/v1/...
Nginx  -> http://api:8000/api/v1/... on the Docker network
```

This keeps the FastAPI service private and avoids CORS or browser access to
`localhost:8000`, `127.0.0.1:8000`, or the VM API debug port.

Production builds should leave `VITE_API_BASE_URL` empty. The frontend will use
relative `/api/v1/...` paths through the Nginx reverse proxy. `VITE_API_BASE_URL`
is only for local Vite development when the frontend dev server is run outside
Docker.

## Running new scout jobs from the dashboard

The Leads page includes a Run Scout panel. Enter a niche, city, and max business
count, then click **Run Scout** to start the existing discovery, audit, score,
and pitch pipeline through `POST /api/v1/run-scout`.

The dashboard stores the returned `job_id` and polls
`/api/v1/jobs/{job_id}` through the same-origin Nginx `/api` proxy. The status
pill shows when the job is running, completed, or failed. When the job completes,
the leads table refreshes automatically so newly discovered leads appear without
manual reload.
