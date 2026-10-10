"""Small, read-only tools for repositories explicitly approved by Novda."""
import os
import re
import logging
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
ALLOWED_ROOTS = (PROJECT_ROOT,)
SUPPORTED_SUFFIXES = {
    '.py', '.js', '.html', '.css', '.json', '.md', '.txt', '.toml', '.yaml', '.yml',
    '.ini', '.cfg', '.gitignore', '.env.example',
}
IGNORED_DIRECTORIES = {
    '.git', '.venv', 'venv', '__pycache__', 'node_modules', '.pytest_cache', '.mypy_cache',
    '.ruff_cache', 'dist', 'build', 'models', 'model_weights', '.ollama', 'cache', '.cache',
    'data', 'uploads', 'exports', 'logs', 'tmp', 'temp', '.aws', '.ssh', '.idea', '.vscode',
}
PRIVATE_FILENAMES = {'credentials.json', 'secrets.json', '.netrc', '.pypirc'}
MAX_FILE_BYTES = 1_000_000
MAX_LIST_RESULTS = 100
MAX_SEARCH_RESULTS = 20
MAX_MATCHES = 20
MAX_READ_LINES = 200
MAX_RESULT_CHARS = 8_000
MAX_TOOL_CALLS = 3
SOURCE_EXTENSION_PATTERN = r'(?:py|js|html|css|json|md|txt|toml|yaml|yml)'
EXPLICIT_PATH_PATTERN = re.compile(
    rf'(?<![\w.-])(((?:[A-Za-z]:)?[\\/]|(?:\.\.?[\\/]))?(?:[A-Za-z0-9_.-]+[\\/])*[A-Za-z0-9_.-]+\.{SOURCE_EXTENSION_PATTERN})(?![\w-])',
    re.IGNORECASE,
)
GENERIC_PATH_PATTERN = re.compile(
    r'(?<![\w.-])(((?:[A-Za-z]:)?[\\/]|(?:\.\.?[\\/]))?(?:[A-Za-z0-9_.-]+[\\/])*[A-Za-z0-9_.-]+\.[A-Za-z0-9]{1,10})(?![\w-])',
    re.IGNORECASE,
)
SEARCH_STOP_WORDS = set(
    'a an and are code do file files find for handles how implemented implementation in is me of on project '
    'repository search show source the to where which'.split()
)
DIRECT_TOPIC_STOP_WORDS = {
    'read', 'open', 'show', 'find', 'code', 'file', 'static', 'templates', 'explain',
    'tell', 'message', 'chat', 'styled', 'that', 'this', 'actual', 'source',
}
repository_log = logging.getLogger('uvicorn.error')


class RepositoryToolError(ValueError):
    pass


def excluded_name(name):
    """Keep local state and common credential files out of every repository tool."""
    lowered = name.lower()
    return (lowered in IGNORED_DIRECTORIES or lowered in PRIVATE_FILENAMES
            or (lowered == '.env' or lowered.startswith('.env.')) and lowered != '.env.example')


def private_data_path(path):
    # A configured data directory may live inside an otherwise readable source tree.
    import database
    return path.resolve().is_relative_to(database.DB_PATH.parent.resolve())


def allowed_root(index=0):
    try:
        return ALLOWED_ROOTS[index].resolve(strict=True)
    except (IndexError, OSError) as error:
        raise RepositoryToolError('The approved repository root is unavailable.') from error


def resolve_approved_path(path='.', root_index=0, *, require_file=False):
    """Resolve one relative path and prove its final target remains in an allowed root."""
    raw = str(path or '.')
    requested = Path(raw)
    if requested.is_absolute() or re.match(r'^[A-Za-z]:', raw) or raw.startswith(('\\', '/')):
        raise RepositoryToolError('Absolute paths are not allowed.')
    if '..' in requested.parts or '..' in raw.replace('\\', '/').split('/'):
        raise RepositoryToolError('Parent-directory traversal is not allowed.')
    root = allowed_root(root_index)
    candidate = (root / requested).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise RepositoryToolError('Path is outside the approved repository.') from error
    if not candidate.exists():
        raise RepositoryToolError(f'File not found: {requested.as_posix()}')
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise RepositoryToolError('Path is outside the approved repository.') from error
    relative_parts = resolved.relative_to(root).parts
    if any(excluded_name(part) for part in relative_parts) or private_data_path(resolved):
        raise RepositoryToolError('That directory is excluded from repository access.')
    if require_file and not resolved.is_file():
        raise RepositoryToolError('A supported text file is required.')
    return root, resolved


def relative_path(path, root):
    return path.relative_to(root).as_posix()


