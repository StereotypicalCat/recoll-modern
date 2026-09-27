"""FastAPI application factory and durable-service lifecycle."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI

from recoll_modern.api import auth, collections, files, health
from recoll_modern.api import documents as document_routes
from recoll_modern.api import jobs as job_routes
from recoll_modern.api import memberships as membership_routes
from recoll_modern.api import search as search_routes
from recoll_modern.api.errors import install_error_handlers
from recoll_modern.api.middleware import PrefixMiddleware
from recoll_modern.config import Settings
from recoll_modern.domain.auth import AuthService
from recoll_modern.domain.collections import CollectionService
from recoll_modern.domain.jobs import Job
from recoll_modern.domain.membership import MembershipService
from recoll_modern.domain.search import SearchService
from recoll_modern.engine.protocol import Engine
from recoll_modern.engine.recoll import RecollEngine
from recoll_modern.indexing.handlers import MembershipJobHandler
from recoll_modern.indexing.map_export import MembershipMapRows, export_membership_map
from recoll_modern.indexing.paths import PathPolicy
from recoll_modern.indexing.reconcile import reconcile_rule
from recoll_modern.indexing.worker import JobWorker
from recoll_modern.storage.auth import SQLiteAuthRepository
from recoll_modern.storage.collections import SQLiteCollectionRepository
from recoll_modern.storage.database import Database
from recoll_modern.storage.documents import DocumentRepository
from recoll_modern.storage.jobs import JobRepository
from recoll_modern.storage.membership import MembershipRepository


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    """Wire config, storage, indexing, and HTTP routes in one process boundary."""
    settings = settings or Settings.from_env()
    engine = engine or RecollEngine(settings.recoll_config_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings.state_root.mkdir(parents=True, exist_ok=True)
        database = Database(settings.database_path)
        database.migrate()
        auth_service = AuthService(
            SQLiteAuthRepository(database),
            lifetime=timedelta(hours=settings.session_lifetime_hours),
        )
        auth_service.seed_initial_admin(
            os.environ.get("RECOLL_MODERN_ADMIN_USERNAME"),
            os.environ.get("RECOLL_MODERN_ADMIN_PASSWORD"),
        )
        policy = PathPolicy(settings.document_root)
        memberships = MembershipRepository(database)
        documents = DocumentRepository(database)
        jobs = JobRepository(database)
        map_rows = MembershipMapRows(memberships, policy.root)
        export_membership_map(map_rows, settings.membership_map_path)
        membership_service = MembershipService(policy, documents, memberships)

        def reindex_changed(paths: tuple[str, ...]) -> None:
            export_membership_map(map_rows, settings.membership_map_path)
            if paths:
                engine.force_reindex(tuple(str(policy.root / path) for path in sorted(set(paths))))

        def current_rule_paths(rule_id: str) -> tuple[str, ...]:
            paths = []
            for content_hash in memberships.rule_documents(rule_id):
                record = documents.get(content_hash)
                if record is not None and record.canonical_path is not None:
                    paths.append(record.canonical_path)
            return tuple(paths)

        def cleanup(job: Job) -> None:
            export_membership_map(map_rows, settings.membership_map_path)
            paths = job.request.get("paths", [])
            if isinstance(paths, list):
                absolute = tuple(str(policy.root / path) for path in paths if isinstance(path, str))
                if absolute:
                    engine.force_reindex(absolute)

        def reconcile_all(_job: Job) -> None:
            changed: set[str] = set()
            for rule in memberships.list_rules():
                result = reconcile_rule(rule.id, policy, documents, memberships)
                changed.update(result.changed_paths)
            export_membership_map(map_rows, settings.membership_map_path)
            if changed:
                engine.force_reindex(tuple(str(policy.root / path) for path in sorted(changed)))

        def remove_membership(job: Job) -> None:
            collection_id = job.request.get("collection_id")
            content_hash = job.request.get("document_hash")
            if not isinstance(collection_id, str) or not isinstance(content_hash, str):
                raise ValueError("invalid membership removal job")
            changed = membership_service.plan_remove_document(collection_id, content_hash)
            reindex_changed(changed)

        def patch_rule(job: Job) -> None:
            rule_id = job.request.get("rule_id")
            exclusions = job.request.get("excluded_directories")
            if not isinstance(rule_id, str) or not isinstance(exclusions, list):
                raise ValueError("invalid rule patch job")
            if not all(isinstance(item, str) for item in exclusions):
                raise ValueError("invalid rule patch job")
            replay_paths = jobs.record_reindex_paths(job.id, current_rule_paths(rule_id))
            result = membership_service.plan_patch_rule(rule_id, tuple(exclusions))
            reindex_changed(tuple(set(replay_paths) | set(result.changed_paths)))

        def delete_rule(job: Job) -> None:
            rule_id = job.request.get("rule_id")
            if not isinstance(rule_id, str):
                raise ValueError("invalid rule deletion job")
            replay_paths = jobs.record_reindex_paths(job.id, current_rule_paths(rule_id))
            changed = membership_service.plan_delete_rule(rule_id)
            reindex_changed(tuple(set(replay_paths) | set(changed)))

        def reindex(job: Job) -> None:
            paths = job.request.get("paths", [])
            collections_requested = job.request.get("collections", [])
            if not isinstance(paths, list) or not isinstance(collections_requested, list):
                raise ValueError("invalid reindex job")
            rules = memberships.list_rules()
            prior_paths = tuple(
                path for rule in rules for path in current_rule_paths(rule.id)
            )
            replay_paths = jobs.record_reindex_paths(job.id, prior_paths)
            changed: set[str] = set()
            for rule in rules:
                changed.update(
                    reconcile_rule(rule.id, policy, documents, memberships).changed_paths
                )
            export_membership_map(map_rows, settings.membership_map_path)
            selected = {
                str(policy.root / path) for path in paths if isinstance(path, str)
            }
            selected.update(str(policy.root / path) for path in changed)
            selected.update(str(policy.root / path) for path in replay_paths)
            requested_ids = {item for item in collections_requested if isinstance(item, str)}
            for path, ids in memberships.membership_map_rows(policy.root):
                if requested_ids.intersection(ids):
                    selected.add(path)
            if not selected and not paths and not collections_requested:
                selected.add(str(policy.root))
            if selected:
                engine.force_reindex(tuple(sorted(selected)))

        membership_handler = MembershipJobHandler(
            policy, documents, memberships, jobs, settings.membership_map_path, engine
        )
        worker = JobWorker(jobs, {
            "membership_add": membership_handler.handle,
            "collection_cleanup": cleanup,
            "reconcile_rules": reconcile_all,
            "membership_remove": remove_membership,
            "rule_patch": patch_rule,
            "rule_delete": delete_rule,
            "reindex": reindex,
        })
        app.state.settings = settings
        app.state.database = database
        app.state.auth = auth_service
        app.state.engine = engine
        app.state.path_policy = policy
        collection_repository = SQLiteCollectionRepository(database)
        app.state.collections = CollectionService(collection_repository)
        app.state.collection_repository = collection_repository
        app.state.memberships = memberships
        app.state.documents = documents
        app.state.jobs = jobs
        app.state.worker = worker
        app.state.search = SearchService(
            engine, documents, memberships, policy, settings.inline_text_limit_max
        )
        if memberships.list_rules():
            jobs.enqueue("reconcile_rules", {"version": 1}, False)
        worker.start()
        try:
            yield
        finally:
            await worker.stop()

    app = FastAPI(root_path=settings.root_path, lifespan=lifespan)
    app.add_middleware(PrefixMiddleware, settings=settings)
    install_error_handlers(app)
    app.include_router(auth.router)
    app.include_router(health.router)
    app.include_router(files.router)
    app.include_router(collections.router)
    app.include_router(membership_routes.router)
    app.include_router(job_routes.router)
    app.include_router(search_routes.router)
    app.include_router(document_routes.router)
    return app
