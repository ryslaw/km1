# Ansible

Everything Ansible lives in `ansible/`. Run all Ansible commands from the repo root: the root `ansible.cfg` points
Ansible at `ansible/inventory.yml`, and Ansible only looks for `ansible.cfg` in the current directory, not in parent
directories.

## Setup

The Ansible tools are pinned in `ansible/requirements.txt` and installed into their own virtual environment, separate
from the services' root `.venv` (which pins different versions of shared dependencies such as Jinja2). The collections
are pinned to exact versions in `ansible/requirements.yml`.

```
python3 -m venv --prompt km1-ansible ansible/.venv
source ansible/.venv/bin/activate
pip install -r ansible/requirements.txt
ansible-galaxy collection install -r ansible/requirements.yml
```

`--prompt` makes the shell show `(km1-ansible)` instead of `(.venv)`, so it is obvious which environment is active.
`ansible-lint --version` should report the versions pinned in `ansible/requirements.txt`.

## Inventory

| Group | Hosts | Connection |
|---|---|---|
| `hypervisors` | `ubuntu1` (192.168.100.31), `ubuntu2` (192.168.100.32) | SSH |
| `local` | `localhost` | local |

`ansible/inventory.yml` only says which host belongs to which group. How to reach each host lives in
`ansible/host_vars/` (`ansible_host`, `ansible_connection`). Settings shared by all hosts live in
`ansible/group_vars/all.yml` (`ansible_python_interpreter`). Settings for one group live in a directory named
after the group, for example `ansible/group_vars/hypervisors/`: `connection.yml` holds the SSH account and key,
and `users.yml` holds the accounts and sudo rules. Check the merged result with:

```
ansible-inventory --graph
ansible-inventory --host ubuntu1
```

## Reaching the physical hosts

`ubuntu1` is the control node. Ansible connects to the `hypervisors` group as the technical account `svc-ansible`,
with its own key `~/.ssh/km1-svc-ansible` (set in `ansible/group_vars/hypervisors/connection.yml`). The key has no
passphrase, because automation cannot type one, and `svc-ansible` has passwordless sudo. A normal run therefore
needs neither an SSH agent nor `-K`. Host key checking stays on: before the first connection, verify each host's
key fingerprint out-of-band and accept it with a manual `ssh`.

Check connectivity and privilege escalation:

```
ansible hypervisors -m ansible.builtin.ping
ansible hypervisors -b -m ansible.builtin.command -a id
```

`-b` runs the module via `sudo`, so the second command should report `uid=0(root)` on both hosts. The personal
account `ryslaw` is used only for the bootstrap run (see below).

## Managing accounts and sudo rules on the physical hosts

`ansible/hypervisors.yml` applies the `users` role to the `hypervisors` group. The role reads three lists from
`ansible/group_vars/hypervisors/users.yml`: role groups (`users_groups`), accounts with their SSH public keys
(`users_accounts`), and sudo rules (`users_sudoers`). The fields of each list are described in the
[users role README](roles/users/README.md#role-variables). Who gets which right, and why, is recorded in
[docs/access-model.md](../docs/access-model.md).

A normal run uses `svc-ansible`:

```
ansible-playbook ansible/hypervisors.yml --check --diff   # preview the changes
ansible-playbook ansible/hypervisors.yml
```

Running it again should report `changed=0` on both hosts.

**Bootstrap run.** `svc-ansible` is created by this same playbook, so the first run on a new host has to use the
personal account `ryslaw`. The same run also repairs `svc-ansible` if it has lost its key or its sudo rule. The key
`~/.ssh/km1-hypervisors` is passphrase-protected, and Ansible cannot ask for a passphrase, so load the key into an
agent first:

```
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/km1-hypervisors
ansible-playbook -K -e ansible_user=ryslaw -e ansible_ssh_private_key_file=~/.ssh/km1-hypervisors ansible/hypervisors.yml
```

Extra vars (`-e`) have the highest precedence, so for this one run they override the account and key from
`connection.yml`. `-K` asks for the sudo password of `ryslaw`. If the run fails with `Permission denied
(publickey)`, check with `ssh-add -l` that the key is in the agent. If `ryslaw` cannot log in either, the only way
back is the host's console.

**Removing an account or a sudo rule.** Deleting an entry from the list deletes nothing on the hosts; see
[Removing an account or a sudo rule](roles/users/README.md#removing-an-account-or-a-sudo-rule).

## Running the Compose stack with Ansible

As an alternative to the manual steps in [Running locally](../services/README.md#running-locally), `ansible/playbook.yml` automates the
same two steps (create `.env` if missing, bring up the Compose stack) on the `local` group, so no SSH is involved:

```
ansible-playbook ansible/playbook.yml
```

Open http://localhost:8000 once all containers report healthy. Running the playbook again is safe: it won't
overwrite an existing `.env` and won't disrupt already-running containers.

## Linting

```
ansible-lint ansible/
```

Always pass `ansible/`: without a path, `ansible-lint` scans the whole repo, including the Compose, Kubernetes and
monitoring YAML. The same command runs in CI, and it includes a syntax check of every playbook. It is configured in
`.ansible-lint` at the repo root:

- `exclude_paths: .venv/` — `ansible-lint` does not honour `.gitignore`, so without this it would lint the thousands
  of files inside `ansible/.venv`.
- `offline: true` — `ansible-lint` does not install anything itself; collections come only from the pinned
  `ansible-galaxy collection install` step. (Its working directory `.ansible/` is git-ignored.)
