# MiDearms

Local-first Dreams memory for sharing lessons across agents. Python 3.10+, standard-library runtime, SQLite storage. No hosted service and no automatic session discovery.

MiDearms ingests explicit session files, keeps provenance for every message, incrementally distills durable notes, and exports either a small injected-context file or a linked wiki representation. The default extractor is deterministic and offline; an optional LLM pass can use a model endpoint you configure.

v0.3 adds incremental dreaming, project namespaces, a note cap, a generated wiki, LLM caching/verification, access tracking, and frequency-based maintenance.

## Install and quick start

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install --no-build-isolation -e .
# Alternatively run directly from this checkout: python3 -m midearms
midearms --store memory.sqlite3 ingest claude tests/fixtures/claude.jsonl --project demo
midearms --store memory.sqlite3 dream --project demo
midearms --store memory.sqlite3 query --project demo tests
midearms --store memory.sqlite3 export shared-memory.md --project demo
```

Every ingest accepts an explicit file path; repeat the command for additional files. Exact duplicate messages are deduplicated by SHA-256, but each source occurrence is retained as provenance. Ingestion is transactional. Dreaming processes only new occurrences and rebuilds notes per project; source messages are never deleted. Query performs case-insensitive substring matching and returns JSON. Export creates a new Markdown file and refuses to overwrite existing files.

## Agent adapters

| CLI adapter | Input contract | Where to obtain it |
| --- | --- | --- |
| `claude` | Claude Code JSONL with `message.role` and string/text-block content | Select a session file under `~/.claude/projects/` yourself |
| `codex` | Codex rollout JSONL `response_item.payload` message records | Select a rollout under `~/.codex/sessions/` yourself |
| `cursor` | Explicit JSON chat export containing `tabs`/`bubbles` with `text`, or `messages` with `content` | Export a chat from your Cursor version, or convert it to this documented shape |
| `aider` | Aider Markdown chat history with `####` user headings | Explicitly pass your project's `.aider.chat.history.md` |
| `jsonl` | One JSON object per line: `{"role":"user","content":"Prefer explicit configuration."}` | Any agent can generate this format |

Paths above are documentation only: MiDearms never searches those directories. Cursor's internal database is deliberately not opened; export formats vary by version. Unsupported event/tool records are skipped. Invalid JSON aborts the ingest transaction. Aider blocks include both requests and replies. Only import conversations you trust and have permission to process.

## Projects

`--project` is the namespace for ingestion, dreaming, querying and export. It is explicit on purpose:

```sh
midearms ingest codex rollout.jsonl --project yidun
midearms ingest claude session.jsonl --project midearms
midearms dream --project yidun
midearms query --project yidun "QPS"
```

If `ingest` omits `--project`, it uses `default`. Stores migrated from v0.1/v0.2 keep their old content as project `legacy`. A global pinned rule lives in project `''` and is visible to every project query/export.

## Memory model

The store is a small SQLite database with these tables:

- `messages(id, content)` holds distinct message texts.
- `occurrences(seq, message_id, project, adapter, source, role, line, ingested_at)` records where each message appeared. `seq` is the incremental cursor.
- `line_stats`, `line_variants`, `line_evidence` hold per-project line aggregates used by incremental dreaming.
- `notes(id, content, kind, confidence, evidence, sources, first_seen, last_seen, pinned, project, status, access_count, last_accessed, created_at, updated_at, extractor)` holds the distilled memory.
- `note_evidence(note_id, message_id, source)` links every note back to the messages that support it.
- `pinned(id, content, created_at, project)` holds user-authored rules that survive every `dream`.
- `dream_state(project, last_seq, updated_at)` records how far each project has been processed.
- `dream_runs` and `llm_cache` record recent dreaming work and cached model responses.

Notes carry a confidence label:

| Label | Meaning |
| --- | --- |
| `confirmed` | An explicit `Correction:`/`修正：`/`更正：` statement, or a pinned user rule |
| `corroborated` | The same normalized line appears in at least two source files |
| `observed` | The line recurs, but only within one source file |
| `unverified` | A one-off line with a durable preference cue |