def ensure_text_file(path):
    if path.suffix.lower() not in SUPPORTED_SUFFIXES and path.name.lower() not in SUPPORTED_SUFFIXES:
        raise RepositoryToolError('Unsupported or binary file type.')
    if path.stat().st_size > MAX_FILE_BYTES:
        raise RepositoryToolError('File is too large for repository tools.')


def read_lines(path):
    ensure_text_file(path)
    try:
        return path.read_text(encoding='utf-8').splitlines()
    except (UnicodeDecodeError, OSError) as error:
        raise RepositoryToolError('File is not readable UTF-8 text.') from error


def list_directory(path='.', root_index=0):
    root, directory = resolve_approved_path(path, root_index)
    if not directory.is_dir():
        raise RepositoryToolError('A directory is required.')
    entries = []
    for child in sorted(directory.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
        if (excluded_name(child.name) or private_data_path(child)
                or child.is_symlink() and not child.resolve().is_relative_to(root)):
            continue
        entries.append({
            'name': child.name,
            'path': relative_path(child, root),
            'type': 'directory' if child.is_dir() else 'file',
            'size': child.stat().st_size if child.is_file() else None,
        })
        if len(entries) == MAX_LIST_RESULTS:
            break
    return entries


def repository_files(root):
    seen = 0
    for directory, names, files in os.walk(root, followlinks=False):
        names[:] = sorted(name for name in names
                          if not excluded_name(name) and not private_data_path(Path(directory) / name))
        current = Path(directory)
        for name in sorted(files):
            path = current / name
            if excluded_name(name) or private_data_path(path):
                continue
            seen += 1
            if seen > 5_000:
                return
            if path.is_symlink():
                try:
                    if not path.resolve().is_relative_to(root):
                        continue
                except OSError:
                    continue
            if path.suffix.lower() in SUPPORTED_SUFFIXES or path.name.lower() in SUPPORTED_SUFFIXES:
                yield path


def query_terms(query):
    lowered = query.lower()
    raw_terms = (term.strip('.-') for term in re.findall(r'[A-Za-z_][A-Za-z0-9_.-]*', lowered))
    terms = [term for term in raw_terms if len(term) > 1 and term not in SEARCH_STOP_WORDS]
    expansions = {
        'web search': ['search_evidence', 'search_web', 'ddgs'],
        'ollama model': ['chat_model', 'payload'],
        'model selected': ['chat_model', 'modelSelect'],
        'selected model': ['chat_model', 'modelSelect', 'chat-model'],
        'model selection': ['chat_model', 'modelSelect', 'chat-model'],
        'model selector': ['chat_model', 'modelSelect', 'chat-model'],
        'conversation persistence': ['conversations', 'messages', 'save_user', 'load_messages'],
        'sqlite': ['sqlite3', 'database'],
        'chat attachments': ['attachment', 'selectedDocumentIds', 'conversation_documents'],
        'attachments': ['attachment', 'selectedDocumentIds', 'conversation_documents'],
        'num_ctx': ['DEFAULT_NUM_CTX', 'options'],
        'send a chat message': ['chatForm', 'submit', 'fetch', '/chat'],
        'sends a chat message': ['chatForm', 'submit', 'fetch', '/chat'],
        'repository access': ['repository_tools', 'gather_repository_evidence', 'repository_access'],
    }
    for phrase, extra in expansions.items():
        if phrase in lowered:
            terms.extend(term.lower() for term in extra)
    return list(dict.fromkeys(terms))[:20]


def best_line(lines, terms):
    best = (0, 0)
    for number, line in enumerate(lines, 1):
        lowered = line.lower()
        score = sum(3 if ('_' in term or term.lower() == line.strip().lower()) else 1
                    for term in terms if term in lowered)
        if 'chat_model' in terms and '"model"' in lowered and 'chat_model' in lowered:
            score += 4
        if score > best[0]:
            best = (score, number)
    return best


def search_files(query, root_index=0, limit=MAX_SEARCH_RESULTS):
    if not 1 <= limit <= MAX_SEARCH_RESULTS:
        raise RepositoryToolError(f'Search limit must be between 1 and {MAX_SEARCH_RESULTS}.')
    terms = query_terms(query)
    lowered_query = query.lower()
    if not terms:
        raise RepositoryToolError('Use at least one meaningful search term.')
    root = allowed_root(root_index)
    results = []
    for path in repository_files(root):
        relative = relative_path(path, root)
        filename_score = sum(3 for term in terms if term in relative.lower())
        filename_score += sum(8 for term in terms if f'{term}.py' in relative.lower() or f'{term}.js' in relative.lower())
        if ('javascript' in lowered_query or ' js ' in f' {lowered_query} ') and path.suffix.lower() == '.js':
            filename_score += 6
        if 'css' in lowered_query and path.suffix.lower() == '.css':
            filename_score += 6
        if 'html' in lowered_query and path.suffix.lower() == '.html':
            filename_score += 6
        if any(word in lowered_query for word in ('footer', 'composer', 'indicator', 'interface')):
            filename_score += 12 if path.suffix.lower() in {'.html', '.js', '.css'} else -5
        try:
            lines = read_lines(path)
        except RepositoryToolError:
            continue
        content_score, line_number = best_line(lines, terms)
        occurrence_score = min(5, sum(1 for line in lines for term in terms if term in line.lower()))
        score = filename_score + content_score + occurrence_score
        if path.name.startswith('test_') and not any(term in {'test', 'tests', 'testing'} for term in terms):
            score -= 20
        if path.name == 'repository_tools.py' and not any(
                phrase in lowered_query for phrase in ('repository tool', 'local file', 'allowed root', 'path traversal')):
            score -= 12
        if not score:
            continue
        snippet = lines[line_number - 1].strip()[:300] if line_number else ''
        results.append({'path': relative, 'line_number': line_number or None, 'snippet': snippet, 'score': score})
    results.sort(key=lambda item: (-item['score'], item['path']))
    return results[:limit]


def find_in_file(path, query, root_index=0, limit=MAX_MATCHES):
    if not 1 <= limit <= MAX_MATCHES:
        raise RepositoryToolError(f'Match limit must be between 1 and {MAX_MATCHES}.')
    root, resolved = resolve_approved_path(path, root_index, require_file=True)
    terms = query_terms(query)
    if not terms:
        raise RepositoryToolError('Use at least one meaningful search term.')
    lines = read_lines(resolved)
    matches = []
    for number, line in enumerate(lines, 1):
        if any(term in line.lower() for term in terms):
            start, end = max(1, number - 1), min(len(lines), number + 1)
            matches.append({'path': relative_path(resolved, root), 'line_number': number,
                            'start_line': start, 'end_line': end,
                            'snippet': '\n'.join(f'{i}: {lines[i - 1]}' for i in range(start, end + 1))})
            if len(matches) == limit:
                break
    return matches


def read_file(path, start_line=None, end_line=None, root_index=0):
    root, resolved = resolve_approved_path(path, root_index, require_file=True)
    lines = read_lines(resolved)
    start = 1 if start_line is None else int(start_line)
    end = min(len(lines), start + MAX_READ_LINES - 1) if end_line is None else int(end_line)
    if start < 1 or end < start:
        raise RepositoryToolError('Invalid line range.')
    if end - start + 1 > MAX_READ_LINES:
        raise RepositoryToolError(f'Read requests are limited to {MAX_READ_LINES} lines.')
    end = min(end, len(lines))
    numbered_lines = []
    actual_end = start - 1
    for number in range(start, end + 1):
        numbered = f'{number} | {lines[number - 1]}'
        candidate_size = sum(len(item) + 1 for item in numbered_lines) + len(numbered)
        if candidate_size > MAX_RESULT_CHARS:
            break
        numbered_lines.append(numbered)
        actual_end = number
    if not numbered_lines and start <= len(lines):
        raise RepositoryToolError('The requested source line exceeds the read-size limit.')
    content = '\n'.join(numbered_lines)
    return {'path': relative_path(resolved, root), 'start_line': start, 'end_line': actual_end,
            'content': content}


def explicit_file_paths(question):
    """Return approved-looking relative source paths explicitly written by the user."""
    return list(dict.fromkeys(match.group(1).replace('\\', '/') for match in EXPLICIT_PATH_PATTERN.finditer(question)))


def direct_file_paths(question):
    paths = explicit_file_paths(question)
    if re.search(r'\b(read|open|show|inspect)\b', question, re.IGNORECASE):
        paths.extend(match.group(1).replace('\\', '/') for match in GENERIC_PATH_PATTERN.finditer(question))
    return list(dict.fromkeys(paths))


def requested_line_range(question):
    match = re.search(r'\blines?\s+(\d+)\s*(?:-|–|to)\s*(\d+)\b', question, re.IGNORECASE)
    return (int(match.group(1)), int(match.group(2))) if match else None


def is_repository_question(question):
    text = question.lower()
    if direct_file_paths(question):
        return True
    indicators = (
        'repository', 'repo', 'codebase', 'source code', 'which file', 'where is', 'where the',
        'find the code', 'find where', 'read file', 'open file', 'search files', 'implemented',
        'implementation', 'function that', 'trace what happens', 'trace the',
        'num_ctx', 'ollama request', 'conversation persistence', 'attachment handling',
        'javascript handles', 'css for', 'html template', 'web search', 'sqlite', 'fastapi route',
    )
    code_identifier = re.search(r'\b(?:[a-z][a-z0-9]*_[a-z0-9_]+|[a-z]+[A-Z][A-Za-z0-9]*)\b', question)
    return any(indicator in text for indicator in indicators) or bool(code_identifier)


def relevant_direct_section(path, question, line_range=None):
    """Read an explicit file directly, centering topic-specific requests on the best matching code."""
    if line_range:
        return read_file(path, line_range[0], line_range[1])
    root, resolved = resolve_approved_path(path, require_file=True)
    lines = read_lines(resolved)
    terms = [term for term in query_terms(question)
             if term not in DIRECT_TOPIC_STOP_WORDS
             and term not in {part.lower() for part in re.split(r'[/\\.]', path)}]
    score, line = best_line(lines, terms)
    if terms:
        # Topic words often occur across a compact block (for example a group of
        # adjacent composer selectors), rather than together on one source line.
        contextual = []
        for number in range(1, len(lines) + 1):
            nearby = '\n'.join(lines[max(0, number - 9):min(len(lines), number + 8)]).lower()
            contextual.append((sum(nearby.count(term) for term in terms), number))
        context_score, context_line = max(contextual)
        if context_score > score:
            line = context_line
            score = context_score
    if score:
        return read_file(path, max(1, line - 24), min(len(lines), line + 24))
    return read_file(path, 1, min(len(lines), 100))


def direct_sections(path, question, line_range=None, limit=1):
    """Return the main direct excerpt plus a second linked JS section when the request needs both."""
    primary = relevant_direct_section(path, question, line_range)
    sections = [primary]
    if (not line_range and limit > 1 and path.lower().endswith('.js')
            and re.search(r'\bsends?.{0,20}chat message\b', question, re.IGNORECASE)):
        root, resolved = resolve_approved_path(path, require_file=True)
        lines = read_lines(resolved)
        run_line = next((number for number, line in enumerate(lines, 1)
                         if re.search(r'\bfunction\s+runGeneration\b', line)), None)
        if run_line and not primary['start_line'] <= run_line <= primary['end_line']:
            sections.insert(0, read_file(path, max(1, run_line - 5), min(len(lines), run_line + 55)))
    return sections[:limit]


def gather_repository_evidence(question, max_calls=MAX_TOOL_CALLS):
    if not 1 <= max_calls <= MAX_TOOL_CALLS:
        raise RepositoryToolError(f'Tool calls are limited to {MAX_TOOL_CALLS} per turn.')
    sources, passages = [], []
    paths = direct_file_paths(question)
    calls = []
    sections = []
    cross_file_request = bool(re.search(r'\b(trace|across files?|which files?)\b', question, re.IGNORECASE))
    if paths and not (len(paths) == 1 and cross_file_request):
        line_range = requested_line_range(question)
        for path in paths[:max_calls]:
            remaining = max_calls - len(calls)
            for section in direct_sections(path, question, line_range if len(paths) == 1 else None, remaining):
                calls.append({'tool': 'read_file', 'path': section['path'],
                              'start_line': section['start_line'], 'end_line': section['end_line']})
                sections.append((section, 'Direct file read'))
    else:
        calls.append({'tool': 'search_files', 'query': question})
        for result in search_files(question):
            if len(calls) >= max_calls or len(sections) == 2:
                break
            line = result['line_number'] or 1
            section = read_file(result['path'], max(1, line - 24), line + 24)
            calls.append({'tool': 'read_file', 'path': result['path'],
                          'start_line': section['start_line'], 'end_line': section['end_line']})
            sections.append((section, result['snippet']))
    for section, snippet in sections:
        number = len(sources) + 1
        reference = f"{section['path']}:{section['start_line']}-{section['end_line']}"
        sources.append({'number': number, 'kind': 'repository', 'title': section['path'],
                        'domain': 'local repository', 'url': '', 'snippet': snippet,
                        'path': section['path'], 'start_line': section['start_line'],
                        'end_line': section['end_line'], 'reference': reference})
        passages.append(f"[{number}] {reference}\n{section['content']}")
        if sum(len(part) for part in passages) >= MAX_RESULT_CHARS:
            break
    repository_log.info('Repository tools query=%r calls=%s references=%s', question, calls,
                        [source['reference'] for source in sources])
    return {'kind': 'repository', 'root': PROJECT_ROOT.name, 'sources': sources,
            'evidence': '\n\n'.join(passages)[:MAX_RESULT_CHARS], 'tool_calls': calls}
