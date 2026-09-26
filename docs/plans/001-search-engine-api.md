# Search Engine and HTTP API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** approved 2026-09-18

**Goal:** Build the authenticated, collection-scoped Recoll service defined by spec 001, including durable membership/indexing jobs, document retrieval, and its Docker deployment.

**Architecture:** A packaged Python service separates domain behavior, SQLite persistence, indexing orchestration, and a narrow Recoll adapter. FastAPI exposes the shared HTTP contract; a durable single-worker queue converts desired membership state into an atomically exported map and forced Recoll reindexes. Docker supplies Recoll, but all paths and network settings remain configuration so a later desktop sidecar can run the same application.

**Tech Stack:** Python 3.13, FastAPI, Uvicorn, stdlib `sqlite3`, `argon2-cffi`, pytest, HTTPX, Ruff, mypy, uv, a small C membership helper, Recoll 1.43+ in Debian trixie, Docker Compose.

**Spec:** `docs/specs/001-search-engine-api.md`

## Global Constraints

- Documents and their extended attributes are read-only; the Compose document mount is `:ro`.
- Only `src/recoll_modern/engine/` may import `recoll` or invoke `recollindex`.
- Searches require one or more collection IDs and never silently span collections.
- Collection IDs match `^c[0-9a-f]{10}$`; document IDs are lowercase SHA-256 digests.
- Membership is additive: direct membership wins over rule-derived exclusions and per-file rule overrides.
- Directory walks never follow directory symlinks; file symlinks must resolve beneath the document root.
- Jobs are durable and replayable; `fail_on_file_error` defaults to `false`.
- Routes, cookies, OpenAPI, redirects, and generated links honor the configured mount prefix.
- Docker is packaging, not an application dependency; paths, listen host/port, and lifecycle are configurable.
- Host tests requiring Recoll skip clearly when the Compose service is unavailable; they never silently pass.
- Use uv only. Runtime dependencies proposed for approval with this plan: `fastapi`, `uvicorn[standard]`, and `argon2-cffi`. Development dependencies: `pytest`, `pytest-asyncio`, `httpx`, `ruff`, and `mypy`.
- Every task follows red-green-refactor, ends with its focused tests plus lint/typecheck for touched code, updates its checkboxes, and creates the listed Conventional Commit.

## Spec Coverage

| Spec area | Implemented by |
|---|---|
| C1, R13–R18 — read-only indexing, metadata helper, forced reindex, durable jobs | Tasks 6–8, 13–14 |
| C2–C3, R5–R12 — content identity, canonical paths, sources, rules and exclusions | Tasks 4–7, 11, 14 |
| C4, R19–R23 — mandatory scope, ranking, projection, retrieval and pagination | Tasks 8, 12, 14 |
| R1–R4 — collection identity and lifecycle | Tasks 3, 10–11, 14 |
| R24–R26 — passwords, sessions, CSRF and first-boot seeding | Tasks 9–10, 14 |
| R27–R30 — health, browsing, subpath/proxy behavior and errors | Tasks 10–14 |
| R31 — configurable process/package seam and recoverable shutdown | Tasks 1, 6, 10, 13–14 |

---

### Task 1: Scaffold the package and configuration boundary

**Files:**
- Create: `pyproject.toml`, `uv.lock`, `.python-version`, `README.md`, `src/recoll_modern/__init__.py`
- Create: `src/recoll_modern/config.py`, `src/recoll_modern/app.py`, `src/recoll_modern/__main__.py`
- Create: `tests/unit/test_config.py`, `tests/conftest.py`
- Modify: `.gitignore`, `AGENTS.md`, `docs/ARCHITECTURE.md`

**Interfaces:**
- Produces: `Settings.from_env(environ: Mapping[str, str]) -> Settings`
- Produces: console entry point `recoll-modern = recoll_modern.__main__:main`

- [x] **Step 1: Initialize and declare the approved dependencies**

Run:

```bash
uv init --package --python 3.13
uv add fastapi 'uvicorn[standard]' argon2-cffi
uv add --dev pytest pytest-asyncio httpx ruff mypy
```

Set `requires-python = ">=3.13,<3.14"`, configure `uv_build`, strict mypy, Ruff formatting/linting, and pytest paths in `pyproject.toml`. Keep the generated `uv.lock`.

- [x] **Step 2: Write the failing configuration tests**

```python
def test_settings_are_rooted_in_configured_state(tmp_path: Path) -> None:
    settings = Settings.from_env({
        "RECOLL_MODERN_DOCUMENT_ROOT": str(tmp_path / "docs"),
        "RECOLL_MODERN_STATE_ROOT": str(tmp_path / "state"),
        "RECOLL_MODERN_HOST": "127.0.0.1",
        "RECOLL_MODERN_PORT": "9123",
        "RECOLL_MODERN_ROOT_PATH": "/recoll",
    })
    assert settings.database_path == tmp_path / "state" / "recoll-modern.sqlite3"
    assert settings.membership_map_path == tmp_path / "state" / "membership.map"
    assert (settings.host, settings.port, settings.root_path) == ("127.0.0.1", 9123, "/recoll")

def test_root_path_rejects_trailing_slash() -> None:
    with pytest.raises(ValueError, match="mount prefix"):
        Settings.from_env({"RECOLL_MODERN_ROOT_PATH": "/recoll/"})
```

- [x] **Step 3: Run the test and observe the missing module failure**

Run: `uv run pytest tests/unit/test_config.py -v`

Expected: FAIL because `recoll_modern.config.Settings` does not exist.

- [x] **Step 4: Implement immutable settings and the CLI seam**

