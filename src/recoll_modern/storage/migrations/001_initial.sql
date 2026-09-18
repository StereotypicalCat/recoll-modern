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
