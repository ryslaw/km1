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
- **Planned additions (see [Roadmap](#roadmap)):** Kubernetes, Prometheus/Grafana 

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
