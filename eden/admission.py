"""Report live, unmatched runtime and build claims from the authoritative ledger."""

import json
import re
import sys


sys.path.insert(0, '/tmp/no-attract-playbook/tools/eden-lifecycle')
from lifecycle import active_claims


def open_builds(body, host):
    active = {}
    for line in body.splitlines():
        match = re.search(r'\bBUILD (CLAIMED|RELEASED)\s+host=(\S+)\s+owner=(\S+)\s+bid=(\S+)', line)
        if match is None or match[2] != host:
            continue
        key = match[3], match[4]
        if match[1] == 'CLAIMED':
            active[key] = line
        else:
            active.pop(key, None)
    return list(active.values())


if __name__ == '__main__':
    body = sys.stdin.read()
    if not body or 'CLAIMED' not in body:
        raise SystemExit('Unable to read the authoritative ledger')
    host = sys.argv[1]
    result = {'host': host, 'runtime': active_claims(body, host), 'build': open_builds(body, host)}
    print(json.dumps(result))
    sys.exit(bool(result['runtime'] or result['build']))
