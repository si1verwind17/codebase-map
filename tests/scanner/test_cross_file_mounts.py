"""A mount whose router comes from another file (`app.use('/users', users)`) joins its prefix onto that file's
routes, through the import that names it, chains composing outward (format.md § routes)."""
from vizcode import structure


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


def test_a_file_with_two_routers_and_a_default_import_is_left_alone(make_repo):
    files = {"package.json": '{"name": "api", "dependencies": {"express": "4"}}\n',
             "src/r.ts": "import { Router } from 'express'\nconst router = Router()\nconst app = Router()\n"
                         "router.get('/a', a)\napp.get('/b', b)\nfunction a() {}\nfunction b() {}\nexport default router\n",
             "src/main.ts": "import express from 'express'\nimport r from './r'\nconst app = express()\napp.use('/x', r)\n"}
    s = structure.build(make_repo(files))
    assert paths(s, "src/r.ts") == [("GET", "/a"), ("GET", "/b")]
