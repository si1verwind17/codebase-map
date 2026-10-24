# Scenario 2: unknown framework in a new language (skill arm only)

Can the agent describe a framework no pack knows, in a language other than
Python and Scala, with SKILL.md alone? Go Fiber and Hono are in no pack;
pgx and ioredis are.

**Fixture:** two temp repos, each `git init` + one commit of the files below,
**without** a `stack.yaml`.

`catalog` (Go):

```text
go.mod      module example.com/catalog
            go 1.22
            require (github.com/gofiber/fiber/v2 v2.52.5; github.com/jackc/pgx/v5 v5.6.0)
Dockerfile  FROM golang:1.22 / COPY . /src / RUN cd /src && go build -o /app . / CMD ["/app"]
```

```go
// main.go
package main

import (
	"context"
	"os"

	"github.com/gofiber/fiber/v2"
	"github.com/jackc/pgx/v5/pgxpool"
)

type Handler struct{ db *pgxpool.Pool }

func (h *Handler) GetItem(c *fiber.Ctx) error {
	var name string
	row := h.db.QueryRow(context.Background(), "SELECT name FROM items WHERE id = $1", c.Params("id"))
	if err := row.Scan(&name); err != nil {
		return fiber.ErrNotFound
	}
	return c.JSON(fiber.Map{"name": name})
}

func (h *Handler) CreateItem(c *fiber.Ctx) error {
	_, err := h.db.Exec(context.Background(), "INSERT INTO items (name) VALUES ($1)", c.FormValue("name"))
	return err
}

func Health(c *fiber.Ctx) error { return c.SendString("ok") }

func main() {
	pool, _ := pgxpool.New(context.Background(), os.Getenv("DATABASE_URL"))
	h := &Handler{db: pool}
	app := fiber.New()
	api := app.Group("/api")
	api.Get("/items/:id", h.GetItem)
	api.Post("/items", h.CreateItem)
	app.Get("/health", Health)
	app.Listen(":8080")
}
```

`notes` (TypeScript; `package.json` with `"name": "notes"` and the
dependencies `hono` 4.6.3, `@hono/node-server` 1.13.1, `ioredis` 5.4.1; a
`Dockerfile` running `node dist/index.js`):

```ts
// src/index.ts
import { Hono, type Context } from "hono";
import { serve } from "@hono/node-server";
import Redis from "ioredis";

const redis = new Redis(process.env.REDIS_URL ?? "redis://localhost:6379");
const app = new Hono();
const notes = new Hono();

async function getNote(c: Context) {
  const body = await redis.get(`note:${c.req.param("id")}`);
  return body ? c.json(JSON.parse(body)) : c.notFound();
}

async function putNote(c: Context) {
  await redis.set(`note:${c.req.param("id")}`, JSON.stringify(await c.req.json()));
  return c.body(null, 204);
}

notes.get("/:id", getNote);
notes.put("/:id", putNote);
app.route("/notes", notes);
app.get("/health", (c) => c.text("ok"));

serve({ fetch: app.fetch, port: 3000 });
```

**Prompt:** the shared one in [`eval/README.md`](../README.md), once per repo, with the repo's path.

**Checks** (PASS/FAIL per repo):

1. **Stack resolved:** after the run, `summary.md` reads
   `## Stack — nothing unrecognised`.
2. **Routes found:** `structure.json` holds every route with its handler:
   catalog `GET /items/{id}` (`Handler#GetItem`), `POST /items`
   (`Handler#CreateItem`), `GET /health` (`Health`); notes `GET /{id}`
   (`getNote`), `PUT /{id}` (`putNote`), `GET /health` (`get_health`: an inline
   handler at the file's top is a method of the file named after the route). A sample `stack.yaml` gives exactly these (checked 2026-10-13).
3. **Mounts, not routes:** `summary.md` lists catalog's `/api` and notes'
   `/notes → notes` as mounts, and the map composes them: any relation or
   `problems` entry that names these routes writes `/api/items/{id}` and
   `/notes/{id}`.
4. **Sinks attached:** catalog's `items` reads and writes hang on `GetItem` and
   `CreateItem` (pgx, a pack library); notes' Redis read and write on `getNote`
   and `putNote` (ioredis).
5. **Honest groups:** no pattern matches a non-route line (`redis.get(` with a
   template string is not a route; every route path starts with `/`); `hono`
   and `github.com/gofiber/fiber` are in `imports` as `http-in`;
   `@hono/node-server` is in `ignore` or `imports`, never a route.
6. **Reported:** as Scenario 1's check 4, from `stack.yaml` and the transcript (the reply is only a path and counts).

A miss is a SKILL.md wording fix, not a test change.
