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
`users.yml` holds the accounts and sudo rules, `ssh_hardening.yml` holds the SSH login policy, and
`hypervisor.yml` holds the size of the VM storage and the expected members of the `libvirt` group. Check the merged
result with:

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

`ansible/hypervisors.yml` applies the `users` role, then the `ssh_hardening` role (see
[SSH policy on the physical hosts](#ssh-policy-on-the-physical-hosts)), then the `hypervisor` role (see
[KVM hypervisors on the physical hosts](#kvm-hypervisors-on-the-physical-hosts)), to the `hypervisors` group. The `users`
role reads four lists from `ansible/group_vars/hypervisors/users.yml`: role groups (`users_groups`), accounts
with their SSH public keys (`users_accounts`), sudo rules (`users_sudoers`), and extra groups for accounts it
does not manage (`users_group_memberships`). The fields of each list are described in the
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
back is the host's console. On a host where the SSH policy is already in place, the bootstrap run still works: `ryslaw`
logs in with a key and is a member of `km1-ssh-users`.

**Removing an account or a sudo rule.** Deleting an entry from the list deletes nothing on the hosts; see
[Removing an account or a sudo rule](roles/users/README.md#removing-an-account-or-a-sudo-rule).

**`--check` on a new host.** Check mode does not create anything, so on a host where `km1-ssh-users` does not
exist yet, a check run stops at the first task that needs the group. A real run creates the group first and
passes.

## SSH policy on the physical hosts

The `ssh_hardening` role sets the SSH login policy on both hosts:

- logins with an SSH key only: no passwords, no keyboard-interactive,
- no `root` login, not even with a key,
- only members of `km1-ssh-users` may log in (`ansible/group_vars/hypervisors/ssh_hardening.yml`).

What the role writes and how it applies a change safely is described in the
[ssh_hardening role README](roles/ssh_hardening/README.md). Who is in `km1-ssh-users` and why is recorded in
[docs/access-model.md](../docs/access-model.md).

Membership of `km1-ssh-users` is managed by the `users` role. Accounts in `users_accounts` list the group
themselves. The personal account `ryslaw` is not managed by Ansible, so it gets the group through
`users_group_memberships`. Its password, keys, and other groups stay as they are. The password is still
needed for `sudo` and for the console.

### Rolling out a change

Change one host at a time, and keep a second SSH session with `sudo -i` open on that host until a new login
works. An open session survives a reload of sshd.

```
ansible-playbook -l ubuntu1 ansible/hypervisors.yml --check --diff
ansible-playbook -l ubuntu1 ansible/hypervisors.yml
```

Verify (below), then repeat for `ubuntu2`. If a new login fails, fix it from the open session. If no session
is left, the host's console still accepts the `ryslaw` password, because console logins do not go through sshd.

### Verifying the policy

```sh
# What the configuration files say (all files merged). This is not proof that the running sshd uses it:
# sshd -T reads the files again.
sudo sshd -T | grep -Ei '^(passwordauthentication|kbdinteractiveauthentication|permitrootlogin|pubkeyauthentication|allowgroups) '

# The running sshd has reloaded since the change
sudo journalctl -u ssh --since "-10 min" | grep -i sighup
```

From a workstation:

```sh
# Key login works
ssh -o PreferredAuthentications=publickey ubuntu1 hostname

# Passwords are refused: expect "Permission denied (publickey)" without a password prompt.
# The list in parentheses is what the server offers, so only publickey is possible.
ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no ubuntu1
```

The negative tests for `AllowGroups` and for `root` need evidence in the log, because a refusal alone does
not show which rule refused it. They are described in [docs/access-model.md](../docs/access-model.md#verification).

### Adding a new workstation

Passwords are off, so a new workstation cannot copy its key with a password login. Generate a key on the new
workstation, move only the public key to a machine that already has access, and append it to
`~/.ssh/authorized_keys` of `ryslaw` on both hosts:

```sh
cat new-workstation.pub | ssh ubuntu1 'cat >> ~/.ssh/authorized_keys'
cat new-workstation.pub | ssh ubuntu2 'cat >> ~/.ssh/authorized_keys'
```

Give each workstation its own key, with a comment naming it (`ryslaw@<workstation>-km1`), so a single
workstation can be revoked. The keys of `ryslaw` are not managed by Ansible: when a workstation is retired,
remove its line from `authorized_keys` on both hosts by hand. Without a working workstation, add the key from
the host's console.

## KVM hypervisors on the physical hosts

The `hypervisor` role turns both hosts into KVM hypervisors managed by libvirt. After a run, each host has:

- QEMU and libvirt installed, with `libvirtd` enabled through its socket,
- a 200 GiB logical volume `vmstore` on the SSD, mounted at `/var/lib/libvirt/images` and registered as the
  libvirt storage pool `default` (active, autostart on),
- the default NAT network `default` (`virbr0`) stopped, with autostart off,
- a check that the `libvirt` group holds exactly the accounts in `hypervisor_libvirt_members`
  (`ansible/group_vars/hypervisors/hypervisor.yml`).

The role creates no VMs and does not change the host's network. What it does, the storage layout, and how to
verify it are described in the [hypervisor role README](roles/hypervisor/README.md). Membership of `libvirt` equals
root on the host; who is in the group and why is recorded in [docs/access-model.md](../docs/access-model.md).

Roll out one host at a time, `ubuntu2` first, because `ubuntu1` is the control node:

```
ansible-playbook -l ubuntu2 ansible/hypervisors.yml --check --diff
ansible-playbook -l ubuntu2 ansible/hypervisors.yml
```

On a new host the check run stops partway, because nothing is installed in check mode; the real run passes.
Running the playbook again should report `changed=0`.

**When the `libvirt` check fails.** The `libvirt-daemon-system` package adds every member of `sudo` to `libvirt`
on each install and upgrade, so a new admin makes the next run stop with a message naming both lists. Decide
whether the account should manage VMs: remove it with `sudo gpasswd -d <user> libvirt`, or add it to
`hypervisor_libvirt_members` and record it in `docs/access-model.md` in the same pull request.

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
