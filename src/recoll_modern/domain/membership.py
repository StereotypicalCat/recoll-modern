"""Validate and apply collection membership sources."""

from dataclasses import dataclass

from recoll_modern.indexing.discovery import DiscoveryReport, Source, discover_sources
from recoll_modern.indexing.paths import PathPolicy
from recoll_modern.indexing.reconcile import reconcile_rule
from recoll_modern.storage.documents import DocumentRepository
from recoll_modern.storage.membership import MembershipRepository


@dataclass(frozen=True, slots=True)
class MembershipPlanResult:
    discovery: DiscoveryReport
    changed_paths: tuple[str, ...]


class MembershipService:
    def __init__(
        self,
        policy: PathPolicy,
        documents: DocumentRepository,
        memberships: MembershipRepository,
    ) -> None:
        self._policy = policy
        self._documents = documents
        self._memberships = memberships

    def plan_add(self, collection_id: str, sources: list[Source]) -> MembershipPlanResult:
        discovered = [(source, discover_sources(self._policy, [source])) for source in sources]
        return self.apply_discovered(collection_id, discovered)

    def apply_discovered(
        self,
        collection_id: str,
        discovered: list[tuple[Source, DiscoveryReport]],
    ) -> MembershipPlanResult:
        """Apply already scanned sources so strict jobs never rescan after validation."""
        for source, _ in discovered:
            if source.type == "directory":
                parent = self._policy.normalize(source.path)
                if any(
                    not self._policy.normalize(path).startswith(parent + "/")
                    for path in source.excluded_directories
                ):
                    raise ValueError("excluded directory must be a descendant")
        files = list({
            file.relative_path: file
            for _, report in discovered
            for file in report.files
        }.values())
        previous_canonical = {
            record.canonical_path
            for file in files
            if (record := self._documents.get(file.content_hash)) is not None
            and record.canonical_path is not None
        }
        observations = self._documents.observe_files(files)
        changed = {
            document.canonical_path
            for document in observations.documents
            if document.canonical_path is not None
        }
        changed.update(previous_canonical)
        for source, report in discovered:
            if source.type == "directory" and source.mode == "persistent":
                rule = self._memberships.ensure_rule(
                    collection_id,
                    self._policy.normalize(source.path),
                    tuple(self._policy.normalize(path) for path in source.excluded_directories),
                )
                failed_paths = tuple(error.relative_path for error in report.errors)
                prior_members = self._memberships.rule_documents(rule.id)
                protected_hashes = {
                    record.content_hash
                    for path in self._documents.known_paths_under(rule.relative_path)
                    if any(
                        path == failed or path.startswith(failed + "/")
                        for failed in failed_paths
                    )
                    if (record := self._documents.by_path(path)) is not None
                    and record.content_hash in prior_members
                }
                changed.update(self._memberships.replace_rule_members(
                    rule.id, [file.content_hash for file in report.files] + sorted(protected_hashes)
                ))
            else:
                for file in report.files:
                    self._memberships.add_direct(collection_id, file.content_hash)
                    record = self._documents.get(file.content_hash)
                    if record is not None and record.canonical_path is not None:
                        changed.add(record.canonical_path)
        return MembershipPlanResult(
            DiscoveryReport(
                tuple(files), tuple(error for _, report in discovered for error in report.errors)
            ),
            tuple(sorted(changed)),
        )

    def plan_remove_document(self, collection_id: str, content_hash: str) -> tuple[str, ...]:
        record = self._documents.get(content_hash)
        self._memberships.remove_document(collection_id, content_hash)
        return (record.canonical_path,) if record and record.canonical_path else ()

    def plan_patch_rule(
        self, rule_id: str, excluded_directories: tuple[str, ...]
    ) -> MembershipPlanResult:
        rule = self._memberships.get_rule(rule_id)
        if rule is None:
            raise ValueError("directory rule was not found")
        parent = rule.relative_path
        if any(
            not self._policy.normalize(path).startswith(parent + "/")
            for path in excluded_directories
        ):
            raise ValueError("excluded directory must be a descendant")
        self._memberships.patch_rule(rule_id, excluded_directories)
        result = reconcile_rule(rule_id, self._policy, self._documents, self._memberships)
        return MembershipPlanResult(result.discovery, result.changed_paths)

    def plan_delete_rule(self, rule_id: str) -> tuple[str, ...]:
        return tuple(self._memberships.delete_rule(rule_id))
