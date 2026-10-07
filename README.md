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

Each service exposes a `GET /health` endpoint and a `GET /metrics` endpoint with Prometheus request metrics (request
count and duration by handler, method and status; probe and scrape traffic is not counted). The three data services
additionally expose `GET /livez` (a database-independent liveness check) and `/chaos/*` endpoints (`break`,
`break-permanent`, `fix`, `status`) used for chaos-engineering exercises (see
[Probes and chaos drills](#probes-and-chaos-drills)).

## Tech stack

- **Language/framework:** Python 3.12, FastAPI, SQLAlchemy
- **Database:** PostgreSQL
- **Containerization:** Docker, Docker Compose
- **CI:** GitHub Actions
- **Configuration management / IaC:** Ansible, Terraform
- **Orchestration:** Kubernetes (k3d, Traefik Ingress)
- **Monitoring:** Prometheus, Grafana (kube-prometheus-stack, Helm)

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
Images are built locally and imported straight into the cluster — no container registry. The application itself is
deployed without Helm; Helm is used only for the optional monitoring stack (see [Monitoring](#monitoring)).

1. Install k3d and kubectl (not part of `requirements-dev.txt`; see the
   [k3d install docs](https://k3d.io/#installation) and the [kubectl install docs](https://kubernetes.io/docs/tasks/tools/)).
   Keep kubectl within one minor version of the cluster's Kubernetes version (`kubectl version`).
2. Create the cluster, mapping host port 8080 to the cluster's load balancer (ports 8000–8003 are left free for the
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

### Redeploying with the script

After a code change, `scripts/deploy-k3d.sh` replaces steps 3 and 5: it builds the service images, imports them into
the cluster, applies `k8s/` recursively, restarts the Deployments and waits for their rollouts to finish. The restart is
what makes the pods pick up the new code: the manifests use the `:local` tag with the default
`imagePullPolicy: IfNotPresent`, so importing a rebuilt image under the same tag leaves the running pods unchanged.

With no arguments it deploys all four services. Name services to rebuild and restart only those; an unknown name stops
the script with a usage message before anything is built. It runs from any directory, and every `kubectl` call targets
the `k3d-<cluster>` context explicitly, whichever context is current. Set `K3D_CLUSTER` to target a cluster other
than `km1`:

```
scripts/deploy-k3d.sh
scripts/deploy-k3d.sh user-service status-page
K3D_CLUSTER=km1-test scripts/deploy-k3d.sh
scripts/deploy-k3d.sh --help
```

Before building anything, the script checks that `docker`, `k3d` and `kubectl` are installed, that the cluster exists
and that the `postgres-credentials` Secret is present in `km1`. It does not create the cluster, the namespace or the
Secret, so on a fresh cluster run steps 2 and 4 by hand first. Any failing command stops the script with a non-zero
exit code.

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
- **`/health`, `/livez` and `/metrics` are the only endpoints not served under the service prefix.** API docs and chaos
  endpoints move under it (e.g. `/users/docs`, `POST /users/chaos/break`), but these three do not, so
  http://localhost:8080/health and http://localhost:8080/metrics are answered by `status-page` (the catch-all `/` path),
  and `/livez` and `/metrics` of the data services are not reachable through the Ingress at all — they are meant for the
  kubelet and for Prometheus inside the cluster.
- **Avoid `@`, `:` and `/` in `POSTGRES_PASSWORD`**, as with Compose: `DATABASE_URL` is assembled from the Secret without
  URL-encoding.

### Probes and chaos drills

Each data service has three probes, and each answers a different question:

| Probe | Check | What it answers |
|---|---|---|
| `startupProbe` | TCP on the app port, every 5 s, up to 18 times | Has the app started? The port only opens after `wait_for_db()`, which can take up to ~60 s; the other probes wait until this one succeeds. |
| `readinessProbe` | `GET /health`, timeout 5 s | Should the pod receive traffic? Fails while the database is unreachable or either chaos flag is set. |
| `livenessProbe` | `GET /livez`, timeout 1 s | Should the container be restarted? Never touches the database; fails only while the in-memory chaos flag is set. |

`/livez` is an `async` handler that never touches the database, and the chaos middleware reads its persistent flag in
a worker thread rather than on the event loop, so `/livez` answers immediately even while the database is unreachable
and the 1 s timeout (the Kubernetes default) is enough. `status-page` has no database and no chaos flags, so its
`/health` serves both readiness and liveness.

The four scenarios below were verified on the k3d cluster:

| Scenario | `/health` | `/livez` | Observed behaviour |
|---|---|---|---|
| Healthy | 200 | 200 | `1/1`, no restarts |
| Database down (`kubectl scale statefulset user-service-db -n km1 --replicas=0`) | 503 | 200 | `0/1`, no restarts; endpoints that need the database return 503 JSON, the API docs keep working; back to `1/1` once the database is scaled back to 1 |
| `POST /users/chaos/break` (in-memory flag) | 503 | 503 | Liveness fails 3 times, the container is restarted ~20–30 s later; the restart clears the flag and the pod is back to `1/1` without `/chaos/fix` |
| `POST /users/chaos/break-permanent` (flag in the database) | 503 | 200 | `0/1` for as long as the flag is set, no restart loop; back to `1/1` after `POST /users/chaos/fix` |

To run the drills, reach the service through a port-forward rather than the Ingress, and watch the pods in a second
terminal:

```
kubectl port-forward -n km1 svc/user-service 8081:8000
curl -i -X POST http://localhost:8081/users/chaos/break-permanent
kubectl get pods -n km1 -l app=user-service -w
curl -i -X POST http://localhost:8081/users/chaos/fix
```

Things to keep in mind:

- **A NotReady pod cannot be fixed through the Ingress.** It is removed from the Service endpoints, so
  `POST http://localhost:8080/users/chaos/fix` gets `503 no available server` from Traefik. Send `/chaos/fix` through
  the port-forward instead: an open port-forward stays attached to its pod regardless of readiness.
- **A port-forward dies with its pod.** After `kubectl rollout restart` the pod is replaced, so start the port-forward
  again. A container restart by the liveness probe keeps the pod, and the port-forward survives it.
- **During a database outage every request still tries the database.** The chaos middleware cannot read the
  persistent flag, logs `chaos flag unreadable, database unavailable` and lets the request through (fail open), so
  endpoints that need the database answer 503 themselves and the rest keep working. `/health` therefore opens two
  connections per probe, which is why its readiness timeout is 5 s.

### Monitoring

Prometheus and Grafana run in a separate `monitoring` namespace, installed with [Helm](https://helm.sh) from the
[kube-prometheus-stack](https://github.com/prometheus-community/helm-charts/tree/main/charts/kube-prometheus-stack)
chart. The chart version is pinned, and every setting that differs from the chart defaults lives in
`helm/kube-prometheus-stack/values.yaml`: Alertmanager is disabled, and so are the scrape jobs for the controller
manager, scheduler, etcd and kube-proxy, which k3s runs inside its own process rather than as pods with reachable
metrics endpoints, so they would only show up as targets that are always down. The stack needs roughly 1.5–2 GB of RAM.

1. Install Helm (verified with Helm 4.3.0, installed with `sudo snap install helm --classic`; see the
   [Helm install docs](https://helm.sh/docs/intro/install/) for other methods) and add the chart repository:
   ```
   helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
   helm repo update
   ```
2. Create the namespace and the Grafana admin Secret. The password is read into a variable without echoing it, so it
   ends up neither on screen nor in the shell history:
   ```
   kubectl create namespace monitoring
   read -rsp "Grafana admin password: " GRAFANA_ADMIN_PASSWORD; echo
   kubectl create secret generic grafana-admin -n monitoring \
     --from-literal=admin-user=admin \
     --from-literal=admin-password="$GRAFANA_ADMIN_PASSWORD"
   unset GRAFANA_ADMIN_PASSWORD
   ```
3. Install the chart (the same command upgrades an existing release):
   ```
   helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
     --namespace monitoring --create-namespace \
     --version 91.9.0 \
     --values helm/kube-prometheus-stack/values.yaml \
     --wait --timeout 10m
   ```
4. Open the UIs through port-forwards (add `--address 0.0.0.0` to reach them from another machine on the network):
   ```
   kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090
   kubectl port-forward -n monitoring svc/kube-prometheus-stack-grafana 3000:80
   ```
   - Prometheus at http://localhost:9090 — all targets under *Status → Targets* should be `UP`.
   - Grafana at http://localhost:3000 — log in as `admin` with the password from step 2. The bundled dashboards include
     *Kubernetes / Compute Resources / Namespace (Pods)*; select the `km1` namespace to see CPU and memory per pod.

Running the same `helm upgrade --install` command again with no changes is a no-op: Helm records a new revision
(`helm history kube-prometheus-stack -n monitoring`), but the rendered manifests of the last two revisions are
identical (`helm get manifest ... --revision N`) and no pod is restarted.

To remove the stack:

```
helm uninstall kube-prometheus-stack -n monitoring
kubectl delete namespace monitoring
```

Two things are left behind on purpose and can be removed by hand for a fully clean cluster:

```
kubectl delete service kube-prometheus-stack-kubelet -n kube-system
kubectl get crd -o name | grep monitoring.coreos.com | xargs kubectl delete
```

Things to keep in mind:

- **Helm never deletes CRDs.** The ten `monitoring.coreos.com` CRDs (`ServiceMonitor`, `Prometheus`, …) stay after
  `helm uninstall`, because deleting a CRD deletes every object of that type in the whole cluster. A later install
  reuses them.
- **The operator, not Helm, creates the `kube-prometheus-stack-kubelet` Service** in `kube-system`, so it scrapes the
  kubelets. Helm does not know about it, and `helm uninstall` leaves it behind.
- **The values file lives outside `k8s/`.** `kubectl apply -R -f k8s/` would try to apply it as a manifest and fail,
  since it has no `apiVersion` or `kind`.
- **Helm keeps its state as Secrets** in the release namespace (`sh.helm.release.v1.<release>.v<revision>`), one per
  revision; deleting the namespace deletes the release history too.

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

Shell scripts are linted with [ShellCheck](https://www.shellcheck.net/) (`sudo apt install shellcheck` locally); CI runs
it on every tracked `*.sh` file:

```
git ls-files '*.sh' | xargs -r shellcheck
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
