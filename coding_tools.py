"""Bounded, approval-gated source edits and a fixed project test runner."""
import difflib
import json
import subprocess
import sys
from pathlib import Path

import repository_tools


MAX_PATCH_FILES = 3
MAX_PATCH_CHARS = 24_000
TEST_TIMEOUT_SECONDS = 120
TEST_OUTPUT_LIMIT = 16_000


class CodingToolError(ValueError):
    pass


def _validated_change(change):
    if not isinstance(change, dict):
        raise CodingToolError('Each proposed change must be an object.')
    path = change.get('path')
    expected = change.get('expected')
    replacement = change.get('replacement')
    if not isinstance(path, str) or not isinstance(expected, str) or not isinstance(replacement, str):
        raise CodingToolError('Every change requires path, expected, and replacement text.')
    root, resolved = repository_tools.resolve_approved_path(path, require_file=True)
    repository_tools.ensure_text_file(resolved)
    return {'path': repository_tools.relative_path(resolved, root), 'expected': expected, 'replacement': replacement}


def prepare_patch(proposal):
    """Validate a structured model proposal and generate the authoritative diff."""
    if not isinstance(proposal, dict) or not isinstance(proposal.get('changes'), list):
        raise CodingToolError('The coding model did not return a valid patch proposal.')
    changes = proposal['changes']
    if not 1 <= len(changes) <= MAX_PATCH_FILES:
        raise CodingToolError(f'A proposal may modify between 1 and {MAX_PATCH_FILES} files.')
    validated = [_validated_change(change) for change in changes]
    if len({change['path'] for change in validated}) != len(validated):
        raise CodingToolError('A proposal may modify each file only once.')
    if sum(len(change['expected']) + len(change['replacement']) for change in validated) > MAX_PATCH_CHARS:
        raise CodingToolError('The proposed patch is too large.')
    previews, normalized = [], []
    for change in validated:
        root, path = repository_tools.resolve_approved_path(change['path'], require_file=True)
        before = path.read_text(encoding='utf-8')
        if before.count(change['expected']) != 1:
            raise CodingToolError(f"Expected text must occur exactly once in {change['path']}.")
        after = before.replace(change['expected'], change['replacement'], 1)
        diff = ''.join(difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
                                             fromfile=f'a/{change["path"]}', tofile=f'b/{change["path"]}'))
        previews.append(diff)
        normalized.append({**change, 'before': before, 'after': after})
    summary = proposal.get('summary') if isinstance(proposal.get('summary'), str) else 'Proposed code change'
    return {'summary': summary[:500], 'changes': normalized, 'diff': '\n'.join(previews),
            'files': len(normalized), 'additions': sum(diff.count('\n+') for diff in previews),
            'deletions': sum(diff.count('\n-') for diff in previews)}


def apply_patch(patch):
    """Apply exactly a previously previewed patch, rejecting stale source files."""
    if not isinstance(patch, dict) or not isinstance(patch.get('changes'), list):
        raise CodingToolError('Stored patch is invalid.')
    changes = [_validated_change(change) for change in patch['changes']]
    if not 1 <= len(changes) <= MAX_PATCH_FILES or len({change['path'] for change in changes}) != len(changes):
        raise CodingToolError('Stored patch has invalid targets.')
    for change, stored in zip(changes, patch['changes']):
        if not isinstance(stored.get('before'), str) or not isinstance(stored.get('after'), str):
            raise CodingToolError('Stored patch is missing its preview state.')
        _, path = repository_tools.resolve_approved_path(change['path'], require_file=True)
        current = path.read_text(encoding='utf-8')
        if current != stored['before']:
            raise CodingToolError(f"Patch is stale: {change['path']} changed after preview.")
        if current.replace(change['expected'], change['replacement'], 1) != stored['after']:
            raise CodingToolError('Stored patch no longer matches its approved preview.')
    for change, stored in zip(changes, patch['changes']):
        _, path = repository_tools.resolve_approved_path(change['path'], require_file=True)
        path.write_text(stored['after'], encoding='utf-8', newline='')
    return {'diff': patch.get('diff', ''), 'changes': changes}


def run_tests():
    """Run the fixed local test command; no model-provided commands are accepted."""
    command = [sys.executable, '-B', '-m', 'unittest', 'discover']
    try:
        result = subprocess.run(command, cwd=repository_tools.PROJECT_ROOT, capture_output=True,
                                text=True, timeout=TEST_TIMEOUT_SECONDS, encoding='utf-8', errors='replace')
        output = (result.stdout + result.stderr)[:TEST_OUTPUT_LIMIT]
        return {'command': 'python -m unittest discover', 'exit_code': result.returncode,
                'passed': result.returncode == 0, 'timed_out': False, 'output': output,
                'truncated': len(result.stdout + result.stderr) > TEST_OUTPUT_LIMIT}
    except subprocess.TimeoutExpired as error:
        output = ((error.stdout or '') + (error.stderr or ''))[:TEST_OUTPUT_LIMIT]
        return {'command': 'python -m unittest discover', 'exit_code': None, 'passed': False,
                'timed_out': True, 'output': output, 'truncated': len(output) >= TEST_OUTPUT_LIMIT}


def parse_model_proposal(text):
    """Accept only a JSON object; prose never becomes a patch."""
    text = text.strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as error:
        raise CodingToolError('The coding model did not return valid patch JSON. Please regenerate the proposal.') from error
