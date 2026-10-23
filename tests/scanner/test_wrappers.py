"""HTTP client wrappers: a function passing its own parameter to an HTTP client is a wrapper, and a call to it with a
path literal is a request (format.md § http clients), so a frontend's calls through its own API helper are found."""
from vizcode import structure


def clients(s, f):
    return [(c["method"], c["path"], c["in"].rsplit("::", 1)[-1]) for c in s["facts"][f].get("clients", [])
            if c.get("framework") != "tapir-client"]


def test_calls_through_a_layered_wrapper_object_are_requests(make_repo):
    files = {
        "package.json": '{"name": "web"}\n',
        "src/http.ts": "import axios from 'axios'\n\nexport const http = {\n"
                       "  get(url: string) { return this.request('get', url) },\n"
                       "  post(url: string, data: unknown) { return this.request('post', url, data) },\n"
                       "  request(method: string, url: string, data?: unknown) {\n"
                       "    return axios.request({ method, url: `/api/${url}`, data })\n  },\n}\n",
        "src/albums.ts": "import { http } from './http'\n\nconst cache = new Map<string, number>()\n\n"
                         "export const albumService = {\n"
                         "  fetch: (id: string) => http.get(`albums/${id}`),\n"
                         "  create: (name: string) => http.post('albums', { name }),\n"
                         "  cached: (k: string) => cache.get(k),\n}\n"}
    s = structure.build(make_repo(files))
    assert clients(s, "src/albums.ts") == [("GET", "/albums/{id}", "src/albums.ts#fetch/1"),
                                           ("POST", "/albums", "src/albums.ts#create/1")]
    assert clients(s, "src/http.ts") == []   # the wrapper's own calls are no requests


def test_a_free_function_wrapper_taking_an_options_object(make_repo):
    files = {
        "package.json": '{"name": "ui"}\n',
        "src/api.ts": "export async function apiFetch({ url, method }: { url: string; method?: string }) {\n"
                      "  return fetch(url, { method })\n}\n",
        "src/user.ts": "import { apiFetch } from './api'\n\nexport function login() {\n"
                       "  return apiFetch({\n    url: '/user/login',\n    method: 'POST',\n  })\n}\n"}
    s = structure.build(make_repo(files))
    assert clients(s, "src/user.ts") == [("POST", "/user/login", "src/user.ts#login/0")]


def test_a_direct_client_call_with_a_path(make_repo):
    files = {
        "build.gradle.kts": "\n",
        "src/main/kotlin/app/Api.kt": "package app\n\nimport io.ktor.client.HttpClient\nimport io.ktor.client.request.get\n\n"
                                      "class Api(private val client: HttpClient) {\n"
                                      "    suspend fun sessions() = client.get(\"sessions\")\n"
                                      "    suspend fun votes(year: Int) = client.get(\"$year/votes\")\n}\n"}
    s = structure.build(make_repo(files))
    assert clients(s, "src/main/kotlin/app/Api.kt") == [("GET", "/sessions", "app.Api#sessions/0"),
                                                         ("GET", "/{year}/votes", "app.Api#votes/1")]