```python
@dataclass(frozen=True, slots=True)
class Settings:
    document_root: Path
    state_root: Path
    recoll_config_dir: Path
    host: str
    port: int
    root_path: str
    trusted_proxies: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]
    inline_text_limit: int
    inline_text_limit_max: int

    @property
    def database_path(self) -> Path:
        return self.state_root / "recoll-modern.sqlite3"

    @property
    def membership_map_path(self) -> Path:
        return self.state_root / "membership.map"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] = os.environ) -> "Settings":
        root_path = environ.get("RECOLL_MODERN_ROOT_PATH", "/")
        if not root_path.startswith("/") or (root_path != "/" and root_path.endswith("/")):
            raise ValueError("mount prefix must start with / and have no trailing slash")
        text_max = int(environ.get("RECOLL_MODERN_INLINE_TEXT_LIMIT_MAX", "100000"))
        text_default = int(environ.get("RECOLL_MODERN_INLINE_TEXT_LIMIT", "20000"))
        if not 0 < text_default <= text_max:
            raise ValueError("inline text limit must be positive and no greater than its maximum")
        proxy_text = environ.get("RECOLL_MODERN_TRUSTED_PROXIES", "")
        proxies = tuple(
            ipaddress.ip_network(value.strip(), strict=False)
            for value in proxy_text.split(",") if value.strip()
        )
        return cls(
            document_root=Path(environ.get("RECOLL_MODERN_DOCUMENT_ROOT", "/documents")).resolve(),
            state_root=Path(environ.get("RECOLL_MODERN_STATE_ROOT", "/var/lib/recoll-modern")).resolve(),
            recoll_config_dir=Path(environ.get("RECOLL_MODERN_RECOLL_CONFIG_DIR", "/etc/recoll-modern")).resolve(),
            host=environ.get("RECOLL_MODERN_HOST", "0.0.0.0"),
            port=int(environ.get("RECOLL_MODERN_PORT", "8000")),
            root_path=root_path,
            trusted_proxies=proxies,
            inline_text_limit=text_default,
            inline_text_limit_max=text_max,
        )
```

Defaults are `/documents`, `/var/lib/recoll-modern`, `/etc/recoll-modern`, `0.0.0.0`, `8000`, `/`, no
trusted proxies, 20,000 characters, and a 100,000-character hard maximum. Add a minimal
`create_app(settings)` returning `FastAPI(root_path=settings.root_path)` with a temporary `/health`
response `{"status": "starting"}`; Task 10 replaces that route with real readiness. `main()` calls
`uvicorn.run(create_app(settings), host=settings.host, port=settings.port)`.

- [x] **Step 5: Record the commands that CI will run**

Replace the command TODO in `AGENTS.md` with:

```text
install: uv sync --locked
dev: uv run recoll-modern
test: uv run pytest
single-test: uv run pytest path/to/test.py::test_name -v
lint: uv run ruff check .
typecheck: uv run mypy src tests
build: uv build
```

Add `src/recoll_modern/` and `tests/` to the architecture map. Ignore `.venv/`, `dist/`, coverage output, SQLite files, membership maps, Recoll config, and index data without ignoring committed configuration templates.

- [x] **Step 6: Verify and commit**

Run: `uv run pytest tests/unit/test_config.py -v && uv run ruff check . && uv run mypy src tests && uv build`

Expected: all commands exit 0.

Also run `timeout 3s uv run recoll-modern`; expected output includes Uvicorn startup and clean shutdown
after `timeout` sends SIGTERM (exit 124 from `timeout` is expected).

```bash
git add pyproject.toml uv.lock .python-version .gitignore AGENTS.md docs/ARCHITECTURE.md src tests
git commit -m "chore: scaffold Python service"
```

---

### Task 2: Add SQLite migrations and transaction handling

**Files:**
- Create: `src/recoll_modern/storage/__init__.py`, `src/recoll_modern/storage/database.py`
- Create: `src/recoll_modern/storage/migrations/__init__.py`, `src/recoll_modern/storage/migrations/001_initial.sql`
- Create: `tests/storage/test_database.py`, `tests/storage/test_migrations.py`

**Interfaces:**
- Consumes: `Settings.database_path`
- Produces: `Database(path: Path)`, `Database.connect()`, `Database.transaction()` and `Database.migrate()`

- [x] **Step 1: Write failing migration and constraint tests**

```python
def test_migrate_creates_all_tables(database: Database) -> None:
    database.migrate()
    with database.connect() as connection:
        names = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )}
    assert EXPECTED_TABLES <= names

def test_one_canonical_path_per_document(database: Database) -> None:
    seed_document_with_two_paths(database)
    with pytest.raises(sqlite3.IntegrityError):
        mark_both_paths_canonical(database)
```

`EXPECTED_TABLES` names all thirteen spec tables. Add tests for foreign keys, unique normalized collection names, unique directory rules, and cascade behavior.

- [x] **Step 2: Run the focused tests and observe failure**

Run: `uv run pytest tests/storage/test_database.py tests/storage/test_migrations.py -v`

Expected: FAIL because `Database` and migration 001 do not exist.

- [x] **Step 3: Implement connection and transaction policy**

Every connection sets `row_factory=sqlite3.Row`, `PRAGMA foreign_keys=ON`, `PRAGMA journal_mode=WAL`, and `PRAGMA busy_timeout=5000`. `transaction()` begins `IMMEDIATE`, commits on success, rolls back on exception, and closes the connection.

Create migration 001 with these exact relations:

```sql
CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE TABLE collections(id TEXT PRIMARY KEY, name TEXT NOT NULL, name_key TEXT NOT NULL UNIQUE,
  description TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE documents(content_hash TEXT PRIMARY KEY, byte_size INTEGER NOT NULL CHECK(byte_size >= 0),
  state TEXT NOT NULL CHECK(state IN ('present','missing')), created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE document_paths(id INTEGER PRIMARY KEY, document_hash TEXT NOT NULL REFERENCES documents(content_hash) ON DELETE CASCADE,
  relative_path TEXT NOT NULL UNIQUE, is_canonical INTEGER NOT NULL CHECK(is_canonical IN (0,1)),
  last_seen_at TEXT NOT NULL, missing_at TEXT);
CREATE UNIQUE INDEX one_canonical_path ON document_paths(document_hash) WHERE is_canonical = 1;
CREATE TABLE direct_memberships(collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
  document_hash TEXT NOT NULL REFERENCES documents(content_hash) ON DELETE CASCADE, created_at TEXT NOT NULL,
  PRIMARY KEY(collection_id, document_hash));
CREATE TABLE directory_rules(id TEXT PRIMARY KEY, collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
  relative_path TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(collection_id, relative_path));
CREATE TABLE directory_rule_exclusions(rule_id TEXT NOT NULL REFERENCES directory_rules(id) ON DELETE CASCADE,
  relative_path TEXT NOT NULL, PRIMARY KEY(rule_id, relative_path));
CREATE TABLE rule_memberships(rule_id TEXT NOT NULL REFERENCES directory_rules(id) ON DELETE CASCADE,
  document_hash TEXT NOT NULL REFERENCES documents(content_hash) ON DELETE CASCADE, last_seen_at TEXT NOT NULL,
  PRIMARY KEY(rule_id, document_hash));
CREATE TABLE membership_exclusions(collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
  document_hash TEXT NOT NULL REFERENCES documents(content_hash) ON DELETE CASCADE, created_at TEXT NOT NULL,
  PRIMARY KEY(collection_id, document_hash));
CREATE TABLE jobs(id TEXT PRIMARY KEY, kind TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('queued','running','completed','completed_with_errors','failed')),
  request_json TEXT NOT NULL, fail_on_file_error INTEGER NOT NULL CHECK(fail_on_file_error IN (0,1)),
  progress INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL DEFAULT 0,
  error_code TEXT, error_message TEXT, created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT);
CREATE TABLE job_file_errors(job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  relative_path TEXT NOT NULL, code TEXT NOT NULL, message TEXT NOT NULL, PRIMARY KEY(job_id, relative_path));
CREATE TABLE users(id TEXT PRIMARY KEY, username TEXT NOT NULL, username_key TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL, created_at TEXT NOT NULL, disabled_at TEXT);
CREATE TABLE sessions(token_hash TEXT PRIMARY KEY, csrf_hash TEXT NOT NULL,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL, last_seen_at TEXT NOT NULL);
```

