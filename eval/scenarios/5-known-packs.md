# Scenario 5: packs that know the stack (skill arm only)

Do the built-in packs carry a Rails, a Laravel and a Spring service with no `stack.yaml` work, and does the agent
give a method serving several routes an example per key?

**Fixture:** three temp repos, each `git init` + one commit of the files below, **without** a `stack.yaml`.

`library` (Ruby): `Gemfile` with `source "https://rubygems.org"` and `gem "rails", "~> 7.1"`;
`config/application.rb` with `require "rails/all"` and `module Library; class Application < Rails::Application; end; end`;
`app/controllers/application_controller.rb` with `class ApplicationController < ActionController::API; end`;
`app/models/application_record.rb` with `class ApplicationRecord < ActiveRecord::Base; self.abstract_class = true; end`.

```ruby
# config/routes.rb
Rails.application.routes.draw do
  resources :books, only: [:index, :show, :create]
  resources :members, param: :member_no, except: [:new, :edit, :destroy]
  resource :session, only: %i[create destroy]
  get "/health", to: "health#show"
end
```

```ruby
# app/models/book.rb
class Book < ApplicationRecord
  self.table_name = "catalog_books"
end
```

```ruby
# app/controllers/books_controller.rb
class BooksController < ApplicationController
  def index
    render json: Book.all
  end

  def show
    render json: Book.find(params[:id])
  end

  def create
    render json: Book.create!(params.permit(:title, :isbn)), status: :created
  end
end
```

`app/controllers/members_controller.rb` (`index`, `show`, `create`, `update`, each `render json: {}`),
`app/controllers/sessions_controller.rb` (`create`, `destroy`, each `head :ok`) and
`app/controllers/health_controller.rb` (`show`, `render plain: "ok"`).

`shop` (PHP): `composer.json` `{"name": "demo/shop", "require": {"laravel/framework": "^11.0"}, "autoload":
{"psr-4": {"App\\": "app/"}}}`.

```php
<?php
// routes/api.php: no `use` of the Route facade (the global alias)

use App\Http\Controllers\ProductController;

Route::get('/products', [ProductController::class, 'index']);
Route::match(['put', 'patch'], '/products/{id}', [ProductController::class, 'update']);
Route::middleware('auth:sanctum')->prefix('admin')->group(function () {
    Route::delete('/products/{id}', [ProductController::class, 'destroy']);
});
```

```php
<?php
// app/Http/Controllers/ProductController.php

namespace App\Http\Controllers;

use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;

class ProductController
{
    public function index()
    {
        return DB::table('products')->get();
    }

    public function update(Request $request, string $id)
    {
        DB::table('products')->where('id', $id)->update($request->only(['name', 'price']));
        return DB::table('products')->find($id);
    }

    public function destroy(string $id)
    {
        DB::table('products')->where('id', $id)->delete();
        return response()->noContent();
    }
}
```

`orders` (Java): `pom.xml` with artifactId `orders` and the dependencies `spring-boot-starter-web`,
`spring-boot-starter-jdbc` and `spring-cloud-starter-openfeign`; a `Dockerfile` running the jar.

```java
// src/main/java/demo/orders/OrderController.java
package demo.orders;

import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/orders")
public class OrderController {
    private final JdbcTemplate jdbc;
    private final PaymentsClient payments;

    public OrderController(JdbcTemplate jdbc, PaymentsClient payments) {
        this.jdbc = jdbc;
        this.payments = payments;
    }

    @GetMapping("/{id}")
    public Map<String, Object> get(@PathVariable String id) {
        return jdbc.queryForMap("SELECT id, total FROM orders WHERE id = ?", id);
    }

    @PostMapping
    public Map<String, Object> place(@RequestBody Map<String, Object> order) {
        jdbc.update("INSERT INTO orders (id, total) VALUES (?, ?)", order.get("id"), order.get("total"));
        return payments.charge(Map.of("order_id", order.get("id"), "amount", order.get("total")));
    }
}
```

```java
// src/main/java/demo/orders/PaymentsClient.java
package demo.orders;

import java.util.Map;
import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;

@FeignClient(name = "payments", url = "${payments.url}")
public interface PaymentsClient {
    @PostMapping("/payments")
    Map<String, Object> charge(@RequestBody Map<String, Object> request);
}
```

**Prompt:** the shared one in [`eval/README.md`](../README.md), once per repo, with the repo's path.

**Checks** (PASS/FAIL per repo):

1. **Valid, stack known:** `validate.py` exits 0 and `summary.md` reads `## Stack — nothing unrecognised` with no
   `stack.yaml` written (the packs know these stacks).
2. **Routes found:** `structure.json` holds exactly these routes. library: `GET /books`, `GET /books/{id}`,
   `POST /books`, `GET /members`, `POST /members`, `GET /members/{member_no}`, `PATCH` and `PUT
   /members/{member_no}`, `POST /session`, `DELETE /session` and `GET /health` (11; each handled by its controller
   action, or by the routes file where the pack names none). shop: `GET /products` (`index`), `PUT` and
   `PATCH /products/{id}` (`update`), `DELETE /admin/products/{id}` (`destroy`; the scanner composes the `/admin`
   mount into the path), with `/admin` listed as a mount. orders: `GET /orders/{id}` (`get`), `POST /orders` (`place`), and no
   `/payments` route (the Feign interface is a client).
3. **Data attached:** library's `catalog_books` is defined on `Book`; shop's `products` reads and writes hang on
   the three controller methods; orders' `orders` read and write on `get` and `place`, and `place` has an outgoing
   HTTP relation (or a `problems` entry) for the payments service.
4. **An example per key:** `scripts/examples.py <repo>` reports `(0 without an example)` with no `missing some keys`
   for shop and orders; shop's `update` has two entries, `PUT` and `PATCH`, and the admin route's key reads
   `DELETE /admin/products/{id}`.
5. **Reported:** the reply's counts line agrees with the map.

A miss is a SKILL.md wording fix, not a test change.
