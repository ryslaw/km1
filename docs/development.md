# Development

Dev tooling (linting and testing) is shared across all four services via a single root-level `requirements-dev.txt`, rather than duplicated per service:

```
pip install -r requirements-dev.txt
```

## Linting & formatting

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

## Testing

Each service has its own `tests/` directory. Run a service's tests from within that service's directory:

```
cd services/user-service && pytest
```

## Continuous integration

CI runs on every pull request to `main` and on every push to `main`
([`.github/workflows/ci.yml`](../.github/workflows/ci.yml)):

| Job | What it does |
|---|---|
| `lint` | `ruff check .` and `ruff format --check .` |
| `test` | `pytest` for each of the four services (matrix job, after `lint`) |
| `ansible` | installs the pinned tools and collections, then `ansible-lint ansible/` (includes a syntax check of every playbook) |
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
