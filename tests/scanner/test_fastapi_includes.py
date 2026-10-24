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
