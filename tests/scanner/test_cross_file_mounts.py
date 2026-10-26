"""A mount whose router comes from another file (`app.use('/users', router)`) joins its prefix onto that file's
routes, through the import that names it, chains composing outward (format.md § routes)."""
from vizcode.scan import structure


def paths(s, f):
    return sorted((r["method"], r["path"]) for r in s["facts"][f]["routes"])


def test_express_routers_mounted_from_other_files(make_repo):
    files = {"package.json": '{"name": "api", "dependencies": {"express": "4"}}\n',
             "src/users.ts": "import { Router } from 'express'\nconst router = Router()\nrouter.get('/:id', show)\n"
                             "function show() {}\nexport default router\n",
             "src/admin.ts": "import { Router } from 'express'\nexport const router = Router()\n"
                             "router.post('/flush', flush)\nfunction flush() {}\n",
             "src/api.ts": "import { Router } from 'express'\nimport users from './users'\nimport { router as adminRouter } from './admin'\n"
                           "const router = Router()\nrouter.use('/users', users)\nrouter.use('/admin', adminRouter)\n"
                           "export default router\n",
             "src/app.ts": "import express from 'express'\nimport api from './api'\nconst app = express()\n"
                           "app.use('/api', api)\napp.get('/health', health)\nfunction health() {}\n"}
    s = structure.build(make_repo(files))
    assert paths(s, "src/users.ts") == [("GET", "/api/users/{id}")]
    assert paths(s, "src/admin.ts") == [("POST", "/api/admin/flush")]
    assert paths(s, "src/app.ts") == [("GET", "/health")]
    md = structure.summary_md(s)
    assert "/api → api (src/app.ts:4, composed onto 2 routes)" in md


def test_a_router_of_the_same_file_mounted_by_name(make_repo):
    # routes registered on `users`, then `app.use('/users', router)` below them: the prefix joins the same file's router
    files = {"package.json": '{"name": "api", "dependencies": {"express": "4"}}\n',
             "src/app.ts": "import express, { Router } from 'express'\nconst app = express()\nconst router = Router()\n"
                           "router.get('/:id', show)\napp.use('/users', router)\napp.get('/health', health)\n"
                           "function show() {}\nfunction health() {}\n"}
    s = structure.build(make_repo(files))
    assert paths(s, "src/app.ts") == [("GET", "/health"), ("GET", "/users/{id}")]
    assert "/users → router (src/app.ts:5, composed onto 1 route)" in structure.summary_md(s)


def test_a_file_with_two_routers_and_a_default_import_is_left_alone(make_repo):
    files = {"package.json": '{"name": "api", "dependencies": {"express": "4"}}\n',
             "src/r.ts": "import { Router } from 'express'\nconst router = Router()\nconst app = Router()\n"
                         "router.get('/a', a)\napp.get('/b', b)\nfunction a() {}\nfunction b() {}\nexport default router\n",
             "src/main.ts": "import express from 'express'\nimport r from './r'\nconst app = express()\napp.use('/x', r)\n"}
    s = structure.build(make_repo(files))
    assert paths(s, "src/r.ts") == [("GET", "/a"), ("GET", "/b")]


def test_django_includes_and_flask_blueprints(make_repo):
    files = {"requirements.txt": "django\nflask\n", "site/__init__.py": "", "site/api/__init__.py": "",
             "site/urls.py": "from django.urls import path, include\n\nurlpatterns = [path('api/', include('site.api.urls'))]\n",
             "site/api/urls.py": "from django.urls import path, include\nfrom site.api import views\n\n"
                                 "urlpatterns = [\n    path('ping/', views.ping),\n    path('users/', include(('site.api.users', 'users'))),\n]\n",
             "site/api/users.py": "from django.urls import path\nfrom site.api import views\n\nurlpatterns = [path('<int:pk>/', views.user)]\n",
             "site/api/views.py": "def ping(request):\n    return 1\n\n\ndef user(request, pk):\n    return pk\n",
             "web/__init__.py": "",
             "web/app.py": "from flask import Flask\nfrom web.auth import bp\n\napp = Flask(__name__)\n"
                           "app.register_blueprint(bp, url_prefix='/auth')\n",
             "web/auth.py": "from flask import Blueprint\n\nbp = Blueprint('auth', __name__)\n\n\n@bp.route('/login', methods=['POST'])\n"
                            "def login():\n    return 1\n",
             "web/admin.py": "from flask import Blueprint\n\nadmin = Blueprint('admin', __name__, url_prefix='/admin')\n\n\n"
                             "@admin.route('/stats')\ndef stats():\n    return 1\n"}
    s = structure.build(make_repo(files))
    assert paths(s, "site/api/urls.py") == [("ANY", "/api/ping")]
    assert paths(s, "site/api/users.py") == [("ANY", "/api/users/{pk}")]
    assert paths(s, "web/auth.py") == [("POST", "/auth/login")]
    assert paths(s, "web/admin.py") == [("GET", "/admin/stats")]


def test_a_register_prefix_replaces_the_blueprints_own(make_repo):
    files = {"requirements.txt": "flask\n", "web/__init__.py": "",
             "web/app.py": "from flask import Flask\nfrom web.admin import admin\n\napp = Flask(__name__)\n"
                           "app.register_blueprint(admin, url_prefix='/v2')\n",
             "web/admin.py": "from flask import Blueprint\n\nadmin = Blueprint('admin', __name__, url_prefix='/admin')\n\n\n"
                             "@admin.route('/stats')\ndef stats():\n    return 1\n"}
    s = structure.build(make_repo(files))
    assert [r["path"] for r in s["facts"]["web/admin.py"]["routes"]] == ["/v2/stats"]


def test_a_name_bound_twice_in_the_file_is_no_router_to_mount(make_repo):
    # two functions each make their own `router`: the mount in one does not reach the other's routes
    files = {"package.json": '{"name": "api", "dependencies": {"express": "4"}}\n',
             "src/app.ts": "import express, { Router } from 'express'\nconst app = express()\n"
                           "function admin() {\n  const router = Router()\n  router.get('/a', a)\n}\n"
                           "function setup() {\n  const router = Router()\n  router.get('/b', b)\n  app.use('/api', router)\n}\n"
                           "function a() {}\nfunction b() {}\n"}
    s = structure.build(make_repo(files))
    assert paths(s, "src/app.ts") == [("GET", "/a"), ("GET", "/b")]