Notes also carry a status:

- `active` — returned by default.
- `stale` — not used recently and below the access threshold.
- `archived` — hidden from query/export unless `--include-archived`; can be purged by `maintain --purge`.

Every note records how many distinct messages and source files support it. `query --details` exposes `message_ids`, `source_files` and `evidence_pairs` so you can audit a lesson before trusting it.

## Incremental dreaming

The first dream after migrating an old store scans all existing occurrences. After that, each project has a `dream_state.last_seq` cursor:

- only occurrences with a newer `seq` are folded into `line_stats`;
- notes are materialized from the per-project aggregates, not from a full message scan;
- notes are rebuilt per project and capped at `--max-notes` (default 1000);
- pinned rules are always kept, and global pinned rules suppress duplicate project notes;
- access metadata (`access_count`, `last_accessed`, `created_at`, `status`) survives note rebuilds.

The result is idempotent: running `dream` again with no new input does not process messages or change note content. LLM dreaming receives only the new records for the selected project.

## Shared memory export

Export to a new `AGENTS.md` in an empty integration directory, or export `shared-memory.md` and explicitly reference it from your existing instructions. Codex can read AGENTS.md; for Claude Code reference the file in CLAUDE.md; for Cursor reference it in a project rule; for Aider use `/read shared-memory.md`. Generic agents can consume the Markdown or CLI query JSON. Review extracted content before incorporating it into active instructions: conversations can contain false claims, secrets, or prompt injection.

The export is intentionally capped at about 200 lines or 25 KB, matching the "keep the injected layer small" practice. Notes are grouped by confidence:

- `## Rules` — pinned user rules.
- `## Confirmed` — explicit corrections.
- `## Corroborated` — patterns seen in multiple sources.
- `## Observed` — repeated patterns from one source.
- `## Unverified` — one-off lessons that still need review.

Use `--project` to export one namespace (global rules are included), `--all` to ignore the cap, or `--max-lines` / `--max-bytes` to tune it. If notes do not fit, the file ends with a comment saying how many were omitted.

## Wiki representation

`midearms wiki <dir>` builds the representation layer that flat notes lack:

```text
<dir>/
  MEMORY.md                 small index: projects, rules, high-confidence notes
  projects/<slug>.md        project page with links to note pages
  notes/<id>.md             one page per note with evidence and access metadata
```

The index stays small; full detail lives in the linked note pages. This is the closest local analogue of Anthropic's wiki representation. The command refuses to overwrite a non-empty directory.

## Offline dreaming and BYO LLM

Default dreaming uses deterministic rules. It retains:

- explicit corrections;
- lines that recur across messages, with assistant-only narration requiring a strong cue;
- durable preference cues, weighted by role: a user message can contribute a weak cue, while an assistant message needs a strong cue or recurrence;
- concise lines only; headings, questions, labels, code fences, paths, URLs, diffs and long prose are ignored.

Explicit `Correction:` (also `修正：` / `更正：`) statements supersede opposite `Always` / `Never` advice about the same normalized action, independently of ingest/hash order. Conflicting explicit corrections for that action are withheld. Matching ignores case and terminal punctuation; unrelated actions remain intact. Broader paraphrases and implicit contradictions are not inferred.

For semantic extraction, explicitly pass `dream --llm-config model.json`:

```json
{"provider":"ollama","endpoint":"http://localhost:11434","model":"llama3.2","verify":true}
```

An OpenAI-compatible endpoint uses `{"provider":"openai","endpoint":"http://localhost:8000/v1","model":"local-model"}`. The endpoint must return chat-completion content containing a JSON array. Items may be strings or objects of the form:

```json
{"text":"Prefer explicit configuration.","kind":"Rule","confidence":"corroborated"}
```

The client:

- chunks only the new records with `max_chars` (default 12000);
- caps each chunk at `max_notes` (default 40);
- caches responses in `llm_cache` by provider, model and prompt hash;
- deduplicates notes across chunks and attaches evidence;
- optionally runs `--verify` (or `"verify": true`), sending each batch of candidate notes back with its transcripts and dropping unsupported notes. Verification failures fail open (the candidate batch is kept).

