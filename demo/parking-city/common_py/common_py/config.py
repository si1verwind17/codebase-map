import os


def env(key: str, default: str | None = None) -> str:
    """Read an environment variable (docker-compose.yml sets them all)."""
    value = os.environ.get(key, default)
    if value is None:
        raise RuntimeError(f"missing env var {key}")
    return value


def db_dsn() -> str:
    return (
        f"host={env('DB_HOST')} port={env('DB_PORT', '5432')} dbname={env('DB_NAME', 'parking')} "
        f"user={env('DB_USER')} password={env('DB_PASSWORD')}"
    )
