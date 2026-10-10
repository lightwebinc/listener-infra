# Terraform usage

Module and example structure, requirements, the Ansible hand-off, running the
`generic` and `aws-ec2` examples and adding a cloud are documented once in
[Terraform layout](https://github.com/lightwebinc/bsv-multicast/blob/main/docs/infra/terraform-layout.md). This page covers what is specific
to listener-infra.

## Modules

- `modules/listener-node`: one listener host. Inputs cover the full listener
  configuration (listen port, shard bits, egress target, NACK tuning, metrics,
  OTLP interval, firewall mgmt CIDRs, BGP).
- `modules/bgp`: variable-aggregation helper producing a `bgp_vars` map for
  `listener-node.extra_ansible_vars`; creates no resources.

`listener_version` in `modules/listener-node/variables.tf` must equal
`listener_version` in `ansible/group_vars/all.yml`, the single source of truth;
move both in one change
([version pin coupling](https://github.com/lightwebinc/bsv-multicast/blob/main/docs/infra/terraform-layout.md#version-pin-coupling)).

## Cloud firewall

The AWS example's security group is the cloud-level perimeter; the on-host
nftables ruleset from the `firewall` role is the fine-grained one (see
[security.md](security.md)). A cloud firewall for listeners must permit:

- UDP/`listen_port` from fabric sources
- TCP/22 and TCP/9200 from `mgmt_cidrs_*`
- TCP/179 when `enable_bgp` is true

## Defaults worth double-checking

| Variable          | Default    | Why                                             |
|-------------------|------------|--------------------------------------------------|
| `listen_port`     | `9001`     | Matches `ingress-infra`'s `egress_port`        |
| `metrics_addr`    | `:9200`    | Avoid collision with proxy (`:9100`)             |
| `bgp_local_as`    | `65002`    | Different from proxy (`65001`)                   |
| `enable_firewall` | `true`     | Default-on for security                          |
| `num_workers`     | `1`        | SO_REUSEPORT delivers every multicast frame to each worker — `>1` forwards frames ×N. Keep `1`. |
| `otlp_interval`   | `"30s"`    | Preserves prior hardcoded value                  |
