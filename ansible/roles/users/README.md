# users

Manages role groups, user accounts with their SSH public keys, and sudo rules on Linux hosts. Accounts get a locked
password, so they log in with their SSH key only.

## Requirements

- The `ansible.posix` collection, pinned in `ansible/requirements.yml` (see [Setup](../../README.md#setup)).
- Root access on the managed hosts: every task runs with `become: true`.
- `sudo` with `/usr/sbin/visudo` on the managed hosts: each sudo rule is checked with `visudo -cf` before it is
  installed.

## Role variables

All three lists default to empty, so the role changes nothing until they are set. In this repository they are set in
`ansible/group_vars/hypervisors/users.yml`.

### `users_groups`

Role groups (supplementary groups, not system ones), created before the accounts:

```yaml
users_groups:
  - role_group1
  - role_group2
```

### `users_accounts`

| Field | Required | Description |
|---|---|---|
| `name` | yes | Login name. |
| `state` | no | `present` (default) or `absent`. `absent` deletes the account, its home directory, and its primary group. |
| `groups` | when present | Full list of supplementary groups. The account is removed from any group not listed. The primary group (same name as the login) is created automatically. |
| `ssh_public_key` | when present | The only key allowed to log in. Any other key in `authorized_keys` is removed. |

Every group must already exist: either a system group or one listed in `users_groups`.

```yaml
users_accounts:
  - name: jdoe
    groups: ["adm", "role_group1"]
    ssh_public_key: "ssh-ed25519 XYZ...XYZ jdoe@example"
  - name: olduser
    state: absent
```

### `users_sudoers`

One file in `/etc/sudoers.d/` per entry.

| Field | Required | Description |
|---|---|---|
| `name` | yes | File name in `/etc/sudoers.d/`. No `.` and no trailing `~`, or sudo silently ignores the file. |
| `state` | no | `present` (default) or `absent`. `absent` deletes the file. |
| `principal` | when present | Who the rule is for: a group as `"%group"`, or a single account. |
| `commands` | when present | List of full command paths with exact arguments, or `["ALL"]`. Avoid wildcards. |
| `runas` | no | User the commands run as (default: `root`). |
| `nopasswd` | no | `true` to run the commands without a password (default: `false`). Accounts managed by this role have locked passwords, so they need it. |

```yaml
users_sudoers:
  - name: role_group1
    principal: "%role_group1"
    commands: ["/usr/bin/systemctl restart example"]
    nopasswd: true
  - name: oldrule
    state: absent
```

## Removing an account or a sudo rule

Deleting an entry from the list deletes nothing on the hosts, because the role leaves unlisted accounts and rules
alone. Instead, set the entry's `state` to `absent`, run the playbook, and remove the entry only after the run:

```yaml
users_accounts:
  - name: olduser
    state: absent
```

An absent account is deleted together with its home directory and its primary group. Close every session of that
account first, because a running process blocks the deletion. An absent sudo rule deletes its file in
`/etc/sudoers.d/`.

## Dependencies

None.

## Example playbook

`ansible/hypervisors.yml` applies the role to the `hypervisors` group:

```yaml
- name: Configure Hypervisor machines
  hosts: hypervisors
  connection: ssh
  gather_facts: false
  roles:
    - users
```

How to run it, including the bootstrap run, is described in
[Managing accounts and sudo rules on the physical hosts](../../README.md#managing-accounts-and-sudo-rules-on-the-physical-hosts).
