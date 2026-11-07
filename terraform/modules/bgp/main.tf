terraform {
  required_version = ">= 1.9"
}

# This module produces a map of BGP-related Ansible variables
# for use with the listener-node module's extra_ansible_vars input.
# No resources are created here: it is a pure variable aggregation helper.

locals {
  bgp_vars = {
    enable_bgp      = tostring(var.enable_bgp)
    bgp_daemon      = var.bgp_daemon
    bgp_health_path = var.bgp_health_path
    bgp_prefix      = var.bgp_prefix
    bgp_vip         = var.bgp_vip
    bgp_prefix6     = var.bgp_prefix6
    bgp_vip6        = var.bgp_vip6
    bgp_local_as    = tostring(var.bgp_local_as)
    bgp_peer_as     = tostring(var.bgp_peer_as)
    bgp_peer_ip     = var.bgp_peer_ip
    bgp_peer_ip6    = var.bgp_peer_ip6
    bgp_router_id   = var.bgp_router_id
    bgp_hold_time   = tostring(var.bgp_hold_time)
    bgp_keepalive   = tostring(var.bgp_keepalive)
    bgp_password    = var.bgp_password
  }
}
