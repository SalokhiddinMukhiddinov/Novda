# Release preparation review

This records the initial preparation. The subsequent
[release verification](RELEASE_VERIFICATION.md) resolved the browser submission
failure, verified live workflows, added safe screenshots, and replaced the
unpublished commit's personal author email with the verified GitHub no-reply
address under the owner's explicit authorization. That report supersedes the
remaining-review items and live-test results below.

## Scope and Git state

The supplied project folder initially had no Git repository, tracked files,
commit history, or remote. Release preparation initialized a local `main`
branch and staged an explicit list of source and documentation files. No
existing history was rewritten, no force-push was performed, and nothing was
published to GitHub.

The source layout, browser UI, preferred chat model, and default runtime data
location were preserved. No runtime dependencies were added.

## Changed files

| Existing file | Change |
| --- | --- |
| `app.py` | Share the configured Ollama endpoint with the embedding pipeline |
| `rag.py` | Read optional `OLLAMA_BASE_URL`, preserving the existing default |
| `database.py` | Read optional `NOVDA_DATA_DIR`; anchor relative paths to the project |
| `repository_tools.py` | Exclude private directories, common credential filenames, and configured runtime storage from listing, searching, and reading |
| `requirements.txt` | Clarify direct dependencies and bounded version ranges; preserve existing requirements |
| `test_coding_tools.py` | Check that credential files cannot become coding patch targets |
| `test_repository_tools.py` | Check private-file exclusion across tools and custom runtime storage |

Added files:

- `README.md`: verified capabilities, installation, workflows, architecture,
  security boundaries, limitations, and a high-level roadmap.
- `.gitignore`: private runtime state, SQLite sidecars, credentials, environments,
  caches, logs, model weights, exports, archives, and generated files.
- `.gitattributes`: consistent source/documentation line endings.
- `.env.example`: public defaults for the two optional environment variables;
  automatic `.env` loading is not claimed or added.
- `test_configuration.py`: default, relative, and absolute configuration checks
  from an unrelated working directory.
- `.github/workflows/tests.yml`: Windows/Ubuntu checks on Python 3.12, with
  read-only repository permissions and no persisted checkout credentials.
- `docs/RELEASE_CHECKLIST.md`: manual review and GitHub publication commands.
- `docs/screenshots/README.md`: screenshot locations and privacy guidance.
- `docs/RELEASE_REVIEW.md`: this review.

The initial commit also includes the unchanged application files and existing
tests. Since there was no prior commit, Git reports all included files as new;
the table above describes changes relative to the supplied folder.

## Removed files

Only generated Python bytecode caches were removed. No source files, documents,
conversations, or model files were deleted. The temporary verification environment
was created for clean-install checks and removed after those checks.

## Security and privacy findings

- One existing SQLite database and four uploaded PDFs remain local and are
  excluded from Git. Their contents were not displayed or included in the commit.
  Hash checks confirmed all five files were unchanged.
- Hash checks also confirmed `static/app.js`, `static/style.css`, and
  `templates/index.html` were unchanged.
- Source and staged-blob scans found no provider-token, private-key,
  credential-assignment, or personal Windows-path indicators. These are heuristic
  checks, not a guarantee that arbitrary sensitive content can be detected.
- There was no existing local Git history to audit for previously committed secrets.
- Repository tools previously permitted some credential-like text files and
  upload/export directories. Those common locations are now blocked by the
  shared path policy, including coding targets. This is still not a content-based
  secret detector.
- The application remains a trusted local, single-user prototype without
  authentication, user isolation, encrypted storage, or a code-execution sandbox.
  Tests run with local user permissions; applied patches are not automatically
  rolled back on failure. Diagnostic logs and exports can contain private text.

## Validation

| Check | Result |
| --- | --- |
| Original unittest baseline | 33 passed |
| Final `python -m unittest discover` in the existing environment | 38 passed |
| Clean virtual-environment install from `requirements.txt` | Passed |
| Clean environment dependency check | No broken requirements |
| Clean environment unittest suite | 38 passed |
| Python compilation and application imports | Passed |
| JavaScript syntax: `node --check static/app.js` | Passed |
| Fresh-store home, JS, CSS, document-library, and model-discovery HTTP checks | All returned 200 |
| Live Ollama model discovery | Reachable |
| Live synthetic TXT upload, local embeddings, and retrieval | Passed |
| Live chat inference | Failed with an Ollama error; a direct preferred-model request returned HTTP 500 with memory/load indicators; the smaller installed model also failed |
| Staged-file privacy audit, Markdown links, and Git whitespace checks | Passed |
| GitHub Actions YAML structure | Parsed and reviewed; hosted jobs have not run yet |

The direct Ollama failure occurs independently of Novda's endpoint configuration
change. No unrelated model/runtime repair was attempted. Before recording a demo,
resolve the local model-loading issue and repeat the live chat check. Browser
interaction, live web search, and a live model-generated coding proposal still
need manual smoke testing; their regression tests passed with mocked responses.

The existing global Python environment has an unrelated `datasets` /
`huggingface-hub` dependency conflict. Global packages were left unchanged; the
dedicated clean environment passed `pip check`. The clean install also emitted
a non-fatal Starlette warning about future TestClient HTTPX compatibility; the
current tests passed without adding a replacement HTTP client dependency.

## Owner review before publication

1. Resolve local Ollama chat-model loading and finish a live workflow smoke test.
2. The owner chose to leave Novda unlicensed for now. No `LICENSE` file was
   added. Choose a license later before describing the project as open source.
3. Capture public-safe screenshots; the current paths are guidance only.
4. Review the Git author name/email that will appear in public commit metadata.
5. Review the initial commit and confirm any future custom runtime directory is
   excluded from Git.
6. The current checkout produced a Git ownership warning. Release preparation
   used a per-command exception for this exact repository and did not alter
   global Git trust settings. Review/trust this specific checkout if Git or the
   GitHub CLI reports the same warning when you publish.

Use the publication commands in `RELEASE_CHECKLIST.md` only after these checks.
