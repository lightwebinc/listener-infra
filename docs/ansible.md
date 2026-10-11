# Ansible usage

Shared workflow, requirements, variable precedence, version pins, the `common`
and `perf-tuning` roles, stat-guarded builds and known issues are documented
once in [Ansible operations](https://github.com/lightwebinc/bsv-multicast/blob/main/docs/infra/ansible-operations.md). This page covers what
is specific to `shard-listener`.

## Layout

```
ansible/
  site.yml                  Main playbook (listener_nodes group)
  bgp-ibgp.yml              Upstream iBGP peer playbook (bgp_ibgp_nodes group)
  requirements.yml          Collection dependencies (community.general, ansible.posix)
  group_vars/all.yml        Default variables for all listener nodes
  inventory/hosts.example.yml
  roles/
    common/                 Base OS deps + Go toolchain
    perf-tuning/            High-PPS host tuning (UDP buffers, busy-poll, C-states)
    shard-listener/         Build + systemd / rc.d unit + config
    networking/             Interface / multicast route / VIP config
    firewall/               nftables (Linux) / pf (FreeBSD) perimeter
    bgp/                    BIRD2 or FRR + health-check + withdraw
    bgp-ibgp/               Upstream iBGP peer role (optional)
```

## Role ordering

`site.yml` runs roles in this order:

1. `common` — install packages, Go toolchain, journald cap + disk-reclaim timer (Linux); opt-in `--tags os_update` patching
2. `perf-tuning` — high-PPS host tuning (UDP buffers, busy-poll, C-states)
3. `shard-listener` — build binary, install service
4. `networking` — configure `ingress_iface`, GRE, BGP VIP
5. `firewall` *(when `enable_firewall: true`)* — lock down the fabric perimeter
6. `bgp` *(when `enable_bgp: true`)* — BIRD2 or FRR

Firewall runs **after** networking so interface names resolve, and **before**
BGP so TCP/179 is permitted when the daemon starts.

## Per-host overrides

Because `group_vars/all.yml` has higher precedence than inventory group vars,
the following must be set on each host (not in group vars):

- `ingress_iface`
- `num_workers` — leave at the default `1` for multicast receive (see note below)
- `mgmt_cidrs_v4`, `mgmt_cidrs_v6` — firewall allow-list; `group_vars/all.yml` defaults to empty lists
- `ansible_host`, `ansible_user`, `ansible_ssh_private_key_file`
- `bgp_router_id`, `bgp_peer_ip`, `bgp_peer_ip6` (when `enable_bgp` is true)

> **`num_workers` and multicast:** Linux delivers multicast datagrams to every
> socket in a SO_REUSEPORT group — it does not load-balance them. Running
> `num_workers > 1` causes each frame to be processed and forwarded N times,
> doubling (or more) all metrics and egress traffic. `group_vars/all.yml` already
> defaults to `1`; raise it only on a host running `listener_mode: delivery`,
> where ingest is unicast and SO_REUSEPORT does load-balance.

## Common operations

```sh
# Re-deploy listener code without touching firewall/networking
ansible-playbook site.yml --tags listener

# Update firewall after changing retry_endpoints
ansible-playbook site.yml --tags firewall

# Rotate BGP peer password
ansible-playbook site.yml --tags bgp -e bgp_password=...

# Apply high-PPS host tuning (UDP buffers, busy-poll, C-states, irqbalance)
ansible-playbook site.yml --tags perf-tuning

# Target one host
ansible-playbook site.yml -l listener-01
```

## Service variables

Every variable in `group_vars/all.yml`, with its default.

### shard-listener source and build

| Variable | Default | Notes |
|---|---|---|
| `listener_repo` | `https://github.com/lightwebinc/shard-listener.git` | Git source of the service |
| `listener_version` | pinned in `group_vars/all.yml` | Release tag to build; see [version pins](https://github.com/lightwebinc/bsv-multicast/blob/main/docs/infra/ansible-operations.md#version-pins) |
| `listener_install_dir` | `/opt/shard-listener` | Clone and build directory |
| `listener_bin_dir` | `/usr/local/bin` | Binary install directory |
| `listener_user` | `shard-listener` | Service user |
| `listener_group` | `shard-listener` | Service group |
| `listener_local_binary` | `""` | Pre-built local binary to push; empty = clone and build on the host |
| `listener_force_build` | `false` | Rebuild even when a binary already exists |
| `go_version` | pinned in `group_vars/all.yml` | Go toolchain; must be at or above the `go` directive in the service go.mod at the pinned tag |
| `go_install_dir` | `/usr/local/go` | Go toolchain install directory |

### Listener runtime configuration

| Variable | Default | Notes |
|---|---|---|
| `listen_port` | `9001` | Matches proxy's `egress_port` |
| `beacon_enabled` | `true` | Join beacon group and discover retry endpoints dynamically |
| `beacon_port` | `9300` | UDP port for ADVERT beacons (must match nack_port on retry endpoints) |
| `beacon_scope` | `site` | Multicast scope for beacon group join: link \| site \| org \| global |
| `subtree_groups` | `""` | Comma-separated 32-char hex GroupIDs; empty = disabled |
| `subtree_group_default_ttl` | `900s` | TTL for entries whose announcement carries TTL=0 |
| `announce_scope` | `site` | Multicast scope(s) for the control group join |
| `sender_include` | `""` | IPv6 CIDRs of trusted announcement senders; empty = all |
| `sender_exclude` | `""` | IPv6 CIDRs to reject before include check |
| `shard_bits` | `2` | Must match proxy |
| `mc_scope` | `site` | link \| site \| org \| global |
| `mc_group_id` | `0x000B` | IANA group-id (default 0x000B = IANA Bitcoin) |
| `listener_mode` | `collapsed` | Or `receiver` / `delivery` (P3b role split) |
| `delivery_addrs` | `""` | receiver mode: comma-separated delivery host:port fan-out (empty = egress_addr) |
| `source_mode` | `ssm` | Default. Needs MLDv2 sysctls + `ssm_bootstrap_*`; `asm` is the lab fallback |
| `ssm_bootstrap_beacon` | `""` | SSM: CSV of retry-endpoint sources for the beacon group join |
| `ssm_bootstrap_manifest` | `""` | SSM: CSV of shard-manifest sources for the manifest group join |
| `ssm_bootstrap_subtree_announce` | `""` | SSM: CSV of subtree-announce emitter sources |
| `ssm_bootstrap_refresh` | `30s` | SSM: DNS re-resolve interval for bootstrap entries |
| `shard_include` | `""` | Comma-separated shard indices, e.g. "0,1" (empty = join ALL groups) |
| `subtree_include` | `""` | Comma-separated hex subtree IDs to allow (V2 only) |
| `subtree_exclude` | `""` | Comma-separated hex subtree IDs to drop (V2 only) |
| `beef_topics` | `""` | mode 2: comma-separated topic names / 64-hex TopicIDs |
| `beef_groups` | `""` | mode 3: comma-separated plane-relative indices, e.g. "0,1,2,3" |
| `beef_shard_bits` | `0` | 0 = single-group plane; MUST match the proxies |
| `beef_versions` | `""` | optional object-version filter (empty = accept all) |
| `beef_verify_content` | `false` | recompute ContentID (SHA-256d) on reassembly and drop on mismatch |
| `egress_addr` | `127.0.0.1:9100` | Downstream consumer |
| `egress_proto` | `udp` | Or `tcp` |
| `strip_header` | `false` | false = forward whole frames (header retained); binary/chart default is true (payload-only) |
| `retry_endpoints` | `""` | `"host:port,host:port"` |
| `nack_jitter_max` | `200ms` |  |
| `nack_backoff_max` | `5s` |  |
| `nack_max_retries` | `8` | Budget for 3 beacon + 3 static-seed entries with headroom |
| `nack_gap_ttl` | `10m` |  |
| `nack_backoff_base` | `500ms` | NACK_BACKOFF_BASE: base retry delay, doubles per failed round |
| `nack_max_flows` | `100000` | NACK_MAX_FLOWS: tracked per-source flow cap (0 = unbounded) |
| `nack_max_forward_jump` | `4096` | NACK_MAX_FORWARD_JUMP: SeqNum jump that re-baselines a flow |
| `nack_tail_probe` | `true` | NACK_TAIL_PROBE: probe the next SeqNum on a quiet flow |
| `nack_tail_probe_idle_factor` | `4.0` | NACK_TAIL_PROBE_IDLE_FACTOR |
| `nack_tail_probe_min_idle` | `500ms` | NACK_TAIL_PROBE_MIN_IDLE |
| `nack_tail_probe_max_misses` | `3` | NACK_TAIL_PROBE_MAX_MISSES |
| `retry_tee_listen` | `""` | Optional `RETRY_TEE`: mirror received frames to a co-resident retry-endpoint `-tee-listen`; rendered only when set |
| `subtree_data_enabled` | `false` | BRC-132 subtree data reception (joins the 0xFFFB announce group). |
| `manifest_consumer_enabled` | `false` | BRC-139 manifest consumer (MANIFEST_CONSUMER_ENABLED) and additive auto-join from manifests (SHARD_INCLUDE_FROM_MANIFEST; needs the consumer). |
| `shard_include_from_manifest` | `false` |  |
| `num_workers` | `1` | Already `1` in `group_vars/all.yml`; raise only for `listener_mode: delivery` (see note) |
| `metrics_addr` | `:9200` | Listener metrics (not :9100 — avoids collision with proxy) |
| `otlp_endpoint` | `""` | OTLP gRPC push; empty disables |
| `otlp_interval` | `30s` | OTLP metric export cadence |
| `log_format` | `json` | text \| json (json for fleet aggregation) |
| `log_level` | `info` | debug\|info\|warn\|error; runtime-togglable via POST /loglevel + SIGHUP |
| `trace_sampling` | `0` | 0..1 trace head sampling (0 = off; exports via otlp_endpoint) |
| `drain_timeout` | `0s` | Pre-shutdown drain; set ≥ LB check interval in prod |
| `instance_id` | `""` | OTel service.instance.id; empty = hostname |
| `listener_debug` | `false` |  |
| `verify_payload_hash` | `false` | Verify SHA256d(payload)==TxID on V2 frames; drop on mismatch |
| `require_block_pow` | `true` | BRC-131 announce PoW gate; **default ON** (bin parity) |
| `min_pow_bits` | `0` | Compact nBits floor; `0` = header self-consistency only |
| `mc_egress_enabled` | `false` | Multicast egress (domain bridging) — disabled by default |
| `mc_egress_iface` | `""` |  |
| `mc_egress_port` | `0` |  |
| `mc_egress_scope` | `""` |  |
| `mc_egress_group_id` | `""` |  |
| `mc_egress_hoplimit` | `1` |  |
| `header_egress_enabled` | `false` | BRC-135 block-header re-emission to a unicast/TCP sink |
| `header_egress_addr` | `127.0.0.1:9101` |  |
| `header_egress_proto` | `udp` |  |
| `header_mc_egress_enabled` | `false` | BRC-135 block-header re-emission to a multicast group |
| `header_mc_egress_iface` | `""` | NIC for BRC-135 egress; defaults to `ingress_iface` |
| `header_mc_egress_port` | `0` |  |
| `header_mc_egress_scope` | `""` |  |
| `header_mc_egress_group_id` | `""` |  |
| `header_mc_egress_hoplimit` | `1` |  |
| `deployment_id` | `""` | Per-deployment egress TxID dedup. HA siblings share deployment_id; distinct deployment_ids race independently. Empty deployment_id/node_id → derived from hostname at runtime. |
| `node_id` | `""` |  |
| `egress_dedup_backend` | `""` | redis\|aerospike\|memory\|none |
| `egress_dedup_redis_addr` | `""` | Per-deployment egress dedup; empty = LRU-only |
| `egress_dedup_aerospike_hosts` | `""` | comma-separated host:port (required when backend=aerospike) |
| `egress_dedup_aerospike_namespace` | `cache` |  |
| `egress_dedup_aerospike_set` | `bsl-egr` |  |
| `egress_dedup_prefix` | `bsl:egr:` | Redis key prefix; deployment-id appended downstream |
| `egress_dedup_ttl_redis` | `60s` | tier-2 entry TTL |
| `egress_dedup_local_cap` | `1048576` | tier-1 LRU capacity; 0 = disable egress dedup |
| `egress_dedup_cap` | `0` | 0 = disabled |
| `egress_dedup_ttl` | `2s` | max age of a remembered tuple |
| `ingress_set_backend` | `""` | redis\|aerospike\|memory\|none |
| `ingress_set_redis_addr` | `""` | Courtesy mark to proxy's `bsp:tx:` namespace |
| `ingress_set_aerospike_hosts` | `""` | comma-separated host:port |
| `ingress_set_aerospike_namespace` | `cache` |  |
| `ingress_set_aerospike_set` | `bsp-tx` |  |
| `ingress_set_prefix` | `bsp:tx:` | **Must match proxy's `txid_dedup_prefix`** |
| `ingress_set_ttl` | `10m` |  |
| `ingress_set_local_cap` | `1048576` |  |

### Firewall perimeter (multicast-fabric isolation)

| Variable | Default | Notes |
|---|---|---|
| `enable_firewall` | `true` | Set `false` for labs only |
| `mgmt_cidrs_v4` | `[]` | **Must be set per-host**; SSH + metrics allow-list |
| `mgmt_cidrs_v6` | `[]` | SSH / metrics scrape allow-list (IPv6). |

### Networking (ingress / multicast-receive side)

| Variable | Default | Notes |
|---|---|---|
| `ingress_mode` | `ethernet` | Or `gre` (then set `ingress_iface: gre6-bsl`) |
| `ingress_iface` | `eth0` | **Must be set per-host** (group_vars precedence) |
| `mc_route_prefix` | `""` | Multicast route prefix for the ingress interface. Empty = auto-derive from mc_scope (link=ff02::/16, site=ff05::/16, etc.) |
| `gre_outer_proto` | `ipv6` | ipv6 \| ipv4 — outer transport for the GRE tunnel |
| `gre_iface` | `gre6-bsl` | Tunnel interface name |
| `gre_inner_ipv6` | `""` | IPv6 address/prefix assigned to the tunnel iface |
| `gre_local_ip6` | `""` | Local outer endpoint (ipv6 outer) |
| `gre_remote_ip6` | `""` | Remote outer endpoint (ipv6 outer) |
| `gre_local_ip4` | `""` | Local outer endpoint (ipv4 outer) |
| `gre_remote_ip4` | `""` | Remote outer endpoint (ipv4 outer) |

### BGP (optional)

| Variable | Default | Notes |
|---|---|---|
| `enable_bgp` | `false` |  |
| `bgp_daemon` | `bird2` | bird2 \| frr |
| `bgp_prefix` | `[]` | IPv4 prefixes announced by this node |
| `bgp_vip` | `""` | IPv4 loopback VIP (this listener's identity) |
| `bgp_prefix6` | `[]` | IPv6 prefixes announced by this node |
| `bgp_vip6` | `""` | IPv6 loopback VIP (this listener's identity) |
| `bgp_local_as` | `65002` | Listener default AS (ingress uses 65001) |
| `bgp_peer_as` | `65000` |  |
| `bgp_peer_ip` | `""` |  |
| `bgp_peer_ip6` | `""` |  |
| `bgp_router_id` | (templated) |  |
| `bgp_hold_time` | `90` |  |
| `bgp_keepalive` | `30` |  |
| `bgp_password` | `""` |  |
| `bgp_health_path` | `/healthz` | Path bsl-bgp-check probes; `/readyz` for graceful drain |
| `bgp_ibgp_peers` | `[]` | iBGP peers (used by bgp-ibgp role, playbook: bgp-ibgp.yml) Each entry: { peer_ip: "", peer_ip6: "", description: "" } |

