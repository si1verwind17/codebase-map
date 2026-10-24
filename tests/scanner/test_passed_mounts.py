"""A mount handed to a function in another package (`users.Register(v1.Group("/users"))`): the routes that function
registers on its router parameter get the mount's full prefix."""
from vizcode import structure


def test_gin_groups_passed_to_register_functions(make_repo):
    files = {"go.mod": "module example.com/app\n\nrequire github.com/gin-gonic/gin v1.9.0\n",
             "main.go": "package main\n\nimport (\n\t\"github.com/gin-gonic/gin\"\n\t\"example.com/app/users\"\n"
                        "\t\"example.com/app/admin\"\n)\n\nfunc main() {\n\tr := gin.Default()\n\tv1 := r.Group(\"/api\")\n"
                        "\tusers.Register(v1.Group(\"/users\"))\n\tadmin.Register(v1.Group(\"/admin\"))\n}\n",
             "users/routes.go": "package users\n\nimport \"github.com/gin-gonic/gin\"\n\nfunc Register(router *gin.RouterGroup) {\n"
                                "\trouter.POST(\"/login\", Login)\n\trouter.GET(\"/:id\", Show)\n}\n\n"
                                "func Login(c *gin.Context) {}\n\nfunc Show(c *gin.Context) {}\n",
             "admin/routes.go": "package admin\n\nimport \"github.com/gin-gonic/gin\"\n\nfunc Register(g *gin.RouterGroup) {\n"
                                "\tg.DELETE(\"/cache\", Flush)\n}\n\nfunc Flush(c *gin.Context) {}\n"}
    s = structure.build(make_repo(files))
    paths = sorted((r["method"], r["path"]) for f in ("users/routes.go", "admin/routes.go") for r in s["facts"][f]["routes"])
    assert paths == [("DELETE", "/api/admin/cache"), ("GET", "/api/users/{id}"), ("POST", "/api/users/login")]
