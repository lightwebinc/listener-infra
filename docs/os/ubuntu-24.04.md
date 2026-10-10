# Ubuntu 24.04 (Noble)

Packages, systemd and netplan conventions, BGP daemon paths and generic
diagnostics shared by all infra repositories are in the canonical
[Ubuntu 24.04 notes](https://github.com/lightwebinc/bsv-multicast/blob/main/docs/infra/os/ubuntu-24.04.md). This page lists what is specific to
`shard-listener`.

## Service

```sh
systemctl status shard-listener
systemctl restart shard-listener
journalctl -u shard-listener -f

# BGP health-check timer (when enable_bgp: true)
systemctl status bsl-bgp-check.timer
journalctl -u bsl-bgp-check.service --since -5min
```

## File locations

| Path | Content |
|---|---|
| `/etc/systemd/system/shard-listener.service` | systemd unit (template `shard-listener.service.j2`) |
| `/etc/shard-listener/config.env` | Environment config |
| `/etc/netplan/60-shard-listener.yaml` | Ingress ethernet |
| `/etc/netplan/61-shard-listener-gre.yaml` | GRE6 tunnel (`ingress_mode: gre`) |
| `/etc/netplan/62-shard-listener-vip.yaml` | BGP VIP on loopback |
| `/etc/sysctl.d/60-shard-listener.conf` | Sysctls |
| `/etc/nftables.d/60-shard-listener.nft` | Firewall ruleset (`nft list table inet shard-listener`) |

## Diagnostics

```sh
tcpdump -i eth0 -nn 'udp and ip6 multicast and port 9001'   # data receive
```

## Known issues

- **`ingress_iface` precedence.** Set it per host, not in group vars.