Migration application is ordered, transactional, records each version, and refuses duplicate version numbers.

- [x] **Step 4: Run tests, lint, typecheck, and commit**

Run: `uv run pytest tests/storage -v && uv run ruff check . && uv run mypy src tests`

Expected: PASS.

```bash
git add src/recoll_modern/storage tests/storage
git commit -m "feat: add SQLite persistence foundation"
```

---

### Task 3: Implement collection identity and repositories

**Files:**
- Create: `src/recoll_modern/domain/__init__.py`, `src/recoll_modern/domain/models.py`, `src/recoll_modern/domain/errors.py`, `src/recoll_modern/domain/collections.py`
- Create: `src/recoll_modern/storage/collections.py`
- Create: `tests/domain/test_collections.py`, `tests/storage/test_collection_repository.py`

**Interfaces:**
- Produces: `Collection`, `CollectionCreate`, `CollectionPatch`
- Produces: `normalize_name(value: str) -> tuple[str, str]`
- Produces: `CollectionService.create/get/list/patch/delete`

- [x] **Step 1: Write failing identity and CRUD tests**

```python
def test_collection_ids_are_opaque() -> None:
    collection = service.create(CollectionCreate(name="Tech Books"))
    assert re.fullmatch(r"c[0-9a-f]{10}", collection.id)

def test_names_are_unique_after_unicode_casefold() -> None:
    service.create(CollectionCreate(name="Straße"))
    with pytest.raises(AppError) as caught:
        service.create(CollectionCreate(name="STRASSE"))
    assert caught.value.code == "collection_name_taken"

def test_rename_does_not_enqueue_work() -> None:
    changed = service.patch(collection.id, CollectionPatch(name="Reference"))
    assert changed.name == "Reference"
    assert jobs.enqueued == []
```

- [x] **Step 2: Run tests and observe missing domain types**

Run: `uv run pytest tests/domain/test_collections.py tests/storage/test_collection_repository.py -v`

Expected: FAIL on imports.

- [x] **Step 3: Implement domain types, errors, normalization, and repository**

`normalize_name` applies Unicode NFC, strips surrounding whitespace for validation, rejects names with no non-whitespace character, preserves the supplied display name, and returns `normalized.casefold()` as `name_key`. Generate IDs from five random bytes and retry on the improbable unique collision.

```python
@dataclass(frozen=True, slots=True)
class AppError(Exception):
    code: str
    message: str
    status: int
    details: Mapping[str, object] = field(default_factory=dict)
```

Define `CollectionRepository` as a `Protocol` with exact methods `create(CollectionCreate) ->
Collection`, `get(str) -> Collection | None`, `list(limit: int, offset: int) -> tuple[list[Collection],
int]`, `patch(str, CollectionPatch) -> Collection`, and `delete(str) -> list[str]`, where delete returns
affected canonical paths.

Map SQLite uniqueness failures to `collection_name_taken`, not raw database text. `delete` returns affected paths before cascading membership rows and never touches the index.

- [x] **Step 4: Verify and commit**

Run: `uv run pytest tests/domain/test_collections.py tests/storage/test_collection_repository.py -v && uv run ruff check . && uv run mypy src tests`

```bash
git add src/recoll_modern/domain src/recoll_modern/storage/collections.py tests/domain tests/storage
git commit -m "feat: add collection domain"
```

---

### Task 4: Discover files and maintain content-hash identity

**Files:**
- Create: `src/recoll_modern/indexing/__init__.py`, `src/recoll_modern/indexing/paths.py`, `src/recoll_modern/indexing/discovery.py`
- Create: `src/recoll_modern/storage/documents.py`
- Create: `tests/indexing/test_paths.py`, `tests/indexing/test_discovery.py`, `tests/storage/test_documents.py`

**Interfaces:**
- Produces: `Source(type, path, mode=None, excluded_directories=())`
- Produces: `PathPolicy.resolve_file/resolve_directory`
- Produces: `discover_sources(policy, sources) -> DiscoveryReport`
- Produces: `DocumentRepository.observe_files(files) -> ObservationResult`

- [x] **Step 1: Write failing filesystem-policy tests**

```python
def test_directory_symlink_is_not_walked(tree: DocumentTree) -> None:
    report = discover_sources(tree.policy, [Source.directory("books", mode="snapshot")])
    assert "books/link/secret.pdf" not in report.relative_paths

def test_file_symlink_must_resolve_inside_root(tree: DocumentTree) -> None:
    report = discover_sources(tree.policy, [Source.file("outside-link")])
    assert report.errors[0].code == "file_outside_root"

def test_same_bytes_have_one_document_and_one_canonical_path(repository: DocumentRepository) -> None:
    result = repository.observe_files([file_a, file_b])
    assert len(result.documents) == 1
    assert result.documents[0].canonical_path == min(file_a.relative_path, file_b.relative_path)
```

Also cover exact recursive directory exclusions, a file vanishing between stat and read, unreadable files, and same-name/different-content files.

