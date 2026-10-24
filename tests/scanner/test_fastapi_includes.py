"""include_router across files: the scanner joins each including router's prefixes onto the included router's
routes, so a FastAPI app's routes carry their full path (format.md § routes)."""
from vizcode import structure


def paths(s, f):
    return sorted((r["method"], r["path"]) for r in s["facts"][f]["routes"])


def test_prefixes_compose_through_imported_routers(make_repo):
    files = {
        "pyproject.toml": "[project]\nname = 'app'\n",
        "app/__init__.py": "", "app/api/__init__.py": "",
        "app/router.py": "from fastapi import APIRouter\n\n\nclass AppRouter(APIRouter):\n    pass\n",
        "app/api/items.py": "from app.router import AppRouter\n\nrouter = AppRouter(\n    tags=['items'],\n"
                            "    dependencies=[Depends(auth())],\n    prefix='/items',\n)\n\n\n"
                            "@router.get(\n    '/{item_id}',\n    responses={404: {}},\n)\ndef read(item_id: int):\n"
                            "    return item_id\n",
        "app/api/users.py": "from fastapi import APIRouter\n\nrouter = APIRouter()\n\n\n@router.post(path='/login')\n"
                            "def login():\n    return 1\n",
        "app/api/main.py": "from fastapi import APIRouter\nfrom app.api import items\nfrom .users import router as users\n\n"
                           "api_router = APIRouter(prefix='/api')\napi_router.include_router(items.router)\n"
                           "api_router.include_router(users, prefix='/users')\n",
        "app/main.py": "from fastapi import FastAPI\nfrom app.api.main import api_router\n\n\n"
                       "def init_views(app: FastAPI) -> None:\n    app.include_router(api_router, prefix='/v1')\n"}
    s = structure.build(make_repo(files))
    assert paths(s, "app/api/items.py") == [("GET", "/v1/api/items/{item_id}")]
    assert paths(s, "app/api/users.py") == [("POST", "/v1/api/users/login")]
    md = structure.summary_md(s)
    assert "include_router(api_router, prefix='/v1') on app (app/main.py:6, composed onto 2 routes)" in md


def test_an_include_naming_no_known_router_is_left_to_the_agent(make_repo):
    files = {"pyproject.toml": "[project]\nname = 'app'\n", "app/__init__.py": "",
             "app/main.py": "from fastapi import FastAPI\nfrom somewhere import router\n\napp = FastAPI()\n"
                            "app.include_router(router, prefix='/x')\n\n\n@app.get('/ping')\ndef ping():\n    return 1\n"}
    s = structure.build(make_repo(files))
    assert paths(s, "app/main.py") == [("GET", "/ping")]
    assert "not composed: compose it yourself" in structure.summary_md(s)


def test_a_stack_pattern_reading_a_fastapi_route_again_is_a_duplicate(make_repo):
    from conftest import with_stack
    files = {"pyproject.toml": "[project]\nname = 'app'\n", "app/__init__.py": "",
             "app/main.py": "from fastapi import FastAPI\n\napp = FastAPI()\n\n\n@app.get('/ping')\ndef ping():\n"
                            "    return 1\n"}
    repo = make_repo(files)
    with_stack(repo, "python:\n  routes:\n    - name: mine\n      when: fastapi\n      path: literal\n"
                     "      method: GET\n      regex: '@app\\.get\\(\\s*[\"''](?P<path>[^\"'']*)'\n")
    s = structure.build(repo, "docs/viz-code")
    assert [(r["path"], r["framework"]) for r in s["facts"]["app/main.py"]["routes"]] == [("/ping", "fastapi")]
    assert next(p for p in s["stack"]["patterns"] if p["name"] == "mine")["duplicates"] == "fastapi"


def test_a_fastapi_router_in_a_file_importing_flask_gives_one_route(make_repo):
    files = {"pyproject.toml": "[project]\nname = 'app'\n", "app/__init__.py": "",
             "app/api.py": "from flask import json\nfrom fastapi import APIRouter\n\nrouter = APIRouter(prefix='/x')\n\n\n"
                           "@router.get('/y')\ndef y():\n    return 1\n"}
    s = structure.build(make_repo(files))
    assert [(r["path"], r["framework"]) for r in s["facts"]["app/api.py"]["routes"]] == [("/x/y", "fastapi")]


def test_a_bracket_in_a_string_argument_does_not_hide_the_prefix():
    from vizcode import routes
    src = "router = APIRouter(tags=['a(b'], prefix='/v1')\nother = APIRouter(prefix='/v2')\n"
    assert routes.fastapi_prefixes(src) == {"router": "/v1", "other": "/v2"}
