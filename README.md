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
- **GitOps:** Argo CD (Helm)

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

A fourth option: the `k8s/` directory holds plain Kubernetes manifests for the same stack, which Argo CD applies from `main`
(see [GitOps with Argo CD](#gitops-with-argo-cd)) into a dedicated `km1` namespace on a single-node [k3d](https://k3d.io) cluster running inside Docker. k3d bundles
Traefik, which serves as the Ingress controller, and the `local-path` storage provisioner for the Postgres volumes.
The service images are pulled from GitHub Container Registry (GHCR), where CI pushes them on every push to `main`
(see [Continuous integration](#continuous-integration)); the manifests pin each image to a commit SHA. The application
itself is deployed without Helm; Helm is used only for the optional monitoring stack (see [Monitoring](#monitoring)).

1. Install k3d and kubectl (not part of `requirements-dev.txt`; see the
   [k3d install docs](https://k3d.io/#installation) and the [kubectl install docs](https://kubernetes.io/docs/tasks/tools/)).
   Keep kubectl within one minor version of the cluster's Kubernetes version (`kubectl version`).
2. Create the cluster, mapping host port 8080 to the cluster's load balancer (ports 8000–8003 are left free for the
   other run methods):
   ```
   k3d cluster create km1 -p "8080:80@loadbalancer"
   ```
3. Create a personal access token (classic) for pulling the images, with only the `read:packages` scope and an expiry
   date: https://github.com/settings/tokens/new?scopes=read:packages. GHCR accepts only classic tokens from outside
   GitHub Actions, and `read:packages` covers every package of the account, not just this repository.
4. Create the namespace, the Postgres credentials Secret from your `.env` (see [Running locally](#running-locally) for
   creating it from `.env.example`) and the image pull Secret with the token from step 3. `read -s` keeps the token
   out of the shell history and off the screen:
   ```
   kubectl apply -f k8s/00-namespace.yaml
   kubectl create secret generic postgres-credentials -n km1 --from-env-file=.env --dry-run=client -o yaml | kubectl apply -f -
   read -rs GH_PAT
   kubectl create secret docker-registry package-read -n km1 --docker-server=ghcr.io --docker-username=<GitHub user> --docker-password="$GH_PAT" --dry-run=client -o yaml | kubectl apply -f -
   unset GH_PAT
   ```
5. Install Argo CD and give it access to this repository (steps 1–5 of [GitOps with Argo CD](#gitops-with-argo-cd)),
   then create the Application and wait until everything it deploys is healthy:
   ```
   kubectl apply -f argocd/application.yaml
   kubectl wait --for=jsonpath='{.status.health.status}'=Healthy application/km1 -n argocd --timeout=300s
   ```
6. Open http://localhost:8080 — a single Ingress routes by path, without rewriting:

   | Path | Service |
   |---|---|
   | `/` | `status-page` |
   | `/users` | `user-service` (API docs at `/users/docs`) |
   | `/products` | `product-service` (API docs at `/products/docs`) |
   | `/orders` | `order-service` (API docs at `/orders/docs`) |

To tear everything down, delete the Application first, then the namespace:

```
kubectl delete application km1 -n argocd
kubectl delete namespace km1
```

Deleting the Application leaves the running resources alone (see [GitOps with Argo CD](#gitops-with-argo-cd)), but
without it Argo CD would keep trying to re-create them while the namespace goes away. Deleting the namespace removes
everything, **including the Postgres volumes (database data is lost) and both Secrets** — re-create the namespace and
the Secrets (step 4) before applying the Application again. `k3d cluster stop km1` / `k3d cluster start km1` pause and
resume the cluster with its data intact; `k3d cluster delete km1` removes the whole cluster.

Things to keep in mind:

- **The namespace and the Secrets are created by hand on purpose.** Argo CD skips `k8s/00-namespace.yaml`, so neither
  pruning nor a mistake in git can delete the namespace together with the Secrets and the database volumes inside it.
- **`kubectl apply -R -f k8s/` is no longer part of the workflow.** It still works (without `-R` it skips
  subdirectories such as `k8s/ingress/`), but with automated sync Argo CD already applies the same manifests, and a
  change applied by hand that is not in git is reverted within seconds.
- **`/health`, `/livez` and `/metrics` are the only endpoints not served under the service prefix.** API docs and chaos
  endpoints move under it (e.g. `/users/docs`, `POST /users/chaos/break`), but these three do not, so
  http://localhost:8080/health and http://localhost:8080/metrics are answered by `status-page` (the catch-all `/` path),
  and `/livez` and `/metrics` of the data services are not reachable through the Ingress at all — they are meant for the
  kubelet and for Prometheus inside the cluster.
- **Avoid `@`, `:` and `/` in `POSTGRES_PASSWORD`**, as with Compose: `DATABASE_URL` is assembled from the Secret without
  URL-encoding.

### Deploying a new version

The image tag in `k8s/` defines what runs on the cluster. To deploy a new version, change the tag of the service in
its `k8s/<service>/app.yaml` to the commit SHA of an image pushed by CI and merge the change to `main`; Argo CD
deploys it within about three minutes, without any `kubectl` command. The tag is the full SHA of the commit on `main`
that CI built; the latest one is the head commit of the last successful push run:

```
gh run list --workflow ci.yml --branch main --event push --status success --limit 1 --json headSha
```

A new version always has a new tag, so the default `imagePullPolicy: IfNotPresent` pulls it and the Deployment rolls
out on its own; no `kubectl rollout restart` is needed. The rolling update keeps the old pod until the new one is
Ready, so a failed pull leaves the running version in place.

Committing a tag change to `main` triggers another CI build with a new SHA, so `k8s/` always points at an image from
an earlier commit. That is expected: the code in that image is the same.

There is no deploy script any more: the former `scripts/deploy-k3d.sh` built and imported `:local` images over the
manifests, which conflicts with the manifests defining the version.

### Pulling the images from GHCR

The packages stay private and the cluster pulls them with the `package-read` Secret, referenced as `imagePullSecrets`
in each Deployment. Making the packages public would remove the token, but a public package can never be made private
again, and the image contains the whole service code of a private repository.

- **Rotating the token.** Create a new token and repeat the `read` and `kubectl create secret docker-registry` commands
  of step 4; `kubectl apply` updates the Secret in place. The kubelet reads the Secret at every pull, so nothing needs
  a restart.
- **A pull Secret problem can stop pods even when the image is on the node.** Running pods keep running, but since
  Kubernetes 1.35 the kubelet checks pull credentials for images it pulled with a Secret
  ([image pull credential verification](https://kubernetes.io/docs/concepts/containers/images/#ensureimagepullcredentialverification)):
  a new pod with a missing Secret or a changed, wrong token has to pull again and ends in `ErrImagePull` /
  `ImagePullBackOff`, even with the image cached. A token that expired but is unchanged still verifies locally, so it
  breaks only new tags and fresh nodes. `kubectl describe pod` shows the registry's answer in Events. Once the Secret
  is fixed, the kubelet's next retry succeeds; deleting the pod only retries sooner.
  The message tells the two failures apart: `failed to fetch anonymous token … 401 Unauthorized`, together with a
  `FailedToRetrieveImagePullSecret` warning, means the Secret named in `imagePullSecrets` was not found;
  `failed to fetch oauth token … 403 Forbidden` means the Secret is there but GHCR rejects its token.
- **Never paste `kubectl get secret -o yaml`.** `kubectl describe secret` shows only the size of each key, but `data`
  is just base64, and the `kubectl.kubernetes.io/last-applied-configuration` annotation added by `kubectl apply`
  holds a second copy of it. Both decode to the plain token.

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

- **Turn off automated sync for the database drill.** Argo CD's self-heal scales the database back to 1 within
  seconds, so the outage never shows. Pause automated sync for the drill and resume it afterwards; resuming syncs the
  Application with git, which scales the database back up on its own:
  ```
  kubectl patch application km1 -n argocd --type merge -p '{"spec":{"syncPolicy":{"automated":{"enabled":false}}}}'
  kubectl patch application km1 -n argocd --type merge -p '{"spec":{"syncPolicy":{"automated":{"enabled":true}}}}'
  ```
  The chaos endpoints and `kubectl rollout restart` need no pause: they do not change anything Argo CD compares.
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
metrics endpoints, so they would only show up as targets that are always down. Prometheus is also set to pick up every
`ServiceMonitor` in the cluster (`serviceMonitorSelectorNilUsesHelmValues: false`), not only those carrying the chart's
`release` label, so the manifests in `monitoring/` do not depend on the Helm release name. The stack needs roughly
1.5–2 GB of RAM.

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
5. Let Prometheus scrape the services. `monitoring/servicemonitor.yaml` holds one `ServiceMonitor` in `km1` that
   selects the four application Services by their `app.kubernetes.io/part-of: km1` label (the `*-db` Services do not
   carry it) and scrapes `/metrics` on their `http` port. Apply it after the chart, since the `ServiceMonitor` type
   only exists once the chart has installed its CRDs:
   ```
   kubectl apply -f monitoring/
   ```
   Within about a minute *Status → Targets* shows a `serviceMonitor/km1/km1-services/0` pool with four `UP` targets,
   one per service (the `job` label is the Service name). After some traffic through the Ingress, this query returns
   request counts per service and status class:
   ```
   sum by (job, status) (http_requests_total)
   ```
6. Open the dashboard. `monitoring/dashboard.yaml` is a ConfigMap with the `grafana_dashboard: "1"` label, applied by
   the same `kubectl apply -f monitoring/`; the Grafana sidecar loads it (see
   [The km1 services dashboard](#the-km1-services-dashboard)). In Grafana go to *Dashboards → km1 services*, or open
   http://localhost:3000/d/km1-services directly.

Running the same `helm upgrade --install` command again with no changes is a no-op: Helm records a new revision
(`helm history kube-prometheus-stack -n monitoring`), but the rendered manifests of the last two revisions are
identical (`helm get manifest ... --revision N`) and no pod is restarted.
`kubectl diff -f monitoring/` prints nothing once the `ServiceMonitor` and the dashboard are applied.

To remove the stack:

```
kubectl delete -f monitoring/
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
- **The values file lives outside `k8s/`.** Argo CD (like `kubectl apply -R -f k8s/`) would try to apply it as a
  manifest and fail, since it has no `apiVersion` or `kind`.
- **`monitoring/` is separate from `k8s/` on purpose.** On a cluster without the monitoring stack there is no
  `ServiceMonitor` type, and applying it fails with `no matches for kind "ServiceMonitor"`. Keeping the file out of
  `k8s/` lets Argo CD sync `k8s/` whether or not the stack is installed.
- **The `ServiceMonitor` names the Service port, not the container port.** `port: http` refers to the named port of
  the Service; a wrong name gives no targets and no error. A Service without metadata labels is never selected.
- **A pod that is not Ready is still scraped.** With `user-service-db` scaled to 0, the `user-service` target stays
  `UP`, because `/metrics` does not touch the database. Requests through the Ingress, however, never reach a pod that is
  not Ready: Traefik answers them itself with a plain-text `503 no available server`, which does not show up in
  `http_requests_total`. To see the service's own 503s in the metrics, send the requests through a port-forward to
  the Service.
- **Helm keeps its state as Secrets** in the release namespace (`sh.helm.release.v1.<release>.v<revision>`), one per
  revision; deleting the namespace deletes the release history too.

#### The km1 services dashboard

The dashboard (uid `km1-services`) has five panels, one line per service. It refreshes every 10 s and shows the last
15 minutes; widen the range to see a whole drill.

| Panel | Query (simplified) | What it shows |
|---|---|---|
| Request rate | `sum by (job) (rate(http_requests_total[2m]))` | Requests per second, probe and scrape traffic excluded |
| 5xx share | 5xx rate / total rate, per `job` | Share of requests answered with 5xx, 0–100 %; `or … * 0` turns "no 5xx series yet" into 0 |
| p95 duration | `histogram_quantile(0.95, …http_request_duration_highr_seconds_bucket…)` | Time within which 95 % of requests finish; uses the fine-grained histogram, the other one only has 0.1/0.5/1 s buckets |
| Ready replicas | `kube_deployment_status_replicas_available`, `kube_statefulset_status_replicas_ready` | Ready pods per Deployment and per database StatefulSet (from kube-state-metrics) |
| Container restarts | `changes(kube_pod_container_status_restarts_total[5m])` | Container restarts in the last 5 minutes, database containers excluded |

All rates use a 2-minute window (four 30 s scrapes), so lines rise and fall over a minute or two rather than jumping.

##### What the chaos drills look like

Run the drills from [Probes and chaos drills](#probes-and-chaos-drills) against `user-service` while sending it
traffic **through the port-forward**, since a pod that is not Ready gets nothing from the Ingress:

```
kubectl port-forward -n km1 svc/user-service 8081:8000
while true; do curl -s -o /dev/null -w "%{http_code} " http://localhost:8081/users; sleep 0.5; done
```

Leave about five minutes between drills, so the 2- and 5-minute windows clear. Observed for `user-service`:

| Drill | 5xx share | Ready replicas | Container restarts | Other panels |
|---|---|---|---|---|
| Database down (`user-service-db` scaled to 0 for ~3 min) | Rises to 100 % within ~1.5 min | `user-service-db` and `user-service` drop to 0, back to 1 after scaling up | 0 | p95 rises slightly (~10 → ~25 ms): every request still tries the database |
| `POST /users/chaos/break` | **No change** (see below) | Drops to 0 briefly, or not at all | Jumps to 1, back to 0 after 5 min | — |
| `POST /users/chaos/break-permanent` for ~3 min, then `fix` | Rises to 100 %, falls after `fix` | `user-service` 0 while the flag is set | 0 | — |

**Why `/chaos/break` shows no 503s.** The request counters live in the memory of the application process. The
liveness probe (every 10 s, 3 failures) restarts the container 20–30 s after the break, before Prometheus scrapes
more than once every 30 s. The restarted process starts its counters from zero, so the 503s are lost with the old
one: at most one scrape catches them, and `rate()` needs two samples. Metrics from the application alone can miss a
failure shorter than the scrape interval that ends in a restart; the restart itself is what the dashboard shows.
Metrics collected outside the process, such as from the Ingress, would not lose them.

##### Changing the dashboard

The dashboard is provisioned from the ConfigMap, so Grafana does not let you save changes to it. To change it:

1. Open it, choose *Edit → Save as* to make a copy and make the changes there. Grafana 13 stores dashboards made in
   the UI in its v2 schema, whose uid (`metadata.name`) cannot be edited, so the uid is fixed in the exported file.
2. *Export → Export as code*: **Model: Classic**, **Format: JSON**, **Export for sharing externally** off (otherwise
   the datasource becomes a `${DS_PROMETHEUS}` placeholder the sidecar does not resolve). Ignore the warning about
   V2 features: the dashboard uses none of them. Download the file and keep it outside the repo.
3. In the file, set `"uid": "km1-services"` and `"id": null`, then regenerate the ConfigMap from the repo root:
   ```
   kubectl create configmap km1-dashboard -n km1 \
     --from-file=km1-services.json=<path to the exported file> \
     --dry-run=client -o yaml \
     | kubectl label --local -f - grafana_dashboard=1 -o yaml \
     > monitoring/dashboard.yaml
   ```
4. Delete the copy in the UI, then `kubectl apply -f monitoring/`. Within a minute the sidecar logs
   `Writing /tmp/dashboards/km1-services.json` (`kubectl logs -n monitoring deploy/kube-prometheus-stack-grafana
   -c grafana-sc-dashboard`) and Grafana reloads the dashboard.

Things to keep in mind:

- **The sidecar is a second container in the Grafana pod.** It watches ConfigMaps labelled `grafana_dashboard: "1"`
  in all namespaces (the chart's default `searchNamespace: ALL`), writes each key ending in `.json` as a file to
  `/tmp/dashboards` and asks Grafana to reload them. The directory is an `emptyDir`, so the dashboard survives a
  Grafana pod restart only because the sidecar writes it again from the ConfigMap.
- **The datasource is referenced by uid `prometheus`**, the fixed uid the chart gives the Prometheus datasource. A
  datasource added by hand would get a random uid, and the dashboard would show "datasource not found".

### GitOps with Argo CD

[Argo CD](https://argo-cd.readthedocs.io) runs in a separate `argocd` namespace, installed with Helm from the
[argo-cd](https://github.com/argoproj/argo-helm/tree/main/charts/argo-cd) chart. The chart version is pinned, and every
setting that differs from the chart defaults lives in `helm/argo-cd/values.yaml`: Dex (SSO through external identity
providers) and the notifications controller are disabled, since the project logs in with the built-in `admin` account
and has no notification channels, and `argocd-server` serves plain HTTP (`server.insecure`), because the UI is reached
only through a port-forward. The ApplicationSet controller stays: chart 10.x has no switch for it. With no applications
yet, Argo CD needs about 120 MB of RAM.

1. Add the chart repository (Helm is already installed for [Monitoring](#monitoring)):
   ```
   helm repo add argo https://argoproj.github.io/argo-helm
   helm repo update
   ```
2. Install the chart (the same command upgrades an existing release):
   ```
   helm upgrade --install argocd argo/argo-cd \
     --namespace argocd --create-namespace \
     --version 10.10.1 \
     --values helm/argo-cd/values.yaml \
     --wait --timeout 10m
   ```
   `kubectl get pods -n argocd` shows five `Running` pods: `argocd-server`, `argocd-repo-server`, `argocd-redis`,
   `argocd-application-controller-0` and `argocd-applicationset-controller`. For about a minute there is also a
   `Completed` `argocd-redis-secret-init` pod: a Helm hook Job that creates the Redis password Secret before the
   install and is deleted one minute after it finishes.
3. Open the UI through a port-forward (`8080` is taken by the cluster's load balancer, `8081` by the drills'
   port-forward):
   ```
   kubectl port-forward -n argocd svc/argocd-server 8090:80
   ```
   To reach it from another machine, prefer an SSH tunnel from that machine over `--address 0.0.0.0`: the server speaks
   plain HTTP, so with `--address 0.0.0.0` the password crosses the network unencrypted. The tunnel forwards the
   machine's local port 8090 through SSH to the port-forward on the cluster host:
   ```
   ssh -L 8090:localhost:8090 <user>@<cluster host>
   ```
4. Log in at http://localhost:8090 as `admin`. The initial password is generated on install:
   ```
   kubectl get secret argocd-initial-admin-secret -n argocd -o jsonpath='{.data.password}' | base64 -d; echo
   ```
   Change it under *User Info → Update Password*, log in again with the new one, then delete the initial Secret.
   Argo CD does not recreate it while an admin password is set:
   ```
   kubectl delete secret argocd-initial-admin-secret -n argocd
   ```
5. Give Argo CD read-only access to this private repository with a GitHub deploy key. Generate a dedicated key pair
   without a passphrase (Argo CD cannot type one), outside the repo:
   ```
   ssh-keygen -t ed25519 -N "" -C "argocd@km1" -f ~/.ssh/km1-argocd
   ```
   Add the public key (`~/.ssh/km1-argocd.pub`) on GitHub under *Settings → Deploy keys → Add deploy key*, leaving
   *Allow write access* unchecked. Then register the repository with a Secret labelled
   `argocd.argoproj.io/secret-type: repository`; it is created by hand and never committed:
   ```
   kubectl create secret generic repo-km1 -n argocd \
     --from-literal=type=git \
     --from-literal=url=git@github.com:ryslaw/km1.git \
     --from-file=sshPrivateKey="$HOME/.ssh/km1-argocd"
   kubectl label secret repo-km1 -n argocd argocd.argoproj.io/secret-type=repository
   ```
   *Settings → Repositories* in the UI lists the repository with the connection status `Successful`.

Running the same `helm upgrade --install` command again with no changes is a no-op: the rendered manifests of the last
two revisions are identical (`helm get manifest argocd -n argocd --revision N`), no pod of the Deployments or the
StatefulSet is restarted, and the admin password and the repository connection stay as they were. Only the
`argocd-redis-secret-init` hook Job runs again, on every upgrade, by design.

To remove Argo CD:

```
helm uninstall argocd -n argocd
kubectl delete namespace argocd
```

Deleting the namespace also removes the Secrets that `helm uninstall` leaves behind (see below). The three
`argoproj.io` CRDs stay and can be removed by hand for a fully clean cluster:

```
kubectl get crd -o name | grep argoproj.io | xargs kubectl delete
```

Things to keep in mind:

- **`helm uninstall` removes only what Helm created.** Objects without the `app.kubernetes.io/managed-by: Helm` label
  stay in the namespace: the `repo-km1` Secret (created by hand, so a reinstall connects to the repository right
  away), `argocd-redis` (written by the hook Job, not by Helm), `argocd-initial-admin-secret` if it was not deleted
  (written by `argocd-server`, and stale after a reinstall), and `kube-root-ca.crt`, which Kubernetes puts in every
  namespace. Helm never deletes the namespace created with `--create-namespace` either.
- **A reinstall resets the admin password.** The chart creates `argocd-secret` empty, and `argocd-server` writes the
  password hash into it later. An upgrade without changes does not touch the Secret, but `helm uninstall` deletes it
  with the password inside, so the next install generates a new initial password: repeat step 4.
- **The CRDs are kept on purpose** (`crds.keep: true`, visible as the `helm.sh/resource-policy: keep` annotation).
  They define the `Application`, `ApplicationSet` and `AppProject` types; deleting a CRD deletes every object of that
  type in the cluster, so an uninstall before a reinstall would otherwise wipe out all applications.
- **The repository Secret needs its label and an SSH URL.** Without `argocd.argoproj.io/secret-type: repository`
  Argo CD ignores the Secret, and an `https://` URL does not work with an SSH key. The GitHub host keys are already in
  the `argocd-ssh-known-hosts-cm` ConfigMap.
- **The deploy key is not your personal key.** It is read-only and limited to this one repository, and it has no
  passphrase, so it must never end up in the repo.

#### The km1 Application

`argocd/application.yaml` defines one Application, `km1`, that deploys `k8s/` from `main` (recursively, without
`00-namespace.yaml`) into the `km1` namespace, with automated sync, pruning and self-heal. It lives outside `k8s/`
because the `Application` type only exists once Argo CD is installed. Argo CD does not manage this file itself: after
changing it, apply it with `kubectl apply -f argocd/application.yaml`.

| Change | What Argo CD does |
|---|---|
| A commit to `k8s/` on `main` | Syncs it within about three minutes (it polls the repository every 120 s plus up to 60 s of jitter; there is no webhook from GitHub to a local cluster). *Refresh* in the UI checks right away. |
| A manual change to a resource from git (e.g. `kubectl scale`) | Self-heal reverts it within seconds. |
| A file removed from `k8s/` | Pruning deletes its resources on the next sync. |
| A resource that is not in git (the Secrets, old ReplicaSets) | Nothing: Argo CD only compares and prunes resources it tracks. |

Check the sync status with `kubectl get application km1 -n argocd` (columns `SYNC STATUS` and `HEALTH STATUS`; the
expected state is `Synced` and `Healthy`) or in the UI. The UI also shows the sync history, the last synced commit and
a diff for every resource.

Things to keep in mind:

- **Self-heal syncs do not appear in the history.** The history lists full syncs only, such as a new commit or a
  manual *Sync*. A self-heal sync touches only the drifted resources and shows up only in the events:
  `kubectl get events -n argocd --field-selector involvedObject.kind=Application,involvedObject.name=km1`. Kubernetes
  keeps events for about an hour.
- **Argo CD adopts existing resources.** Switching from `kubectl apply` to the Application did not recreate any pod,
  StatefulSet or volume; Argo CD only added its `argocd.argoproj.io/tracking-id` annotation. Resources without that
  annotation, such as the hand-made `postgres-credentials` and `package-read` Secrets, are never pruned.
- **Deleting the Application keeps everything it deployed.** The Application has no `resources-finalizer`, so
  `kubectl delete application km1 -n argocd` deletes only the Application; applying it again adopts the same resources
  without recreating them. Avoid deleting it from the UI, which offers a cascading delete that removes every
  resource the Application deployed.
- **Pausing automated sync is not in git.** The patch from [Probes and chaos drills](#probes-and-chaos-drills) changes
  only the object in the cluster, and nothing reverts it. Resume it with the second patch or with
  `kubectl apply -f argocd/application.yaml`; until then, commits to `main` are not deployed.
- **Restarts are not drift.** `kubectl rollout restart` and the UI's *Restart* action add a `restartedAt` annotation
  that is not in git; Argo CD only compares fields defined in git, so the Application stays `Synced`.
- **The StatefulSets stay `Synced`.** Unlike `kubectl apply`, which always reported them as `configured` because the
  API server fills in defaults in their `volumeClaimTemplates`, Argo CD shows no difference, so no `ignoreDifferences`
  is needed.
- **Keep `namespace: km1` in every manifest.** Argo CD puts a resource without a namespace into the Application's
  destination namespace, but an explicit namespace keeps the manifests correct for a plain `kubectl apply` too.

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

### Continuous integration

CI runs on every pull request to `main` and on every push to `main`
([`.github/workflows/ci.yml`](.github/workflows/ci.yml)):

| Job | What it does |
|---|---|
| `lint` | `ruff check .` and `ruff format --check .` |
| `test` | `pytest` for each of the four services (matrix job, after `lint`) |
| `ansible` | syntax check and `ansible-lint` of the playbook |
| `shellcheck` | ShellCheck on every tracked `*.sh` file |
| `images` | builds the Docker image of each of the four services (matrix job, after `test`) |

On pull requests the `images` job only builds the images, so a broken Dockerfile fails the PR. On pushes to `main` it
also pushes them to the GitHub Container Registry (GHCR) as `ghcr.io/ryslaw/km1/<service>:<commit SHA>`, tagged with
the full 40-character SHA of the commit. There is no `latest` tag, so every image points to exactly one commit, and
all four images of a commit share the same tag even if a service did not change. The job logs in with the workflow's
`GITHUB_TOKEN` and is the only job with `packages: write`. The `org.opencontainers.image.source` label links the
packages to this repository; they are private and listed under the repository's *Packages*.

To pull an image outside GitHub Actions, create a classic personal access token with only the `read:packages` scope
(GHCR does not accept fine-grained tokens) and an expiry date, then pass it on stdin so it does not end up in the
shell history:

```
read -rs GHCR_TOKEN
printf '%s' "$GHCR_TOKEN" | docker login ghcr.io -u <github-user> --password-stdin
unset GHCR_TOKEN
docker pull ghcr.io/ryslaw/km1/user-service:<commit SHA>
```

Docker stores the credentials unencrypted in its config file, so run `docker logout ghcr.io` when you no longer need
them. The database-backed services wait for their database before they open port 8000, so to try an image on its own
run it on a user-defined Docker network next to a `postgres` container and point `DATABASE_URL` at that container's
name.

## Roadmap

This project is developed milestone by milestone, each tracked as a GitHub Milestone with issues (✅ = done):

0. ✅ Git/GitHub project foundation
1. ✅ Docker Compose (all services running together locally)
2. ✅ Code quality & automated testing baseline
3. ✅ Continuous Integration (GitHub Actions)
4. ✅ Configuration management with Ansible
5. ✅ Infrastructure as Code with Terraform (local)
6. ✅ Kubernetes deployment
7. ✅ Observability (metrics & dashboards)
8. ✅ GitOps & continuous delivery (Argo CD, container images in GHCR)
9. Configuration management II: Ansible on real Linux hosts (roles, Vault, testing; a multi-node k3s cluster)
10. Automation platform: AWX
11. Packaging & workload security (a Helm chart for km1, image scanning, pod hardening, per-service database roles)
12. Cloud foundation: Google Cloud with Terraform (remote state, IAM, networking, keyless CI)
13. Kubernetes in the cloud: km1 on GKE (managed secrets, network policies)
14. CI/CD across platforms (GitLab CI, Cloud Build and Cloud Deploy, Jenkins)
15. Operations & SRE on GKE (SLOs, alerting, logging)

Throughout all phases: least privilege on every layer, both for people (admin, operator, developer and auditor roles) and for applications and automation (a dedicated technical account per application, pipeline and tool), and troubleshooting drills on deliberately broken scenarios.

## Contributing

This is a solo learning project with a lightweight PR review process. See `.github/PULL_REQUEST_TEMPLATE.md` and the issue templates under `.github/ISSUE_TEMPLATE/`. Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/).
