import subprocess
import sys
from pathlib import Path

from vizcode import secrets

SCRIPT = Path(__file__).resolve().parents[2] / "skills/visualizing-codebases/scripts/config.py"


def masked(text: str) -> list[str]:
    return [line for _, line in secrets.mask(text)]


def test_credential_keys_are_hidden_and_the_rest_stays_readable():
    yaml_text = ("server:\n  servlet:\n    context-path: /accounts\nspring:\n  data:\n    mongodb:\n"
                 "      host: account-mongodb\n      password: ${MONGODB_PASSWORD:s3cr3t}\n"
                 "rates:\n  url: https://api.exchangeratesapi.io\n  cron: 0 0 0 * * *\n"
                 "security:\n  oauth2:\n    client:\n      clientSecret: hunter2\n      accessTokenUri: http://auth/uaa\n")
    assert masked(yaml_text) == [
        "server:", "  servlet:", "    context-path: /accounts", "spring:", "  data:", "    mongodb:",
        "      host: account-mongodb", "      password: <hidden>", "rates:", "  url: https://api.exchangeratesapi.io",
        "  cron: 0 0 0 * * *", "security:", "  oauth2:", "    client:", "      clientSecret: <hidden>",
        "      accessTokenUri: http://auth/uaa"]


def test_each_format_and_values_that_carry_a_secret():
    assert masked("db.url=jdbc:postgresql://app:pw@db:5432/app\napi_key = abc\nPORT=8080\n") == [
        "db.url=jdbc:postgresql://<hidden>@db:5432/app", "api_key = <hidden>", "PORT=8080"]
    assert masked('{\n  "name": "web",\n  "token": "x",\n  "github": "ghp_abcdefghijklmnopqrstuvwxyz0123456789"\n}\n') == [
        "{", '  "name": "web",', '  "token": <hidden>,', '  "github": <hidden>', "}"]
    # compose environment, list and mapping forms; HOCON; a comment naming a credential
    assert masked("    environment:\n      - POSTGRES_PASSWORD=pw\n      - POSTGRES_DB=app\n"
                  "      REDIS_HOST: cache\n") == [
        "    environment:", "      - POSTGRES_PASSWORD=<hidden>", "      - POSTGRES_DB=app", "      REDIS_HOST: cache"]
    assert masked('db {\n  user = "app"\n  password = ${?DB_PASSWORD}\n}\n# old password: hunter2\n') == [
        "db {", '  user = "app"', "  password = <hidden>", "}", "# <hidden>"]


def test_multi_line_secrets_are_hidden_whole():
    text = ("tls:\n  key: |\n    -----BEGIN PRIVATE KEY-----\n    MIIEv\n    -----END PRIVATE KEY-----\n"
            "  port: 443\ncert: -----BEGIN CERTIFICATE-----\nabc\n-----END CERTIFICATE-----\nname: x\n")
    assert masked(text) == ["tls:", "  key: |", "    <hidden>", "    <hidden>", "    <hidden>", "  port: 443",
                            "cert: <hidden>", "<hidden>", "<hidden>", "name: x"]


def test_the_script_prints_numbered_lines_and_refuses_env_files(tmp_path):
    (tmp_path / "app.yml").write_text("a: 1\nsecret: x\n")
    (tmp_path / ".env").write_text("DB_PASSWORD=x\n")
    out = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path / "app.yml")], capture_output=True, text=True)
    assert out.returncode == 0 and out.stdout == f"== {tmp_path / 'app.yml'}\n1: a: 1\n2: secret: <hidden>\n"
    out = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path / ".env")], capture_output=True, text=True)
    assert out.returncode == 1 and "key names only" in out.stderr and "x" not in out.stdout


def test_a_dsn_keeps_its_host_and_database_and_the_script_reads_a_commit(tmp_path):
    assert masked("WAREHOUSE_DSN: postgresql://etl@warehouse/analytics\nDB_DSN: postgres://app:pw@db/app\n"
                  "ConnectionStrings__Main: Server=db;Database=shop;Password=x;\n") == [
        "WAREHOUSE_DSN: postgresql://etl@warehouse/analytics", "DB_DSN: postgres://<hidden>@db/app",
        "ConnectionStrings__Main: Server=db;Database=shop;Password=<hidden>;"]
    repo = tmp_path / "r"
    repo.mkdir()
    (repo / "compose.yml").write_text("services:\n  db:\n    environment:\n      POSTGRES_PASSWORD: s3cr3t\n")
    for c in (["init", "-q"], ["add", "."], ["-c", "user.email=x@x", "-c", "user.name=x", "commit", "-qm", "x"]):
        subprocess.run(["git", "-C", str(repo)] + c, check=True)
    (repo / "compose.yml").write_text("changed: 1\n")
    out = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(repo), "--commit", "HEAD", "compose.yml"],
                         capture_output=True, text=True)
    assert out.returncode == 0 and "s3cr3t" not in out.stdout and "4:       POSTGRES_PASSWORD: <hidden>" in out.stdout
