"""Refresh one persistent directory rule from the read-only document tree."""

from dataclasses import dataclass

from recoll_modern.indexing.discovery import DiscoveryReport, Source, discover_sources
from recoll_modern.indexing.paths import PathPolicy
from recoll_modern.storage.documents import DocumentRepository
from recoll_modern.storage.membership import MembershipRepository


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    discovery: DiscoveryReport
    changed_paths: tuple[str, ...]


def reconcile_rule(
    rule_id: str,
    policy: PathPolicy,
    documents: DocumentRepository,
    memberships: MembershipRepository,
) -> ReconcileResult:
    rule = memberships.get_rule(rule_id)
    if rule is None:
        raise ValueError("directory rule was not found")
    report = discover_sources(policy, [Source.directory(
        rule.relative_path,
        mode="persistent",
        excluded_directories=rule.excluded_directories,
    )])
    failed_paths = tuple(error.relative_path for error in report.errors)
    skipped = (*rule.excluded_directories, *failed_paths)
    existing_paths = documents.known_paths_under(rule.relative_path)
    known_paths = tuple(
        path for path in existing_paths
        if not any(path == prefix or path.startswith(prefix + "/") for prefix in skipped)
    )
    retired_paths = set(known_paths) - set(report.relative_paths)
    previous_hashes = memberships.rule_documents(rule_id)
    protected_hashes = {
        record.content_hash
        for path in existing_paths
        if any(path == failed or path.startswith(failed + "/") for failed in failed_paths)
        if (record := documents.by_path(path)) is not None
        and record.content_hash in previous_hashes
    }
    previous_canonical = {
        record.canonical_path
        for file in report.files
        if (record := documents.get(file.content_hash)) is not None
        and record.canonical_path is not None
    }
    observed = documents.observe_files(list(report.files), reconcile_paths=known_paths)
    changed = memberships.replace_rule_members(
        rule_id, [file.content_hash for file in report.files] + sorted(protected_hashes)
    )
    canonical_changes = [
        document.canonical_path
        for document in observed.documents
        if document.canonical_path is not None
    ]
    return ReconcileResult(
        report, tuple(sorted(set(changed + canonical_changes) | retired_paths | previous_canonical))
    )
