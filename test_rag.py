"""Small deterministic RAG checks; no live model or user documents required."""
import asyncio
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
import app
import database
import rag


def pdf_bytes():
    writer = PdfWriter()
    for text in ['Linked lists connect nodes with pointers.', 'Embedded records keep related data together. References connect separate records by identifier.']:
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
        stream = DecodedStreamObject()
        stream.set_data(('BT /F1 12 Tf 40 740 Td (' + text + ') Tj ET').encode())
        page[NameObject('/Contents')] = stream
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


class RagTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(database, 'DB_PATH', Path(self.temp.name) / 'study.db')
        self.db_patch.start()
        self.status_patch = patch.object(app, 'get_model_status', return_value=(True, 'Ready'))
        self.status_patch.start()
        self.models_patch = patch.object(app, 'installed_chat_models', return_value=[
            {'name': app.DEFAULT_CHAT_MODEL, 'display_name': 'Ornith 1.5 9B'}])
        self.models_patch.start()
        async def embed(text, **kwargs):
            if 'weather' in text.lower(): return [-1.0, -1.0]
            return [1.0, 0.0] if 'record' in text.lower() else [0.0, 1.0]
        self.embed_patch = patch.object(rag, 'embed_text', side_effect=embed)
        self.embed_mock = self.embed_patch.start()
        self.client = TestClient(app.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.embed_patch.stop()
        self.status_patch.stop()
        self.models_patch.stop()
        self.db_patch.stop()
        self.temp.cleanup()

    def upload(self):
        response = self.client.post('/documents', files={'file': ('../../lecture.pdf', pdf_bytes(), 'application/pdf')})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_pdf_pages_embeddings_retrieval_and_cleanup(self):
        document = self.upload()
        self.assertEqual(document['filename'], 'lecture.pdf')
        self.assertEqual(document['page_count'], 2)
        self.assertEqual(document['status'], 'ready')
        path = rag.documents_directory() / document['storage_name']
        self.assertTrue(path.exists())
        chunks = database.load_chunks([document['id']])
        self.assertEqual([c['page_number'] for c in chunks], [1, 2])
        self.assertEqual(len(chunks[0]['embedding']), 2)
        retrieved = asyncio.run(rag.retrieve_chunks('How do embedded records work?', [document['id']]))
        self.assertEqual(retrieved[0]['page_number'], 2)
        web = rag.build_rag_context(retrieved)
        self.assertEqual(web['sources'][0]['filename'], 'lecture.pdf')
        self.assertEqual(web['sources'][0]['page_number'], 2)
        self.assertEqual(web['sources'][0]['url'], '')
        self.assertEqual(asyncio.run(rag.retrieve_chunks('Weather tomorrow?', [document['id']])), [])
        self.client.post('/documents/' + document['id'] + '/delete')
        self.assertFalse(path.exists())
        self.assertEqual(database.load_chunks([document['id']]), [])

    def test_grounded_answer_persistence_regeneration_snapshot(self):
        document = self.upload()
        seen = []
        async def generate(request, conversation, save, web=None, settings=None):
            seen.append(web)
            yield app.stream_event('token', content='Grounded ')
            save('Grounded explanation [1]')
            yield app.stream_event('done', title='Test', content='Grounded explanation [1]')
        with patch.object(app, 'stream_from_ollama', generate):
            response = self.client.post('/chat', data={'message': 'Explain embedded records', 'course_materials': 'true', 'document_ids': json.dumps([document['id']])})
            events = [json.loads(line) for line in response.text.splitlines()]
            identifier = events[0]['conversation_id']
            original = database.load_messages(identifier)[-1]
            self.assertEqual(original['web']['kind'], 'document')
            self.assertEqual(database.selected_documents(identifier), [document['id']])
            self.client.__exit__(None, None, None)
            self.client = TestClient(app.app)
            self.client.__enter__()
            html = self.client.get('/', params={'conversation_id': identifier}).text
            self.assertIn('lecture.pdf — page 2', html)
            self.assertIn('lecture.pdf — page 2', self.client.get('/download', params={'conversation_id': identifier}).text)
            self.client.post('/documents/' + document['id'] + '/delete')
            self.assertEqual(database.selected_documents(identifier), [])
            with patch.object(rag, 'retrieve_chunks', side_effect=AssertionError('Must reuse evidence')):
                regen = self.client.post('/regenerate', data={'conversation_id': identifier})
            self.assertIn('"done"', regen.text)
            restored = database.load_messages(identifier)
            self.assertEqual(len(restored), 2)
            self.assertEqual(restored[-1]['id'], original['id'])
            self.assertEqual(restored[-1]['web'], original['web'])
            self.assertEqual(seen[-1], seen[0])

    def test_chat_attachments_are_automatic_scoped_and_detachable(self):
        async def generate(request, conversation, save, web=None, settings=None):
            answer = 'Grounded [1]' if web else 'Local answer'
            yield app.stream_event('token', content=answer)
            save(answer)
            yield app.stream_event('done', title='Test', content=answer)

        with patch.object(app, 'stream_from_ollama', generate):
            first = self.client.post('/chat', data={'message': 'Start conversation A'})
            conversation_a = json.loads(first.text.splitlines()[0])['conversation_id']
            upload = self.client.post('/documents', data={'conversation_id': conversation_a},
                                      files={'file': ('lecture.pdf', pdf_bytes(), 'application/pdf')})
            document = upload.json()
            self.assertEqual(database.selected_documents(conversation_a), [document['id']])
            document_embedding_calls = self.embed_mock.call_count

            answer = self.client.post('/chat', data={'conversation_id': conversation_a,
                                                      'message': 'Explain embedded records'})
            self.assertEqual(database.load_messages(conversation_a)[-1]['web']['kind'], 'document')
            self.assertIn('lecture.pdf', answer.text)
            self.assertEqual(self.embed_mock.call_count, document_embedding_calls + 1)

            self.client.post('/chat', data={'conversation_id': conversation_a,
                                            'message': 'Explain referenced records'})
            self.assertEqual(self.embed_mock.call_count, document_embedding_calls + 2)

            second = self.client.post('/chat', data={'message': 'Start conversation B'})
            conversation_b = json.loads(second.text.splitlines()[0])['conversation_id']
            self.assertEqual(database.selected_documents(conversation_b), [])
            self.assertIsNone(database.load_messages(conversation_b)[-1]['web'])

            reopened = self.client.get('/', params={'conversation_id': conversation_a}).text
            self.assertIn('lecture.pdf', reopened)
            detached = self.client.post(f'/conversations/{conversation_a}/documents',
                                        data={'document_ids': '[]'})
            self.assertEqual(detached.status_code, 200)
            self.assertEqual(database.selected_documents(conversation_a), [])
            self.assertIsNotNone(database.get_document(document['id']))
            self.assertTrue(database.load_chunks([document['id']]))

    def test_no_support_never_calls_qwen(self):
        document = self.upload()
        with patch.object(app, 'stream_from_ollama', side_effect=AssertionError('No evidence')):
            response = self.client.post('/chat', data={'message': 'Weather tomorrow?', 'course_materials':'true', 'document_ids':json.dumps([document['id']])})
        self.assertIn('does not provide enough relevant evidence', response.text)
        self.assertNotIn('"sources": [', response.text)

    def test_bad_uploads_and_embedding_failure(self):
        self.assertEqual(self.client.post('/documents', files={'file':('script.exe', b'bad')}).status_code, 400)
        self.assertEqual(self.client.post('/documents', files={'file':('fake.pdf', b'bad')}).status_code, 400)
        blank = PdfWriter()
        blank.add_blank_page(width=100, height=100)
        output = io.BytesIO()
        blank.write(output)
        response = self.client.post('/documents', files={'file':('scan.pdf', output.getvalue())})
        self.assertIn('No extractable text', response.text)
        with patch.object(rag, 'embed_text', AsyncMock(side_effect=RuntimeError('Offline'))):
            response = self.client.post('/documents', files={'file':('test.pdf', pdf_bytes())})
        self.assertEqual(response.status_code, 400)
        self.assertTrue(all(doc['status'] == 'error' for doc in database.list_documents()))
        self.assertEqual(database.load_chunks([doc['id'] for doc in database.list_documents()]), [])
        with patch.object(rag, 'MAX_UPLOAD_BYTES', 10):
            self.assertEqual(self.client.post('/documents', files={'file':('large.txt', b'x' * 11)}).status_code, 400)

    def test_modes_and_chunk_boundaries(self):
        response = self.client.post('/chat', data={'message':'Test', 'search_web':'true', 'course_materials':'true'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.post('/chat', data={'message':'Test', 'course_materials':'true'}).status_code, 400)
        chunks = rag.chunk_text([(1, 'word ' * 600), (3, 'A short final page')])
        self.assertTrue(all(len(c['text']) <= 1150 for c in chunks))
        self.assertEqual(chunks[-1]['page_number'], 3)
        self.assertEqual(rag.cosine_similarity([1,0], [1,0]), 1)
        self.assertAlmostEqual(rag.cosine_similarity([1,0], [0,1]), 0)


if __name__ == '__main__':
    unittest.main()
