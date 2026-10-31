"""Offline regression checks for live-run lock nesting and request-ID reuse.

Does not import paid providers, load private cases, or issue API calls.
"""
import ast
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent


def calls_named(tree, name):
    return [node for node in ast.walk(tree) if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name) and node.func.id == name]


class LiveSafety(unittest.TestCase):
    def test_single_owner_of_exclusive_lock(self):
        runner = ast.parse((HERE / 'live_v6.py').read_text(encoding='utf8'))
        provider = ast.parse((HERE / 'guarded_provider_v6.py').read_text(encoding='utf8'))
        functions = [n for n in runner.body if isinstance(n, ast.FunctionDef) and n.name == 'execute']
        self.assertEqual(len(functions), 1)
        self.assertTrue(any(isinstance(node, ast.With) and
            any(isinstance(item.context_expr, ast.Call) and
                isinstance(item.context_expr.func, ast.Name) and
                item.context_expr.func.id == 'run_lock' for item in node.items)
            for node in ast.walk(functions[0])), 'outer runner must own run_lock')
        cls = next(n for n in provider.body if isinstance(n, ast.ClassDef) and n.name == 'GuardedTextTransport')
        call = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'call')
        self.assertEqual(calls_named(call, 'run_lock'), [],
            'transport must not reacquire non-reentrant parent run_lock')
        self.assertIn('parent_project_run_lock_required', (HERE / 'guarded_provider_v6.py').read_text(encoding='utf8'))

    def test_v6_ledger_ids_are_namespaced(self):
        source=(HERE / 'guarded_provider_v6.py').read_text(encoding='utf8')
        self.assertIn("request_id=f'v6one_{self.case}_{arm}_{self.sequence:02d}'",source)
        self.assertNotIn("request_id=f'preflight2_",source)

    def test_v6_import_order_documented(self):
        doc=(HERE / 'README.md').read_text(encoding='utf8')
        self.assertIn('src;synthetic_benchmark_v1/v6_one_shot;synthetic_benchmark_v1/preflight_rebuild',doc)


if __name__=='__main__':
    unittest.main()
