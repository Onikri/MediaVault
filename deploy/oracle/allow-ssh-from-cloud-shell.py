#!/usr/bin/env python3
"""Add one source-specific SSH ingress rule to an existing VM via OCI CLI."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess


class RepairError(RuntimeError):
    pass


def cli(args, region):
    result = subprocess.run(['oci', '--region', region, '--output', 'json', '--query', '@', *args],
                            capture_output=True, text=True, timeout=120)
    if result.returncode:
        match = re.search(r'"code"\s*:\s*"([\w-]+)"', result.stderr)
        option = re.search(r'No such option:\s*(--[a-z-]+)', result.stderr)
        reason = match[1] if match else 'unsupported option ' + option[1] if option else 'request failed'
        raise RepairError('OCI: ' + reason + ' at ' + ' '.join(args[:3]) + ' (exit ' + str(result.returncode) + ')')
    return json.loads(result.stdout)


def camel(value):
    if isinstance(value, list):
        return [camel(v) for v in value]
    if isinstance(value, dict):
        return {re.sub(r'-([a-z])', lambda m: m[1].upper(), k): camel(v) for k, v in value.items()}
    return value


def allows(rule, source):
    rule = camel(rule)
    if rule.get('direction', 'INGRESS') != 'INGRESS' or rule.get('sourceType', 'CIDR_BLOCK') != 'CIDR_BLOCK':
        return False
    try:
        if not ipaddress.ip_network(source).subnet_of(ipaddress.ip_network(rule.get('source', ''))):
            return False
    except ValueError:
        return False
    if str(rule.get('protocol')) == 'all':
        return True
    if str(rule.get('protocol')) != '6':
        return False
    options = rule.get('tcpOptions') or {}
    if options.get('sourcePortRange'):
        return False
    ports = options.get('destinationPortRange')
    return not ports or ports.get('min', 65536) <= 22 <= ports.get('max', -1)


def repair(public_ip, source, region, *, request=cli, backup=None):
    source = str(ipaddress.ip_network(source, strict=True))
    if ipaddress.ip_network(source).version != 4 or ipaddress.ip_network(source).prefixlen != 32:
        raise RepairError('Use exactly one IPv4 address (/32).')
    # Resource Search has --limit/--page, unlike the list commands' --all.
    items=[];page=None;seen_pages=set()
    while True:
        args=['search', 'resource', 'structured-search', '--query-text',
              "query instance resources where lifecycleState = 'RUNNING'", '--limit', '1000']
        if page:args+=['--page',page]
        result=request(args,region)
        items.extend(result['data'].get('items',[]))
        page=result.get('opc-next-page')
        if not page:break
        if page in seen_pages:raise RepairError('OCI repeated a search page; nothing changed.')
        seen_pages.add(page)
    matches = []
    for item in items:
        identity = item.get('identifier', '')
        if not re.fullmatch(r'ocid1\.instance\.[a-zA-Z0-9.-]+', identity):
            continue
        vnics = request(['compute', 'instance', 'list-vnics', '--instance-id', identity, '--all'], region)['data']
        matches.extend(v for v in vnics if v.get('public-ip') == public_ip)
    if len(matches) != 1:
        raise RepairError('Expected exactly one VM VNIC with the specified public IP; nothing changed.')
    vnic = matches[0]
    subnet = request(['network', 'subnet', 'get', '--subnet-id', vnic['subnet-id']], region)['data']
    lists = []
    for identity in subnet.get('security-list-ids', []):
        value = request(['network', 'security-list', 'get', '--security-list-id', identity], region)
        lists.append((identity, value))
        if any(allows(r, source) for r in value['data'].get('ingress-security-rules', [])):
            return 'SSH is already permitted by the OCI security list. Check sshd/Ubuntu firewall on the VM.'
    for identity in vnic.get('nsg-ids', []):
        rules = request(['network', 'nsg', 'rules', 'list', '--nsg-id', identity, '--all'], region)['data']
        if any(allows(r, source) for r in rules):
            return 'SSH is already permitted by the OCI NSG. Check sshd/Ubuntu firewall on the VM.'
    rule = {'protocol': '6', 'source': source, 'sourceType': 'CIDR_BLOCK', 'isStateless': False,
            'tcpOptions': {'destinationPortRange': {'min': 22, 'max': 22}},
            'description': 'MediaVault source-specific SSH maintenance'}
    if vnic.get('nsg-ids'):
        request(['network', 'nsg', 'rules', 'add', '--nsg-id', vnic['nsg-ids'][0],
                 '--security-rules', json.dumps([{**rule, 'direction': 'INGRESS'}])], region)
    else:
        if not lists:
            raise RepairError('No attached security list or NSG; nothing changed.')
        identity, value = lists[0]
        if not value.get('etag'):
            raise RepairError('OCI returned no ETag; refusing to overwrite rules without a concurrency check.')
        if backup:
            path = Path(backup);path.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as saved:
                json.dump(value, saved)
        rules = [*camel(value['data'].get('ingress-security-rules', [])), rule]
        request(['network', 'security-list', 'update', '--security-list-id', identity,
                 '--if-match', value['etag'], '--ingress-security-rules', json.dumps(rules), '--force'], region)
    return 'SSH ingress added for ' + source + ' only. Existing rules and egress preserved. Retry SSH.'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--public-ip', required=True)
    parser.add_argument('--source-cidr', required=True)
    parser.add_argument('--region', default='eu-frankfurt-1')
    args = parser.parse_args()
    try:
        root = Path(__file__).resolve().parent
        os.environ['TMPDIR'] = str(root / 'tmp');Path(os.environ['TMPDIR']).mkdir(exist_ok=True)
        print(repair(args.public_ip, args.source_cidr, args.region,
                     backup=root / ('ssh-rules-before-' + str(__import__('time').time_ns()) + '.json')))
    except (RepairError, ValueError, KeyError, OSError, subprocess.TimeoutExpired) as error:
        print(str(error) if isinstance(error, RepairError) else 'SSH repair stopped; inspect OCI configuration.')
        raise SystemExit(1)
