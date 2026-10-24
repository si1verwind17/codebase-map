"""A route a class handles is one route per HTTP-verb method of the class (its repo bases' too); a class with an
invoke method keeps the route's method (structure._class_routes)."""
from vizcode import structure


def routes(s, f):
    names = {n["id"]: n["name"] for n in s["nodes"]}
    return sorted((r["method"], r["path"], names.get(r["handler"], r["handler"])) for r in s["facts"][f]["routes"])


def test_flask_resource_classes_and_method_views(make_repo):
    files = {"requirements.txt": "flask\nflask-restx\nflask-restful\n", "app/__init__.py": "",
             "app/api.py": "from flask_restx import Namespace, Resource\n\nns = Namespace('users')\n\n\n"
                           "class Base(Resource):\n    def delete(self, uid):\n        return 1\n\n\n"
                           "@ns.route('/users/<int:uid>')\nclass User(Base):\n    def get(self, uid):\n        return uid\n\n"
                           "    def patch(self, uid):\n        return uid\n\n    def _helper(self):\n        return 0\n",
             "app/rest.py": "from flask_restful import Api, Resource\n\napi = Api()\n\n\nclass Teams(Resource):\n"
                            "    def get(self):\n        return []\n\n    def post(self):\n        return 1\n\n\n"
                            "api.add_resource(Teams, '/teams')\n",
             "app/views.py": "from flask import Blueprint\nfrom flask.views import MethodView\n\nbp = Blueprint('v', __name__)\n\n\n"
                             "class Items(MethodView):\n    def get(self):\n        return []\n\n\n"
                             "bp.add_url_rule('/items', view_func=Items.as_view('items'))\n"}
    s = structure.build(make_repo(files))
    assert routes(s, "app/api.py") == [("DELETE", "/users/{uid}", "delete"), ("GET", "/users/{uid}", "get"),
                                       ("PATCH", "/users/{uid}", "patch")]
    assert routes(s, "app/rest.py") == [("GET", "/teams", "get"), ("POST", "/teams", "post")]
    assert routes(s, "app/views.py") == [("GET", "/items", "get")]


def test_django_class_and_function_views_and_a_laravel_invokable(make_repo):
    files = {"requirements.txt": "django\n", "shop/__init__.py": "",
             "shop/views.py": "from django.views import View\n\n\nclass OrderApi(View):\n    def get(self, request, pk):\n"
                              "        return pk\n\n    def put(self, request, pk):\n        return pk\n\n\ndef health(request):\n"
                              "    return 'ok'\n",
             "shop/urls.py": "from django.urls import path, include\nfrom shop import views\n\nurlpatterns = [\n"
                             "    path('orders/<int:pk>/', views.OrderApi.as_view(), name='order'),\n"
                             "    path('health/', views.health),\n    path('api/', include('shop.api.urls')),\n]\n",
             "composer.json": "{}\n",
             "app/Http/Controllers/UnblockUser.php": "<?php\nnamespace App\\Http\\Controllers;\nclass UnblockUser\n{\n"
                                                     "    public function __invoke() { return 1; }\n}\n",
             "routes/web.php": "<?php\nuse App\\Http\\Controllers\\UnblockUser;\n"
                               "Route::put('users/{u}/unblock', UnblockUser::class);\n"}
    s = structure.build(make_repo(files))
    assert routes(s, "shop/urls.py") == [("ANY", "/health", "health"), ("GET", "/orders/{pk}", "get"),
                                         ("PUT", "/orders/{pk}", "put")]
    assert routes(s, "routes/web.php") == [("PUT", "/users/{u}/unblock", "__invoke")]


