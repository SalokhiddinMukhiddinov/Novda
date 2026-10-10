"""Focused regression checks; run with python -m unittest test_web_reliability."""
import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

import app


class WebReliabilityTests(unittest.IsolatedAsyncioTestCase):
    def test_context_and_relevance(self):
        query = app.improve_query('Astra models', [{'role': 'user', 'content': 'Explain AI language models'}])
        self.assertIn('AI language', query)
        car = {'title': 'Vauxhall Astra models', 'body': 'New hatchback and horsepower', 'href': 'https://vauxhall.co.uk/astra'}
        ai = {'title': 'Astra AI models', 'body': 'Language models for reasoning', 'href': 'https://example.com/astra'}
        self.assertEqual(app.source_scores(car, query)[0], 0)
        self.assertGreater(app.source_scores(ai, query)[0], 0)
        self.assertEqual(app.improve_query('Mercury', []), 'Mercury')
        self.assertEqual(app.improve_query('Vauxhall Astra cars', [{'role': 'user', 'content': 'AI models'}]), 'Vauxhall Astra cars')

    def test_quality_and_freshness(self):
        official = {'title': 'Qwen new model', 'body': 'Qwen release', 'href': 'https://qwen.ai/blog', 'date': app.date.today().isoformat()}
        unrelated = {'title': 'Unrelated', 'body': 'Nothing useful', 'href': 'https://qwen.ai/'}
        score = app.source_scores(official, 'latest Qwen model')
        self.assertEqual(score[1:3], (4, 3))
        old = dict(official, date='2020-01-01')
        self.assertEqual(app.source_scores(old, 'latest Qwen model')[2], -2)
        self.assertEqual(app.source_scores(unrelated, 'Astra AI models')[0], 0)

    async def test_snippets_survive_fetch_failure_and_conflicts(self):
        results = [
            {'title': 'Qwen announcement', 'href': 'https://qwen.ai/a', 'body': 'Qwen launches on Monday.'},
            {'title': 'Qwen reporting', 'href': 'https://reuters.com/b', 'body': 'Qwen launches on Tuesday.'},
        ]
        async def valid(url): return url, '1.1.1.1'
        with patch('ddgs.DDGS') as ddgs, patch.object(app, 'public_url', valid), patch.object(app, 'fetch_page', AsyncMock(side_effect=ValueError('Fetch failed'))):
            ddgs.return_value.text.return_value = results
            web = await app.search_evidence('latest Qwen model')
        self.assertEqual(len(web['sources']), 2)
        self.assertIn('Monday', web['evidence'])
        self.assertIn('Tuesday', web['evidence'])
        self.assertEqual(web['sources'][0]['snippet'], results[0]['body'])
        self.assertLessEqual(len(web['evidence']), 4500)

    async def test_stream_validates_citations_before_saving(self):
        class Response:
            status_code = 200
            def raise_for_status(self): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def aiter_lines(self):
                for text in ['A fact [', '1]. Another [99].']:
                    yield json.dumps({'message': {'content': text}})
                yield json.dumps({'done': True})
        class Client(Response):
            def __init__(self, *args, **kwargs): pass
            def stream(self, *args, **kwargs): return Response()
        request = AsyncMock()
        request.is_disconnected.return_value = False
        saved = []
        with patch.object(app.httpx, 'AsyncClient', Client):
            events = [json.loads(e) async for e in app.stream_from_ollama(request, [{'role':'user','content':'Test'}], lambda text, runtime: saved.append(text), {'sources':[{'number':1}], 'evidence':'Fact'})]
        self.assertEqual(len([e for e in events if e['type']=='token']), 2)
        self.assertNotIn('[99]', saved[0])
        self.assertIn('[1]', saved[0])
        self.assertEqual(events[-1]['content'], saved[0])


if __name__ == '__main__':
    unittest.main()
