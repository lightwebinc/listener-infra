# FreeBSD 14

Packages, rc.d and rc.conf conventions, pf usage, `gif0` tunnels, BGP daemon
paths and generic diagnostics shared by all infra repositories are in the
canonical [FreeBSD 14 notes](https://github.com/lightwebinc/bsv-multicast/blob/main/docs/infra/os/freebsd-14.md). This page lists what is
specific to `shard-listener`.

## Service

```sh
sysrc shard_listener_enable=YES
service shard_listener status
service shard_listener restart
tail -f /var/log/shard_listener.log
```

## File locations

| Path | Content |
|---|---|
| `/usr/local/etc/rc.d/shard_listener` | rc.d script (template `shard_listener.rc.j2`) |
| `/usr/local/etc/shard-listener.conf` | Environment config |
| `/etc/pf.anchors/shard-listener` | pf anchor (`pfctl -a shard-listener -sr`) |
| `/usr/local/bin/bsl-bgp-check.sh` | BGP health check, run from cron every minute |

`/etc/rc.conf` also carries `ipv6_route_bsl_mcast` (multicast route on the
ingress interface) and the `ifconfig_lo0_alias*` BGP VIPs.

## Diagnostics

```sh
tcpdump -i vtnet0 -nn 'udp and ip6 multicast and port 9001'
```

## Known issues

- Set `ingress_iface` per host to the FreeBSD name (`vtnet0`, `em0`, ...).
