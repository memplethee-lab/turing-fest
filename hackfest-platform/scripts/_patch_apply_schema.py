import io

path = "scripts/apply_schema.py"
s = io.open(path, encoding="utf-8").read()

old = """SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "schema.sql")


async def main() -> None:
    conn = await asyncpg.connect(os.environ["DATABASE_URL"])"""

new = """SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..", "db", "schema.sql")
DOTENV_PATH = os.path.join(os.path.dirname(__file__), "..", ".env")


def get_database_url() -> str:
    \"\"\"DATABASE_URL from the environment; falls back to the repo .env file
    so `python scripts/apply_schema.py` works straight after `cp .env.example
    .env`, without exporting anything.\"\"\"
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    try:
        with open(DOTENV_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("DATABASE_URL=") and not line.startswith("#"):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    raise SystemExit("DATABASE_URL is not set and no .env file was found")


async def main() -> None:
    conn = await asyncpg.connect(get_database_url())"""

assert old in s
s = s.replace(old, new, 1)
io.open(path, "w", encoding="utf-8", newline="\n").write(s)
print("patched", path)