- [x] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/indexing/test_paths.py tests/indexing/test_discovery.py tests/storage/test_documents.py -v`

- [x] **Step 3: Implement secure discovery and stable hashing**

`PathPolicy` rejects absolute paths, `..`, NUL, and resolved targets outside `document_root`. Directory
traversal uses `os.scandir(directory_path)` and calls `entry.is_dir(follow_symlinks=False)`, sorts entries
by normalized relative path, never enters symlinked directories, and filters exact excluded descendants
before traversal. File symlinks are dereferenced only after containment validation.

`hash_file_stable` opens read-only, hashes in 1 MiB chunks, compares `(device, inode, size, mtime_ns)` before and after, and returns `file_changed_during_scan` if they differ. Map `ENOENT`, `EACCES`, containment, and read failures to the stable codes in the spec.

`observe_files` upserts documents and paths in one transaction, chooses the lexicographically smallest live normalized path as canonical, clears all previous canonical flags before setting the new one, marks unseen known paths missing only during full/rule reconciliation, and marks a document missing only when it has no live paths.

- [x] **Step 4: Verify and commit**

Run: `uv run pytest tests/indexing tests/storage/test_documents.py -v && uv run ruff check . && uv run mypy src tests`

```bash
git add src/recoll_modern/indexing src/recoll_modern/storage/documents.py tests/indexing tests/storage/test_documents.py
git commit -m "feat: add document discovery and identity"
```

---

### Task 5: Implement additive membership and directory rules

**Files:**
- Create: `src/recoll_modern/domain/membership.py`
- Create: `src/recoll_modern/storage/membership.py`
- Create: `src/recoll_modern/indexing/reconcile.py`
- Create: `tests/domain/test_membership.py`, `tests/indexing/test_reconcile.py`, `tests/storage/test_membership_repository.py`

**Interfaces:**
- Produces: `MembershipRepository.add_direct`, `replace_rule_members`, `exclude_document`, `effective_collections`
- Produces: `MembershipService.plan_add`, `plan_remove_document`, `plan_patch_rule`, `plan_delete_rule`
- Produces: `reconcile_rule(rule_id, policy, repositories) -> ReconcileResult`

- [x] **Step 1: Write failing provenance tests**

```python
def test_direct_membership_wins_over_rule_exclusions(repo: MembershipRepository) -> None:
    repo.add_direct("c0000000001", HASH)
    repo.exclude_document("c0000000001", HASH)
    assert repo.effective_collections(HASH) == ["c0000000001"]

def test_removing_one_overlapping_rule_keeps_other_source(repo: MembershipRepository) -> None:
    repo.replace_rule_members(RULE_A, [HASH])
    repo.replace_rule_members(RULE_B, [HASH])
    repo.delete_rule(RULE_A)
    assert repo.effective_collections(HASH) == [COLLECTION_ID]

def test_rule_reconciliation_removes_departed_file_without_touching_direct(repo: MembershipRepository) -> None:
    reconcile_rule(RULE_ID, policy, repos)
    assert repo.rule_documents(RULE_ID) == {STILL_PRESENT_HASH}
    assert repo.has_direct(COLLECTION_ID, DEPARTED_HASH)
```

- [x] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/domain/test_membership.py tests/indexing/test_reconcile.py tests/storage/test_membership_repository.py -v`

- [x] **Step 3: Implement desired-state operations**

Snapshot directory results and file sources call `add_direct`; persistent directories create `r` plus ten hex digits, validate exclusions as exact descendants, then atomically replace that rule's materialized membership. Effective membership is this SQL shape:

```sql
SELECT collection_id FROM direct_memberships WHERE document_hash = ?
UNION
SELECT r.collection_id
FROM rule_memberships rm JOIN directory_rules r ON r.id = rm.rule_id
WHERE rm.document_hash = ?
  AND NOT EXISTS (
    SELECT 1 FROM membership_exclusions e
    WHERE e.collection_id = r.collection_id AND e.document_hash = rm.document_hash
  )
ORDER BY collection_id;
```

Removing a document deletes its direct row and upserts a collection-level rule override. Explicitly adding that file again deletes the override and adds direct membership. Rule deletion returns canonical paths whose effective collection set changed.

- [x] **Step 4: Verify and commit**

Run: `uv run pytest tests/domain/test_membership.py tests/indexing/test_reconcile.py tests/storage/test_membership_repository.py -v && uv run ruff check . && uv run mypy src tests`

```bash
git add src/recoll_modern/domain/membership.py src/recoll_modern/storage/membership.py src/recoll_modern/indexing/reconcile.py tests
git commit -m "feat: add membership provenance and rules"
```

---

### Task 6: Add the durable single-worker job queue

**Files:**
- Create: `src/recoll_modern/domain/jobs.py`, `src/recoll_modern/storage/jobs.py`
- Create: `src/recoll_modern/indexing/worker.py`, `src/recoll_modern/indexing/handlers.py`
- Create: `tests/storage/test_job_repository.py`, `tests/indexing/test_worker.py`, `tests/indexing/test_job_handlers.py`

**Interfaces:**
- Produces: `JobRepository.enqueue/claim_next/progress/complete/fail/recover_running/retry`
- Produces: `JobWorker.start()`, `JobWorker.stop()`, `JobWorker.run_once() -> bool`
- Produces: `MembershipJobHandler.handle(job: Job) -> None`

- [x] **Step 1: Write failing transition, recovery, and policy tests**

```python
def test_recover_running_requeues_valid_jobs(repo: JobRepository) -> None:
    job = repo.enqueue("membership_add", VALID_REQUEST, False)
    repo.claim_next()
    repo.recover_running()
    assert repo.get(job.id).state == JobState.QUEUED

def test_strict_discovery_error_applies_nothing(handler: MembershipJobHandler) -> None:
    handler.handle(job(fail_on_file_error=True, sources=[good_file, vanished_file]))
    assert memberships.all() == []
    assert jobs.current.state == JobState.FAILED

def test_best_effort_applies_valid_files_and_records_errors(handler: MembershipJobHandler) -> None:
    handler.handle(job(fail_on_file_error=False, sources=[good_file, vanished_file]))
    assert memberships.all() == [good_hash]
    assert jobs.current.state == JobState.COMPLETED_WITH_ERRORS
```

