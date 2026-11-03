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
| `svc-ansible` | Ansible on the control node (ubuntu1) | Runs all playbooks against the physical hosts. It is created and repaired by the bootstrap run as `ryslaw` |

## Access matrix

### Physical hosts (ubuntu1, ubuntu2)

Managed by the `users` role in `ansible/roles/users/`, from `ansible/group_vars/hypervisors/users.yml`: role
groups from `users_groups`, accounts from `users_accounts`, and sudo rules from `users_sudoers`. Each sudo rule is
one file in `/etc/sudoers.d/` (owner `root:root`, mode `0440`), checked with `visudo` before it is installed.
Access is revoked by setting the entry's `state` to `absent` and running the playbook. Only then is the entry
removed from the list (see F6).

| Identity      | Login        | Groups                   | sudo |
|---------------|--------------|--------------------------|------|
| `kkrawczyk`   | SSH key only | `km1-operators`          | through `%km1-operators`: `/usr/bin/systemctl restart systemd-timesyncd` as root, without a password |
| `akrawczyk`   | SSH key only | `km1-auditors`, `adm`    | none |
| `svc-ansible` | SSH key only | —                        | every command as any user, without a password (see F4) |
| `ryslaw`      | password and SSH key | ubuntu1: `adm`, `cdrom`, `sudo`, `dip`, `plugdev`, `lxd`, `docker`; ubuntu2: `adm`, `cdrom`, `sudo`, `dip`, `plugdev`, `lxd` | full, with password (`sudo` group) |

What each right is for:

- `adm` lets the auditor read the logs in `/var/log`, including `auth.log`, without changing anything.
- The operator may restart time synchronisation (`systemd-timesyncd`), a routine runbook step when the clock
  drifts. The rule names the exact arguments, so any other `systemctl` action is refused, including `status`,
  whose pager could otherwise be used to escape to a shell. It needs `NOPASSWD` because the persona's password
  is locked; a stolen operator key gives this one command and nothing more.
- `svc-ansible` needs unrestricted root. Ansible runs its module code through `sudo /bin/sh -c ...`, so a list of
  allowed commands cannot work. The rule allows any target user (`(ALL)`) because a task may become a user
  other than root.
- `km1-auditors` grants nothing by itself. It identifies the role, so rules can be attached to it later.

## Secrets

Where the secret of each identity lives. Public keys are committed in `ansible/group_vars/hypervisors/users.yml`.
Private keys are never committed.

| Identity      | Secret | Location | Protection |
|---------------|--------|----------|------------|
| `kkrawczyk`   | SSH private key | `~/.ssh/km1-kkrawczyk` of `ryslaw` on ubuntu1 | passphrase, file mode 0600 |
| `akrawczyk`   | SSH private key | `~/.ssh/km1-akrawczyk` of `ryslaw` on ubuntu1 | passphrase, file mode 0600 |
| `svc-ansible` | SSH private key | `~/.ssh/km1-svc-ansible` of `ryslaw` on ubuntu1 | file mode 0600 only (no passphrase, since automation cannot type one) |
| `ryslaw`      | SSH private key | `~/.ssh/km1-hypervisors` on ubuntu1 | passphrase, file mode 0600 |

A lost key is replaced, not recovered: generate a new key pair, replace the public key in the variables, and
run the playbook. If the lost key belongs to `svc-ansible`, use the bootstrap run as `ryslaw` (see
[Managing accounts and sudo rules on the physical hosts](../README.md#managing-accounts-and-sudo-rules-on-the-physical-hosts)).

## Findings and accepted risks

| # | Finding | Risk | Decision |
|---|---------|------|----------|
| F1 | `ryslaw` is in the `docker` group on ubuntu1 | Root-equivalent: anyone with this account can start a privileged container without a password | Accepted for now: k3d runs on ubuntu1. Revisit when k3d is retired |
| F2 | `ryslaw` is in the `lxd` group on both hosts, but LXD is not installed | None today. It becomes root-equivalent if LXD is installed again | Remove the membership when the personal account is cleaned up |
| F3 | The private keys of all personas and of `svc-ansible` are in the home directory of `ryslaw` on ubuntu1 | Whoever controls `ryslaw` on ubuntu1 can act as every other identity | Accepted in the lab: the personas are fictional. The `svc-ansible` key moves to AWX in phase 10 |
| F4 | `svc-ansible` can run every command as root without a password | Root-equivalent: whoever holds its private key controls both hosts | Accepted: the usual compromise for a configuration management account. Mitigated by key-only login, a locked password, and a private key that never leaves the control node (see F3). Revisit with AWX in phase 10 |
| F5 | A refused `sudo -n` attempt leaves no trace in `auth.log` | The auditor sees every command run through sudo, but not every refused attempt | Accepted for now. Revisit with central logging in phase 15 |
| F6 | An account or sudo rule whose entry is deleted from the list stays on the hosts | Orphaned access: a person who left keeps their login and rights, and nothing in the repo shows it | Accepted: revoking is an explicit step (`state: absent`, run, then delete the entry), documented in the role defaults and the README. Revisit if the role gets a mode that removes everything not listed |

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

# Sudo rules as sudo itself sees them (run by ryslaw): one rule for the operator, none for the auditor,
# and ALL for svc-ansible. sudo -l run by a persona proves nothing: the locked password stops it
# before any rule is checked.
ssh -t ryslaw@192.168.100.31 'sudo -l -U kkrawczyk; sudo -l -U akrawczyk; sudo -l -U svc-ansible'

# The operator's rule works...
ssh -i ~/.ssh/km1-kkrawczyk kkrawczyk@192.168.100.31 'sudo -n /usr/bin/systemctl restart systemd-timesyncd && echo OK'

# ...and nothing else does: expect "a password is required" and exit code 1 each time
ssh -i ~/.ssh/km1-kkrawczyk kkrawczyk@192.168.100.31 \
  'sudo -n /usr/bin/systemctl status systemd-timesyncd; echo $?; sudo -n /usr/bin/id; echo $?; sudo -n -i; echo $?'

# Only the allowed command opened a root session (checked by the auditor)
ssh -i ~/.ssh/km1-akrawczyk akrawczyk@192.168.100.31 'grep "sudo:.*kkrawczyk" /var/log/auth.log | tail -n 5'

# svc-ansible has passwordless sudo
ssh -i ~/.ssh/km1-svc-ansible svc-ansible@192.168.100.31 'sudo -n true && echo OK'

# After revoking an account and its rule (state: absent, then a playbook run): no passwd or group entry,
# "No such file or directory" for the home directory, and no rule file left in /etc/sudoers.d/
ssh -t ryslaw@192.168.100.31 'getent passwd olduser; getent group olduser; ls -d /home/olduser; ls /etc/sudoers.d/'
```

A refused `sudo -n` attempt is not logged (F5), so the negative tests rely on `sudo -l -U` and on the exit
codes, not on the log.
