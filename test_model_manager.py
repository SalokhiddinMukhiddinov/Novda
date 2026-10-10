"""Focused model discovery, runtime payload, and settings persistence checks."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import app
import database


CHAT_MODELS = [
    {'name': 'ornith-1.5:9b', 'display_name': 'Ornith 1.5 9B'},
    {'name': 'qwen3:4b-instruct-2507-q4_K_M', 'display_name': 'Qwen3 4B'},
]


class ModelManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(database, 'DB_PATH', Path(self.temp.name) / 'study.db')
        self.db_patch.start()
        database.initialize()

    def tearDown(self):
        self.db_patch.stop()
        self.temp.cleanup()

    def test_installed_models_exclude_embedding_only(self):
        payload = {'models': [
            {'name': 'ornith-1.5:9b', 'size': 10, 'capabilities': ['completion'],
             'details': {'family': 'qwen35', 'parameter_size': '9.0B'}},
            {'name': 'nomic-embed-text:latest', 'size': 5, 'capabilities': ['embedding'],
             'details': {'family': 'nomic-bert', 'parameter_size': '137M'}},
        ]}

        class Response:
            def raise_for_status(self): pass
            def json(self): return payload

        class Client:
            def __init__(self, *args, **kwargs): pass
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def get(self, url): return Response()

        with patch.object(app.httpx, 'Client', Client), TestClient(app.app) as client:
            result = client.get('/api/models').json()
        self.assertEqual([model['name'] for model in result['models']], ['ornith-1.5:9b'])
        self.assertNotIn('nomic-embed-text', json.dumps(result))

    def test_settings_persist_and_old_database_migrates(self):
        conversation_id, _ = database.save_user('', 'Hello', 'Hello')
        with patch.object(app, 'installed_chat_models', return_value=CHAT_MODELS), TestClient(app.app) as client:
            response = client.post(f'/conversations/{conversation_id}/settings', data={
                'chat_model': CHAT_MODELS[1]['name'], 'thinking': 'true', 'num_ctx': '16384'})
            self.assertEqual(response.status_code, 200)
            restored = database.get_conversation(conversation_id)
            self.assertEqual(restored['chat_model'], CHAT_MODELS[1]['name'])
            self.assertEqual(restored['thinking'], 1)
            self.assertEqual(restored['num_ctx'], 16384)
            html = client.get('/', params={'conversation_id': conversation_id}).text
            self.assertIn(f'value="{CHAT_MODELS[1]["name"]}" selected', html)
            self.assertIn('id="thinking-enabled" type="checkbox" checked', html)
            self.assertIn('value="16384" selected', html)

        legacy = Path(self.temp.name) / 'legacy.db'
        db = sqlite3.connect(legacy)
        try:
            db.execute('CREATE TABLE conversations(id TEXT PRIMARY KEY,title TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 0)')
            db.execute("INSERT INTO conversations VALUES ('old','Old','now','now',0)")
            db.commit()
        finally:
            db.close()
        with patch.object(database, 'DB_PATH', legacy):
            database.initialize()
            old = database.get_conversation('old')
        self.assertEqual((old['chat_model'], old['thinking'], old['num_ctx']),
                         (app.DEFAULT_CHAT_MODEL, 0, app.DEFAULT_NUM_CTX))

    def test_selected_runtime_reaches_ollama_and_metrics_are_saved(self):
        captured = {}

        class Response:
            status_code = 200
            def raise_for_status(self): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def aiter_lines(self):
                yield json.dumps({'message': {'content': 'Hello '}})
                yield json.dumps({'message': {'content': 'there'}, 'done': True,
                                  'model': CHAT_MODELS[1]['name'], 'total_duration': 6_200_000_000,
                                  'prompt_eval_count': 20, 'eval_count': 42, 'eval_duration': 5_000_000_000})

        class Client:
            def __init__(self, *args, **kwargs): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            def stream(self, method, url, json):
                captured.update(json)
                return Response()

        request = AsyncMock()
        request.is_disconnected.return_value = False
        saved = []
        settings = {'chat_model': CHAT_MODELS[1]['name'], 'thinking': True, 'num_ctx': 16384}

        async def collect():
            return [json.loads(event) async for event in app.stream_from_ollama(
                request, [{'role': 'user', 'content': 'Hi'}],
                lambda answer, runtime: saved.append((answer, runtime)), settings=settings)]

        import asyncio
        with patch.object(app.httpx, 'AsyncClient', Client):
            events = asyncio.run(collect())
        self.assertEqual(captured['model'], CHAT_MODELS[1]['name'])
        self.assertTrue(captured['think'])
        self.assertEqual(captured['options']['num_ctx'], 16384)
        self.assertEqual(saved[0][0], 'Hello there')
        self.assertEqual(saved[0][1]['tokens_per_second'], 8.4)
        self.assertEqual(events[-1]['runtime']['eval_count'], 42)

    def test_regeneration_uses_current_conversation_settings(self):
        conversation_id, revision = database.save_user('', 'Explain it', 'Explain It')
        database.set_conversation_settings(conversation_id, CHAT_MODELS[1]['name'], True, 4096)
        database.save_assistant(conversation_id, revision, 'First answer', None)
        seen = []

        async def generate(request, conversation, save, web=None, settings=None):
            seen.append(settings)
            yield app.stream_event('token', content='Revised')
            save('Revised', {'model': settings['chat_model']})
            yield app.stream_event('done', title='Explain It', runtime={'model': settings['chat_model']})

        with (patch.object(app, 'installed_chat_models', return_value=CHAT_MODELS),
              patch.object(app, 'stream_from_ollama', generate), TestClient(app.app) as client):
            response = client.post('/regenerate', data={'conversation_id': conversation_id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(seen[0], {'chat_model': CHAT_MODELS[1]['name'], 'thinking': True, 'num_ctx': 4096})
        self.assertEqual(database.load_messages(conversation_id)[-1]['content'], 'Revised')


if __name__ == '__main__':
    unittest.main()