- [x] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/storage/test_job_repository.py tests/indexing/test_worker.py tests/indexing/test_job_handlers.py -v`

- [x] **Step 3: Implement durable transitions and handlers**

Use opaque `j` plus 32 hex digits. `claim_next` runs under `BEGIN IMMEDIATE`, selects the oldest queued job, and changes it to running atomically. Valid transitions are queued→running, running→completed/completed_with_errors/failed, and failed→queued via retry. Startup requeues running jobs whose JSON decodes to the registered request type; malformed requests become failed with `invalid_job_request`.

The worker owns one asyncio task, sleeps on an `asyncio.Event`, performs blocking discovery/database/engine work with `asyncio.to_thread`, and on shutdown stops claiming new work and leaves an interrupted running job recoverable. Membership handlers scan completely before opening the desired-state transaction in strict mode. Best-effort handlers persist every safe file error and continue.

- [x] **Step 4: Verify and commit**

Run: `uv run pytest tests/storage/test_job_repository.py tests/indexing/test_worker.py tests/indexing/test_job_handlers.py -v && uv run ruff check . && uv run mypy src tests`

```bash
git add src/recoll_modern/domain/jobs.py src/recoll_modern/storage/jobs.py src/recoll_modern/indexing tests
git commit -m "feat: add durable indexing jobs"
```

---

### Task 7: Export membership atomically and build the native helper

**Files:**
- Create: `src/recoll_modern/indexing/map_export.py`
- Create: `helper/recoll_membership.c`, `helper/Makefile`
- Create: `tests/indexing/test_map_export.py`, `tests/helper/test_membership_helper.py`

**Interfaces:**
- Produces: `export_membership_map(repository, destination: Path) -> None`
- Produces: `recoll-membership FILE_PATH`, reading `RECOLL_MODERN_MEMBERSHIP_MAP`

- [x] **Step 1: Write failing binary-format and helper tests**

```python
def test_export_is_atomic_and_handles_newlines(tmp_path: Path) -> None:
    destination = tmp_path / "membership.map"
    export_membership_map(fake_repo({"odd\nname.pdf": ["c0000000001"]}), destination)
    assert decode_map(destination) == {"odd\nname.pdf": "c0000000001"}
    assert list(tmp_path.glob("*.tmp")) == []

def test_helper_returns_sorted_space_separated_ids(compiled_helper: Path, map_file: Path) -> None:
    result = subprocess.run([compiled_helper, "/documents/a.pdf"], env={
        "RECOLL_MODERN_MEMBERSHIP_MAP": str(map_file)
    }, text=True, capture_output=True, check=True)
    assert result.stdout == "c0000000001 c0000000002\n"
```

- [x] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/indexing/test_map_export.py tests/helper/test_membership_helper.py -v`

- [x] **Step 3: Implement the robust flat-map format and C reader**

The format is `RCM1`, followed by sorted records of big-endian `uint32 path_length`, raw UTF-8 path bytes, big-endian `uint32 value_length`, and ASCII space-separated collection IDs. The exporter writes and fsyncs a sibling temporary file, chmods it `0640`, `os.replace()`s it, then fsyncs the parent directory. Paths in this private map are absolute because Recoll passes `%f`; no API exposes them.

The C helper opens the configured map read-only, validates every length against file size and a 16 MiB ceiling, scans records with `memcmp`, writes only the matched value plus newline, returns 0 for no membership, and returns nonzero with a generic stderr message for corrupt/unreadable maps. Compile with `cc -std=c17 -O2 -Wall -Wextra -Werror`.

- [x] **Step 4: Wire export before every forced reindex**

Extend `MembershipJobHandler` so a successful desired-state transaction calls `export_membership_map` once, then invokes the engine with the distinct sorted changed canonical paths. Add a failure-injection test proving the old map remains intact if write or replace fails.

- [x] **Step 5: Verify and commit**

Run: `make -C helper clean all && uv run pytest tests/indexing/test_map_export.py tests/helper/test_membership_helper.py tests/indexing/test_job_handlers.py -v && uv run ruff check . && uv run mypy src tests`

```bash
git add helper src/recoll_modern/indexing tests/helper tests/indexing
git commit -m "feat: export Recoll membership metadata"
```

---

### Task 8: Define the engine contract and Recoll adapter

**Files:**
- Create: `src/recoll_modern/engine/__init__.py`, `src/recoll_modern/engine/protocol.py`, `src/recoll_modern/engine/fake.py`, `src/recoll_modern/engine/recoll.py`
- Create: `tests/contract/engine_contract.py`, `tests/contract/test_fake_engine.py`, `tests/contract/test_recoll_engine.py`

**Interfaces:**
- Produces: `SearchRequest`, `EngineHit`, `EnginePage`, `EngineHealth`
- Produces: `Engine.health/search/extracted_text/force_reindex`

- [x] **Step 1: Write one contract suite against the fake**

```python
class EngineContract:
    engine: Engine

    def test_search_returns_one_ranked_page(self) -> None:
        page = self.engine.search(SearchRequest(
            query="python", collection_ids=("c0000000001", "c0000000002"),
            limit=20, offset=0, fetch_text=False,
        ))
        assert page.total >= len(page.hits)
        assert [hit.score for hit in page.hits] == sorted(
            [hit.score for hit in page.hits], reverse=True
        )
```

Cover metadata, snippets, optional text, offset, total estimate, health, missing text, and forced paths. `test_fake_engine.py` subclasses the contract with deterministic fixtures.

- [x] **Step 2: Run fake contract and observe failure**

Run: `uv run pytest tests/contract/test_fake_engine.py -v`

- [x] **Step 3: Implement Protocol and fake**

Define `Engine` as a `Protocol` with exact methods `health() -> EngineHealth`,
`search(SearchRequest) -> EnginePage`, `extracted_text(str) -> str`, and
`force_reindex(Sequence[str]) -> None`.

The fake applies collection OR semantics, returns each document once, and logs force-reindex calls.

- [x] **Step 4: Implement the isolated Recoll adapter**

Import `from recoll import recoll` only inside this file. Connect with the configured Recoll config
directory. Build `(<user query>) AND (collection:c0123456789 OR collection:cabcdef012)` using the actual
validated IDs. Call `query.execute(query_string, fetchtext=request.fetch_text)`,
`scroll(offset, "absolute")`, `fetchmany(limit)`, and `getsnippets`. Map stored fields to `EngineHit`,
decode file URLs, and use `query.rowcount` as approximate total. Use a safely quoted path-scoped query
with `fetchtext=True` for `extracted_text`; its contract test includes spaces, quotes, and parentheses in
filenames.

Implementation ruling: exact-path text retrieval uses Recoll's documented `fsudi.fs_udi(path)` plus
`Db.getDoc()` and `rclextract`, which avoids query-language escaping for unusual filenames. The Python
search API does not document a numeric relevance weight, so `score` currently derives from result rank;
verify a native score when the real container contract runs.

Run indexing as an argument list, never a shell string:

```python
subprocess.run(
    ["recollindex", "-c", str(config_dir), "-i", "-Z", *absolute_paths],
    check=True, capture_output=True, text=True, timeout=index_timeout,
)
```

Convert import, connection, timeout, and subprocess failures to `EngineUnavailable` without leaking stderr to clients.

- [x] **Step 5: Make the real contract skip only when unavailable**

`test_recoll_engine.py` probes the Compose service/config in a fixture. If unreachable it calls `pytest.skip("Recoll test container is not running")`; otherwise it runs the inherited contract. A separate assertion ensures the fixture did not return without either constructing an engine or recording a skip.

- [x] **Step 6: Verify and commit**

Run: `uv run pytest tests/contract -v && uv run ruff check . && uv run mypy src tests`