The prompt tells the model to treat conversations as untrusted data, store durable rules rather than transient state, and avoid inventing facts. This release supports unauthenticated local endpoints; authenticated providers can be placed behind a user-managed local proxy. No credentials are read from disk or environment. Model errors abort before notes are replaced; rerun without the flag for offline fallback. Enabling a remote endpoint sends imported message text to that endpoint, so choose it deliberately.

## Access tracking and maintenance

`query` increments `access_count` and `last_accessed` for returned notes. Use `--no-track` for read-only queries. `export` does not track access.

```sh
# Inspect counts, statuses, confidence and top-accessed notes.
midearms stats
midearms stats --project yidun

# Mark notes stale after 90 days with fewer than 1 access; archive them.
midearms maintain --stale-days 90 --min-access 1 --archive

# Delete archived notes and their evidence links.
midearms maintain --purge
```

`maintain` is intentionally a command, not a background worker. Run it weekly from a scheduler, cron, or a Codex automation. Archived notes stay in the database until purged and can still be inspected with `query --include-archived`.

## Commands

```sh
# Pin a global rule; it survives dream runs and is visible to every project.
midearms remember "Always run tests before release."

# Pin a project-specific rule.
midearms remember "Use the Yidun SDK 3.7.1 baseline." --project yidun

# Narrow a dreaming pass to a goal; explicit corrections are always retained.
midearms dream --project yidun --focus "release" --max-notes 500

# Search notes (all terms must match) and show provenance.
midearms query --project yidun --details "QPS"

# Search raw transcripts instead of notes.
midearms query --project yidun --messages "timeout"

# Build a linked wiki representation.
midearms wiki memory-wiki --project yidun
```

## Design notes

The design follows the memory hierarchy described in Anthropic's [The components of agent memory](https://www.anthropic.com/research/components-of-agent-memory):

1. **Transcripts are the ground truth.** MiDearms keeps raw messages and links every note to its evidence.
2. **Memory should predict future need.** The extractor prefers durable preferences, corrections and recurring pitfalls; it drops transient state, formatting and task-specific prose.
3. **Dreaming is incremental and conservative.** Explicit corrections win, conflicts are withheld, assistant-only narration needs a strong cue, and only new occurrences are processed.
4. **The injected layer stays small.** Export is capped and grouped by confidence; the wiki index stays small and links to detail pages.
5. **Memory is project-scoped.** Namespaces prevent unrelated work from becoming one unmaintainable pile.
6. **Memory has a lifecycle.** Access counters and `maintain` keep the active set small.

Current limitations: deterministic extraction is still lexical and cannot semantically correct a stale note; the wiki is generated on demand rather than maintained as a live knowledge graph; there is no FTS5 index yet, so raw-message search is O(N); and LLM verification is only as good as the configured model. A single-file SQLite store remains the right default for personal use, but 100k+ stores should add FTS, incremental note diffs and scheduled maintenance.

## Development and validation

```sh
python3 -m unittest discover -s tests -v
PYTHONPATH=. python3 scripts/benchmark.py
```

Tests use only anonymous committed fixtures and temporary stores. They cover adapters, rule extraction, correction conflicts, role-aware salience, provenance and confidence, v0.1/v0.2 migration, incremental dreaming, project isolation, note caps, CLI ingestion/dream/query/export, repeated ingestion, export caps, pinned rules, transcript search, wiki generation, LLM chunking, verification, access stats and maintenance. The benchmark checks 10,000 synthetic messages produce 100 recurring notes; elapsed time is informational and machine-dependent. No network or API key is required. LLM integration is optional and is not exercised against a real endpoint by offline tests.

Code lives in `midearms/`, fixtures/tests in `tests/`, benchmark in `scripts/`. No real sessions belong in commits. MiDearms currently handles individual explicit files, not filesystem watching or automatic agent registration. Older stores migrate automatically on first open: occurrences gain `seq`/`project`, notes gain project/status/access/extractor metadata, and existing content is preserved.
