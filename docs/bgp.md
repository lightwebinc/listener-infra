# BGP on the listener

## Purpose

The listener BGP role has **one purpose**: advertise the listener's own
unicast prefix into the multicast fabric so MLD/PIM can build distribution
trees toward the node in L3 fabrics.

**NACK reply routing matters.** NACK dispatch
(`shard-listener/nack/nack.go`) uses an unconnected UDP socket that also
*receives* the retry endpoint's unicast replies: a retransmit of the
missing frame plus a small ACK/MISS/THROTTLED control response. Those
replies are addressed to the NACK's source address, so that address must
be routable from the retry endpoints. On tunnelled fabrics the kernel's
per-route source pick (e.g. a point-to-point tunnel inner address) can
misroute the reply off the tunnel; a routable unicast identity avoids
this.

The loopback VIP (`bgp_vip` / `bgp_vip6`) is the listener's own unicast
identity inside the fabric.

### IPv4 vs IPv6 advertisements

The fabric is IPv6-only, so `bgp_prefix6` / `bgp_vip6` are the
fabric-relevant fields. `bgp_prefix` / `bgp_vip` (IPv4) remain available
for environments where the BGP session also carries IPv4 toward an
upstream provider; they do not participate in fabric reachability.

## Daemon choice

| Daemon | Distro default | Notes                                                     |
|--------|----------------|-----------------------------------------------------------|
| BIRD2  | Ubuntu, FreeBSD| Default. Minimal, explicit filter syntax.                  |
| FRR    | Ubuntu, FreeBSD| Cisco-like CLI, handy for mixed shops.                     |

Select via `bgp_daemon: bird2` or `bgp_daemon: frr`.

## Variables

| Variable        | Default   | Purpose                                              |
|-----------------|-----------|-------------------------------------------------------|
| `enable_bgp`    | `false`   | Master switch                                         |
| `bgp_daemon`    | `bird2`   | `bird2` or `frr`                                      |
| `bgp_local_as`  | `65002`   | Listener default AS (ingress uses `65001`)            |
| `bgp_peer_as`   | `65000`   | Upstream provider AS                                  |
| `bgp_peer_ip`   | `""`      | IPv4 peer (set per-host)                              |
| `bgp_peer_ip6`  | `""`      | IPv6 peer                                             |
| `bgp_router_id` | host IP   | Router-ID                                             |
| `bgp_prefix`    | `[]`      | IPv4 prefixes to advertise                            |
| `bgp_prefix6`   | `[]`      | IPv6 prefixes to advertise                            |
| `bgp_vip`       | `""`      | IPv4 loopback VIP                                     |
| `bgp_vip6`      | `""`      | IPv6 loopback VIP                                     |
| `bgp_password`  | `""`      | Optional MD5 session password                         |
| `bgp_hold_time` | `90`      |                                                       |
| `bgp_keepalive` | `30`      |                                                       |
| `bgp_health_path` | `/healthz` | Path `bsl-bgp-check.sh` probes; `/readyz` withdraws at drain start |

## Health-driven withdrawal

The role installs three pieces:

- `/usr/local/bin/bsl-bgp-check.sh`: probes
  `http://127.0.0.1:9200{{ bgp_health_path }}` (default `/healthz`) and
  enables/disables the upstream BGP protocol accordingly. Set
  `bgp_health_path: /readyz` to withdraw at drain start (graceful
  anycast shed).
- `bsl-bgp-check.service` + `bsl-bgp-check.timer` (systemd): runs every
  10 s after a 30 s delay on boot.
- `/usr/local/bin/bsl-bgp-withdraw.sh`: called from
  `shard-listener.service` `ExecStop=` to shut down sessions
  before the listener exits.

On FreeBSD the check runs as a `cron` entry (every minute); the withdraw
script is invoked from the rc.d `stop_precmd`.

## Firewall interaction

When `enable_bgp: true`, the `firewall` role permits TCP/179 in both
directions. The perimeter invariant still holds: the fabric interface
carries only multicast data, NACK, ICMPv6, and (now) BGP.

## iBGP upstream peers

Use `bgp-ibgp.yml` against the `bgp_ibgp_nodes` group to configure upstream
routers that accept listener prefixes. Each peer entry is
`{ peer_ip: "", peer_ip6: "", description: "" }`.

## Troubleshooting

```sh
# BIRD2
birdc show protocols
birdc show route export upstream4
birdc show route export upstream6

# FRR
vtysh -c 'show bgp summary'
vtysh -c 'show bgp ipv4 unicast'
vtysh -c 'show bgp ipv6 unicast'

# Systemd timer
systemctl status bsl-bgp-check.timer
journalctl -u bsl-bgp-check.service --since -5min
```
