# Monitoring

Prerequisites: the k3d cluster from [Kubernetes (k3d)](../k8s/README.md). Run all commands from the repo root.

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

## The km1 services dashboard

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

### What the chaos drills look like

Run the drills from [Probes and chaos drills](../k8s/README.md#probes-and-chaos-drills) against `user-service` while sending it
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

### Changing the dashboard

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
