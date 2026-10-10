"""Security, bounded reads/searches, orchestration, and citation-integrity tests."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import app
import repository_tools as tools


class RepositoryToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'approved'
        self.root.mkdir()
        (self.root / 'app.py').write_text('\n'.join([
            'from fastapi import FastAPI',
            'OLLAMA_CHAT_URL = "http://localhost:11434/api/chat"',
            'def stream_from_ollama():',
            '    payload = {"options": {"num_ctx": 8192}}',
            '    return payload',
        ]), encoding='utf-8')
        (self.root / 'database.py').write_text('import sqlite3\n\ndef load_messages():\n    return sqlite3.connect("chat.db")\n', encoding='utf-8')
        (self.root / 'notes.md').write_text('Conversation persistence uses SQLite.\n', encoding='utf-8')
        for filename, content in {
            'settings.json': '    {"enabled": true}\n',
            'notes.txt': '    plain text\n',
            'project.toml': '    name = "novda"\n',
            'config.yaml': '    enabled: true\n',
            'config.yml': '    enabled: true\n',
        }.items():
            (self.root / filename).write_text(content, encoding='utf-8')
        (self.root / 'static').mkdir()
        (self.root / 'static' / 'app.js').write_text('function sendMessage() {\n    return fetch("/chat");\n}\n', encoding='utf-8')
        (self.root / 'static' / 'style.css').write_text('.composer {\n    display: flex;\n}\n', encoding='utf-8')
        (self.root / 'templates').mkdir()
        (self.root / 'templates' / 'index.html').write_text('<form id="chat-form">\n    <button>Send</button>\n</form>\n', encoding='utf-8')
        (self.root / 'binary.db').write_bytes(b'\x00\x01')
        (self.root / '.git').mkdir()
        (self.root / '.git' / 'secret.py').write_text('num_ctx secret', encoding='utf-8')
        self.outside = Path(self.temp.name) / 'outside.py'
        self.outside.write_text('outside', encoding='utf-8')
        self.roots_patch = patch.object(tools, 'ALLOWED_ROOTS', (self.root,))
        self.roots_patch.start()

    def tearDown(self):
        self.roots_patch.stop()
        self.temp.cleanup()

    def test_private_content_is_excluded_from_all_repository_tools(self):
        sensitive_paths = ['.env', '.env.private.json', 'credentials.json', 'secrets.json',
                           'uploads/notes.md', 'exports/chat.txt', 'logs/session.txt',
                           '.aws/settings.json', '.ssh/config.txt', 'DATA/notes.md']
        for relative in sensitive_paths:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('private_content_sentinel', encoding='utf-8')
            with self.subTest(path=relative):
                with self.assertRaises(tools.RepositoryToolError):
                    tools.read_file(relative)
                with self.assertRaises(tools.RepositoryToolError):
                    tools.resolve_approved_path(relative, require_file=True)
                with self.assertRaises(tools.RepositoryToolError):
                    tools.find_in_file(relative, 'private_content_sentinel')
        names = {entry['name'] for entry in tools.list_directory()}
        self.assertTrue(names.isdisjoint({path.split('/')[0] for path in sensitive_paths}))
        self.assertEqual(tools.search_files('private_content_sentinel'), [])
        (self.root / '.env.example').write_text('OLLAMA_BASE_URL=http://localhost:11434\n', encoding='utf-8')
        self.assertIn('OLLAMA_BASE_URL', tools.read_file('.env.example')['content'])

    def test_configured_data_directory_is_private(self):
        import database
        private_directory = self.root / 'local-state'
        private_directory.mkdir()
        (private_directory / 'notes.md').write_text('private_content_sentinel', encoding='utf-8')
        with patch.object(database, 'DB_PATH', private_directory / 'chat.db'):
            with self.assertRaises(tools.RepositoryToolError):
                tools.read_file('local-state/notes.md')
            self.assertNotIn('local-state', {entry['name'] for entry in tools.list_directory()})
            with self.assertRaises(tools.RepositoryToolError):
                tools.find_in_file('local-state/notes.md', 'private_content_sentinel')
            self.assertEqual(tools.search_files('private_content_sentinel'), [])

    def test_allowed_listing_and_escape_rejection(self):
        listing = tools.list_directory()
        self.assertIn('app.py', [entry['name'] for entry in listing])
        self.assertNotIn('.git', [entry['name'] for entry in listing])
        with self.assertRaises(tools.RepositoryToolError):
            tools.read_file('../outside.py')
        with self.assertRaises(tools.RepositoryToolError):
            tools.read_file('..\\outside.py')
        with self.assertRaises(tools.RepositoryToolError):
            tools.read_file(str(self.outside.resolve()))
        with self.assertRaises(tools.RepositoryToolError):
            tools.read_file('binary.db')
        with self.assertRaises(tools.RepositoryToolError):
            tools.list_directory('.git')

    def test_filename_text_find_and_partial_read(self):
        filenames = tools.search_files('database')
        self.assertEqual(filenames[0]['path'], 'database.py')
        content = tools.search_files('num_ctx Ollama')
        self.assertEqual(content[0]['path'], 'app.py')
        self.assertNotIn('.git/secret.py', [result['path'] for result in content])
        matches = tools.find_in_file('app.py', 'num_ctx')
        self.assertEqual(matches[0]['line_number'], 4)
        section = tools.read_file('app.py', 2, 4)
        self.assertEqual((section['start_line'], section['end_line']), (2, 4))
        self.assertIn('4 |     payload', section['content'])

    def test_required_code_types_are_read_as_numbered_source(self):
        expected = {
            'app.py': '1 | from fastapi',
            'static/app.js': '2 |     return fetch',
            'templates/index.html': '2 |     <button>',
            'static/style.css': '2 |     display: flex',
            'settings.json': '1 |     {"enabled": true}',
            'notes.md': '1 | Conversation persistence',
            'notes.txt': '1 |     plain text',
            'project.toml': '1 |     name = "novda"',
            'config.yaml': '1 |     enabled: true',
            'config.yml': '1 |     enabled: true',
        }
        for path, source_line in expected.items():
            with self.subTest(path=path):
                result = tools.read_file(path)
                self.assertIn(source_line, result['content'])

    def test_direct_filename_and_relative_path_requests_route_to_direct_reads(self):
        for prompt, path in (
            ('Read app.py.', 'app.py'),
            ('Open templates/index.html.', 'templates/index.html'),
            ('Read static/app.js and explain sendMessage.', 'static/app.js'),
            ('Find the composer in static/style.css.', 'static/style.css'),
        ):
            with self.subTest(prompt=prompt):
                self.assertTrue(tools.is_repository_question(prompt))
                evidence = tools.gather_repository_evidence(prompt)
                self.assertEqual(evidence['tool_calls'][0]['tool'], 'read_file')
                self.assertEqual(evidence['tool_calls'][0]['path'], path)
                self.assertIn(expected_reference_prefix(path), evidence['sources'][0]['reference'])

    def test_explicit_line_range_and_real_errors(self):
        evidence = tools.gather_repository_evidence('Show me lines 2-3 of app.py.')
        self.assertEqual(evidence['sources'][0]['reference'], 'app.py:2-3')
        with self.assertRaisesRegex(tools.RepositoryToolError, 'Unsupported'):
            tools.gather_repository_evidence('Read binary.db')
        with self.assertRaisesRegex(tools.RepositoryToolError, 'traversal'):
            tools.gather_repository_evidence('Read ../outside.py')

    def test_read_search_and_tool_call_limits(self):
        (self.root / 'long.py').write_text('\n'.join(f'line {number}' for number in range(250)), encoding='utf-8')
        with self.assertRaises(tools.RepositoryToolError):
            tools.read_file('long.py', 1, 201)
        for number in range(25):
            (self.root / f'match_{number}.py').write_text('shared_search_term = True', encoding='utf-8')
        self.assertEqual(len(tools.search_files('shared_search_term')), tools.MAX_SEARCH_RESULTS)
        with self.assertRaises(tools.RepositoryToolError):
            tools.search_files('term', limit=tools.MAX_SEARCH_RESULTS + 1)
        with self.assertRaises(tools.RepositoryToolError):
            tools.gather_repository_evidence('num_ctx', max_calls=tools.MAX_TOOL_CALLS + 1)
        evidence = tools.gather_repository_evidence('Where is num_ctx configured?')
        self.assertLessEqual(len(evidence['tool_calls']), tools.MAX_TOOL_CALLS)
        self.assertTrue(evidence['sources'][0]['reference'].startswith('app.py:'))
        self.assertLessEqual(len(evidence['evidence']), tools.MAX_RESULT_CHARS)

    def test_backend_removes_fabricated_repository_references(self):
        web = {'kind': 'repository', 'sources': [
            {'number': 1, 'reference': 'app.py:2-4'}
        ], 'evidence': '[1] app.py:2-4\n2: OLLAMA_CHAT_URL'}

        class Response:
            status_code = 200
            def raise_for_status(self): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def aiter_lines(self):
                yield json.dumps({'message': {'content': 'See app.py:2-4 [1], not evil.py:999 [8].'}, 'done': True})

        class Client:
            def __init__(self, *args, **kwargs): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            def stream(self, *args, **kwargs): return Response()

        request = AsyncMock()
        request.is_disconnected.return_value = False
        saved = []

        async def run():
            return [json.loads(event) async for event in app.stream_from_ollama(
                request, [{'role': 'user', 'content': 'Where?'}],
                lambda answer, runtime: saved.append(answer), web,
                {'chat_model': app.DEFAULT_CHAT_MODEL, 'thinking': False, 'num_ctx': 8192})]

        with patch.object(app.httpx, 'AsyncClient', Client):
            events = asyncio.run(run())
        self.assertIn('app.py:2-4 [1]', saved[0])
        self.assertNotIn('evil.py:999', saved[0])
        self.assertNotIn('[8]', saved[0])
        self.assertEqual(events[-1]['content'], saved[0])

    def test_repository_prompt_prevents_false_capability_refusal(self):
        self.assertIn('controlled read-only access', app.REPOSITORY_PROMPT)
        self.assertIn('never say you cannot access', app.REPOSITORY_PROMPT)


def expected_reference_prefix(path):
    return f'{path}:'


class ActualRepositoryAcceptanceTests(unittest.TestCase):
    def test_real_required_files_return_numbered_source(self):
        for path in ('app.py', 'database.py', 'repository_tools.py', 'templates/index.html',
                     'static/app.js', 'static/style.css'):
            with self.subTest(path=path):
                result = tools.read_file(path, 1, 5)
                self.assertEqual(result['path'], path)
                self.assertTrue(result['content'].startswith('1 | '))

    def test_real_cross_file_queries_read_relevant_files(self):
        model_flow = tools.gather_repository_evidence('Trace the model selection flow from the browser to app.py.')
        self.assertEqual(model_flow['tool_calls'][0]['tool'], 'search_files')
        self.assertEqual({source['path'] for source in model_flow['sources']}, {'app.py', 'static/app.js'})
        repository_access = tools.gather_repository_evidence(
            'Which files implement repository access? Explain using the actual code.')
        self.assertIn('repository_tools.py', {source['path'] for source in repository_access['sources']})


if __name__ == '__main__':
    unittest.main()
