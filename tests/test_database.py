import os
import subprocess
import sys


def test_heroku_postgres_url_uses_installed_driver():
    env = {**os.environ, "DATABASE_URL": "postgres://u:p@localhost:5432/db"}
    code = "import database; print(database.engine.dialect.driver)"
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "psycopg2"
