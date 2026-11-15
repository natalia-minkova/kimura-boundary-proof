import copy,unittest
from external_assessment.core import build,verify,verdict,digest
class ExternalTests(unittest.TestCase):
    def setUp(self):
        self.rows=[dict(role='control',before=False,after=True,status='success',rule=None),dict(role='telemetry',before=False,after=False,status='rejected',rule='authz.insufficient_scope')]
        self.target=dict(repository='https://github.com/PeterJBurke/droneserver',commit='a'*40,auth_enabled=True,adapter='registered-tool-in-process/1')
    def test_held_and_verifiable(self): self.assertTrue(verify(build(self.target,self.rows)))
    def test_observed_violation_overrides_claimed_denial(self):
        self.rows[1]['after']=True
        self.assertEqual(verdict(self.rows),'BOUNDARY_VIOLATED')
    def test_failed_positive_is_inconclusive(self):
        self.rows[0]['after']=False
        self.assertEqual(verdict(self.rows),'INCONCLUSIVE')
    def test_missing_observation_rejected(self):
        with self.assertRaises(ValueError): verdict(self.rows[:1])
    def test_hash_tampering_rejected(self):
        e=build(self.target,self.rows);e['observations'][1]['after']=True
        self.assertFalse(verify(e))
    def test_rehashed_false_verdict_rejected(self):
        e=build(self.target,self.rows);e['verdict']='BOUNDARY_VIOLATED';e['sha256']=digest({k:v for k,v in e.items() if k!='sha256'})
        self.assertFalse(verify(e))
    def test_boolean_not_integer(self):
        self.rows[1]['after']=0
        with self.assertRaises(ValueError): verdict(self.rows)
    def test_unexplained_no_effect_inconclusive(self):
        self.rows[1]['status']='failed';self.rows[1]['rule']=None
        self.assertEqual(verdict(self.rows),'INCONCLUSIVE')
    def test_http_evidence_has_distinct_limits(self):
        self.target['adapter']='http-sse-loopback/1'
        e=build(self.target,self.rows)
        self.assertTrue(verify(e))
        self.assertIn('HTTP/SSE',e['limitations'][0])
    def test_relabelled_transport_rejected(self):
        e=build(self.target,self.rows)
        e['target']['adapter']='http-sse-loopback/1'
        e['sha256']=digest({k:v for k,v in e.items() if k!='sha256'})
        self.assertFalse(verify(e))
    def test_unknown_adapter_rejected(self):
        e=build(self.target,self.rows);e['target']['adapter']='unreviewed'
        self.assertFalse(verify(e))
