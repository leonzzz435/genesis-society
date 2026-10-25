import argparse
import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv

from .config import Laws, Settings
from .connectors import build_foundry_model
from .mock import MockResident
from .runtime import Coordinator
from .storage import Store
from .world import initialize


def _model_factory_for(store: Store, settings: Settings):
    if settings.provider == "mock":
        return lambda _: MockResident()
    if not settings.paid_inference_enabled:
        raise ValueError(
            "Live Azure Foundry inference requires SOCIETY_PAID_INFERENCE_ENABLED=true"
        )
    if not settings.azure_resource.strip():
        raise ValueError("Live Azure Foundry inference requires SOCIETY_AZURE_RESOURCE")
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider

    tp = get_bearer_token_provider(
        DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
    )

    def build_for_actor(actor: str):
        profile = store.snapshot()["residents"][actor].get("profile", "mock-v1")
        if profile == "mock-v1":
            return MockResident()
        return build_foundry_model(settings.azure_resource, profile, token_provider=tp)

    return build_for_actor


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="GENESIS Society")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-demo", help="Initialize two synthetic residents; refuses existing worlds")
    init_founders = sub.add_parser(
        "init-founders",
        help="Initialize founders using birth_weights and fast lifecycle laws",
    )
    init_founders.add_argument("--founders", type=int, default=12)
    weights_cmd = sub.add_parser(
        "set-weights",
        help="Update global birth_weights (e.g. gpt-5.6-sol=2 claude-sonnet-5-5=2 old-model=0)",
    )
    weights_cmd.add_argument("pairs", nargs="+")
    run = sub.add_parser("run", help="Run the world coordinator")
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
    elif args.command == "init-founders":
        s = initialize(
            store,
            Laws(
                founders=args.founders,
                population_cap=max(128, args.founders * 4),
                founder_window_seconds=0,
                lifespan_min_days=5,
                lifespan_max_days=14,
                founder_age_min_days=1,
                founder_age_max_days=3,
                reproduction_min_days=1,
                gestation_days=1,
            ),
            demo=False,
        )
        summary = {rid: r["profile"] for rid, r in s["residents"].items()}
        print(json.dumps(dict(world=s["name"], residents=summary, paused=True)))
    elif args.command == "set-weights":
        weights = {k: float(v) for pair in args.pairs for k, v in [pair.split("=", 1)]}
        Laws(birth_weights=weights)
        with store.transaction() as (_, state):
            state["laws"]["birth_weights"] = weights
        print(json.dumps(weights))
    elif args.command in ("pause", "resume"):
        with store.transaction() as (_, state):
            state["paused"] = args.command == "pause"
        print(args.command)
    elif args.command == "run":
        if args.seconds <= 0:
            parser.error("--seconds must be positive")
        factory = _model_factory_for(store, settings)
        coordinator = Coordinator(
            store, settings.database_url, factory, settings.concurrency, tracing=settings.tracing
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
                    profiles={
                        rid: r.get("profile", "mock-v1") for rid, r in state["residents"].items()
                    },
                    calls=len(store.requests_summary()),
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
