# ssh_hardening

Hardens the OpenSSH server on Ubuntu hosts with a single drop-in file: logins with an SSH key only, no root
login, and optionally logins limited to a list of groups.

## What the role enforces

The role writes `/etc/ssh/sshd_config.d/40-km1-hardening.conf` (owner `root:root`, mode `0400`):

| Option | Value | Why |
|---|---|---|
| `PasswordAuthentication` | `no` | No password logins over SSH. |
| `KbdInteractiveAuthentication` | `no` | Keyboard-interactive login goes through PAM, which asks for the password. With only `PasswordAuthentication no`, passwords would still work by this path. |
| `PermitRootLogin` | `no` | `root` cannot log in at all, not even with a key. |
| `PubkeyAuthentication` | `yes` | The default, stated explicitly: keys are the only way in. |
| `AllowGroups` | `ssh_hardening_allow_groups` | Only when the list is not empty (see below). |

The first four options are fixed in the template on purpose. They are not variables, so nothing in the
inventory can weaken them. Changing the policy means changing the role, through a pull request.

### Why the file name starts with `40-`

For each option, sshd uses the first value it reads. Ubuntu's `/etc/ssh/sshd_config` includes
`/etc/ssh/sshd_config.d/*.conf` at the top, and the files are read in lexical order. On first boot cloud-init
writes `50-cloud-init.conf` with `PasswordAuthentication yes`. A file starting with `40-` is read first, so its
values win. The cloud-init file is left in place on purpose and has no effect. A file that sorts before `40-`
(for example from a package) would win over this one, so check the effective values with `sshd -T`, not by
reading the files.

## Requirements

- Ubuntu 24.04: the service is `ssh.service`, started on demand by `ssh.socket`.
- Root access on the managed hosts: the tasks that change the system run with `become: true`.
- `/usr/sbin/sshd` on the managed hosts, used to validate the configuration.

## Role variables

### `ssh_hardening_allow_groups`

Groups whose members may log in over SSH. Default: `[]`.

```yaml
ssh_hardening_allow_groups:
  - ssh_users_group
```

- Empty list: no `AllowGroups` line, so any account with a valid key may log in.
- Non-empty list: an `AllowGroups` line with the groups separated by spaces. An account outside every listed
  group cannot log in, even with a valid key. This includes the account Ansible connects with.

In this repository the list is set in `ansible/group_vars/hypervisors/ssh_hardening.yml`.

## How a change is applied safely

1. **Lockout check.** When `ssh_hardening_allow_groups` is not empty, the role first checks that every listed
   group exists and that `ansible_user` is a member of at least one of them. If not, the play fails before the
   drop-in is written.
   Limitation: the check sees supplementary members only, because `getent group` does not list members whose
   primary group it is, while sshd also accepts the primary group. The check may therefore refuse a list that
   sshd would accept, but it never accepts a list that would lock Ansible out.
2. **Validation of the drop-in.** The template is checked with `sshd -t -f <temporary file>` before it is
   installed. This checks the drop-in as if it were the whole configuration: option names and values. If the
   check fails, the file on the host is not touched.
3. **Reload, not restart.** A changed file notifies a handler that reloads `ssh.service`. systemd first runs
   `sshd -t` on the whole configuration (including `Include`) and sends `SIGHUP` only if that passes. If it
   fails, the running sshd keeps its old configuration and the play fails. The new file is already on disk
   then: fix it before the next reboot or restart of sshd. Open sessions survive a reload.
4. **A failed handler loses its notification.** On the next run the file is already in place, so the task
   reports `ok` and nothing reloads sshd. Reload it once by hand:

   ```
   ansible <host> -b -m ansible.builtin.systemd_service -a "name=ssh state=reloaded"
   ```

`--check` does not run the validation in step 2, because the file is not written in check mode. A clean check
run does not prove that the drop-in is valid.

## Dependencies

None. Group memberships are expected to be managed elsewhere. In this repository the `users` role manages
them and runs first.

## Example playbook

```yaml
- name: Configure Hypervisor machines
  hosts: hypervisors
  connection: ssh
  gather_facts: false
  roles:
    - users
    - ssh_hardening
```

`users` runs first, so the group memberships exist before `AllowGroups` takes effect. How to roll out and
verify a change is described in
[SSH policy on the physical hosts](../../README.md#ssh-policy-on-the-physical-hosts).
