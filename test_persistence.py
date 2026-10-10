"""Persistence and route lifecycle checks using an isolated temporary database."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
import app
import database


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path_patch = patch.object(database, 'DB_PATH', Path(self.temp.name) / 'data' / 'test.db')
        self.path_patch.start()
        self.mode = 'complete'
        self.histories = []
        self.web = {'query': 'AI releases', 'evidence': '[1] Official evidence', 'sources': [
            {'number': 1, 'title': 'Official <documentation>', 'domain': 'example.com',
             'url': 'https://example.com/docs', 'snippet': 'Release information', 'scores': {'quality': 4}}]}

        self.models_patch = patch.object(app, 'installed_chat_models', return_value=[
            {'name': app.DEFAULT_CHAT_MODEL, 'display_name': 'Ornith 1.5 9B'}])
        self.models_patch.start()
        async def generate(request, conversation, save_response, web=None, settings=None):
            self.histories.append(conversation)
            yield app.stream_event('token', content='Partial ')
            if self.mode == 'stop':
                return
            if self.mode == 'fail':
                yield app.stream_event('error', message='Failed')
                return
            save_response('Completed answer [1]' if web else 'Completed answer')
            yield app.stream_event('done', title=app.make_conversation_title(conversation))
        self.generation_patch = patch.object(app, 'stream_from_ollama', generate)
        self.generation_patch.start()
        self.search_patch = patch.object(app, 'search_evidence', AsyncMock(return_value=self.web))
        self.search_mock = self.search_patch.start()
        self.status_patch = patch.object(app, 'get_model_status', return_value=(True, 'Ready'))
        self.status_patch.start()

    def tearDown(self):
        self.status_patch.stop()
        self.models_patch.stop()
        self.search_patch.stop()
        self.generation_patch.stop()
        self.path_patch.stop()
        self.temp.cleanup()

    def send(self, client, text, conversation_id='', web=False):
        response = client.post('/chat', data={'message': text, 'conversation_id': conversation_id, 'search_web': str(web).lower()})
        self.assertEqual(response.status_code, 200)
        events = [json.loads(line) for line in response.text.splitlines()]
        return events[0]['conversation_id'], events

    def test_two_chats_restart_sources_regeneration_delete_export(self):
        with TestClient(app.app) as client:
            a, _ = self.send(client, 'Explain Astra models', web=True)
            client.post('/new-chat')
            self.assertEqual(len(database.list_conversations()), 1)
            b, _ = self.send(client, 'Python linked lists')
            self.assertNotEqual(a, b)
            self.assertNotIn('Astra', str(self.histories[-1]))
            html = client.get('/', params={'conversation_id': a}).text
            self.assertIn('Astra models', html)
            self.assertIn('https://example.com/docs', html)
            self.assertIn('Official &lt;documentation&gt;', html)
            self.assertIn('Python Linked Lists', html)  # Sidebar keeps B visible.

        # A fresh app lifespan recreates schema safely and reloads the same file.
        with TestClient(app.app) as client:
            self.assertEqual(len(database.list_conversations()), 2)
            restored = database.load_messages(a)
            self.assertEqual(restored[-1]['web']['evidence'], self.web['evidence'])
            self.assertEqual(restored[-1]['web']['sources'][0]['scores'], {'quality': 4})
            old_id = restored[-1]['id']
            calls = self.search_mock.await_count
            client.post('/regenerate', data={'conversation_id': a})
            self.assertEqual(self.search_mock.await_count, calls)
            self.assertEqual(len(database.load_messages(a)), 2)
            self.assertEqual(database.load_messages(a)[-1]['id'], old_id)
            self.mode = 'stop'
            client.post('/regenerate', data={'conversation_id': a})
            self.assertEqual(database.load_messages(a)[-1]['content'], restored[-1]['content'])
            self.mode = 'fail'
            client.post('/regenerate', data={'conversation_id': a})
            self.assertEqual(database.load_messages(a)[-1]['web'], restored[-1]['web'])
            export = client.get('/download', params={'conversation_id': a}).text
            self.assertIn('https://example.com/docs', export)
            self.assertNotIn('linked lists', export)
            client.post(f'/conversations/{a}/delete', data={'active_id': b})
            self.assertIsNone(database.get_conversation(a))
            self.assertEqual(len(database.load_messages(b)), 2)
            with database.connection() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM sources').fetchone()[0], 0)
            self.assertEqual(client.get('/', params={'conversation_id': a}).status_code, 404)

    def test_stop_and_retry_no_duplicate_user_or_partial_answer(self):
        with TestClient(app.app) as client:
            self.mode = 'stop'
            a, _ = self.send(client, "A user's question")
            self.assertEqual([m['role'] for m in database.load_messages(a)], ['user'])
            self.assertIn('data-pending-message="true"', client.get('/', params={'conversation_id': a}).text)
            self.mode = 'complete'
            self.send(client, 'Edited question', a)
            self.assertEqual([m['role'] for m in database.load_messages(a)], ['user', 'assistant'])
            self.assertEqual(database.load_messages(a)[0]['content'], 'Edited question')

    def test_stale_completion_and_deleted_chat_cannot_save(self):
        database.initialize()
        a, first = database.save_user('', 'First', 'First')
        _, second = database.save_user(a, 'Revised', 'First')
        with self.assertRaises(ValueError):
            database.save_assistant(a, first, 'Stale', None)
        database.save_assistant(a, second, 'Correct', None)
        database.delete_conversation(a)
        with self.assertRaises(ValueError):
            database.save_assistant(a, second + 1, 'Late', None)
        self.assertEqual(database.load_messages(a), [])


if __name__ == '__main__':
    unittest.main()
