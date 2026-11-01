# Security model

This document describes the multicast-fabric perimeter enforced by the
`firewall` Ansible role.

## Threat model

The listener sits inside a service-provider multicast fabric. The fabric is
a shared L2/L3 domain: any host with a path to it can, in principle, send
unicast traffic to any other host on it. Without perimeter enforcement a
listener could become a pivot to consumer / management networks, and
downstream consumer traffic could leak back into the fabric.

The invariant this repo enforces is:

> **The fabric interface carries only (a) inbound multicast group data and
> beacon ADVERTs, (b) outbound NACK datagrams to configured retry
> endpoints, and (c) inbound unicast NACK replies (retransmit +
> ACK/MISS/THROTTLED) from those endpoints.**
>
> All other traffic on the fabric interface is dropped. No IP forwarding
> is permitted between the fabric interface and any other interface.

## Allow-list summary

| Direction | Interface              | Protocol / Port / Address                                   |
|-----------|------------------------|--------------------------------------------------------------|
| In        | fabric (`ingress_iface` / `gre6-bsl`) | UDP `ff00::/8` → `LISTEN_PORT` (9001 default)  |
| In        | fabric                 | UDP `ff00::/8` → `BEACON_PORT` (9300 default; retry-endpoint ADVERTs) |
| In        | fabric                 | UDP unicast from `RETRY_ENDPOINTS` (NACK retransmit + ACK/MISS/THROTTLED replies) |
| In        | fabric                 | ICMPv6 (NDP, MLD, diag); ICMPv4 (echo, dest-unreach)         |
| Out       | fabric                 | UDP → `RETRY_ENDPOINTS` (NACK dispatch)                      |
| Out       | fabric                 | ICMPv6 (NDP, MLD reports)                                    |
| In        | non-fabric             | TCP/22 + metrics port, from `mgmt_cidrs_v4/v6`               |
| Out       | non-fabric             | `EGRESS_PROTO` → `EGRESS_ADDR` (downstream forward)          |
| Out       | non-fabric             | DNS (53), NTP (123), HTTP/S (80/443) for OS updates          |
| Out       | non-fabric             | TCP → dedup / ingress-mark backend ports (only when configured) |
| In / Out  | any                    | BGP (TCP/179), **only when `enable_bgp: true`**              |
| Forward   | any                    | Always dropped                                               |

## Implementation

### Linux (nftables)

Ruleset template: `ansible/roles/firewall/templates/shard-listener.nft.j2`.

Installed as `/etc/nftables.d/60-shard-listener.nft` and sourced from
`/etc/nftables.conf` via a managed `include` block. `nftables.service` is
enabled at boot.

Verify:

```sh
nft list table inet shard-listener
nft -c -f /etc/nftables.d/60-shard-listener.nft     # validate syntax
```

### FreeBSD (pf)

Anchor template: `ansible/roles/firewall/templates/shard-listener.pf.conf.j2`.

Installed as `/etc/pf.anchors/shard-listener` and loaded via a managed
anchor block in `/etc/pf.conf`.

Verify:

```sh
pfctl -sr
pfctl -a shard-listener -sr
```

## Operational notes

- **Adding a retry endpoint.** Edit `retry_endpoints` in inventory (or
  per-host vars) and re-run `ansible-playbook site.yml --tags firewall`.
  The template resolves hostnames at play time; after DNS changes, re-run
  the firewall role.
- **Adding a management CIDR.** Extend `mgmt_cidrs_v4` / `mgmt_cidrs_v6`
  and re-run with `--tags firewall`.
- **Enabling BGP after deploy.** Set `enable_bgp: true`; re-run with
  `--tags firewall,bgp`. The firewall role must run before the BGP daemon
  starts, otherwise TCP/179 will be dropped.
- **Disabling the role for labs.** Set `enable_firewall: false` in
  inventory. The role is skipped entirely. **Not recommended in
  production.**

## What this role does *not* protect against

- Compromise of a legitimate `retry_endpoint`: the listener dispatches
  NACK datagrams to it, so it is trusted by design.
- A consumer that pivots through the `egress_addr` target host: downstream
  topology protection is out of scope here; use network segmentation
  upstream.
- Multicast flooding: under `source_mode: asm` the listener accepts all
  UDP on `LISTEN_PORT` from any multicast source on the fabric iface. The
  default `source_mode: ssm` (MLDv2 source-include joins) restricts
  reception to discovered/bootstrap sources; see `source_mode` in
  `group_vars/all.yml` and the MLDv2 sysctl notes in
  [`networking.md`](networking.md).

## Cloud SGs vs host firewall

The Terraform AWS example (`terraform/examples/aws-ec2/`) creates a Security
Group acting as the cloud-level perimeter. This SG and the host-level
nftables policy are complementary:

- **SG** = coarse edge at the hypervisor, decoupled from interface names.
  Denies anything outside `fabric_source_cidrs_*`, SSH CIDRs, metrics CIDRs,
  BGP.
- **Host firewall** = fine-grained, interface-aware, enforces the
  "fabric iface is multicast-only" invariant that SGs cannot express
  (because SGs don't distinguish interfaces on a multi-homed instance).

Keep both aligned. If you widen one, re-evaluate the other.
