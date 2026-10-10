# Public release checklist

## Review the release contents

- Read the main README and confirm the claims match the version being published.
- Review `git status --short`, `git diff --cached --stat`, and `git diff --cached`.
- Check `git ls-files`: runtime databases, uploads, document text/embeddings, logs,
  credentials, environment files, model weights, exports, and caches must be absent.
- Confirm `.env.example` contains only public defaults and no credentials.
- If `NOVDA_DATA_DIR` points inside the repository outside `data/`, add that
  dedicated directory to `.gitignore` before staging. Repository tools protect
  the configured data directory, but Git needs its own exclusion.
- Review any screenshot for conversation text, private document names, evidence
  excerpts, personal paths, account details, and unrelated desktop content.
- Review Git author metadata with `git var GIT_AUTHOR_IDENT`. Configure a GitHub
  no-reply email before committing if you do not want your email in public history.
- Choose and add a license before advertising the project as open source. Public
  source visibility alone does not grant an open-source license. Also review rights
  to any assets or third-party material you later add. Model weights are not bundled.

## Validate locally

```text
python -m unittest discover
python -m compileall -q app.py database.py rag.py repository_tools.py coding_tools.py
node --check static/app.js
```

Use a dedicated Python environment with `requirements.txt`. A conflict reported
by `pip check` in an unrelated global environment should not be "fixed" by
changing unrelated packages as part of this project cleanup.

With local Ollama and the required models running, also exercise a fresh
conversation, stop/retry, model switching, attachment indexing/retrieval, web
search, source links, and a harmless Coding Mode preview. If testing Apply & Test,
use a disposable copy or a backed-up working tree: tests run with local user
permissions and a failed test does not undo a patch.

For a fresh demo store without touching existing conversations, set
`NOVDA_DATA_DIR=data/demo` before starting the app. Do not copy private documents
into the demo. The entire `data/` directory is excluded from Git.

## Existing history

`.gitignore` affects untracked files; it does not remove committed private content.
If a secret appears in any history intended for publication, stop publication,
rotate or revoke the credential, and agree on a remediation plan before rewriting
history. Do not force-push or rewrite history without explicit authorization.

The project folder had no `.git` directory when this release preparation began.
There was therefore no local history, tracked-file list, or remote to inspect.
If you import history from another copy later, audit that history separately.

## Connect a new GitHub repository

After reviewing the local commit and completing the manual checks, run these
commands from the repository root. Choose a different repository name if `novda`
already exists in your account.

```text
gh auth status
gh repo create novda --public --source=. --remote=origin
git push -u origin main
```

If the CLI is not authenticated, run `gh auth login` first. Alternatively, create
an empty GitHub repository named `novda` in the GitHub UI, without initializing a
README or license, then connect it (replace `YOUR_GITHUB_USERNAME`):

```text
git remote add origin https://github.com/YOUR_GITHUB_USERNAME/novda.git
git push -u origin main
```

Creating the public repository and pushing are separate publication steps. These
commands are provided for the owner to run; release preparation does not publish
the repository or force-push anything.