def test_same_named_handler_classes_are_told_apart_by_the_files_imports(make_repo):
    """Two controllers of one name in two namespaces: the route file's `use` (and its alias) says which; a plain
    name the file renames away (`use Admin\\X as AdminX`) is the other one."""
    ctl = lambda ns, body: f"<?php\nnamespace App\\Http\\Controllers{ns};\nclass {body}\n"
    files = {"composer.json": "{}\n",
             "app/Http/Controllers/Admin/Posts.php": ctl("\\Admin", "Posts\n{\n    public function show() {}\n}"),
             "app/Http/Controllers/Blog/Posts.php": ctl("\\Blog", "Posts\n{\n    public function show() {}\n}"),
             "app/Http/Controllers/Unblock.php": ctl("", "Unblock\n{\n    public function __invoke() {}\n}"),
             "app/Http/Controllers/Settings/Unblock.php": ctl("\\Settings", "Unblock\n{\n    public function __invoke() {}\n}"),
             "routes/web.php": "<?php\nuse App\\Http\\Controllers\\Admin\\Posts as AdminPosts;\nuse App\\Http\\Controllers\\Blog\\Posts;\n"
                               "use App\\Http\\Controllers\\Unblock;\nuse App\\Http\\Controllers\\Settings\\Unblock as SettingsUnblock;\n"
                               "Route::get('posts/{p}', [Posts::class, 'show']);\nRoute::get('admin/posts/{p}', [AdminPosts::class, 'show']);\n"
                               "Route::put('unblock', Unblock::class);\nRoute::put('settings/unblock', SettingsUnblock::class);\n"}
    s = structure.build(make_repo(files))
    got = {r["path"]: r["handler"].split("::", 1)[-1] for r in s["facts"]["routes/web.php"]["routes"]}
    assert got == {"/posts/{p}": "App\\Http\\Controllers\\Blog.Posts#show/0",
                   "/admin/posts/{p}": "App\\Http\\Controllers\\Admin.Posts#show/0",
                   "/unblock": "App\\Http\\Controllers.Unblock#__invoke/0",
                   "/settings/unblock": "App\\Http\\Controllers\\Settings.Unblock#__invoke/0"}


def test_rails_namespaces_and_scopes_prefix_routes_and_name_controllers(make_repo):
    files = {"Gemfile": "gem 'rails'\n",
             "app/controllers/api/v1/gems_controller.rb": "module Api\n  module V1\n    class GemsController\n"
                                                          "      def index\n      end\n\n      def show\n      end\n"
                                                          "    end\n  end\nend\n",
             "app/controllers/gems_controller.rb": "class GemsController\n  def index\n  end\nend\n",
             "app/controllers/pages_controller.rb": "class PagesController\n  def about\n  end\nend\n",
             "config/routes.rb": "Rails.application.routes.draw do\n  namespace :api do\n    namespace :v1 do\n"
                                 "      resources :gems, only: %i[index show]\n    end\n  end\n  resources :gems, only: [:index]\n"
                                 "  scope '/info' do\n    get 'about', to: 'pages#about'\n  end\nend\n"}
    s = structure.build(make_repo(files))
    got = sorted((r["method"], r["path"], r["handler"].split("::", 1)[-1]) for r in s["facts"]["config/routes.rb"]["routes"])
    assert [(m, p) for m, p, _ in got] == [("GET", "/api/v1/gems"), ("GET", "/api/v1/gems/{id}"), ("GET", "/gems"),
                                           ("GET", "/info/about")]
    h = {p: h for _, p, h in got}
    assert "V1" in h["/api/v1/gems"] and "V1" not in h["/gems"] and h["/info/about"].endswith("PagesController#about/0")


def test_a_named_method_a_library_class_and_decorators_between_route_and_class(make_repo):
    """An explicit `methods=['GET']` keeps that verb only; a Laravel `::class` that is not invokable is no verb
    dispatch; a class view imported from a library binds no repo class of that name; a restx route reaches its
    class past any number of decorators, and a restx-looking decorator on a function is no route."""
    files = {"requirements.txt": "flask\nflask-restx\ndjango\n", "app/__init__.py": "",
             "app/views.py": "from flask import Blueprint\nfrom flask.views import MethodView\n\nbp = Blueprint('v', __name__)\n\n\n"
                             "class Items(MethodView):\n    def get(self):\n        return []\n\n    def post(self):\n"
                             "        return 1\n\n\nbp.add_url_rule('/items', view_func=Items.as_view('items'), methods=['GET'])\n",
             "app/api.py": "from flask import Flask\nfrom flask_restx import Namespace, Resource\n\napp = Flask(__name__)\n"
                           "ns = Namespace('users')\n\n\n@ns.route('/users/<int:uid>')\n@ns.param('uid', 'id')\n"
                           "@ns.response(404, 'x')\n@ns.doc(security='x')\nclass User(Resource):\n    def delete(self, uid):\n"
                           "        return 1\n\n\n@app.route('/plain', methods=['POST'])\ndef plain():\n    return 1\n",
             "shop/__init__.py": "",
             "shop/urls.py": "from django.urls import path\nfrom rest_framework_simplejwt.views import TokenObtainPairView\n\n"
                             "urlpatterns = [\n    path('token/', TokenObtainPairView.as_view()),\n]\n",
             "auth/__init__.py": "",
             "auth/views.py": "from django.views import View\n\n\nclass TokenObtainPairView(View):\n    def post(self, request):\n"
                              "        return 1\n",
             "composer.json": "{}\n",
             "app/Http/Controllers/PhotoController.php": "<?php\nnamespace App\\Http\\Controllers;\nclass PhotoController\n{\n"
                                                         "    public function get() {}\n    public function delete() {}\n}\n",
             "routes/web.php": "<?php\nuse App\\Http\\Controllers\\PhotoController;\nRoute::get('p3', PhotoController::class);\n"}
    s = structure.build(make_repo(files))
    assert routes(s, "app/views.py") == [("GET", "/items", "get")]
    assert routes(s, "app/api.py") == [("DELETE", "/users/{uid}", "delete"), ("POST", "/plain", "plain")]
    assert [r[2] for r in routes(s, "shop/urls.py")] == ["urls.py"]
    assert routes(s, "routes/web.php") == [("GET", "/p3", "PhotoController")]


