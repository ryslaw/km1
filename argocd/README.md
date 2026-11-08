# GitOps with Argo CD

Prerequisites: the k3d cluster from [Kubernetes (k3d)](../k8s/README.md). Run all commands from the repo root.

[Argo CD](https://argo-cd.readthedocs.io) runs in a separate `argocd` namespace, installed with Helm from the
[argo-cd](https://github.com/argoproj/argo-helm/tree/main/charts/argo-cd) chart. The chart version is pinned, and every
setting that differs from the chart defaults lives in `helm/argo-cd/values.yaml`: Dex (SSO through external identity
providers) and the notifications controller are disabled, since the project logs in with the built-in `admin` account
and has no notification channels, and `argocd-server` serves plain HTTP (`server.insecure`), because the UI is reached
only through a port-forward. The ApplicationSet controller stays: chart 10.x has no switch for it. With no applications
yet, Argo CD needs about 120 MB of RAM.

1. Add the chart repository (Helm is already installed for [Monitoring](../monitoring/README.md)):
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

## The km1 Application

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
- **Pausing automated sync is not in git.** The patch from [Probes and chaos drills](../k8s/README.md#probes-and-chaos-drills) changes
  only the object in the cluster, and nothing reverts it. Resume it with the second patch or with
  `kubectl apply -f argocd/application.yaml`; until then, commits to `main` are not deployed.
- **Restarts are not drift.** `kubectl rollout restart` and the UI's *Restart* action add a `restartedAt` annotation
  that is not in git; Argo CD only compares fields defined in git, so the Application stays `Synced`.
- **The StatefulSets stay `Synced`.** Unlike `kubectl apply`, which always reported them as `configured` because the
  API server fills in defaults in their `volumeClaimTemplates`, Argo CD shows no difference, so no `ignoreDifferences`
  is needed.
- **Keep `namespace: km1` in every manifest.** Argo CD puts a resource without a namespace into the Application's
  destination namespace, but an explicit namespace keeps the manifests correct for a plain `kubectl apply` too.
