import argparse
import asyncio
import json
from pathlib import Path

from .config import Laws, Settings
from .mock import MockResident
from .runtime import Coordinator
from .storage import Store
from .world import initialize


def main():
    parser = argparse.ArgumentParser(description="GENESIS Society offline starter")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-demo", help="Initialize two synthetic residents; refuses existing worlds")
    run = sub.add_parser("run", help="Run the mock owner; no live provider exists in this starter")
    run.add_argument("--seconds", type=float, default=10)
    sub.add_parser("pause")
    sub.add_parser("resume")
    sub.add_parser("status")
    serve = sub.add_parser("inspect")
    serve.add_argument("--port", type=int, default=8787)
    sub.add_parser("migrate")
    args = parser.parse_args()
    settings = Settings()
    store = Store(settings.sqlalchemy_url)
    if args.command == "migrate":
        from alembic import command
        from alembic.config import Config

        config = Config(str(Path("alembic.ini")))
        config.attributes["database_url"] = settings.sqlalchemy_url
        command.upgrade(config, "head")
    elif args.command == "init-demo":
        s = initialize(store, Laws(founders=2, founder_window_seconds=0))
        print(json.dumps(dict(world=s["name"], residents=list(s["residents"]), paused=True)))
    elif args.command in ("pause", "resume"):
        with store.transaction() as (_, state):
            state["paused"] = args.command == "pause"
        print(args.command)
    elif args.command == "run":
        if args.seconds <= 0:
            parser.error("--seconds must be positive")
        coordinator = Coordinator(
            store, settings.database_url, lambda _: MockResident(), settings.concurrency
        )
        asyncio.run(coordinator.run(seconds=args.seconds))
        print(json.dumps(dict(peak=coordinator.peak, errors=coordinator.errors)))
    elif args.command == "status":
        from .inspector import worker_status

        state = store.snapshot()
        print(
            json.dumps(
                dict(
                    world=state["name"],
                    synthetic=state["synthetic"],
                    clock=state["clock"],
                    paused=state["paused"],
                    worker=worker_status(state),
                    residents=len(state["residents"]),
                    calls=len(store.requests()),
                    tickets_spent=state["spent"],
                )
            )
        )
    elif args.command == "inspect":
        import uvicorn

        from .inspector import app_for

        token = settings.creator_token.get_secret_value() if settings.creator_token else None
        uvicorn.run(app_for(store, token), host="127.0.0.1", port=args.port)
    store.engine.dispose()


if __name__ == "__main__":
    main()
