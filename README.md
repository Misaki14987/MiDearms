# MiDearms

Local-first Dreams memory for sharing lessons across agents. Python 3.10+, standard-library runtime, SQLite storage. No hosted service and no automatic session discovery.

MiDearms ingests explicit session files, keeps provenance for every message, distills a small set of durable notes, and exports them as Markdown that an agent can read. The default extractor is deterministic and offline; an optional LLM pass can use a model endpoint you configure.

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

Every ingest accepts an explicit file path; repeat the command for additional files. Exact duplicate messages are deduplicated by SHA-256, but each source occurrence is retained as provenance. Ingestion is transactional. Dreaming replaces notes atomically and leaves source messages intact. Query performs case-insensitive substring matching and returns JSON. Export creates a new Markdown file and refuses to overwrite existing files.

## Agent adapters

| CLI adapter | Input contract | Where to obtain it |
| --- | --- | --- |
| `claude` | Claude Code JSONL with `message.role` and string/text-block content | Select a session file under `~/.claude/projects/` yourself |
| `codex` | Codex rollout JSONL `response_item.payload` message records | Select a rollout under `~/.codex/sessions/` yourself |
| `cursor` | Explicit JSON chat export containing `tabs`/`bubbles` with `text`, or `messages` with `content` | Export a chat from your Cursor version, or convert it to this documented shape |
| `aider` | Aider Markdown chat history with `####` user headings | Explicitly pass your project's `.aider.chat.history.md` |
| `jsonl` | One JSON object per line: `{"role":"user","content":"Prefer explicit configuration."}` | Any agent can generate this format |

Paths above are documentation only: MiDearms never searches those directories. Cursor's internal database is deliberately not opened; export formats vary by version. Unsupported event/tool records are skipped. Invalid JSON aborts the ingest transaction. Aider blocks include both requests and replies. Only import conversations you trust and have permission to process.

## Memory model

The store is a small SQLite database with five tables:

- `messages(id, content)` holds distinct message texts.
- `occurrences(message_id, adapter, source, role, line, ingested_at)` records where each message appeared. The same text from two sessions is one message with two occurrences.
- `notes(id, content, kind, confidence, evidence, sources, first_seen, last_seen, pinned)` holds the distilled memory.
- `note_evidence(note_id, message_id, source)` links every note back to the messages that support it.
- `pinned(id, content, created_at)` holds user-authored rules that survive every `dream`.

Notes carry a confidence label:

| Label | Meaning |
| --- | --- |
| `confirmed` | An explicit `Correction:`/`修正：`/`更正：` statement, or a pinned user rule |
| `corroborated` | The same normalized line appears in at least two source files |
| `observed` | The line recurs, but only within one source file |
| `unverified` | A one-off line with a durable preference cue |

Every note also records how many distinct messages and source files support it. `query --details` exposes `message_ids` and `source_files` so you can audit a lesson before trusting it.

## Shared memory export

Export to a new `AGENTS.md` in an empty integration directory, or export `shared-memory.md` and explicitly reference it from your existing instructions. Codex can read AGENTS.md; for Claude Code reference the file in CLAUDE.md; for Cursor reference it in a project rule; for Aider use `/read shared-memory.md`. Generic agents can consume the Markdown or CLI query JSON. Review extracted content before incorporating it into active instructions: conversations can contain false claims, secrets, or prompt injection.

The export is intentionally capped at about 200 lines or 25 KB, matching the "keep the injected layer small" practice. Notes are grouped by confidence:

- `## Rules` — pinned user rules.
- `## Confirmed` — explicit corrections.
- `## Corroborated` — patterns seen in multiple sources.
- `## Observed` — repeated patterns from one source.
- `## Unverified` — one-off lessons that still need review.

If notes do not fit, the file ends with a comment saying how many were omitted; use `midearms query` to inspect them. Pass `--all` to export everything, or tune `--max-lines` / `--max-bytes`.

SQLite contains the tables above. Back up the database locally. Deleting a database removes that store; exports are independent files. Raw conversations remain local unless the user explicitly enables a model endpoint.

