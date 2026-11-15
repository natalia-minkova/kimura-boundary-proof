import argparse,json
from pathlib import Path
from .core import verify
p=argparse.ArgumentParser(description='Verify external evidence structure, integrity and contract; does not rerun target.')
p.add_argument('--verify',required=True)
a=p.parse_args()
try:
    v=json.loads(Path(a.verify).read_text())
    valid=verify(v)
except (ValueError,OSError): valid=False; v={}
print(json.dumps({'evidence_valid':valid,'boundary_verdict':v.get('verdict') if valid else None,
                  'independent_authenticity':False}))
raise SystemExit(0 if valid else 1)
