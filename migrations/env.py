from alembic import context

from genesis_society.config import Settings
from genesis_society.storage import Base, Store

config = context.config
url = config.attributes.get("database_url") or Settings().sqlalchemy_url
engine = Store(url).engine
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
engine.dispose()
