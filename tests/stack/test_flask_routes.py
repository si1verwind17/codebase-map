"""Flask routes from the built-in pack: `route` with `methods`, the Flask 2 verb decorators and `add_url_rule`."""
from vizcode import structure


def test_flask_decorators_and_url_rules(make_repo):
    files = {"requirements.txt": "flask\n", "app/__init__.py": "",
             "app/views.py": "from flask import Blueprint\n\nbp = Blueprint('v', __name__)\n\n\n@bp.route('/health')\n"
                             "def health():\n    return 'ok'\n\n\n@bp.route('/users/<int:uid>', methods=['GET', 'DELETE'])\n"
                             "def user(uid):\n    return uid\n\n\n@bp.post('/login')\ndef login():\n    return 1\n\n\n"
                             "class Items:\n    @classmethod\n    def as_view(cls, name):\n        return cls\n\n\n"
                             "def ping():\n    return 1\n\n\n"
                             "bp.add_url_rule('/ping', view_func=ping, methods=['POST'])\n"
                             "bp.add_url_rule('/pong', methods=['PUT'], strict_slashes=False, view_func=ping)\n"
                             "bp.add_url_rule('/items', 'items', Items.as_view('items'))\n"}
    s = structure.build(make_repo(files))
    names = {n["id"]: n["name"] for n in s["nodes"]}
    got = sorted((r["method"], r["path"], names.get(r["handler"], r["handler"])) for r in s["facts"]["app/views.py"]["routes"])
    assert got == [("DELETE", "/users/{uid}", "user"), ("GET", "/health", "health"), ("GET", "/items", "views.py"),   # a class view: the agent names its method
                   ("GET", "/users/{uid}", "user"), ("POST", "/login", "login"), ("POST", "/ping", "ping"),
                   ("PUT", "/pong", "ping")]
