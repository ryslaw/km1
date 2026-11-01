# Access model

Who can do what in km1, on which layer, and why. The code is the source of truth for how access is granted
(Ansible variables, sudoers rules, RBAC manifests, IAM policies). This document is the one place that shows the
whole picture, records why each right exists, and lists the risks that were accepted on purpose.

Every issue that changes access updates this document in the same pull request.

## Principles

- **Least privilege.** Every identity gets only the rights its role needs, on every layer.
- **People and machines are separate.** People use personal accounts. Automation uses dedicated technical
  accounts, one per application, pipeline, or tool.
- **Rights come from groups, not from people.** A person is a member of a role group, and the right is
  granted to the group. Linux has no nested groups, so a right that comes from a system group (for example
  `adm`) is assigned to the account directly.
- **No root-equivalent groups for managed accounts.** `sudo`, `docker`, `lxd`, `libvirt`, and `disk` are
  never assigned through the account list. Administrative rights go through files in `/etc/sudoers.d/`.
- **Every right is tested both ways.** A positive test shows the right works. A negative test shows that
  nothing beyond it is possible.

## Identities

### People

The personas are fictional characters from the Polish sitcom *Miodowe lata*. Logins use the first letter of
the first name followed by the last name. Each identity has the same name on every layer.

| Login       | Person          | Role      | Role group       | Status  |
|-------------|-----------------|-----------|------------------|---------|
| `kkrawczyk` | Karol Krawczyk  | operator  | `km1-operators`  | active  |
| `akrawczyk` | Alina Krawczyk  | auditor   | `km1-auditors`   | active  |
| `tnorek`    | Tadeusz Norek   | developer | `km1-developers` | planned |
| `dnorek`    | Danuta Norek    | admin     | `km1-admins`     | planned |
| `ryslaw`    | project owner   | admin (bootstrap) | —        | active, not managed by Ansible |

### Technical accounts

| Account       | Used by | Purpose |
|---------------|---------|---------|
| `svc-ansible` | Ansible on the control node (ubuntu1) | Runs all playbooks against the physical hosts after the bootstrap run |

## Access matrix

### Physical hosts (ubuntu1, ubuntu2)

Managed by the `users` role in `ansible/roles/users/`, from `ansible/group_vars/hypervisors.yml`.

| Identity      | Login        | Groups                   | sudo |
|---------------|--------------|--------------------------|------|
| `kkrawczyk`   | SSH key only | `km1-operators`          | *planned (#39): one narrow rule granted to `%km1-operators`* |
| `akrawczyk`   | SSH key only | `km1-auditors`, `adm`    | none |
| `svc-ansible` | SSH key only | —                        | *TBD (#39): the rights Ansible needs* |
| `ryslaw`      | password and SSH key | ubuntu1: `adm`, `cdrom`, `sudo`, `dip`, `plugdev`, `lxd`, `docker`; ubuntu2: `adm`, `cdrom`, `sudo`, `dip`, `plugdev`, `lxd` | full, with password (`sudo` group) |

What each right is for:

- `adm` lets the auditor read the logs in `/var/log`, including `auth.log`, without changing anything.
- `km1-operators` and `km1-auditors` grant nothing by themselves yet. They identify the role, and sudoers
  rules are attached to them.

## Secrets

Where the secret of each identity lives. Public keys are committed in `ansible/group_vars/hypervisors.yml`.
Private keys are never committed.

| Identity      | Secret | Location | Protection |
|---------------|--------|----------|------------|
| `kkrawczyk`   | SSH private key | `~/.ssh/km1-kkrawczyk` of `ryslaw` on ubuntu1 | passphrase, file mode 0600 |
| `akrawczyk`   | SSH private key | `~/.ssh/km1-akrawczyk` of `ryslaw` on ubuntu1 | passphrase, file mode 0600 |
| `svc-ansible` | SSH private key | `~/.ssh/km1-svc-ansible` of `ryslaw` on ubuntu1 | file mode 0600 only (no passphrase, since automation cannot type one) |
| `ryslaw`      | SSH private key | `~/.ssh/km1-hypervisors` on ubuntu1 | passphrase, file mode 0600 |

A lost key is replaced, not recovered: generate a new key pair, replace the public key in the variables, and
run the playbook as `ryslaw` (the bootstrap run).

## Findings and accepted risks

| # | Finding | Risk | Decision |
|---|---------|------|----------|
| F1 | `ryslaw` is in the `docker` group on ubuntu1 | Root-equivalent: anyone with this account can start a privileged container without a password | Accepted for now: k3d runs on ubuntu1. Revisit when k3d is retired |
| F2 | `ryslaw` is in the `lxd` group on both hosts, but LXD is not installed | None today. It becomes root-equivalent if LXD is installed again | Remove the membership when the personal account is cleaned up |
| F3 | The private keys of all personas and of `svc-ansible` are in the home directory of `ryslaw` on ubuntu1 | Whoever controls `ryslaw` on ubuntu1 can act as every other identity | Accepted in the lab: the personas are fictional. The `svc-ansible` key moves to AWX in phase 10 |
| F4 | `svc-ansible` sudo rights | *TBD (#39)* | *TBD (#39)* |

## Verification

Run these from the control node (ubuntu1) after a playbook run. Replace the host as needed.

```sh
# Accounts, groups, and locked passwords
ssh -i ~/.ssh/km1-akrawczyk akrawczyk@192.168.100.31 id
sudo passwd -S svc-ansible            # on the host: expect L (locked password)

# Key-only login works
ssh -i ~/.ssh/km1-svc-ansible svc-ansible@192.168.100.31 whoami

# The auditor can read logs
ssh -i ~/.ssh/km1-akrawczyk akrawczyk@192.168.100.31 'tail -n 1 /var/log/auth.log'

# The auditor has no sudo rules: expect "User akrawczyk is not allowed to run sudo on ..."
# (sudo -l run by the auditor proves nothing: the locked password stops it before any rule is checked)
ssh -t ryslaw@192.168.100.31 sudo -l -U akrawczyk
```

The negative `sudo -l` tests for the operator are added together with the sudoers rules (#39).