def test_a_rails_namespace_block_ignores_end_in_strings_and_takes_parentheses(make_repo):
    files = {"Gemfile": "gem 'rails'\n",
             "app/controllers/api/calls_controller.rb": "module Api\n  class CallsController\n    def end\n    end\n"
                                                        "    def start\n    end\n  end\nend\n",
             "config/routes.rb": "Rails.application.routes.draw do\n  namespace :api do\n"
                                 "    post 'calls/end', to: 'calls#end'\n    post 'calls/start', to: 'calls#start'\n  end\n"
                                 "  namespace(:admin) do\n    get 'stats', to: 'stats#show'\n  end\nend\n"}
    s = structure.build(make_repo(files))
    assert [(m, p) for m, p, _ in routes(s, "config/routes.rb")] == [
        ("GET", "/admin/stats"), ("POST", "/api/calls/end"), ("POST", "/api/calls/start")]


def test_relatively_imported_views_and_restx_routes_across_lines_or_stacked(make_repo):
    files = {"requirements.txt": "django\nflask-restx\n", "shop/__init__.py": "",
             "shop/views.py": "from django.views import View\n\n\nclass Thing(View):\n    def get(self, request):\n"
                              "        return 1\n\n    def post(self, request):\n        return 2\n",
             "shop/urls.py": "from django.urls import path\nfrom .views import Thing\n\nurlpatterns = [path('t/', Thing.as_view())]\n",
             "app/__init__.py": "",
             "app/api.py": "from flask_restx import Namespace, Resource\n\nns = Namespace('x')\n\n\n"
                           "@ns.route(\n    '/b',\n)\n@ns.doc(params={\n    'a': 'b'})\nclass B(Resource):\n"
                           "    def post(self):\n        return 1\n\n\n@ns.route('/d')\n@ns.route('/d2')\nclass D(Resource):\n"
                           "    def delete(self):\n        return 1\n"}
    s = structure.build(make_repo(files))
    assert routes(s, "shop/urls.py") == [("GET", "/t", "get"), ("POST", "/t", "post")]
    assert routes(s, "app/api.py") == [("DELETE", "/d", "delete"), ("DELETE", "/d2", "delete"), ("POST", "/b", "post")]


def test_a_restx_class_with_only_inherited_verbs_keeps_its_routes(make_repo):
    files = {"requirements.txt": "flask-restx\n", "app/__init__.py": "",
             "app/base.py": "from flask_restx import Resource\n\n\nclass CrudBase(Resource):\n    def get(self):\n"
                            "        return 1\n\n    def delete(self):\n        return 1\n",
             "app/api.py": "from flask_restx import Namespace\nfrom app.base import CrudBase\n\nns = Namespace('x')\n\n\n"
                           "@ns.route('/k')\nclass K(CrudBase):\n    pass\n\n\ndef init(api):\n    @api.route('/nested')\n"
                           "    class A(CrudBase):\n        pass\n\n\nclass Other(CrudBase):\n    def post(self):\n        return 1\n\n\n"
                           "class Outer:\n    @ns.route('/inner')\n    class Inner(CrudBase):\n        def put(self):\n"
                           "            return 1\n",
             "app/views.py": "from flask import Blueprint\nfrom flask_restx import Namespace\n\nbp = Blueprint('b', __name__)\n\n\n"
                             "@bp.route('/token', methods=['GET', 'POST'])\ndef token():\n    return 1\n"}
    s = structure.build(make_repo(files))
    # a class nested in a function has no node: its route never takes the next top-level class's verbs
    assert routes(s, "app/api.py") == [("DELETE", "/inner", "delete"), ("DELETE", "/k", "delete"),
                                       ("GET", "/inner", "get"), ("GET", "/k", "get"), ("PUT", "/inner", "put")]
    # a Flask route on a function in a file that also imports restx: the restx match goes before dedupe
    assert routes(s, "app/views.py") == [("GET", "/token", "token"), ("POST", "/token", "token")]
