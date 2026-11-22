#!/usr/bin/python
"""Report whether a FreeBSD gif(4) interface runs the wanted tunnel and inner address."""

DOCUMENTATION = r"""
module: gif_status
short_description: Compare a gif(4) interface's running tunnel and inner address with the wanted ones
description:
  - Runs C(ifconfig NAME) on FreeBSD and reads its flags and its C(tunnel) and C(inet6) lines.
  - Addresses are compared by value, so any spelling of an address matches.
  - Changes nothing.
options:
  name:
    description: Interface name.
    type: str
    default: gif0
  tunnel:
    description: Wanted outer source and destination address.
    type: list
    elements: str
    required: true
  inet6:
    description: Wanted inner IPv6 address, with or without a prefix length.
    type: str
    required: true
"""

RETURN = r"""
exists:
  description: The interface exists.
  type: bool
  returned: always
up:
  description: The interface is administratively up (C(UP) in its flags).
  type: bool
  returned: always
matches:
  description: The interface is up and runs the wanted tunnel and inner address.
  type: bool
  returned: always
tunnel:
  description: The running outer source and destination.
  type: list
  returned: always
inet6:
  description: The running inet6 addresses, with prefix length and without a scope zone.
  type: list
  returned: always
"""

import ipaddress
import re

from ansible.module_utils.basic import AnsibleModule

# sbin/ifconfig: "\ttunnel inet6 %s --> %s" (af_inet6.c), "\ttunnel inet %s --> %s"
# (af_inet.c), "\tinet6 %s" ... " prefixlen %d" (af_inet6.c).
FLAGS = re.compile(r"^\S+: flags=[0-9a-f]+<([^>]*)>")
TUNNEL = re.compile(r"^\s*tunnel inet6? (\S+) --> (\S+)")
INET6 = re.compile(r"^\s*inet6 (\S+) prefixlen (\d+)")


def address(text):
    """An inner address: its scope zone, if any, is dropped."""
    return ipaddress.ip_address(text.split("%", 1)[0])


def endpoint(text):
    """A tunnel endpoint keeps its zone: fe80::1%em0 and fe80::1%em1 are different links."""
    try:
        return ipaddress.ip_address(text)
    except ValueError:
        if "%" not in text:
            raise
        return address(text)  # Python before 3.9 has no scoped IPv6Address


def main():
    module = AnsibleModule(
        argument_spec=dict(
            name=dict(type="str", default="gif0"),
            tunnel=dict(type="list", elements="str", required=True),
            inet6=dict(type="str", required=True),
        ),
        supports_check_mode=True,
    )
    params = module.params
    try:
        want_tunnel = [endpoint(a) for a in params["tunnel"]]
        if "/" in params["inet6"]:
            want_inner = ipaddress.ip_interface(params["inet6"])
        else:
            want_inner = address(params["inet6"])
    except ValueError as exc:
        module.fail_json(msg="not an address: %s" % exc)
    if len(want_tunnel) != 2:
        module.fail_json(msg="tunnel takes a source and a destination address")

    rc, out, err = module.run_command([module.get_bin_path("ifconfig", required=True), params["name"]])
    tunnel, inner, up = [], [], False
    if rc == 0:
        for line in out.splitlines():
            # gif_transmit drops every packet while IFF_UP is clear (if_gif.c).
            match = FLAGS.match(line)
            if match:
                up = "UP" in match.group(1).split(",")
            match = TUNNEL.match(line)
            if match:
                tunnel = [endpoint(match.group(1)), endpoint(match.group(2))]
            # Every address, link-local included: a configured link-local inner
            # address matches its scoped line, and the automatic one never equals
            # a configured global address.
            match = INET6.match(line)
            if match:
                inner.append(ipaddress.ip_interface("%s/%s" % (match.group(1).split("%", 1)[0], match.group(2))))
    if isinstance(want_inner, (ipaddress.IPv4Interface, ipaddress.IPv6Interface)):
        inner_ok = want_inner in inner
    else:
        inner_ok = any(i.ip == want_inner for i in inner)
    module.exit_json(
        changed=False,
        exists=rc == 0,
        up=up,
        matches=rc == 0 and up and tunnel == want_tunnel and inner_ok,
        tunnel=[str(a) for a in tunnel],
        inet6=[i.with_prefixlen for i in inner],
        stdout=out,
        stderr=err,
    )


if __name__ == "__main__":
    main()
