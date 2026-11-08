# Kubernetes (k3d)

An alternative to [Docker Compose](../services/README.md#running-locally): the `k8s/` directory holds plain Kubernetes
manifests for the same stack, which Argo CD applies from `main` (see [GitOps with Argo CD](../argocd/README.md)) into
a dedicated `km1` namespace on a single-node [k3d](https://k3d.io) cluster running inside Docker. k3d bundles
Traefik, which serves as the Ingress controller, and the `local-path` storage provisioner for the Postgres volumes.
The service images are pulled from GitHub Container Registry (GHCR), where CI pushes them on every push to `main`
(see [Continuous integration](../docs/development.md#continuous-integration)); the manifests pin
each image to a commit SHA. The application itself is deployed without Helm; Helm is used only for the optional monitoring
stack (see [Monitoring](../monitoring/README.md)).

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
4. Create the namespace, the Postgres credentials Secret from your `.env` (see [Running locally](../services/README.md#running-locally) for
   creating it from `.env.example`) and the image pull Secret with the token from step 3. `read -s` keeps the token
   out of the shell history and off the screen:
   ```
   kubectl apply -f k8s/00-namespace.yaml
   kubectl create secret generic postgres-credentials -n km1 --from-env-file=.env --dry-run=client -o yaml | kubectl apply -f -
   read -rs GH_PAT
   kubectl create secret docker-registry package-read -n km1 --docker-server=ghcr.io --docker-username=<GitHub user> --docker-password="$GH_PAT" --dry-run=client -o yaml | kubectl apply -f -
   unset GH_PAT
   ```
5. Install Argo CD and give it access to this repository (steps 1–5 of [GitOps with Argo CD](../argocd/README.md)),
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

Deleting the Application leaves the running resources alone (see [GitOps with Argo CD](../argocd/README.md)), but
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

## Deploying a new version

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

## Pulling the images from GHCR

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

## Probes and chaos drills

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
