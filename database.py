"""Local chat storage. Each operation owns and closes its SQLite connection."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

# Relative overrides are anchored to the project, independent of the launch directory.
PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIRECTORY = Path(os.environ.get('NOVDA_DATA_DIR', 'data')).expanduser()
if not DATA_DIRECTORY.is_absolute():
    DATA_DIRECTORY = PROJECT_ROOT / DATA_DIRECTORY
DB_PATH = DATA_DIRECTORY.resolve() / 'study_assistant.db'


@contextmanager
def connection():
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys = ON')
    try:
        with db:
            yield db
    finally:
        db.close()


def initialize():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connection() as db:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY, title TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                revision INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY, conversation_id TEXT NOT NULL
                    REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                content TEXT NOT NULL, created_at TEXT NOT NULL, web_json TEXT
            );
            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY, message_id INTEGER NOT NULL
                    REFERENCES messages(id) ON DELETE CASCADE,
                number INTEGER NOT NULL, title TEXT NOT NULL, domain TEXT NOT NULL,
                url TEXT NOT NULL, snippet TEXT NOT NULL, metadata_json TEXT NOT NULL,
                UNIQUE(message_id, number)
            );
            CREATE INDEX IF NOT EXISTS messages_conversation ON messages(conversation_id, id);
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY, filename TEXT NOT NULL, storage_name TEXT NOT NULL,
                created_at TEXT NOT NULL, page_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL, error TEXT NOT NULL DEFAULT '', embedding_model TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS document_chunks (
                id INTEGER PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                page_number INTEGER NOT NULL, chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL, embedding TEXT NOT NULL,
                UNIQUE(document_id, chunk_index)
            );
            CREATE TABLE IF NOT EXISTS conversation_documents (
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                PRIMARY KEY(conversation_id, document_id)
            );
            CREATE TABLE IF NOT EXISTS coding_patches (
                id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                summary TEXT NOT NULL, patch_json TEXT NOT NULL, diff TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('proposed','rejected','applied','stale','failed')),
                test_json TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS coding_patches_conversation ON coding_patches(conversation_id, created_at);
        ''')
        # Lightweight additive migrations preserve databases created by V0.6–V0.8.
        conversation_columns = {row['name'] for row in db.execute('PRAGMA table_info(conversations)')}
        if 'chat_model' not in conversation_columns:
            db.execute("ALTER TABLE conversations ADD COLUMN chat_model TEXT NOT NULL DEFAULT 'ornith-1.5:9b'")
        if 'thinking' not in conversation_columns:
            db.execute('ALTER TABLE conversations ADD COLUMN thinking INTEGER NOT NULL DEFAULT 0')
        if 'num_ctx' not in conversation_columns:
            db.execute('ALTER TABLE conversations ADD COLUMN num_ctx INTEGER NOT NULL DEFAULT 8192')
        message_columns = {row['name'] for row in db.execute('PRAGMA table_info(messages)')}
        if 'runtime_json' not in message_columns:
            db.execute('ALTER TABLE messages ADD COLUMN runtime_json TEXT')


def now():
    return datetime.now(timezone.utc).isoformat()


def list_conversations():
    with connection() as db:
        return [dict(row) for row in db.execute('SELECT * FROM conversations ORDER BY updated_at DESC, id')]


def get_conversation(conversation_id):
    with connection() as db:
        row = db.execute('SELECT * FROM conversations WHERE id = ?', (conversation_id,)).fetchone()
        return dict(row) if row else None


def load_messages(conversation_id):
    with connection() as db:
        messages = []
        for row in db.execute('SELECT * FROM messages WHERE conversation_id = ? ORDER BY id', (conversation_id,)):
            message = dict(row)
            message['web'] = json.loads(message.pop('web_json')) if row['web_json'] else None
            message['runtime'] = json.loads(message.pop('runtime_json')) if row['runtime_json'] else None
            if message['web'] is not None:
                message['web']['sources'] = []
                for source_row in db.execute('SELECT * FROM sources WHERE message_id = ? ORDER BY number', (row['id'],)):
                    source = dict(source_row)
                    extra = json.loads(source.pop('metadata_json'))
                    source.pop('id')
                    source.pop('message_id')
                    source.update(extra)
                    message['web']['sources'].append(source)
            messages.append(message)
        return messages


def save_user(conversation_id, content, title):
    """Create on first send, or retry the last unanswered user message in place."""
    timestamp = now()
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        if not conversation_id:
            conversation_id = uuid4().hex
            db.execute('INSERT INTO conversations(id,title,created_at,updated_at) VALUES (?,?,?,?)',
                       (conversation_id, title, timestamp, timestamp))
        elif not db.execute('SELECT id FROM conversations WHERE id = ?', (conversation_id,)).fetchone():
            raise ValueError('Conversation no longer exists.')
        last = db.execute('SELECT id,role FROM messages WHERE conversation_id = ? ORDER BY id DESC LIMIT 1', (conversation_id,)).fetchone()
        if last and last['role'] == 'user':
            db.execute('UPDATE messages SET content = ? WHERE id = ?', (content, last['id']))
        else:
            db.execute('INSERT INTO messages(conversation_id,role,content,created_at) VALUES (?,?,?,?)',
                       (conversation_id, 'user', content, timestamp))
        db.execute('UPDATE conversations SET revision = revision + 1, updated_at = ? WHERE id = ?', (timestamp, conversation_id))
        revision = db.execute('SELECT revision FROM conversations WHERE id = ?', (conversation_id,)).fetchone()['revision']
    return conversation_id, revision


def save_assistant(conversation_id, revision, content, web, replace_id=None, runtime=None):
    """Commit text and sources atomically; reject stale/deleted-chat completions."""
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        changed = db.execute('UPDATE conversations SET updated_at = ?, revision = revision + 1 WHERE id = ? AND revision = ?',
                             (now(), conversation_id, revision))
        if changed.rowcount != 1:
            raise ValueError('Conversation changed while generating. Reload it before retrying.')
        metadata = json.dumps({key: value for key, value in web.items() if key != 'sources'}, ensure_ascii=False) if web else None
        runtime_metadata = json.dumps(runtime, ensure_ascii=False) if runtime else None
        if replace_id is not None:
            changed = db.execute("UPDATE messages SET content = ?, web_json = ?, runtime_json = ? WHERE id = ? AND conversation_id = ? AND role = 'assistant'",
                                 (content, metadata, runtime_metadata, replace_id, conversation_id))
            if changed.rowcount != 1:
                raise ValueError('Answer no longer exists.')
            db.execute('DELETE FROM sources WHERE message_id = ?', (replace_id,))
            message_id = replace_id
        else:
            message_id = db.execute('INSERT INTO messages(conversation_id,role,content,created_at,web_json,runtime_json) VALUES (?,?,?,?,?,?)',
                                    (conversation_id, 'assistant', content, now(), metadata, runtime_metadata)).lastrowid
        for source in web['sources'] if web else []:
            extra = {key: value for key, value in source.items() if key not in {'number','title','domain','url','snippet'}}
            db.execute('INSERT INTO sources(message_id,number,title,domain,url,snippet,metadata_json) VALUES (?,?,?,?,?,?,?)',
                       (message_id, source['number'], source['title'], source['domain'], source['url'], source.get('snippet', ''), json.dumps(extra)))
        return message_id


def create_coding_patch(conversation_id, patch):
    patch_id = uuid4().hex
    timestamp = now()
    stored = {'summary': patch['summary'], 'changes': patch['changes'], 'files': patch['files'],
              'additions': patch['additions'], 'deletions': patch['deletions']}
    with connection() as db:
        db.execute('INSERT INTO coding_patches(id,conversation_id,summary,patch_json,diff,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)',
                   (patch_id, conversation_id, patch['summary'], json.dumps(stored), patch['diff'], 'proposed', timestamp, timestamp))
    return get_coding_patch(patch_id)


def get_coding_patch(patch_id):
    with connection() as db:
        row = db.execute('SELECT * FROM coding_patches WHERE id = ?', (patch_id,)).fetchone()
        if not row:
            return None
        patch = dict(row)
        patch['patch'] = json.loads(patch.pop('patch_json'))
        patch['test'] = json.loads(patch.pop('test_json')) if patch['test_json'] else None
        return patch


def list_coding_patches(conversation_id):
    with connection() as db:
        ids = [row['id'] for row in db.execute('SELECT id FROM coding_patches WHERE conversation_id = ? ORDER BY created_at', (conversation_id,))]
    return [get_coding_patch(patch_id) for patch_id in ids]


def update_coding_patch(patch_id, status, test=None):
    with connection() as db:
        changed = db.execute('UPDATE coding_patches SET status = ?, test_json = ?, updated_at = ? WHERE id = ?',
                             (status, json.dumps(test) if test is not None else None, now(), patch_id))
        if changed.rowcount != 1:
            raise ValueError('Patch proposal no longer exists.')


def delete_conversation(conversation_id):
    with connection() as db:
        db.execute('DELETE FROM conversations WHERE id = ?', (conversation_id,))


def set_conversation_settings(conversation_id, chat_model, thinking, num_ctx):
    with connection() as db:
        changed = db.execute(
            'UPDATE conversations SET chat_model = ?, thinking = ?, num_ctx = ? WHERE id = ?',
            (chat_model, int(bool(thinking)), num_ctx, conversation_id),
        )
        if changed.rowcount != 1:
            raise ValueError('Conversation no longer exists.')


def list_documents():
    with connection() as db:
        return [dict(row) for row in db.execute('SELECT * FROM documents ORDER BY created_at DESC')]


def get_document(document_id):
    with connection() as db:
        row = db.execute('SELECT * FROM documents WHERE id = ?', (document_id,)).fetchone()
        return dict(row) if row else None


def create_document(document_id, filename, storage_name, model):
    with connection() as db:
        db.execute('INSERT INTO documents(id,filename,storage_name,created_at,status,embedding_model) VALUES (?,?,?,?,?,?)',
                   (document_id, filename, storage_name, now(), 'processing', model))


def complete_document(document_id, page_count, chunks):
    with connection() as db:
        changed = db.execute("UPDATE documents SET page_count = ?, status = 'ready', error = '' WHERE id = ? AND status = 'processing'", (page_count, document_id))
        if changed.rowcount != 1:
            raise ValueError('Document was removed during processing.')
        db.executemany('INSERT INTO document_chunks(document_id,page_number,chunk_index,text,embedding) VALUES (?,?,?,?,?)',
                       [(document_id, chunk['page_number'], index, chunk['text'], json.dumps(chunk['embedding'])) for index, chunk in enumerate(chunks)])


def fail_document(document_id, error):
    with connection() as db:
        db.execute("UPDATE documents SET status = 'error', error = ? WHERE id = ?", (error, document_id))
        db.execute('DELETE FROM document_chunks WHERE document_id = ?', (document_id,))


def recover_document_processing():
    with connection() as db:
        db.execute("UPDATE documents SET status = 'error', error = ? WHERE status = 'processing'",
                   ('Processing was interrupted. Remove the document and upload it again.',))


def selected_documents(conversation_id):
    with connection() as db:
        return [row['document_id'] for row in db.execute('SELECT document_id FROM conversation_documents WHERE conversation_id = ?', (conversation_id,))]


def validate_documents(document_ids):
    if len(document_ids) > 20 or any(not isinstance(identifier, str) for identifier in document_ids):
        raise ValueError('Select at most 20 documents.')
    for identifier in document_ids:
        document = get_document(identifier)
        if not document or document['status'] != 'ready':
            raise ValueError('A selected document is missing or not ready. Check Course Materials.')


def set_selected_documents(conversation_id, document_ids):
    validate_documents(document_ids)
    with connection() as db:
        db.execute('DELETE FROM conversation_documents WHERE conversation_id = ?', (conversation_id,))
        db.executemany('INSERT INTO conversation_documents(conversation_id,document_id) VALUES (?,?)',
                       [(conversation_id, identifier) for identifier in dict.fromkeys(document_ids)])


def load_chunks(document_ids):
    chunks = []
    with connection() as db:
        for identifier in dict.fromkeys(document_ids):
            for row in db.execute("SELECT c.*, d.filename, d.embedding_model FROM document_chunks c JOIN documents d ON c.document_id = d.id WHERE d.id = ? AND d.status = 'ready'", (identifier,)):
                chunk = dict(row)
                chunk['embedding'] = json.loads(chunk['embedding'])
                chunks.append(chunk)
    return chunks


def delete_document(document_id):
    with connection() as db:
        db.execute('DELETE FROM documents WHERE id = ?', (document_id,))
