#!/usr/bin/env python3
"""Assert perimeter invariants on a RENDERED firewall ruleset.

Syntax checkers (`nft -c -f`, `pfctl -nf`) prove a ruleset parses. They say
nothing about whether it is safe, so a fix applied to one backend has three
times been shipped without its twin: a blanket TCP accept, a spoofable
`sport 179` hole, and world-open metrics have each survived a green CI run.

This checks policy, not syntax, and is deliberately backend-aware but
repo-agnostic: point it at any rendered nft or pf ruleset.

Usage:  firewall-policy-check.py --backend nft|pf FILE [FILE...]
"""
import argparse
import re
import sys

# Tokens that restrict a rule to a source, interface, or port. A rule carrying
# none of these admits traffic from anywhere on every port.
NFT_RESTRICTORS = re.compile(
    r"(dport|sport|saddr|daddr|iifname|oifname|@[a-z0-9_]+|ct state|type \d)", re.I
)
# pf: a rule is restricted if it pins a port, an interface, or a concrete
# source/destination (table, macro, or literal address). A pass carrying a
# protocol but none of these admits that protocol from anywhere to everywhere.
PF_RESTRICTORS = re.compile(
    r"(\bport\b"                 # ... port 22
    r"|\bon\s+!?\s*\$?\w+"       # on $fabric_if / on ! $fabric_if / on lo0
    r"|\b(from|to)\s+<\w+>"      # from <mgmt_v4> / to <retry_v6>
    r"|\b(from|to)\s+\$\w+"      # from $egress_host
    r"|\b(from|to)\s+[0-9a-f]+[.:]" # literal v4/v6 address
    r")",
    re.I,
)

# Ports that must never be admitted without a management-source restriction.
MGMT_PORTS = ("22", "$metrics_port")

# A management port is adequately gated by any of:
#   * a management CIDR set/table (<mgmt_v6>, @mgmt_allow_v4)
#   * a pin to the encrypted admin overlay — reaching that interface already
#     requires a WireGuard key, a stronger gate than a source CIDR
#   * a concrete source/destination address or CIDR literal
# A pin to any OTHER interface (a WAN port, say) is not a gate, and neither is
# `from any`.
MGMT_SOURCES_PF = re.compile(
    r"(<mgmt_v[46]>"
    r"|\bon\s+!?\s*(wg[-\w]*|mgmt[-\w]*|admin[-\w]*)\b"
    r"|\b(from|to)\s+(?!any\b)[<$\w]"      # from/to anything that is not `any`
    r")",
    re.I,
)
MGMT_SOURCES_NFT = re.compile(
    r"(@mgmt_allow_v[46]"
    r"|(iifname|oifname)\s+\"?!?\s*\"?(wg[-\w]*|mgmt[-\w]*|admin[-\w]*)\b"
    r"|\bip6?\s+(saddr|daddr)\s+\S"
    r")",
    re.I,
)

# pf spells default-deny several ways; any leading `block ... all` counts.
PF_DEFAULT_DENY = re.compile(r"^block(\s+(log|drop|return|in|out|quick))*\s+all\b", re.I)


def strip(line: str) -> str:
    return line.split("#", 1)[0].strip()


def check_nft(path, lines):
    problems = []
    chain = None
    saw_drop_policy = False
    for n, raw in enumerate(lines, 1):
        line = strip(raw)
        if not line:
            continue
        m = re.match(r"chain\s+(\w+)", line)
        if m:
            chain = m.group(1)
        if "policy drop" in line:
            saw_drop_policy = True

        if line.endswith("accept") or " accept" in line:
            # 1. Catch-all: an accept with no restricting token at all.
            if re.search(r"\b(tcp|udp|meta l4proto)\b", line) and not NFT_RESTRICTORS.search(line):
                problems.append(f"{path}:{n}: catch-all accept with no source/port restriction: {line!r}")
            # 2. Spoofable source-port hole on an input path.
            if chain and "input" in chain.lower() and re.search(r"\bsport\s+179\b", line):
                problems.append(
                    f"{path}:{n}: `sport 179` in an input chain admits every destination port "
                    f"to a spoofed source port; use `dport 179` + ct established: {line!r}"
                )
            # 3. Management ports must carry a management-source restriction.
            if re.search(r"dport\s+\{?[^}]*\b22\b", line) and not MGMT_SOURCES_NFT.search(line):
                problems.append(f"{path}:{n}: SSH admitted without a mgmt source set: {line!r}")
    if not saw_drop_policy:
        problems.append(f"{path}: no chain declares `policy drop` — ruleset is not default-deny")
    return problems


def check_pf(path, lines):
    problems = []
    saw_block_all = False
    for n, raw in enumerate(lines, 1):
        line = strip(raw)
        if not line:
            continue
        if PF_DEFAULT_DENY.match(line):
            saw_block_all = True
        if not line.startswith("pass"):
            continue
        # 1. Catch-all: a pass carrying a protocol but no port/source/lo restriction.
        if re.search(r"\bproto\s+(tcp|udp)\b", line) and not PF_RESTRICTORS.search(line):
            problems.append(
                f"{path}:{n}: catch-all pass with no port or source restriction — `quick` makes "
                f"it short-circuit every rule below it: {line!r}"
            )
        # 2. Spoofable source-port hole.
        if re.search(r"from\s+any\s+port\s+179\b", line):
            problems.append(
                f"{path}:{n}: `from any port 179` exposes every destination port to a spoofed "
                f"source port; keep the dport rule with `keep state`: {line!r}"
            )
        # 3. Management ports must be sourced from a mgmt table.
        if any(p in line for p in MGMT_PORTS) and not MGMT_SOURCES_PF.search(line):
            problems.append(f"{path}:{n}: management port admitted without a mgmt table: {line!r}")
    if not saw_block_all:
        problems.append(f"{path}: no `block all` — ruleset is not default-deny")
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", required=True, choices=("nft", "pf"))
    ap.add_argument("files", nargs="+")
    args = ap.parse_args()

    problems = []
    for path in args.files:
        with open(path) as fh:
            lines = fh.readlines()
        problems += (check_nft if args.backend == "nft" else check_pf)(path, lines)

    if problems:
        print(f"FAIL: {len(problems)} perimeter policy violation(s)\n", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 1
    print(f"OK: {args.backend} policy invariants hold for {len(args.files)} file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
