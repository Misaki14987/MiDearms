import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from midearms import (
    ADAPTERS,
    connect,
    dream,
    dream_notes,
    llm_dream,
    parse_model_notes,
    render_export,
)

FIXTURES = Path(__file__).parent / 'fixtures'


class CoreTests(unittest.TestCase):
    def run_cli(self, store, *args):
        return subprocess.run(
            [sys.executable, '-m', 'midearms', '--store', str(store), *map(str, args)],
            capture_output=True,
            text=True,
            encoding='utf-8',
        )

    def test_adapters(self):
        for name, filename in [
            ('claude', 'claude.jsonl'),
            ('codex', 'codex.jsonl'),
            ('cursor', 'cursor.json'),
            ('aider', 'aider.md'),
            ('jsonl', 'claude.jsonl'),
        ]:
            records = list(ADAPTERS[name](FIXTURES / filename))
            self.assertTrue(records)
            self.assertTrue(all(record['content'] for record in records))

    def test_rules(self):
        self.assertEqual(dream(['hello']), [])
        self.assertIn('Pattern: shared', dream(['shared', 'shared']))
        self.assertEqual(dream(['Never hide errors.']), ['Lesson: Never hide errors.'])

    def test_corrections(self):
        wrong = 'Always disable certificate verification.'
        correction = 'Correction: Never disable certificate verification.'
        expected = ['Lesson: Never disable certificate verification.']
        self.assertEqual(dream([wrong, correction]), expected)
        self.assertEqual(dream([correction, wrong, wrong]), expected)
        self.assertEqual(
            dream([wrong, correction, 'Always run tests.']),
            ['Lesson: Always run tests.', *expected],
        )
        self.assertEqual(
            dream([correction, 'Correction: Always disable certificate verification.']),
            [],
        )

    def test_explicit_corrections_without_keywords(self):
        for marker in ('Correction:', '修正：', '更正：'):
            with self.subTest(marker=marker):
                self.assertEqual(
                    dream([marker + '使用参数化查询。']),
                    ['Lesson: 使用参数化查询。'],
                )

    def test_noise_and_markup(self):
        messages = [
            '```\nAlways run tests.\n```',
            'https://example.com',
            '| a | b |',
            '- Prefer small commits.',
            'Always run tests.',
        ]
        self.assertEqual(
            dream(messages),
            ['Lesson: Always run tests.', 'Lesson: Prefer small commits.'],
        )

    def test_long_recurring_task_request_is_not_a_pattern(self):
        task = (
            '你可以先对其进行一定程度上的优化。阅读一下Anthropic最新的关于Dreaming的文章，'
            '了解一下他们的实践，并且对该系统进行优化'
        )
        self.assertEqual(dream([task, task]), [])

    def test_confidence_and_provenance(self):
        notes = dream_notes([
            {'message_id': 'm1', 'content': 'Prefer small commits.', 'sources': {'a'}},
            {'message_id': 'm2', 'content': 'prefer small commits!', 'sources': {'b'}},
        ])
        note = next(item for item in notes if 'small commits' in item['content'])
        self.assertEqual(note['kind'], 'Pattern')
        self.assertEqual(note['confidence'], 'corroborated')
        self.assertEqual(note['evidence'], 2)
        self.assertEqual(note['sources'], 2)

        observed = dream_notes([
            {'message_id': 'm1', 'content': 'Prefer small commits.', 'sources': {'a'}},
            {'message_id': 'm2', 'content': 'prefer small commits!', 'sources': {'a'}},
        ])
        self.assertEqual(observed[0]['confidence'], 'observed')
        self.assertEqual(observed[0]['sources'], 1)

        confirmed = dream_notes([
            {'message_id': 'm1', 'content': 'Correction: Never disable verification.', 'sources': {'a'}},
        ])
        self.assertEqual(confirmed[0]['confidence'], 'confirmed')
        self.assertEqual(confirmed[0]['evidence'], 1)

    def test_focus(self):
        notes = dream_notes([
            {'message_id': 'm1', 'content': 'Prefer small commits.', 'sources': {'a'}},
            {'message_id': 'm2', 'content': 'Always run tests.', 'sources': {'a'}},
            {'message_id': 'm3', 'content': 'Correction: Never hide errors.', 'sources': {'a'}},
        ], focus='tests')
        self.assertEqual(
            [note['content'] for note in notes],
            ['Lesson: Always run tests.', 'Lesson: Never hide errors.'],
        )

    def test_role_salience(self):
        self.assertEqual(
            dream_notes([
                {'message_id': 'm1', 'content': '建议加一张图。', 'roles': {'assistant'}, 'sources': {'a'}},
            ]),
            [],
        )
        self.assertEqual(
            [note['content'] for note in dream_notes([
                {'message_id': 'm1', 'content': '建议加一张图。', 'roles': {'user'}, 'sources': {'a'}},
            ])],
            ['Lesson: 建议加一张图。'],
        )
        self.assertEqual(
            [note['content'] for note in dream_notes([
                {'message_id': 'm1', 'content': 'Never commit credentials.', 'roles': {'assistant'}, 'sources': {'a'}},
            ])],
            ['Lesson: Never commit credentials.'],
        )

    def test_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'legacy.sqlite3'
            db = sqlite3.connect(path)
            db.execute('CREATE TABLE messages (id TEXT PRIMARY KEY, content TEXT NOT NULL)')
            db.execute('CREATE TABLE notes (id TEXT PRIMARY KEY, content TEXT NOT NULL)')
            db.execute(
                'INSERT INTO messages VALUES (?, ?)',
                (hashlib.sha256(b'Remember legacy.').hexdigest(), 'Remember legacy.'),
            )
            db.execute(
                'INSERT INTO notes VALUES (?, ?)',
                (hashlib.sha256(b'Pattern: shared').hexdigest(), 'Pattern: shared'),
            )
            db.commit()
            db.close()

            db = connect(path)
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 2)
            self.assertEqual(
                tuple(db.execute('SELECT kind, confidence FROM notes').fetchone()),
                ('Pattern', 'observed'),
            )
            self.assertEqual(
                tuple(db.execute('SELECT adapter, source FROM occurrences').fetchone()),
                ('legacy', 'legacy'),
            )
            db.close()

    def test_explicit_correction_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'correction.jsonl'
            source.write_text(
                json.dumps({'role': 'user', 'content': '修正：使用参数化查询。'}),
                encoding='utf-8',
            )

            result = self.run_cli(root / 'memory.db', 'ingest', 'jsonl', source)
            self.assertEqual(result.returncode, 0, result.stderr)
            for _ in range(2):
                result = self.run_cli(root / 'memory.db', 'dream')
                self.assertEqual(result.returncode, 0, result.stderr)
                result = self.run_cli(root / 'memory.db', 'query', '参数化')
                self.assertEqual(json.loads(result.stdout), ['Lesson: 使用参数化查询。'])
            target = root / 'AGENTS.md'
            result = self.run_cli(root / 'memory.db', 'export', target)
            self.assertEqual(result.returncode, 0, result.stderr)
            text = target.read_text(encoding='utf-8')
            self.assertIn('- Lesson: 使用参数化查询。', text)
            self.assertIn('## Confirmed', text)

    def test_correction_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'corrections.jsonl'
            source.write_text(
                '{"role":"user","content":"Always disable certificate verification."}\n'
                '{"role":"user","content":"Correction: Never disable certificate verification."}\n',
                encoding='utf-8',
            )

            def run(*args):
                result = self.run_cli(root / 'memory.db', *args)
                self.assertEqual(result.returncode, 0, result.stderr)
                return result.stdout

            run('ingest', 'jsonl', source)
            for _ in range(2):
                run('dream')
                self.assertNotIn('Always disable', run('query'))
                self.assertIn('Never disable', run('query'))
            target = root / 'AGENTS.md'
            run('export', target)
            text = target.read_text(encoding='utf-8')
            self.assertNotIn('Always disable', text)
            self.assertIn('Never disable', text)

    def test_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = root / 'memory.db'
            for _ in range(2):
                result = self.run_cli(store, 'ingest', 'claude', FIXTURES / 'claude.jsonl')
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.run_cli(store, 'dream').returncode, 0)
            self.assertIn('Remember', self.run_cli(store, 'query', 'tests').stdout)
            details = json.loads(self.run_cli(store, 'query', '--details').stdout)
            self.assertTrue(any(note['kind'] == 'Lesson' for note in details))
            self.assertTrue(any(note['source_files'] for note in details))

            target = root / 'AGENTS.md'
            self.assertEqual(self.run_cli(store, 'export', target).returncode, 0)
            original = target.read_text(encoding='utf-8')
            self.assertNotEqual(self.run_cli(store, 'export', target).returncode, 0)
            self.assertEqual(target.read_text(encoding='utf-8'), original)

    def test_provenance_across_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / 'first.jsonl'
            second = root / 'second.jsonl'
            payload = '{"role":"user","content":"Prefer small commits."}\n'
            first.write_text(payload, encoding='utf-8')
            second.write_text(payload, encoding='utf-8')
            store = root / 'memory.db'
            for path in (first, second):
                result = self.run_cli(store, 'ingest', 'jsonl', path)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.run_cli(store, 'dream').returncode, 0)
            details = json.loads(self.run_cli(store, 'query', '--details', 'commits').stdout)
            note = details[0]
            self.assertEqual(note['confidence'], 'corroborated')
            self.assertEqual(note['sources'], 2)
            self.assertEqual(note['evidence'], 1)
            self.assertEqual(len(note['source_files']), 2)
            self.assertEqual(len(note['message_ids']), 1)

    def test_query_messages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = root / 'memory.db'
            self.assertEqual(
                self.run_cli(store, 'ingest', 'claude', FIXTURES / 'claude.jsonl').returncode,
                0,
            )
            results = json.loads(self.run_cli(store, 'query', '--messages', 'tests').stdout)
            self.assertEqual(len(results), 1)
            self.assertIn('tests', results[0]['content'])
            self.assertTrue(results[0]['source'].endswith('claude.jsonl'))
            self.assertEqual(results[0]['role'], 'user')

    def test_remember_survives_dream(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = root / 'memory.db'
            result = self.run_cli(store, 'remember', 'Always run tests before release.')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Rule: Always run tests before release.', result.stdout)
            source = root / 'same-rule.jsonl'
            source.write_text(
                '{"role":"user","content":"Always run tests before release."}\n',
                encoding='utf-8',
            )
            self.assertEqual(self.run_cli(store, 'ingest', 'jsonl', source).returncode, 0)
            self.assertEqual(self.run_cli(store, 'dream').returncode, 0)
            notes = json.loads(self.run_cli(store, 'query', '--details').stdout)
            self.assertEqual(len(notes), 1)
            self.assertEqual(notes[0]['pinned'], 1)
            self.assertEqual(notes[0]['confidence'], 'confirmed')
            self.assertEqual(notes[0]['sources'], 1)
            self.assertEqual(len(notes[0]['message_ids']), 1)
            target = root / 'AGENTS.md'
            self.assertEqual(self.run_cli(store, 'export', target).returncode, 0)
            text = target.read_text(encoding='utf-8')
            self.assertIn('## Rules', text)
            self.assertIn('- Rule: Always run tests before release.', text)

    def test_export_cap(self):
        records = [
            {'message_id': f'm{index}', 'content': f'Remember rule {index:03d}.', 'sources': {'s'}}
            for index in range(300)
        ]
        notes = dream_notes(records)
        self.assertEqual(len(notes), 300)
        capped = render_export(notes, max_lines=20, max_bytes=5000)
        self.assertLessEqual(len(capped.splitlines()), 22)
        self.assertIn('omitted', capped)
        full = render_export(notes, include_all=True)
        self.assertEqual(full.count('- Lesson:'), 300)

    def test_llm_parse(self):
        notes = parse_model_notes(
            '```json\n[{"text":"Prefer explicit configuration.","kind":"Rule",'
            '"confidence":"corroborated"}]\n```'
        )
        self.assertEqual(
            notes,
            [{'text': 'Prefer explicit configuration.', 'kind': 'Rule', 'confidence': 'corroborated'}],
        )

    def test_llm_chunking(self):
        records = [
            {
                'message_id': f'm{index}',
                'content': f'Prefer explicit configuration for module {index}. ' * 12,
                'sources': {f'file{index}'},
                'first_seen': '2026-01-01T00:00:00+00:00',
                'last_seen': '2026-01-01T00:00:00+00:00',
            }
            for index in range(5)
        ]
        body = json.dumps({
            'choices': [{
                'message': {
                    'content': json.dumps([
                        {
                            'text': 'Prefer explicit configuration.',
                            'kind': 'Rule',
                            'confidence': 'corroborated',
                        }
                    ])
                }
            }]
        }).encode('utf-8')

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return body

        with patch('midearms.urllib.request.urlopen', return_value=FakeResponse()) as mocked:
            notes = llm_dream(
                records,
                {
                    'provider': 'openai',
                    'endpoint': 'http://localhost:9999/v1',
                    'model': 'test',
                    'max_chars': 250,
                },
            )
        self.assertGreaterEqual(mocked.call_count, 2)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]['content'], 'Rule: Prefer explicit configuration.')
        self.assertEqual(notes[0]['confidence'], 'corroborated')
        self.assertGreater(notes[0]['sources'], 1)


if __name__ == '__main__':
    unittest.main()
