"""Offline guard-policy regression tests, needing no API/large optional dependencies."""
import ast,unittest
from pathlib import Path

SOURCE=Path(__file__).with_name('guarded_provider_v6.py').read_text(encoding='utf8')
MODULE=ast.parse(SOURCE)
HELPER=next(n for n in MODULE.body if isinstance(n,ast.FunctionDef) and n.name=='_allow_repeated_settled_A')
NAMESPACE={}
exec(compile(ast.Module(body=[HELPER],type_ignores=[]),'guard_policy_test','exec'),NAMESPACE)
allow=NAMESPACE['_allow_repeated_settled_A']

class DuplicateA(unittest.TestCase):
    def setUp(self):self.ok={'status':'ok','response_id':'resp_existing','request_hash':'hash'}
    def test_fresh_A_draw_with_same_successful_body(self):self.assertTrue(allow('A',[self.ok]))
    def test_only_fully_settled_prior_calls_allowed(self):
        for status in ('error_unknown_cost','error','reserved_unknown_outcome','reserved_unknown_cost'):
            with self.subTest(status=status):
                self.assertFalse(allow('A',[self.ok,{'status':status,'response_id':'r'}]))
        self.assertFalse(allow('A',[{'status':'ok'}]))
    def test_B_C_excluded(self):
        self.assertFalse(allow('B',[self.ok]));self.assertFalse(allow('C',[self.ok]))
    def test_no_prior_and_structure_wiring(self):
        self.assertFalse(allow('A',[]))
        self.assertIn('if old:',SOURCE)
        self.assertIn("raise ValueError('attempted_request_no_replay')",SOURCE)
        self.assertIn('if prior_matching_hashes and not _allow_repeated_settled_A',SOURCE)
        self.assertIn("raise ValueError('duplicate_request_no_replay')",SOURCE)

if __name__=='__main__':unittest.main()
