"""Routes a framework derives from file paths (Next.js, SvelteKit, Nuxt), for a project whose package.json names it."""
from vizcode import structure


def routes(s, f):
    return [(r["method"], r["path"], r["handler"].rsplit("::", 1)[-1], r["framework"]) for r in s["facts"][f]["routes"]]


def test_next_pages_api_and_app_route_handlers(make_repo):
    files = {"web/package.json": '{"name": "web", "dependencies": {"next": "14", "react": "18"}}\n',
             "web/pages/api/users/[id].ts": "export default async function handler(req, res) {\n  res.json({})\n}\n",
             "web/pages/api/index.ts": "export default function ping(req, res) {}\n",
             "web/pages/api/_helpers.ts": "export function util() {}\n",
             "web/pages/api/cart.ts": "const handler = async (req, res) => {\n  res.json([])\n}\nexport default withTrace(handler);\n",
             "web/pages/api/auth/[...nextauth].ts": "export default NextAuth(options)\n",
             "web/pages/api/hook.ts": "export default async (req, res) => {\n  res.end()\n}\n",
             "web/src/app/(shop)/orders/[...slug]/route.ts":
                 "export async function GET(req: Request) {\n  return Response.json([])\n}\n"
                 "export const POST = async (req: Request) => Response.json({})\n",
             "web/src/app/items/route.ts": "async function handle(req) {}\nexport { handle as PUT, handle as DELETE }\n",
             "web/src/app/items/page.tsx": "export default function Page() { return null }\n"}
    s = structure.build(make_repo(files))
    assert routes(s, "web/pages/api/users/[id].ts") == [("ANY", "/api/users/{id}", "pages/api/users/[id].ts#handler/2", "next-files")]
    assert [r[:2] for r in routes(s, "web/pages/api/index.ts")] == [("ANY", "/api")]
    assert s["facts"]["web/pages/api/_helpers.ts"]["routes"] == []
    assert routes(s, "web/pages/api/cart.ts") == [("ANY", "/api/cart", "pages/api/cart.ts#handler/2", "next-files")]
    assert [r[:2] for r in routes(s, "web/pages/api/hook.ts")] == [("ANY", "/api/hook")]
    assert [r[:2] for r in routes(s, "web/pages/api/auth/[...nextauth].ts")] == [("ANY", "/api/auth/{nextauth}")]
    assert [r[:2] for r in routes(s, "web/src/app/(shop)/orders/[...slug]/route.ts")] == [
        ("GET", "/orders/{slug}"), ("POST", "/orders/{slug}")]
    assert [r[:2] for r in routes(s, "web/src/app/items/route.ts")] == [("PUT", "/items"), ("DELETE", "/items")]
    assert s["facts"]["web/src/app/items/page.tsx"]["routes"] == []


def test_sveltekit_and_nuxt_server_routes_and_no_framework(make_repo):
    files = {"kit/package.json": '{"devDependencies": {"@sveltejs/kit": "2"}}\n',
             "kit/src/routes/api/cart/[id=int]/+server.ts": "export async function GET({ params }) {\n  return new Response()\n}\n",
             "nx/package.json": '{"dependencies": {"nuxt": "3"}}\n',
             "nx/server/api/notes/[id].get.ts": "export default defineEventHandler(async (event) => {\n  return {}\n})\n",
             "nx/server/api/[[...opt]].get.ts": "export default defineEventHandler(() => 1)\n",
             "nx/server/routes/health.ts": "export default defineEventHandler(() => 'ok')\n",
             "plain/package.json": '{"dependencies": {"express": "4"}}\n',
             "plain/pages/api/x.ts": "export default function handler() {}\n"}
    s = structure.build(make_repo(files))
    assert [r[:2] for r in routes(s, "kit/src/routes/api/cart/[id=int]/+server.ts")] == [("GET", "/api/cart/{id}")]
    assert [r[:2] for r in routes(s, "nx/server/api/notes/[id].get.ts")] == [("GET", "/api/notes/{id}")]
    assert [r[:2] for r in routes(s, "nx/server/routes/health.ts")] == [("ANY", "/health")]
    assert [r[:2] for r in routes(s, "nx/server/api/[[...opt]].get.ts")] == [("GET", "/api/{opt}")]
    assert s["facts"]["plain/pages/api/x.ts"]["routes"] == []
