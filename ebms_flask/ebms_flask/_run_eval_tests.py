import io
import sys
import unittest

buf = io.StringIO()
runner = unittest.TextTestRunner(stream=buf, verbosity=2)
suite = unittest.defaultTestLoader.discover('tests', pattern='test_evaluator_assignments.py')
result = runner.run(suite)
with open('eval_results.txt', 'w', encoding='utf-8') as out:
    out.write(buf.getvalue())
sys.exit(0 if result.wasSuccessful() else 1)