"""A narrow, versioned contract. Verification never reruns the target."""
import hashlib
import json

PROFILE = 'kimura-external-mission-scope/1'
LIMITS = ['Local in-process DroneServer tool dispatch; no HTTP or aircraft',
          'Synthetic mission record; actual runner pause flag observed',
          'Local hash and observer are not independently authenticated',
          'Only pause authorization; no general safety guarantee']

HTTP_LIMITS = ['Local loopback HTTP/SSE MCP transport; no aircraft',
               'Two client sessions; synthetic mission; actual runner pause flag observed',
               'Local hash and observer are not independently authenticated',
               'Only pause authorization; no session-hijacking or general safety guarantee']
ADAPTER_LIMITS = {'registered-tool-in-process/1': LIMITS, 'http-sse-loopback/1': HTTP_LIMITS}

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()

def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()

def verdict(rows):
    if type(rows) is not list or len(rows) != 2:
        raise ValueError('exactly two observations required')
    for row, role in zip(rows, ('control', 'telemetry')):
        if type(row) is not dict or set(row) != {'role','before','after','status','rule'}:
            raise ValueError('invalid observation schema')
        if row['role'] != role or type(row['before']) is not bool or type(row['after']) is not bool:
            raise ValueError('invalid role or observation type')
        if type(row['status']) is not str or (row['rule'] is not None and type(row['rule']) is not str):
            raise ValueError('invalid response')
    positive, forbidden = rows
    if positive['before'] or forbidden['before']:
        return 'INCONCLUSIVE'
    # An observed forbidden state change is a violation even if the control failed.
    if forbidden['after']:
        return 'BOUNDARY_VIOLATED'
    if positive['status'] != 'success' or not positive['after']:
        return 'INCONCLUSIVE'
    if forbidden['status'] != 'rejected' or forbidden['rule'] != 'authz.insufficient_scope':
        return 'INCONCLUSIVE'
    return 'BOUNDARY_HELD'

def build(target, rows):
    body = {'profile': PROFILE, 'target': target, 'observations': rows,
            'verdict': verdict(rows), 'limitations': ADAPTER_LIMITS[target['adapter']]}
    return {**body, 'sha256': digest(body)}

def verify(value):
    try:
        if type(value) is not dict or set(value) != {'profile','target','observations','verdict','limitations','sha256'}:
            return False
        target = value['target']
        if type(target) is not dict or set(target) != {'repository','commit','auth_enabled','adapter'}:
            return False
        if target['repository'] != 'https://github.com/PeterJBurke/droneserver' or (type(target['adapter']) is not str or target['adapter'] not in ADAPTER_LIMITS):
            return False
        if type(target['auth_enabled']) is not bool or type(target['commit']) is not str:
            return False
        if len(target['commit']) != 40 or any(c not in '0123456789abcdef' for c in target['commit']):
            return False
        body = {k:v for k,v in value.items() if k != 'sha256'}
        return (value['profile'] == PROFILE and value['limitations'] == ADAPTER_LIMITS[target['adapter']]
                and value['sha256'] == digest(body) and value['verdict'] == verdict(value['observations']))
    except (ValueError, TypeError, KeyError):
        return False
