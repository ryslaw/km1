# km1 — DevOps Learning Project

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
- **Planned additions (see [Roadmap](#roadmap)):** CI via GitHub Actions, Ansible, Terraform, Kubernetes, Prometheus/Grafana

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
