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
  listener joins groups on the tunnel interface. On FreeBSD the role always
  names the tunnel `gif0` and does not read `gre_iface`, so set
  `ingress_iface: gif0` there.

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

On FreeBSD hosts `link` installs no multicast route: FreeBSD reserves
`ff02::/16` (at boot `rc.d/routing` installs `ff02::/16 ::1 -reject`), so a
route for it can never be installed. The shard-listener needs none: it joins
its groups on the ingress interface by index, and its multicast egress sets
`IPV6_MULTICAST_IF` (on `mc_egress_iface`, by default the ingress interface),
so FreeBSD picks that interface without a route lookup (`ip6_output()`,
`in6_src.c` `selectroute()`), and a single-segment link-scope fabric works.
The role skips the route, removes a route line an earlier converge wrote for
another scope, and prints a warning; a sender that does not set
`IPV6_MULTICAST_IF` hits the reject route. The same applies to an
`mc_route_prefix` of `ff02::/16` in any spelling.

## BGP VIP

When `enable_bgp: true` and `bgp_vip` / `bgp_vip6` is set, a third netplan
file is deployed:

- `/etc/netplan/62-shard-listener-vip.yaml`: VIP on loopback (`lo`).

The VIP is this listener's unicast identity inside the fabric.

## FreeBSD

On FreeBSD the role edits `/etc/rc.conf` directly:

- `ifconfig_<iface>` / `ifconfig_<iface>_ipv6` for ethernet
- `ifconfig_gif0*` for GRE mode, with `gif0` added to `cloned_interfaces`
  (interfaces already listed stay)
- `ifconfig_lo0_alias0` / `alias1` for BGP VIPs
- `ipv6_route_bsl_mcast` for the multicast route, with `bsl_mcast` added to
  `ipv6_static_routes` (names already listed stay) so a boot installs it
- Restart of the changed interface only, by name (`service netif restart gif0`
  in GRE mode, which creates it; the ingress interface in ethernet mode), when
  its configuration above changed or `gif0` does not run it: a converge that
  changes nothing leaves `gif0`, the listener bound to it and every other
  interface alone. What each converge applied is recorded in
  `/var/db/shard-listener-netif.json`, so a converge stopped between its
  rc.conf writes and the restart is finished by the next one. A host without
  that record (the first converge with this role) restarts only an interface
  that fails its live check (`gif0` not up with its tunnel and inner address;
  the ingress interface down, or its rc.conf lines changed by this converge),
  so a node an earlier version set up keeps running untouched. Every
  converge also compares the running `gif0` with its configuration (up, tunnel
  endpoints and inner address, by value) and restarts it when they differ;
  after a restart it stops with an error if they still differ, because
  `service netif restart` exits 0 even when an `ifconfig` it runs fails
- The BGP VIPs, changed live on `lo0`, which is never restarted: a missing VIP
  is added (`ifconfig lo0 inet VIP/32 alias`, `ifconfig lo0 inet6 VIP6
  prefixlen 128 alias`), one the role no longer gives is removed (`-alias`)
  with its rc.conf line, and 127.0.0.1, ::1 and the other VIP stay
- The live multicast route, added after the restart; a route for the prefix
  that already goes through another interface (`ingress_iface` or
  `ingress_mode` changed while the old interface stays up) is moved there with
  `route change`

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
