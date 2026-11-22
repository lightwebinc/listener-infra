#!/usr/bin/python
"""Add and remove host addresses on a FreeBSD loopback, one alias at a time."""

DOCUMENTATION = r"""
module: loopback_vips
short_description: Add and remove /32 and /128 aliases on a FreeBSD loopback without restarting it
description:
  - Runs C(ifconfig NAME), adds each wanted address the interface lacks
    (C(ifconfig NAME inet ADDR/32 alias), C(ifconfig NAME inet6 ADDR prefixlen 128 alias))
    and removes each unwanted address it carries (C(ifconfig NAME inet ADDR -alias),
    C(ifconfig NAME inet6 ADDR -alias)), then reads the interface again and fails unless it
    carries exactly what was asked.
  - Every other address stays, 127.0.0.1 and ::1 included. C(service netif restart lo0)
    would instead remove every address on the interface before adding them back.
  - Addresses are compared by value, so any spelling of an address matches.
options:
  name:
    description: Interface name.
    type: str
    default: lo0
  present:
    description: Addresses the interface must carry, IPv4 as a /32 and IPv6 as a /128.
    type: list
    elements: str
    default: []
  absent:
    description: Addresses the interface must not carry. An address that is also in I(present) stays.
    type: list
    elements: str
    default: []
"""

RETURN = r"""
added:
  description: The addresses added.
  type: list
  returned: always
removed:
  description: The addresses removed.
  type: list
  returned: always
inet:
  description: The addresses the interface carries afterwards, without a scope zone.
  type: list
  returned: always
"""

import ipaddress
import re

from ansible.module_utils.basic import AnsibleModule

# sbin/ifconfig: "\tinet %s netmask %#x" (af_inet.c), "\tinet6 %s prefixlen %d" (af_inet6.c).
INET = re.compile(r"^\s*inet6? (\S+)")


def carried(module, ifconfig, name):
    rc, out, err = module.run_command([ifconfig, name])
    if rc != 0:
        module.fail_json(msg="ifconfig %s: %s" % (name, (err or out).strip()), rc=rc)
    addrs = []
    for line in out.splitlines():
        match = INET.match(line)
        if match:
            addrs.append(ipaddress.ip_address(match.group(1).split("%", 1)[0]))
    return addrs


def run(module, argv):
    rc, out, err = module.run_command(argv)
    if rc != 0:
        module.fail_json(msg="%s: %s" % (" ".join(argv), (err or out).strip()), rc=rc)


def main():
    module = AnsibleModule(
        argument_spec=dict(
            name=dict(type="str", default="lo0"),
            present=dict(type="list", elements="str", default=[]),
            absent=dict(type="list", elements="str", default=[]),
        ),
        supports_check_mode=True,
    )
    params = module.params
    try:
        want = [ipaddress.ip_address(a.strip()) for a in params["present"] if a.strip()]
        drop = [ipaddress.ip_address(a.strip()) for a in params["absent"] if a.strip()]
    except ValueError as exc:
        module.fail_json(msg="not an address: %s" % exc)
    for addr in want + drop:
        if addr.is_loopback:
            module.fail_json(msg="%s is a loopback address, not a VIP" % addr)
    want = list(dict.fromkeys(want))
    drop = [a for a in dict.fromkeys(drop) if a not in want]

    ifconfig = module.get_bin_path("ifconfig", required=True)
    name = params["name"]
    have = carried(module, ifconfig, name)
    add = [a for a in want if a not in have]
    remove = [a for a in drop if a in have]
    if not module.check_mode:
        # Added before any is removed, so a VIP that moves never leaves the
        # interface without one.
        for addr in add:
            if addr.version == 4:
                run(module, [ifconfig, name, "inet", "%s/32" % addr, "alias"])
            else:
                run(module, [ifconfig, name, "inet6", str(addr), "prefixlen", "128", "alias"])
        for addr in remove:
            run(module, [ifconfig, name, "inet" if addr.version == 4 else "inet6", str(addr), "-alias"])
        have = carried(module, ifconfig, name)
        missing = [str(a) for a in want if a not in have]
        left = [str(a) for a in drop if a in have]
        if missing or left:
            module.fail_json(msg="%s after the changes: missing %s, still present %s"
                             % (name, ", ".join(missing) or "none", ", ".join(left) or "none"),
                             inet=[str(a) for a in have])
    module.exit_json(
        changed=bool(add or remove),
        added=[str(a) for a in add],
        removed=[str(a) for a in remove],
        inet=[str(a) for a in have],
    )


if __name__ == "__main__":
    main()
