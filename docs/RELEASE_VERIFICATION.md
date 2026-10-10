# Release verification — 2026-10-10

**PUBLICATION READY** for a public portfolio release of this experimental,
single-user application. Intentionally unlicensed at the owner's request.
No GitHub repository was created, no remote was added, and nothing was pushed.
Hosted CI cannot be verified until publication.

## Live model diagnosis and repair

Ollama 0.40.1 discovered two chat models: `ornith-1.5:9b` and
`qwen3:4b-instruct-2507-q4_K_M`, plus the `nomic-embed-text:latest` embedding model.
The tested machine has about 15.25 GiB usable RAM and 6 GB RTX 4050 laptop VRAM;
approximately 4.62 GiB RAM was free at the diagnostic check.

The exact failing direct request to Ollama `/api/chat` was:

```json
{
  "model": "ornith-1.5:9b",
  "messages": [{"role": "user", "content": "Reply with only: hello"}],
  "stream": false,
  "think": false,
  "options": {"num_ctx": 4096, "num_predict": 16},
  "keep_alive": 0
}
```

Ollama returned HTTP 500: llama-server startup failed after a projector CPU
offload retry; allocation of a 2,923,940,352-byte CUDA_Host buffer failed.
This reproduces independently of Novda. The 9B Q4_K_M weights occupy about
6.10 GiB before runtime/context overhead, suggesting resource pressure on this
machine. The exact underlying allocator/driver cause was not established.

The equivalent smaller-model request succeeded. Actual Novda browser requests
then streamed successfully with Qwen3 4B, thinking off, at both 4K and 8K context.
Recommended starting setting on this hardware: the exact tested Qwen model at
4K, thinking off. More available memory or hardware capacity may permit the
larger model; 16K context was not live-certified. Preferred-model selection,
all context options, and application functionality were preserved.
See [Ollama context and memory guidance](https://docs.ollama.com/faq).

The browser also exposed an independent application defect:
`ReferenceError: updateFooterModel is not defined` prevented message submission
before any chat request. A five-line helper in `static/app.js` now updates the
existing footer while preserving web/document status. No architecture or layout
change was made. A fresh browser context verified the repaired submission path.

## Browser smoke tests

Real headless Edge, isolated browser profile and synthetic runtime store;
existing personal conversations and documents were never loaded.
Playwright was used only in an ignored verification environment, without adding
any application dependency. Tokens were observed in actual NDJSON network
responses and incrementally rendered in the browser.

| Workflow | Verified result |
| --- | --- |
| Open Novda | Fresh store opened; two chat models discovered |
| Create/load conversation and local message | Real streaming reply; user/assistant messages persisted and reloaded |
| Switch models | Selection switched in both directions and persisted; successful inference verified with Qwen only |
| Context setting | 4K and 8K settings persisted and produced live replies; returned to 4K |
| Document attachment/RAG | Synthetic TXT indexed using local embeddings; retrieval and page citation verified |
| Web Search | Real unpaid DuckDuckGo/DDGS search, streamed answer and source links; bounded page fetching can fall back to snippets |
| Repository read/search | Numbered direct file read and cross-file persistence search with backend-owned references |
| Coding Mode | One valid model proposal displayed authoritative diff and Apply & Test/Reject controls; Reject persisted correctly |
| Browser errors | Zero JavaScript console errors, page errors, or failed browser requests in the completed workflows |

Coding proposal generation remains unreliable: three additional attempts were
safely refused for empty changes or expected text that did not match source.
One valid proposal was rejected by the tester. **Zero patches were applied.**
Validation was not weakened, and the proposed target still matches its original
text. Apply & Test was not exercised live; existing regression tests cover its
write/stale-source/test-runner behavior. These results do not establish model
accuracy, safe hostile-code execution, or multi-user support.

## Screenshots and privacy

Five actual PNGs in [screenshots/](screenshots/README.md) use only synthetic
conversations, a synthetic study guide, public Python documentation, and relative
repository references. Visual and visible-text checks found no personal documents,
private chats, absolute personal paths, usernames, emails, or keys. The Coding
capture explicitly shows a rejected proposal. PNG metadata was also inspected.

The original SQLite database and four uploaded PDFs are unchanged by SHA-256.
The template and stylesheet are unchanged; only the missing JavaScript helper
was repaired. All runtime stores, uploads, temporary browser tooling, logs,
caches, model files, and private environment files remain excluded from Git.
The tracked `.env.example` contains public defaults only.

The public GitHub account and its numeric ID were verified against authenticated
account information and the public API. The exact no-reply address follows
[GitHub's documented format](https://docs.github.com/en/account-and-profile/reference/email-addresses-reference)
for this account's creation date. Repository-local identity retains the requested
author name. With explicit owner approval, the unpublished initial commit was
amended for both author and committer; its obsolete recovery copy was removed.
Tracked contents and all remaining commit objects contain no personal Gmail.
Global identity configuration was not changed.

## Automated checks and documentation

- `python -m unittest discover`: 38 passed after the JavaScript repair.
- Python compilation and application-module imports: passed.
- `node --check static/app.js`: passed.
- Dedicated clean environment dependency check: passed; no runtime dependencies added.
- Tracked/staged privacy scan, original-data hashes, local Markdown links,
  image metadata and Git whitespace checks: passed.
- README claims reviewed against source, regression coverage and actual live
  results; hardware, proposal-generation and untested Apply/16K limits disclosed.
- Git author/committer metadata uses the verified no-reply identity throughout
  the two publication commits; no remote or push exists.

The initial preparation's global environment had an unrelated package conflict;
its installed packages were not modified. Clean dependency checks passed.

## Exact public file manifest

Only these 30 files and the two release commits are intended for publication:

```text
.env.example
.gitattributes
.github/workflows/tests.yml
.gitignore
README.md
app.py
coding_tools.py
database.py
docs/RELEASE_CHECKLIST.md
docs/RELEASE_REVIEW.md
docs/RELEASE_VERIFICATION.md
docs/screenshots/README.md
docs/screenshots/chat.png
docs/screenshots/coding.png
docs/screenshots/documents.png
docs/screenshots/repository.png
docs/screenshots/web-search.png
rag.py
repository_tools.py
requirements.txt
static/app.js
static/style.css
templates/index.html
test_coding_tools.py
test_configuration.py
test_model_manager.py
test_persistence.py
test_rag.py
test_repository_tools.py
test_web_reliability.py
```

Use the [publication checklist](RELEASE_CHECKLIST.md) only when the owner explicitly
authorizes publication. Its commands select `github.com` explicitly to avoid
accidentally targeting an enterprise CLI login.
