# km1 — DevOps Learning Project

[![CI](https://github.com/ryslaw/km1/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/ryslaw/km1/actions/workflows/ci.yml)

A small e-commerce-style microservices system used as a hands-on playground for building DevOps skills: containerization, CI/CD, configuration management, infrastructure as code, Kubernetes, and observability — layered incrementally on top of an existing application.

## Architecture

Four Python services, each independently containerized:

| Service | Description | Depends on |
|---|---|---|
| `user-service` | User registration and lookup (Postgres-backed) | — |
| `product-service` | Product catalog with stock and reservation | — |
| `order-service` | Places orders: validates the user, reserves stock, computes total | `user-service`, `product-service` |
| `status-page` | Dashboard polling `/health` on the three services above | all of the above |

Each service exposes a `GET /health` endpoint, and the three data services additionally expose `/chaos/*` endpoints (`break`, `break-permanent`, `fix`, `status`) used later for chaos-engineering exercises.

## Tech stack

- **Language/framework:** Python 3.12, FastAPI, SQLAlchemy
- **Database:** PostgreSQL
- **Containerization:** Docker, Docker Compose
- **CI:** GitHub Actions
- **Configuration management / IaC:** Ansible, Terraform
- **Orchestration:** Kubernetes (k3d, Traefik Ingress)
- **Planned additions (see [Roadmap](#roadmap)):** Prometheus/Grafana

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

## Running locally with Ansible

As an alternative to the manual steps above, a minimal Ansible playbook automates the same two steps (create
`.env` if missing, bring up the Compose stack). This targets your own machine only (`connection: local`) — no remote hosts or SSH involved.

1. Install Ansible (not part of `requirements-dev.txt`; install separately):
   ```
   pip install ansible
   ```
2. Install the required collection from Ansible Galaxy:
   ```
   ansible-galaxy collection install -r ansible/requirements.yml
   ```
3. Run the playbook from the repo root:
   ```
   ansible-playbook ansible/playbook.yml
   ```
4. Open http://localhost:8000 once all containers report healthy, same as above.

Running the playbook again is safe — it won't overwrite an existing `.env` and won't disrupt already-running containers.

## Running locally with Terraform

A third option: the `terraform/` directory describes the same stack declaratively (network, Postgres volumes, images
built from each service's `Dockerfile`, and containers) using the `kreuzwerker/docker` provider against your local
Docker daemon. State is kept locally in `terraform/terraform.tfstate` (gitignored) — no remote backend or cloud provider.

1. Install Terraform (not part of `requirements-dev.txt`; install separately, see the
   [Terraform install docs](https://developer.hashicorp.com/terraform/install)).
2. Copy the variables template and fill in your own Postgres credentials:
   ```
   cp terraform/terraform.tfvars.example terraform/terraform.tfvars
   ```
3. From the `terraform/` directory, download the provider and bring up the stack:
   ```
   cd terraform
   terraform init
   terraform apply
   ```
4. Open http://localhost:8000 — services are published on the same host ports as above (8001–8003).

Running `terraform apply` again with no changes reports `No changes`. Tear everything down with `terraform destroy` —
this removes the containers, images, network, and the Postgres volumes (database data is lost).

Things to keep in mind:

- **Use one method at a time.** Both stacks publish the same host ports and name the Postgres containers identically, so
  run `docker compose down` before `terraform apply`, and `terraform destroy` before switching back. The two methods use
  separate volumes, so they don't share database data.
- **Images are not rebuilt when source code changes.** Terraform only rebuilds an image when its own configuration
  changes. After editing a service, force a rebuild explicitly, e.g.
  `terraform apply -replace='docker_image.service["user-service"]'`.
- **No healthchecks or start-up ordering between services.** `Apply complete!` means the containers were created, not
  that the services are ready — check http://localhost:8000 (the DB-backed services wait for their own database on start-up).
- **`terraform.tfstate` contains the Postgres password in plain text** (`sensitive` only hides it in CLI output). Keep the
  state file local — don't commit it or copy it to another machine.

## Running locally with Kubernetes (k3d)

A fourth option: the `k8s/` directory holds plain Kubernetes manifests for the same stack, deployed with `kubectl apply`
into a dedicated `km1` namespace on a single-node [k3d](https://k3d.io) cluster running inside Docker. k3d bundles
Traefik, which serves as the Ingress controller, and the `local-path` storage provisioner for the Postgres volumes.
Images are built locally and imported straight into the cluster — no container registry, no Helm.

1. Install k3d and kubectl (not part of `requirements-dev.txt`; see the
   [k3d install dev](https://k3d.io/#installation) and the [kubectl install docs](https://kubernetes.io/docs/tasks/tools/)).
   Keep kubectl within one minor version of the cluster's Kubernetes version (`kubectl version`).
2. Create the cluster, mapping host port 8080 to the cluster's load balancer (ports 8000—8003 are left free for the
   other run methods):
   ```
   k3d cluster create km1 -p "8080:80@loadbalancer"
   ```
3. Build the service images and import them into the cluster:
   ```
   docker build -t km1/user-service:local services/user-service
   docker build -t km1/product-service:local services/product-service
   docker build -t km1/order-service:local services/order-service
   docker build -t km1/status-page:local services/status-page
   k3d image import km1/user-service:local km1/product-service:local km1/order-service:local km1/status-page:local -c km1
   ```
4. Create the namespace, then the Postgres credentials Secret from your `.env` (see [Running locally](#running-locally)
   for creating it from `.env.example`):
   ```
   kubectl apply -f k8s/00-namespace.yaml
   kubectl create secret generic postgres-credentials -n km1 --from-env-file=.env --dry-run=client -o yaml | kubectl apply -f -
   ```
5. Apply all manifests and wait until the services are available:
   ```
   kubectl apply -R -f k8s/
   kubectl wait --for=condition=Available deployment --all -n km1 --timeout=300s
   ```
6. Open http://localhost:8080 — a single Ingress routes by path, without rewriting:

   | Path | Service |
   |---|---|
   | `/` | `status-page` |
   | `/users` | `user-service` (API docs at `/users/docs`) |
   | `/products` | `product-service` (API docs at `/products/docs`) |
   | `/orders` | `order-service` (API docs at `/orders/docs`) |

Applying the manifests again with no changes is a no-op: `kubectl diff -R -f k8s/` prints nothing. `kubectl apply`
still reports the three Postgres StatefulSets as `configured` — a cosmetic quirk of client-side apply, because the API
server fills in defaults and `status` inside their `volumeClaimTemplates`; nothing is actually changed.

`kubectl delete namespace km1` tears down everything, **including the Postgres volumes (database data is lost) and the
Secret** — re-create the Secret (step 4) before the next apply. `k3d cluster stop km1` / `k3d cluster start km1` pause
and resume the cluster with its data intact; `k3d cluster delete km1` removes the whole cluster.

Things to keep in mind:

- **Rebuilt images are not picked up automatically.** After changing a service, rebuild and re-import its image
  (step 3), then restart it, e.g. `kubectl rollout restart deployment/user-service -n km1`. The `:local` tag doesn't
  change, so `kubectl apply` reports `unchanged` and running pods keep the old image.
- **Apply the directory recursively.** Without `-R`, `kubectl apply -f k8s/` skips subdirectories such as `k8s/ingress/`.
  Files are applied in alphabetical order, which is why the namespace manifest is named `00-namespace.yaml`.
- **Behind the Ingress, only the API and docs move under the service prefix.** Chaos endpoints are served under it too
  (e.g. `POST /users/chaos/break`), but `/health` is not prefixed, so http://localhost:8080/health is answered by
  `status-page`.
- **`/health` is the only endpoint not served under the service prefix.** API docs and chaos endpoints move under it
  (e.g. `/users/docs`, `POST /users/chaos/break`), but `/health` does not, so http://localhost:8080/health is answered
  by `status-page`.
- **Avoid `@`, `:` and `/` in `POSTGRES_PASSWORD`**, as with Compose: `DATABASE_URL` is assembled from the Secret without
  URL-encoding.

## Development

Dev tooling (linting and testing) is shared across all four services via a single root-level `requirements-dev.txt`, rather than duplicated per service:

```
pip install -r requirements-dev.txt
```

### Linting & formatting

Linting and formatting are handled by [ruff](https://docs.astral.sh/ruff/), configured once at the repo root (`pyproject.toml`) for all services:

```
ruff check .
ruff format --check .
```

### Testing

Each service has its own `tests/` directory. Run a service's tests from within that service's directory:

```
cd services/user-service && pytest
```

## Roadmap

This project is developed milestone by milestone, each tracked as a GitHub Milestone with issues:

0. Git/GitHub project foundation
1. Docker Compose (all services running together locally)
2. Code quality & automated testing baseline
3. Continuous Integration (GitHub Actions)
4. Configuration management with Ansible
5. Infrastructure as Code with Terraform (local)
6. Kubernetes deployment
7. Observability (metrics & dashboards)
8. GitOps (stretch goal)

## Contributing

This is a solo learning project with a lightweight PR review process. See `.github/PULL_REQUEST_TEMPLATE.md` and the issue templates under `.github/ISSUE_TEMPLATE/`. Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/).
