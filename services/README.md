# Services

Four FastAPI services, one directory each, every one with its own `Dockerfile` and `tests/` (how to run the tests and
linters is described in [Development](../docs/development.md)). The table of services and their dependencies is in
the [root README](../README.md#architecture).

## Endpoints

Each service exposes a `GET /health` endpoint and a `GET /metrics` endpoint with Prometheus request metrics (request
count and duration by handler, method and status; probe and scrape traffic is not counted). The three data services
additionally expose `GET /livez` (a database-independent liveness check) and `/chaos/*` endpoints (`break`,
`break-permanent`, `fix`, `status`) used for chaos-engineering exercises (see
[Probes and chaos drills](../k8s/README.md#probes-and-chaos-drills)).

## Running locally

Requires Docker with the Compose plugin (`docker compose version`).

1. Copy the environment template and fill in your own values:
   ```
   cp .env.example .env
   ```
2. Start the stack:
   ```
   docker compose up --build
   ```
3. Open the status dashboard at http://localhost:8000 once all containers report healthy.

Each service is also reachable directly from the host for debugging: `user-service` on http://localhost:8001,
`product-service` on http://localhost:8002, and `order-service` on http://localhost:8003 (e.g. append `/docs`
to any of these for its interactive API docs). Internally, services talk to each other over the Compose network
by service name.

Stop the stack with `docker compose down` (add `-v` to also remove the Postgres volumes and start from a clean database).
