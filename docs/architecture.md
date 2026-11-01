# Architecture

`listener-infra` is the deployment/operations repo for
[`shard-listener`](https://github.com/lightwebinc/shard-listener), the
inverse side of the `ingress-infra` / `shard-proxy` pipeline. Where
the ingress proxy _sends_ sharded transaction frames into an IPv6 multicast
fabric, the listener _receives_ those frames, filters by shard / subtree, and
forwards matching frames as unicast to downstream consumers and/or re-emits
them via multicast egress for domain bridging.

```
       ┌───────────────┐     IPv6 multicast fabric      ┌────────────────┐
       │ shard-proxy   │ ───►  (FF0x::/16, UDP 9001)  ──► shard-listener │
       │ (ingress)     │                                │                │
       └───────────────┘                                └──────┬─────────┘
                                                               │ egress
                                                      ┌────────┼─────────┐
                                                      │         ▼        │
                                                      │ unicast (UDP/TCP)│─▶ consumer (egress_addr)
                                                      │ multicast (opt.) │─▶ bridged domain
                                                      └──────────────────┘

                NACK (UDP, request/reply):
                  shard-listener ──► retry-endpoints
                  (unicast retransmit + ACK/MISS/THROTTLED replies return)
```

## Protocol details

Deploys `shard-listener`, which receives BRC-124/BRC-128 transaction frames,
BRC-142 bundle (coalesced) frames, BRC-130 fragments, BRC-131 block control,
BRC-132 subtree data, BRC-134 anchor frames, and BRC-139 shard manifests
on the multicast fabric. Frame formats, filtering, gap tracking, NACK/retransmission, and
beacon discovery are documented in the service and project repos:

- [shard-listener: Architecture](https://github.com/lightwebinc/shard-listener/blob/main/docs/architecture.md)
- [shard-listener: Configuration](https://github.com/lightwebinc/shard-listener/blob/main/docs/configuration.md)
- [bsv-multicast: DESIGN.md](https://github.com/lightwebinc/bsv-multicast/blob/main/DESIGN.md)
- BRC specifications: `bsv-multicast/docs/brc-{124,126,127,128,129,130,131,132,133,134,135,139,142,143,144,148,149}-*.md`

## Data plane

1. **Ingress interface** (`ingress_iface` / `gre6-bsl`) joins a **subset**
   of the per-shard IPv6 multicast groups via MLD; see
   [Group subscription](#group-subscription) below. The listener receives
   frames directly on this interface; no routing-table entry is required
   on the receive side (unlike the proxy's send path, which needs
   `ff00::/8` routed to `egress_iface`).
2. **User-space filters** provide a second pass (shard filter + subtree filter).
3. **NACK tracker** detects sequence gaps and dispatches retransmission
   requests to configured `retry_endpoints`.
4. **Downstream egress** forwards accepted frames via unicast (UDP or TCP)
   and/or multicast egress (domain bridging).

### Group subscription

The total number of groups is `2^shard_bits` (e.g. `shard_bits=2` → 4
groups). The set of groups actually joined is:

| `shard_include` value | Groups joined via MLD         |
| --------------------- | ----------------------------- |
| unset / empty         | **all** `2^shard_bits` groups |
| `"0,1"`               | only groups 0 and 1           |
| `"3"`                 | only group 3                  |

The kernel's MLDv1/v2 stack means unjoined groups are never delivered to
the socket in the first place.

> **Best practice:** always set `shard_include` in production. A listener
> with `shard_include=""` joins every group on the fabric and receives
> every frame, which is rarely what you want and puts unnecessary load on
> the NIC, kernel, and parser.

## Control plane

- **BGP** (optional) advertises _this listener's own unicast prefix_ into the
  fabric so MLD/PIM can build distribution trees toward the node in L3
  fabrics. The loopback VIP (`bgp_vip`/`bgp_vip6`) is the listener's
  identity.
- **Metrics** (Prometheus + OTLP) exposed on `:9200/healthz`, `:9200/readyz`,
  `:9200/metrics`. `OTLP_INTERVAL` controls the push cadence (default 30 s).
- **Firewall** (nftables on Linux, pf on FreeBSD) enforces the
  multicast-fabric perimeter. See `security.md`.

## How this repo is organised

| Layer     | Location     | Purpose                                          |
| --------- | ------------ | ------------------------------------------------ |
| Ansible   | `ansible/`   | Roles + playbooks for provisioning               |
| Terraform | `terraform/` | Node module + AWS / generic examples             |
| Docs      | `docs/`      | Architecture, ops, security, BGP, networking, OS |

## Relationship to `ingress-infra`

| Concern                                       | `ingress-infra` (proxy) | `listener-infra` (this repo)    |
| --------------------------------------------- | ------------------------- | --------------------------------- |
| Direction                                     | TX onto fabric            | RX from fabric                    |
| Primary iface                                 | `egress_iface` (send)     | `ingress_iface` (receive)         |
| Needs `ExecStartPre ip -6 route add ff00::/8` | **Yes**                   | **No** (MLD-only)                 |
| Default AS                                    | `65001`                   | `65002`                           |
| Metrics port                                  | `:9100`                   | `:9200`                           |
| Listen port                                   | `8725` UDP                | `9001` UDP (matches proxy egress) |
| BGP role                                      | Fabric reachability       | Listener-reachability **only**    |
| Firewall role                                 | n/a                       | Built-in `firewall` Ansible role  |

Shared patterns: Go toolchain install, systemd unit hardening, netplan-based
interface config on Ubuntu/Debian, rc.d on FreeBSD, BGP via BIRD2 or FRR,
management-plane helpers (`bsp-*` / `bsl-*`).