Expected: fake contract passes; real contract passes or reports explicit skips.

```bash
git add src/recoll_modern/engine tests/contract
git commit -m "feat: add Recoll engine boundary"
```

---

### Task 9: Implement users, sessions, seeding, and CSRF

**Files:**
- Create: `src/recoll_modern/domain/auth.py`, `src/recoll_modern/storage/auth.py`
- Create: `tests/domain/test_auth.py`, `tests/storage/test_auth_repository.py`

**Interfaces:**
- Produces: `AuthService.login/authenticate/logout/seed_initial_admin`
- Produces: `SessionCredentials(cookie_token, csrf_token, expires_at)`

- [x] **Step 1: Write failing auth tests**

```python
def test_passwords_are_argon2_hashes(auth: AuthService) -> None:
    auth.seed_initial_admin("admin", "correct horse battery staple")
    stored = repository.get_user_by_name("admin")
    assert stored.password_hash.startswith("$argon2id$")
    assert "correct horse" not in stored.password_hash

def test_database_stores_only_token_hashes(auth: AuthService) -> None:
    credentials = auth.login("admin", PASSWORD)
    assert repository.get_session(credentials.cookie_token) is not None
    assert credentials.cookie_token not in database_bytes()
    assert credentials.csrf_token not in database_bytes()

def test_first_boot_without_credentials_refuses_startup(empty_auth: AuthService) -> None:
    with pytest.raises(AppError, match="initial administrator"):
        empty_auth.seed_initial_admin(None, None)
```

Also test disabled/expired sessions, generic invalid credentials, case-folded usernames, CSRF mismatch, and cleanup.

- [x] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/domain/test_auth.py tests/storage/test_auth_repository.py -v`

- [x] **Step 3: Implement auth services**

Use `argon2.PasswordHasher` defaults, `secrets.token_urlsafe(32)` for independent cookie/CSRF tokens, and SHA-256 digests for stored lookup values. Session lifetime is configurable, defaults to 12 hours, and sliding refresh updates `last_seen_at` without extending beyond the configured policy. Use `hmac.compare_digest` for CSRF hashes. Seed `RECOLL_MODERN_ADMIN_USERNAME` and `RECOLL_MODERN_ADMIN_PASSWORD` only when no user exists; erase local password references after hashing and never log them.

- [x] **Step 4: Verify and commit**

Run: `uv run pytest tests/domain/test_auth.py tests/storage/test_auth_repository.py -v && uv run ruff check . && uv run mypy src tests`

```bash
git add src/recoll_modern/domain/auth.py src/recoll_modern/storage/auth.py tests/domain/test_auth.py tests/storage/test_auth_repository.py
git commit -m "feat: add session authentication"
```

---

### Task 10: Build the FastAPI shell, middleware, and core resources

**Files:**
- Modify: `src/recoll_modern/app.py`
- Create: `src/recoll_modern/api/__init__.py`, `src/recoll_modern/api/errors.py`, `src/recoll_modern/api/dependencies.py`
- Create: `src/recoll_modern/api/middleware.py`, `src/recoll_modern/api/auth.py`, `src/recoll_modern/api/health.py`
- Create: `src/recoll_modern/api/files.py`, `src/recoll_modern/api/collections.py`, `src/recoll_modern/api/schemas.py`
- Create: `tests/api/test_auth.py`, `tests/api/test_health.py`, `tests/api/test_files.py`, `tests/api/test_collections.py`, `tests/api/test_errors.py`, `tests/api/test_root_path.py`

**Interfaces:**
- Consumes: `Settings`, repositories, `AuthService`, `Engine`, `JobWorker`
- Produces: `create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI`

- [x] **Step 1: Write failing API contract tests**

```python
def test_error_envelope(client: TestClient) -> None:
    response = client.get("/collections/cffffffffff")
    assert response.status_code == 404
    assert response.json() == {"error": {
        "code": "collection_not_found", "message": "Collection not found", "details": {}
    }}

def test_cookie_and_openapi_honor_root_path(prefixed_client: TestClient) -> None:
    response = prefixed_client.post("/recoll/auth/login", json=VALID_LOGIN)
    assert "Path=/recoll" in response.headers["set-cookie"]
    assert prefixed_client.get("/recoll/openapi.json").status_code == 200

def test_untrusted_forwarded_prefix_is_ignored(client: TestClient) -> None:
    response = client.get("/health", headers={"X-Forwarded-Prefix": "/evil"})
    assert "/evil" not in response.text
```

Add tests for every auth route, CSRF on unsafe methods, strict same-origin login checks when `Origin` is present, `Secure` production cookies, request IDs, health 200/503, path traversal, one-level file browsing, list pagination, CRUD, confirmation, and no job on rename/empty creation.

- [x] **Step 2: Run API tests and observe failure**

Run: `uv run pytest tests/api/test_auth.py tests/api/test_health.py tests/api/test_files.py tests/api/test_collections.py tests/api/test_errors.py tests/api/test_root_path.py -v`

- [x] **Step 3: Implement lifespan and dependency wiring**

The lifespan creates state directories, migrates the database, seeds/refuses auth, recovers jobs,
enqueues one reconciliation job for all persistent rules, starts the worker, and on exit calls
`await worker.stop()`. Dependency callables read services from `app.state`. Tests inject a fake engine
and temporary settings; production constructs `RecollEngine` only through the engine factory.

- [x] **Step 4: Implement middleware and error mapping**

Map every `AppError` code to the spec status and envelope. Add an opaque request ID to unexpected 500
responses and logs. Prefix middleware strips the configured prefix from incoming paths before routing,
sets `scope["root_path"]`, and rejects unprefixed routes when the prefix is not `/`. For requests from a
configured proxy network, it may instead validate and apply forwarded scheme/host/prefix, stripping the
forwarded prefix only when it is present on the incoming path. Ignore all such headers from other
clients. Do not enable permissive CORS.

- [x] **Step 5: Implement auth, health, files, and collections routes**

Use JSON login. Set cookie `recoll_modern_session` as HttpOnly, SameSite=Lax, root-path scoped, and Secure outside explicit development mode. Return CSRF token in the login/session JSON and require `X-CSRF-Token` on POST/PATCH/DELETE. `GET /files` returns name, relative path, kind, size, and mtime for one sorted directory level. Collection create with no sources returns 201; with sources delegates to Task 11 and returns 202. Deletion validates exact confirmation, captures affected paths, deletes database state, and enqueues cleanup.

- [x] **Step 6: Verify and commit**

Run: `uv run pytest tests/api -v && uv run ruff check . && uv run mypy src tests`

```bash
git add src/recoll_modern/app.py src/recoll_modern/api tests/api
git commit -m "feat: add authenticated HTTP service"
```

---

### Task 11: Expose membership, rule, and job APIs

**Files:**
- Create: `src/recoll_modern/api/memberships.py`, `src/recoll_modern/api/jobs.py`
- Modify: `src/recoll_modern/api/schemas.py`, `src/recoll_modern/app.py`
- Create: `tests/api/test_memberships.py`, `tests/api/test_jobs.py`

**Interfaces:**
- Consumes: Task 5 membership plans and Task 6 job repository
- Produces: spec endpoints under `/collections/{id}/memberships`, `/directory-rules`, and `/jobs`

- [x] **Step 1: Write failing request/response tests**

```python
def test_persistent_directory_request_enqueues_replayable_job(client: TestClient) -> None:
    response = client.post(f"/collections/{COLLECTION_ID}/memberships", headers=csrf(), json={
        "sources": [{"type": "directory", "path": "books", "mode": "persistent",
                     "excluded_directories": ["books/.calibre"]}],
        "fail_on_file_error": False,
    })
    assert response.status_code == 202
    assert response.json()["job"]["state"] == "queued"

