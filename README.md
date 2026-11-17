# MiDearms

Local-first Dreams memory for sharing lessons across agents. Python 3.10+, standard-library runtime, SQLite storage. No hosted service or automatic session discovery.

## Install and quick start

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install --no-build-isolation -e .
# Alternatively run directly from this checkout: python3 -m midearms
midearms --store memory.sqlite3 ingest claude tests/fixtures/claude.jsonl
midearms --store memory.sqlite3 dream
midearms --store memory.sqlite3 query tests
midearms --store memory.sqlite3 export shared-memory.md
```

Every ingest accepts an explicit file path; repeat the command for additional files. Exact duplicate messages are deduplicated by SHA-256. Ingestion is transactional. Dreaming replaces notes atomically and leaves source messages intact. Query performs case-insensitive substring matching and returns JSON. Export creates a new Markdown file and refuses to overwrite existing files.

## Agent adapters

| CLI adapter | Input contract | Where to obtain it |
| --- | --- | --- |
| `claude` | Claude Code JSONL with `message.role` and string/text-block content | Select a session file under `~/.claude/projects/` yourself |
| `codex` | Codex rollout JSONL `response_item.payload` message records | Select a rollout under `~/.codex/sessions/` yourself |
| `cursor` | Explicit JSON chat export containing `tabs`/`bubbles` with `text`, or `messages` with `content` | Export a chat from your Cursor version, or convert it to this documented shape |
| `aider` | Aider Markdown chat history with `####` user headings | Explicitly pass your project's `.aider.chat.history.md` |
| `jsonl` | One JSON object per line: `{"role":"user","content":"Prefer explicit configuration."}` | Any agent can generate this format |

Paths above are documentation only: MiDearms never searches those directories. Cursor's internal database is deliberately not opened; export formats vary by version. Unsupported event/tool records are skipped. Invalid JSON aborts the ingest transaction. Aider blocks include both requests and replies. Only import conversations you trust and have permission to process.

## Shared memory

Export to a new `AGENTS.md` in an empty integration directory, or export `shared-memory.md` and explicitly reference it from your existing instructions. Codex can read AGENTS.md; for Claude Code reference the file in CLAUDE.md; for Cursor reference it in a project rule; for Aider use `/read shared-memory.md`. Generic agents can consume the Markdown or CLI query JSON. Review extracted content before incorporating it into active instructions: conversations can contain false claims, secrets, or prompt injection.

SQLite contains `messages(id, content)` and `notes(id, content)` tables. Back up the database locally. Deleting a database removes that store; exports are independent files. Raw conversations remain local unless the user explicitly enables a model endpoint.

## Offline dreaming and BYO LLM

Default dreaming uses deterministic rules: retain recurring lines and explicit correction/preference cues, producing labeled Pattern/Lesson notes. It does not infer semantic contradictions or resolve conflicting claims. Exact duplicate messages are deduplicated before dreaming, so recurrence must occur across distinct messages. This conservative fallback works without keys, dependencies, or a network.

For semantic extraction, explicitly pass `dream --llm-config model.json`:

```json
{"provider":"ollama","endpoint":"http://localhost:11434","model":"llama3.2"}
```

An OpenAI-compatible endpoint uses `{"provider":"openai","endpoint":"http://localhost:8000/v1","model":"local-model"}`. The endpoint must return chat-completion content containing a JSON array of strings. This initial release supports unauthenticated local endpoints; authenticated providers can be placed behind a user-managed local proxy. No credentials are read from disk or environment. Model errors abort without replacing existing notes; rerun without the flag for offline fallback. Enabling a remote endpoint sends imported message text to that endpoint, so choose it deliberately. Large stores must be split to fit your model context window.

## Development and validation

```sh
python3 -m unittest discover -s tests -v
PYTHONPATH=. python3 scripts/benchmark.py
```

Tests use only anonymous committed fixtures and temporary stores. They cover all adapter contracts, rule extraction, CLI ingestion/dream/query/export, repeated ingestion, and overwrite protection. The benchmark checks 10,000 synthetic messages produce 100 recurring notes; elapsed time is informational and machine-dependent. No network or API key is required. LLM integration is optional and is not exercised by offline tests.

Code lives in `midearms/`, fixtures/tests in `tests/`, benchmark in `scripts/`. No real sessions belong in commits. MiDearms currently handles individual explicit files, not filesystem watching or automatic agent registration.
