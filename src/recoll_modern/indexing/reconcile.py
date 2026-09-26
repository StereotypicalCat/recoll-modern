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
    skipped = (*rule.excluded_directories, *(error.relative_path for error in report.errors))
    known_paths = tuple(
        path for path in documents.known_paths_under(rule.relative_path)
        if not any(path == prefix or path.startswith(prefix + "/") for prefix in skipped)
    )
    observed = documents.observe_files(list(report.files), reconcile_paths=known_paths)
    changed = memberships.replace_rule_members(
        rule_id, [file.content_hash for file in report.files]
    )
    canonical_changes = [
        document.canonical_path
        for document in observed.documents
        if document.canonical_path is not None
    ]
    return ReconcileResult(report, tuple(sorted(set(changed + canonical_changes))))
