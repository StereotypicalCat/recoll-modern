"""FastAPI application factory and durable-service lifecycle."""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import FastAPI

from recoll_modern.api import auth, collections, files, health
from recoll_modern.api.errors import install_error_handlers
from recoll_modern.api.middleware import PrefixMiddleware
from recoll_modern.config import Settings
from recoll_modern.domain.auth import AuthService
from recoll_modern.domain.collections import CollectionService
from recoll_modern.domain.jobs import Job
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

        membership_handler = MembershipJobHandler(
            policy, documents, memberships, jobs, settings.membership_map_path, engine
        )
        worker = JobWorker(jobs, {
            "membership_add": membership_handler.handle,
            "collection_cleanup": cleanup,
            "reconcile_rules": reconcile_all,
        })
        app.state.settings = settings
        app.state.database = database
        app.state.auth = auth_service
        app.state.engine = engine
        app.state.path_policy = policy
        app.state.collections = CollectionService(SQLiteCollectionRepository(database))
        app.state.memberships = memberships
        app.state.documents = documents
        app.state.jobs = jobs
        app.state.worker = worker
        if memberships.list_rules():
            jobs.enqueue("reconcile_rules", {}, False)
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
    return app
