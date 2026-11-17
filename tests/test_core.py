import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from midearms import ADAPTERS, dream

FIXTURES = Path(__file__).parent / 'fixtures'

class CoreTests(unittest.TestCase):
    def test_adapters(self):
        for name, filename in [('claude','claude.jsonl'),('codex','codex.jsonl'),('cursor','cursor.json'),('aider','aider.md'),('jsonl','claude.jsonl')]:
            self.assertTrue(list(ADAPTERS[name](FIXTURES / filename)))

    def test_rules(self):
        self.assertEqual(dream(['hello']), [])
        self.assertIn('Pattern: shared', dream(['shared','shared']))
        self.assertEqual(dream(['Never hide errors.']), ['Lesson: Never hide errors.'])

    def test_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            store = str(Path(directory) / 'memory.db')
            def run(*args):
                return subprocess.run([sys.executable,'-m','midearms','--store',store,*map(str,args)], capture_output=True, text=True)
            for _ in range(2):
                self.assertEqual(run('ingest','claude',FIXTURES/'claude.jsonl').returncode, 0)
            self.assertEqual(run('dream').returncode, 0)
            self.assertIn('Remember', run('query','tests').stdout)
            target = Path(directory)/'AGENTS.md'
            self.assertEqual(run('export',target).returncode,0)
            original = target.read_text()
            self.assertNotEqual(run('export',target).returncode,0)
            self.assertEqual(target.read_text(),original)

if __name__ == '__main__':
    unittest.main()
