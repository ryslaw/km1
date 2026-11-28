# hypervisor

Turns an Ubuntu host into a KVM hypervisor managed by libvirt: checks that hardware virtualization is available,
installs QEMU and libvirt, gives VM disks their own logical volume registered as the libvirt storage pool
`default`, stops the default NAT network, and checks who is in the `libvirt` group. It creates no VMs.

## What the role does

In this order:

1. **Checks virtualization.** If `hypervisor_kvm_path` (`/dev/kvm`) does not exist, the play stops with a message
   naming the path: enable VT-x in the BIOS and check that the `kvm_intel` module is loaded.
2. **Installs the packages** `qemu-system-x86`, `qemu-utils`, `libvirt-daemon-system`, `libvirt-clients`, and the
   Python bindings `python3-libvirt` and `python3-lxml`, which the `community.libvirt` modules need on the host.
3. **Enables libvirt.** `libvirtd.socket` is enabled and started, `libvirtd.service` is enabled. The socket starts
   the service on demand, so `libvirtd.service` may show as `inactive` while nothing uses it. That is normal.
4. **Creates the storage for VM disks** (see [Storage layout](#storage-layout)).
5. **Defines the storage pool** `hypervisor_pool_name` on that storage, starts it, and enables its autostart.
6. **Stops the default network** `hypervisor_network_name` and disables its autostart
   (see [Default network](#default-network)).
7. **Checks the `libvirt` group** against `hypervisor_libvirt_members` (see [libvirt group](#libvirt-group)).

The pool and the network each use separate tasks for the state and for autostart, because the
`community.libvirt` modules silently ignore `autostart` in a task that also sets `state`.

## Requirements

- Ubuntu 24.04 with hardware virtualization (Intel VT-x, `kvm_intel`).
- Root access on the managed hosts: every task that changes the system runs with `become: true`.
- The collections `community.libvirt`, `community.general` (`lvol`, `filesystem`), and `ansible.posix` (`mount`),
  pinned in `ansible/requirements.yml` (see [Setup](../../README.md#setup)).
- A volume group with free space for the logical volume. In this repository it is on the SSD of each host.

## Role variables

| Variable | Default | Meaning |
|---|---|---|
| `hypervisor_kvm_path` | `/dev/kvm` | Device that exists only when hardware virtualization is available. |
| `hypervisor_vg` | none, required | Volume group for the VM disks. Set per host, because the names differ. |
| `hypervisor_lv_name` | `vmstore` | Logical volume for the VM disks. |
| `hypervisor_lv_size` | none, required | Size of that volume, in `lvol` syntax (for example `200g`). |
| `hypervisor_lv_mountpoint` | `/var/lib/libvirt/images` | Where the volume is mounted, and the path of the pool. |
| `hypervisor_pool_name` | `default` | libvirt storage pool on the mount point. |
| `hypervisor_network_name` | `default` | libvirt network created by the package, which the role stops. |
| `hypervisor_libvirt_members` | `[]` | Accounts expected in the `libvirt` group. The role only checks, it adds nobody. |

In this repository `hypervisor_vg` is set in `ansible/host_vars/ubuntu1.yml` (`ubuntu-vg`) and
`ansible/host_vars/ubuntu2.yml` (`ubuntu-vg-1`). `hypervisor_lv_size` and `hypervisor_libvirt_members` are set in
`ansible/group_vars/hypervisors/hypervisor.yml`.

## Storage layout

| Layer | Value on both hosts |
|---|---|
| Disk | `sdb` (SSD), the system disk. The HDD `sda` is not used. |
| Volume group | `ubuntu-vg` (ubuntu1), `ubuntu-vg-1` (ubuntu2) |
| Logical volume | `vmstore`, 200 GiB |
| File system | ext4 |
| Mount point | `/var/lib/libvirt/images`, owner `root:root`, mode `0711` |
| Mount options | `defaults,nofail,x-systemd.before=libvirtd.service` |
| libvirt pool | `default`, type `dir`, active, autostart on |

- **Why SSD and a separate volume.** VM disks of k3s nodes carry etcd and databases, which wait for every
  `fsync`; on the HDD several VMs at once would stall
  ([k3s disk requirements](https://docs.k3s.io/installation/requirements#disks)). A separate volume also means that
  full VM disks cannot fill `/`. 200 GiB holds a few VMs of 40 GiB and leaves about 174 GiB free in the VG.
- **Why `default`.** `virt-install` and `virt-manager` look for a pool with this name, and create their own when
  they do not find it.
- **Why `0711`.** Only root lists the directory. libvirt sets the owner of each disk image itself when a VM uses it.
- **Mount options.** `nofail` lets the host boot when the volume is missing. `x-systemd.before=libvirtd.service`
  orders the mount before libvirt, so the pool's autostart does not race with the mount. A change of the options
  in `/etc/fstab` notifies a handler that reloads systemd, so the generated mount unit matches the file.
- **Limitation.** `x-systemd.before` only orders, it does not require. If the volume fails to mount, libvirt still
  starts, and the pool points at the empty directory on `/`. After a boot with disk problems, check `findmnt`
  before starting VMs.
- **Free space.** `virsh pool-info default` shows about 195.8 GiB available, `df -h` shows 186G. libvirt does not
  subtract the 5% that ext4 reserves for root, so about 186G is really usable for VM disks.
- **Growing the volume.** Raise `hypervisor_lv_size` and run the playbook: `lvol` grows the volume and
  `filesystem` with `resizefs` grows ext4 online. Shrinking is refused, because the role does not pass `force`.
- **Changing the pool.** `virt_pool` with `state: present` does not compare XML, so a later change of
  `templates/pool.xml.j2` does not change an existing pool. To apply it, run
  `sudo virsh -c qemu:///system pool-destroy default` and `pool-undefine default`, then the playbook.
  Never use `pool-delete`: it deletes the directory.

## Default network

The package defines the NAT network `default` with the bridge `virbr0`, its own DHCP server (dnsmasq), and its own
firewall rules. VMs in km1 are meant to sit in the LAN through a bridge (#56), so the role stops this network and
disables its autostart. It is stopped, not removed: it stays defined, so it can be started by hand for a test
(`sudo virsh -c qemu:///system net-start default`), and the next playbook run stops it again.

## libvirt group

Membership of `libvirt` equals root on the host: a member can start a VM with the host's disk or root file
system attached. The role therefore adds nobody, and only checks. It reads the group with `getent` and stops the
play when the members differ from `hypervisor_libvirt_members`, in either direction. The comparison ignores order.
The message names both lists and the fix.

The check exists because two things change the group without Ansible:

- The `libvirt-daemon-system` package adds every member of `sudo` to `libvirt` on each install and upgrade. A new
  admin therefore appears in `libvirt` after the next package upgrade.
- The `users` role sets the groups of the accounts it manages with `append: false`, so it removes a `libvirt`
  membership that is not in that account's entry. An account that needs `libvirt` must list it there.

Who is in the group and why is recorded in [docs/access-model.md](../../../docs/access-model.md).

## Check mode

- On a new host `--check` stops partway: nothing is installed in check mode, so later tasks find no service, device,
  or libvirt bindings. This is expected and is not masked with `ignore_errors`. After the first real run, `--check`
  passes cleanly.
- Before the first real run, `--check` reports `changed` for the pool tasks without details, because the pool does
  not exist yet.

## Verifying

On each host, after a run:

```sh
findmnt /var/lib/libvirt/images
df -h /var/lib/libvirt/images
sudo stat -c '%U:%G %a' /var/lib/libvirt/images   # root:root 711
systemctl is-enabled libvirtd.service libvirtd.socket
systemctl is-active libvirtd.socket               # active (the service may be inactive)
sudo virsh -c qemu:///system pool-list --all      # default: active, autostart yes
sudo virsh -c qemu:///system net-list --all       # default: inactive, autostart no
ip link show virbr0                               # Device "virbr0" does not exist.
getent group libvirt
```

Always pass `-c qemu:///system`. Without it, a regular user may get the private `qemu:///session` instance
without any message, and see an empty list.

The role's own safeguards can be tested in check mode. Each run must stop with the role's message:

```sh
ansible-playbook -l ubuntu2 ansible/hypervisors.yml --check -e hypervisor_kvm_path=/dev/kvm-missing
ansible-playbook -l ubuntu2 ansible/hypervisors.yml --check -e '{"hypervisor_libvirt_members": []}'
ansible-playbook -l ubuntu2 ansible/hypervisors.yml --check -e '{"hypervisor_libvirt_members": ["ryslaw", "akrawczyk"]}'
```

Pass the list as JSON: with `key=value`, `-e` gives a string, not a list.

The access tests are in [docs/access-model.md](../../../docs/access-model.md#libvirt).

## Dependencies

None. Accounts and groups are managed elsewhere. In this repository the `users` and `ssh_hardening` roles run
first, so a failure in libvirt cannot block a repair of accounts or SSH.

## Example playbook

```yaml
- name: Configure Hypervisor machines
  hosts: hypervisors
  connection: ssh
  gather_facts: false
  roles:
    - users
    - ssh_hardening
    - hypervisor
```
