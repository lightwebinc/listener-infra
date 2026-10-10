# Terraform usage

Terraform orchestrates cloud infrastructure and hands off per-host provisioning
to the Ansible playbook in `ansible/`.

## Modules

### `modules/listener-node`

Provisions a single listener host:

1. Renders a per-host Ansible inventory (`generated-inventory-*.yml`).
2. Runs `ansible-playbook site.yml` via `local-exec`, passing all listener
   variables as `--extra-vars`.

Inputs include the full listener configuration (listen port, shard bits,
egress target, NACK tuning, metrics, OTLP interval, firewall mgmt CIDRs,
BGP).

#### Version pin coupling

Inputs are passed as `--extra-vars`, which **outrank**
`ansible/group_vars/all.yml`. `listener_version` is therefore pinned twice: the
`variables.tf` default must equal the `listener_version` in `group_vars/all.yml`
(the single source of truth for the current release). Move both in the same change — a lagging default (or `main`)
silently deploys a different build from Terraform than a plain `ansible-playbook`
run does, with nothing in the output saying so.

### `modules/bgp`

Pure variable-aggregation helper that produces a `bgp_vars` map for feeding
into `listener-node.extra_ansible_vars`. No resources created.

## Examples

### `examples/generic/`

Cloud-agnostic. Accepts a list of existing hosts and provisions each via
Ansible. Use this when you already have VMs (e.g. bare metal, a lab, or
another IaC tool created them).

```sh
cd terraform/examples/generic
cp terraform.tfvars.example terraform.tfvars
$EDITOR terraform.tfvars
terraform init
terraform apply
```

### `examples/aws-ec2/`

Provisions VPC, subnets, SGs, EC2 instances (Ubuntu 24.04), optional EIPs,
then runs Ansible.

```sh
cd terraform/examples/aws-ec2
cp terraform.tfvars.example terraform.tfvars
$EDITOR terraform.tfvars
terraform init
terraform apply
```

The AWS example creates a Security Group that is the cloud-level perimeter.
The on-host nftables ruleset (deployed by the `firewall` Ansible role) is
the fine-grained perimeter. Both must stay aligned — see
[`security.md`](security.md).

## Extending to other clouds

Copy `examples/generic/` or `examples/aws-ec2/` and adapt:

1. Create VMs / VPC / security groups.
2. Collect the resulting host IPs into `local.node_ips` (or equivalent).
3. Pass them to `module.listener_nodes` (one instance per host).
4. Ensure cloud-level firewall permits:
   - UDP/`listen_port` from fabric sources
   - TCP/22 and TCP/9200 from `mgmt_cidrs_*`
   - TCP/179 when `enable_bgp` is true
   - Outbound per your organisation's policy

## Defaults worth double-checking

| Variable          | Default    | Why                                             |
|-------------------|------------|--------------------------------------------------|
| `listen_port`     | `9001`     | Matches `ingress-infra`'s `egress_port`        |
| `metrics_addr`    | `:9200`    | Avoid collision with proxy (`:9100`)             |
| `bgp_local_as`    | `65002`    | Different from proxy (`65001`)                   |
| `enable_firewall` | `true`     | Default-on for security                          |
| `num_workers`     | `1`        | SO_REUSEPORT delivers every multicast frame to each worker — `>1` forwards frames ×N. Keep `1`. |
| `otlp_interval`   | `"30s"`    | Preserves prior hardcoded value                  |