def test_removing_rule_preserves_overlapping_membership(client: TestClient) -> None:
    response = client.delete(f"/collections/{COLLECTION_ID}/directory-rules/{RULE_A}", headers=csrf())
    assert response.status_code == 202
    run_job(response.json()["job"]["id"])
    assert document_collections(HASH) == [COLLECTION_ID]
```

Cover invalid source combinations, exclusions outside source, default best-effort, strict atomicity, effective provenance, per-file overrides, patching rule exclusions, non-retryable jobs, and 50/200 pagination.

- [x] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/api/test_memberships.py tests/api/test_jobs.py -v`

- [x] **Step 3: Implement validated schemas and routes**

Use discriminated Pydantic models `FileSource(type="file", path)` and
`DirectorySource(type="directory", path, mode, excluded_directories)`. Reject mode/exclusions on files
and reject duplicate normalized sources. All mutations enqueue JSON containing a `version: 1`
discriminator and return the persisted job representation. `GET /collections/{id}/documents` returns
effective membership plus `direct`, contributing rule IDs, and override state. Implement `GET /jobs`,
`GET /jobs/{id}`, `POST /jobs/{id}/retry`, and `POST /jobs/reindex`; reindex accepts optional paths or
collection IDs and uses the whole document root when neither is present. Retry accepts failed or
completed-with-errors jobs only.

- [x] **Step 4: Verify and commit**

Run: `uv run pytest tests/api/test_memberships.py tests/api/test_jobs.py -v && uv run ruff check . && uv run mypy src tests`

```bash
git add src/recoll_modern/api src/recoll_modern/app.py tests/api
git commit -m "feat: expose membership and job APIs"
```

---

### Task 12: Expose scoped search and document retrieval

**Files:**
- Create: `src/recoll_modern/domain/search.py`, `src/recoll_modern/api/search.py`, `src/recoll_modern/api/documents.py`
- Modify: `src/recoll_modern/api/schemas.py`, `src/recoll_modern/app.py`
- Create: `tests/domain/test_search.py`, `tests/api/test_search.py`, `tests/api/test_documents.py`

**Interfaces:**
- Produces: `SearchService.search(SearchInput) -> SearchResult`
- Produces: `GET /search`, `GET /documents/{hash}/text`, `GET /documents/{hash}/file`

- [x] **Step 1: Write failing scope and projection tests**

```python
def test_search_requires_scope(client: TestClient) -> None:
    response = client.get("/search", params={"q": "python"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "scope_required"

def test_field_projection_and_text_limit(client: TestClient) -> None:
    response = client.get("/search", params=[
        ("q", "python"), ("collections", COLLECTION_ID), ("fields", "title"),
        ("fields", "text"), ("text_limit", "12"),
    ])
    hit = response.json()["hits"][0]
    assert set(hit) == {"document_id", "title", "text", "text_truncated"}
    assert len(hit["text"]) == 12 and hit["text_truncated"] is True
```

Add tests for unknown collections/fields, repeated collections, default fields, one ranked set, approximate total flag, 20/100 pagination, mount-safe links, missing documents, safe Content-Disposition, MIME type, and byte ranges (`206`, `Content-Range`, invalid range `416`).

- [x] **Step 2: Run tests and observe failure**

Run: `uv run pytest tests/domain/test_search.py tests/api/test_search.py tests/api/test_documents.py -v`

- [x] **Step 3: Implement search validation and projection**

Require nonblank `q`, at least one unique existing collection ID, `offset >= 0`, and `1 <= limit <= 100`. Allowed fields are exactly `title`, `author`, `path`, `mime_type`, `size`, `date`, `score`, `collections`, `snippets`, `text`, and `links`; always emit `document_id`. Default to all metadata, collections, and snippets. Set `fetch_text=True` only when requested, clamp `text_limit` to the configured maximum, slice by Unicode code points, and emit `text_truncated` only with text.

Resolve hit collection IDs from SQLite, not stale engine metadata. Build links with `request.url_for`, so configured/trusted scope supplies scheme, host, and prefix.

- [x] **Step 4: Implement full text and original streaming**

Look up the live canonical path by hash and return `document_not_found` for unknown hashes or `document_missing` when none remains. Text delegates to `Engine.extracted_text`. Original files use Starlette `FileResponse`, which handles byte ranges, after a final containment/open check. Sanitize the download filename to remove CR/LF/quotes and use RFC 5987 encoding; use `attachment` for HTML/SVG and `inline` only for an allowlist of safe document/media types.

- [x] **Step 5: Verify and commit**

Run: `uv run pytest tests/domain/test_search.py tests/api/test_search.py tests/api/test_documents.py -v && uv run ruff check . && uv run mypy src tests`

```bash
git add src/recoll_modern/domain/search.py src/recoll_modern/api src/recoll_modern/app.py tests
git commit -m "feat: add scoped search and retrieval"
```

---

### Task 13: Package Recoll and the service with Docker Compose

**Files:**
- Create: `Dockerfile`, `compose.yaml`, `.dockerignore`
- Create: `docker/recoll.conf`, `docker/fields`, `docker/entrypoint.sh`
- Create: `tests/integration/test_container_smoke.py`, `tests/integration/test_read_only_corpus.py`
- Modify: `README.md`, `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`

**Interfaces:**
- Produces: `docker compose up --build` service on configured host port and root path
- Consumes: `recoll-modern`, `recoll-membership`, persisted state and document volumes

