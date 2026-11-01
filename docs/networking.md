# Networking

The `networking` role configures the **ingress** side of the listener:
the interface on which it joins multicast groups.

## Fabric address family

The multicast fabric is **IPv6-only**. Every multicast group, NACK target,
and listener-to-fabric BGP advertisement uses IPv6. IPv4 is used only
where unavoidable: public-internet management (SSH, metrics scrape) and
optionally the **outer** transport of a GRE tunnel when the fabric edge
is only reachable over the IPv4 Internet.

## Modes

### `ingress_mode: ethernet`

The listener joins IPv6 multicast groups directly on `ingress_iface`.
Deploys:

- `/etc/netplan/60-shard-listener.yaml`: IPv6 on the ingress iface
  (DHCPv4 optional via `ingress_dhcp4`, defaults to `true` so a single-NIC
  host can still reach mgmt over v4; set `false` on multi-NIC or lab hosts
  where the ingress iface is dedicated to the fabric).
- `/etc/sysctl.d/60-shard-listener.conf`: `accept_ra` settings to allow
  IPv6 autoconf, plus `force_mld_version=2` and `mld_max_msf=1024`
  (configurable via `networking_mld_max_msf`). MLDv2 is mandatory when
  the listener runs in `sourceMode=ssm` (see
  [DESIGN.md, Source-Specific Multicast](https://github.com/lightwebinc/bsv-multicast/blob/main/DESIGN.md#source-specific-multicast-ssm)),
  and the kernel default of 64 source filters per socket is below the
  production publisher count; `MCAST_JOIN_SOURCE_GROUP` returns
  `ENOBUFS` once exceeded. Pick `≥ 2 × N_publishers`.

No `ip -6 route add ff00::/8` is needed on the receive side: MLD joins
handle reception regardless of routing table. (The ingress proxy *does*
need this; it is the send side.)

### `ingress_mode: gre`

The listener receives multicast over a GRE tunnel. The **inner** payload
is always IPv6 (the fabric is IPv6-only). The **outer** transport may be
IPv4 or IPv6, controlled by `gre_outer_proto`:

| `gre_outer_proto` | Linux tunnel type | FreeBSD    | Typical use                |
|-------------------|-------------------|------------|-----------------------------|
| `ipv6` (default)  | `ip6gre`          | `gif`/v6   | Fabric edge reachable via v6 |
| `ipv4`            | `gre`             | `gif`/v4   | Fabric edge only reachable over public IPv4 |

Deploys:

- `/etc/netplan/61-shard-listener-gre.yaml`: tunnel definition +
  multicast route on the tunnel.
- When using this mode, set `ingress_iface: gre6-bsl` on each host so the
  listener joins groups on the tunnel interface.

Variables:

| Variable           | Meaning                                                     |
|--------------------|--------------------------------------------------------------|
| `gre_outer_proto`  | `ipv6` or `ipv4`; chooses the outer-transport address family |
| `gre_local_ip6`    | Local IPv6 outer endpoint (when `gre_outer_proto=ipv6`)       |
| `gre_remote_ip6`   | Remote IPv6 outer endpoint (when `gre_outer_proto=ipv6`)      |
| `gre_local_ip4`    | Local IPv4 outer endpoint (when `gre_outer_proto=ipv4`)       |
| `gre_remote_ip4`   | Remote IPv4 outer endpoint (when `gre_outer_proto=ipv4`)      |
| `gre_iface`        | Tunnel iface name (default `gre6-bsl`)                        |
| `gre_inner_ipv6`   | IPv6 address on the tunnel interface                          |

## Multicast route prefix

`mc_route_prefix` defaults to the FF0x::/16 corresponding to `mc_scope`:

| Scope    | Prefix      |
|----------|-------------|
| `link`   | `ff02::/16` |
| `site`   | `ff05::/16` |
| `org`    | `ff08::/16` |
| `global` | `ff0e::/16` |

Override `mc_route_prefix` when using an assigned narrower prefix (in
conjunction with `mc_group_id`).

## BGP VIP

When `enable_bgp: true` and `bgp_vip` / `bgp_vip6` is set, a third netplan
file is deployed:

- `/etc/netplan/62-shard-listener-vip.yaml`: VIP on loopback (`lo`).

The VIP is this listener's unicast identity inside the fabric.

## FreeBSD

On FreeBSD the role edits `/etc/rc.conf` directly:

- `ifconfig_<iface>` / `ifconfig_<iface>_ipv6` for ethernet
- `cloned_interfaces="gif0"` + `ifconfig_gif0*` for GRE mode
- `ifconfig_lo0_alias0` / `alias1` for BGP VIPs
- `ipv6_route_bsl_mcast` for the multicast route
- Restart via `service netif restart`

## Verifying multicast receive

```sh
# Linux: show joined groups
ip -6 maddr show dev eth0

# Inspect live receive
tcpdump -i eth0 -nn 'udp and ip6 multicast and port 9001'

# FreeBSD
netstat -g -f inet6
```

## Dedup backend connectivity

The egress dedup and ingress-mark backends (`egress_dedup_backend` /
`ingress_set_backend`) are out-of-band TCP services on the management network:
Redis/Valkey/Dragonfly on 6379, or Aerospike Community Edition on 3000. They are
addressed independently of each other and of the multicast fabric. Backend
errors fail open (the listener forwards and records a metric). See
[shard-common cache backend](https://github.com/lightwebinc/shard-common/blob/main/docs/cache-backend.md).

The `firewall` role renders outbound TCP allow rules (non-fabric
interfaces only) for the ports in `egress_dedup_redis_addr`,
`egress_dedup_aerospike_hosts`, `ingress_set_redis_addr`, and
`ingress_set_aerospike_hosts`. After changing a backend address, re-run
with `--tags firewall` or the connection will be dropped by the
default-deny output policy.
