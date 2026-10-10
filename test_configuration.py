"""Configuration must stay portable without changing the existing local defaults."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent


class ConfigurationTests(unittest.TestCase):
    def read_configuration(self, **overrides):
        environment = os.environ.copy()
        environment.pop('OLLAMA_BASE_URL', None)
        environment.pop('NOVDA_DATA_DIR', None)
        environment.update(overrides)
        environment['PYTHONPATH'] = str(PROJECT_ROOT)
        script = (
            'import json, app, database, rag; '
            'print(json.dumps([str(database.DB_PATH), app.OLLAMA_CHAT_URL, rag.EMBED_URL]))'
        )
        with tempfile.TemporaryDirectory() as unrelated_directory:
            output = subprocess.check_output(
                [sys.executable, '-B', '-c', script], cwd=unrelated_directory,
                env=environment, text=True, timeout=30,
            )
        return json.loads(output)

    def test_defaults_work_from_an_unrelated_directory(self):
        db_path, chat_url, embed_url = self.read_configuration()
        self.assertEqual(Path(db_path), PROJECT_ROOT / 'data' / 'study_assistant.db')
        self.assertEqual(chat_url, 'http://localhost:11434/api/chat')
        self.assertEqual(embed_url, 'http://localhost:11434/api/embed')

    def test_relative_data_override_and_shared_ollama_endpoint(self):
        db_path, chat_url, embed_url = self.read_configuration(
            NOVDA_DATA_DIR='data/demo', OLLAMA_BASE_URL='http://127.0.0.1:11435/',
        )
        self.assertEqual(Path(db_path), PROJECT_ROOT / 'data' / 'demo' / 'study_assistant.db')
        self.assertEqual(chat_url, 'http://127.0.0.1:11435/api/chat')
        self.assertEqual(embed_url, 'http://127.0.0.1:11435/api/embed')

    def test_absolute_data_override(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path, _, _ = self.read_configuration(NOVDA_DATA_DIR=directory)
            self.assertEqual(Path(db_path), Path(directory).resolve() / 'study_assistant.db')


if __name__ == '__main__':
    unittest.main()