- [ ] **Step 1: Write failing container smoke tests**

```python
def test_document_mount_is_read_only(compose_service: ComposeService) -> None:
    result = compose_service.exec(["sh", "-c", "touch /documents/must-fail"])
    assert result.returncode != 0

def test_recoll_binding_and_helper_are_present(compose_service: ComposeService) -> None:
    compose_service.exec(["python3", "-c", "from recoll import recoll"], check=True)
    compose_service.exec(["recoll-membership", "/documents/none"], check=True)
```

The fixture skips with `Docker Compose service is not running` when unavailable for normal host test runs; a dedicated `RECOLL_MODERN_REQUIRE_DOCKER=1` mode converts absence into failure for container CI.

- [ ] **Step 2: Add the multi-stage image and Compose deployment**

Base both stages on `debian:trixie-slim`; copy uv from `ghcr.io/astral-sh/uv:0.12.16`. Install
`build-essential` only in the helper build stage. Runtime installs `python3`, `python3-recoll`, `recoll`,
`poppler-utils`, `python3-lxml`, and `unzip`, covering the generated plain-text, HTML, PDF, and EPUB
corpus. Create `/opt/venv` with:

```dockerfile
RUN uv venv --python /usr/bin/python3 --system-site-packages /opt/venv
ENV VIRTUAL_ENV=/opt/venv UV_PROJECT_ENVIRONMENT=/opt/venv PATH="/opt/venv/bin:$PATH"
RUN uv sync --locked --no-dev
```

Before accepting the image, assert `python -c 'from recoll import recoll'` during build. Run as a fixed non-root UID/GID. The entrypoint creates only configured writable state/config directories, renders no secrets, and `exec`s `recoll-modern` so SIGTERM reaches Uvicorn.

Compose mounts `${RECOLL_MODERN_DOCUMENTS:?}:/documents:ro`, separate named volumes at `/var/lib/recoll-modern` and `/var/lib/recoll`, and seeds admin credentials through environment variables without defaults. Healthcheck calls `/health` at the configured prefix.

- [ ] **Step 3: Configure Recoll**

`recoll.conf` sets `topdirs = /documents`, a persistent `dbdir`, text storage, and:

```text
metadatacmds = ; collection = /usr/local/bin/recoll-membership %f
```

Define `collection` as a stored/queryable field in `fields`. The service passes `RECOLL_MODERN_MEMBERSHIP_MAP` to all `recollindex` subprocesses. Never initialize by deleting an existing index.

- [ ] **Step 4: Run image, integration, and read-only tests**

Run:

```bash
docker build -t recoll-modern:test .
docker compose config
docker compose up -d --build
RECOLL_MODERN_REQUIRE_DOCKER=1 uv run pytest tests/contract/test_recoll_engine.py tests/integration -v
docker compose down
```

Expected: image and configuration succeed; generated corpus indexes and searches on a read-only mount; shutdown preserves volumes. Do not pass `-v` to `docker compose down`.

- [ ] **Step 5: Document and commit**

Document first boot, subpath proxying, trusted proxies, volumes, admin seed rotation, backups, health, and explicit non-destructive reindex behavior. Record image/process boundaries in architecture and any packaging choices in decisions.

```bash
git add Dockerfile compose.yaml .dockerignore docker tests/integration README.md docs/ARCHITECTURE.md docs/DECISIONS.md
git commit -m "feat: package Recoll service"
```

---

### Task 14: Complete contract, recovery, security, and acceptance coverage

**Files:**
- Create: `tests/contract/test_http_contract.py`, `tests/integration/test_end_to_end.py`
- Create: `tests/security/test_paths.py`, `tests/security/test_proxy_headers.py`, `tests/security/test_downloads.py`
- Modify: implementation and focused tests only where the new acceptance test exposes a defect
- Modify: `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, `docs/TODO.md`, `docs/plans/001-search-engine-api.md`

**Interfaces:**
- Consumes: all prior tasks
- Produces: executable evidence for every spec acceptance criterion

- [ ] **Step 1: Add a requirement-to-test matrix**

At the top of `test_http_contract.py`, map `R1` through `R31` and `C1` through `C4` to named tests. Write missing tests before changing implementation. The end-to-end flow must: login under `/recoll`; create two collections; add explicit, snapshot, and persistent sources; exclude `.calibre`; index duplicate/same-name fixtures; search one and several collections; request projected fields and bounded text; fetch full text and a byte range; reconcile a moved/deleted canonical path; restart during a running job; and verify recovery.

- [ ] **Step 2: Prove each new test fails for its intended reason**

Run each new node individually, for example:

```bash
uv run pytest tests/integration/test_end_to_end.py::test_complete_collection_lifecycle -v
uv run pytest tests/security/test_proxy_headers.py::test_direct_client_cannot_forge_prefix -v
```

Expected: each new test fails on the missing/incorrect behavior, not fixture setup.

- [ ] **Step 3: Apply minimal fixes and rerun focused tests**

For every failure, change only the responsible module, rerun the single red test to green, then its containing test file. Append deferred discoveries to `docs/TODO.md`; do not leave source TODO comments.

- [ ] **Step 4: Run the complete verification matrix**

Run in this order:

```bash
uv sync --locked
uv run pytest
uv run ruff check .
uv run mypy src tests
uv build
docker build -t recoll-modern:test .
docker compose config
docker compose up -d --build
RECOLL_MODERN_REQUIRE_DOCKER=1 uv run pytest tests/contract/test_recoll_engine.py tests/integration -v
docker compose down
git diff --check
git status --short
```

Expected: every command exits 0; host suite reports explicit skips only for Recoll-dependent tests when the container is down; required-container suite has no such skips; Git status contains only the intended final documentation/checkbox changes before the commit.

- [ ] **Step 5: Complete docs and commit**

Check every acceptance box in the spec only when its named test passed in this session. Update the
architecture map/data flow, append decisions that an implementer actually made, remove completed TODO
entries, and check every plan box completed through this step. Then commit all intended implementation,
test, build, and documentation paths:

```bash
git add AGENTS.md README.md pyproject.toml uv.lock src tests helper docker Dockerfile compose.yaml .dockerignore docs
git commit -m "test: verify search engine API acceptance"
```

- [ ] **Step 6: Request review before integration**

Invoke `superpowers:requesting-code-review`, resolve findings with `superpowers:receiving-code-review`, rerun the complete verification matrix, then use `superpowers:finishing-a-development-branch`. Do not merge, push, or use GitHub tooling; this repository uses Gitea and integration is the maintainer's decision.