## Offline dreaming and BYO LLM

Default dreaming uses deterministic rules. It retains:

- explicit corrections;
- lines that recur across messages;
- durable preference cues, weighted by role: a user message can contribute a weak cue, while an assistant message needs a strong cue or recurrence;
- concise lines only; headings, questions, labels, code fences, paths, URLs, diffs and long prose are ignored.

Explicit `Correction:` (also `修正：` / `更正：`) statements supersede opposite `Always` / `Never` advice about the same normalized action, independently of ingest/hash order. Conflicting explicit corrections for that action are withheld. Matching ignores case and terminal punctuation; unrelated actions remain intact. Broader paraphrases and implicit contradictions are not inferred. Exact duplicate messages are deduplicated before dreaming, so recurrence must occur across distinct messages.

For semantic extraction, explicitly pass `dream --llm-config model.json`:

```json
{"provider":"ollama","endpoint":"http://localhost:11434","model":"llama3.2"}
```

An OpenAI-compatible endpoint uses `{"provider":"openai","endpoint":"http://localhost:8000/v1","model":"local-model"}`. The endpoint must return chat-completion content containing a JSON array. Items may be strings or objects of the form:

```json
{"text":"Prefer explicit configuration.","kind":"Rule","confidence":"corroborated"}
```

The client chunks the store with `max_chars` (default 12000), caps each chunk at `max_notes` (default 40), deduplicates notes across chunks, and attaches the messages that support each note. The prompt tells the model to treat conversations as untrusted data, store durable rules rather than transient state, and avoid inventing facts. This initial release supports unauthenticated local endpoints; authenticated providers can be placed behind a user-managed local proxy. No credentials are read from disk or environment. Model errors abort without replacing existing notes; rerun without the flag for offline fallback. Enabling a remote endpoint sends imported message text to that endpoint, so choose it deliberately.

## Commands

```sh
# Pin a rule immediately; it survives later dream runs.
midearms remember "Always run tests before release."

# Narrow a dreaming pass to a goal; explicit corrections are always retained.
midearms dream --focus "release"

# Search notes (all terms must match) and show provenance.
midearms query --details "tests"

# Search raw transcripts instead of notes.
midearms query --messages "timeout"
```

## Design notes

The design follows the memory hierarchy described in Anthropic's [The components of agent memory](https://www.anthropic.com/research/components-of-agent-memory):

1. **Transcripts are the ground truth.** MiDearms keeps raw messages and links every note to its evidence instead of storing an ungrounded summary.
2. **Memory should predict future need.** The extractor prefers durable preferences, corrections and recurring pitfalls; it drops transient state, formatting and task-specific prose.
3. **Dreaming should be conservative.** Explicit corrections win, conflicts are withheld, and weak one-off assistant suggestions are ignored.
4. **The injected layer must stay small.** Export is capped and grouped by confidence; full detail stays queryable in SQLite.
5. **A goal can shape memory.** `--focus` narrows a pass without discarding explicit corrections.

## Development and validation

```sh
python3 -m unittest discover -s tests -v
PYTHONPATH=. python3 scripts/benchmark.py
```

Tests use only anonymous committed fixtures and temporary stores. They cover all adapter contracts, rule extraction, correction conflicts, role-aware salience, provenance and confidence, schema migration, CLI ingestion/dream/query/export, repeated ingestion, export caps, pinned rules, transcript search, and LLM chunking with a mocked endpoint. The benchmark checks 10,000 synthetic messages produce 100 recurring notes; elapsed time is informational and machine-dependent. No network or API key is required. LLM integration is optional and is not exercised against a real endpoint by offline tests.

Code lives in `midearms/`, fixtures/tests in `tests/`, benchmark in `scripts/`. No real sessions belong in commits. MiDearms currently handles individual explicit files, not filesystem watching or automatic agent registration. Legacy v0.1 stores migrate automatically on first open: messages get a `legacy` occurrence, notes get confidence metadata, and existing content is preserved.
