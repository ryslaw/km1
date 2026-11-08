# Terraform

An alternative to [Docker Compose](../services/README.md#running-locally): the `terraform/` directory describes the same
stack declaratively (network, Postgres volumes, images built from each service's `Dockerfile`, and containers) using the
`kreuzwerker/docker` provider against your local Docker daemon. State is kept locally in `terraform/terraform.tfstate`
(gitignored) — no remote backend or cloud provider.

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
4. Open http://localhost:8000 — services are published on the same host ports as with
   [Compose](../services/README.md#running-locally) (8001–8003).

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
