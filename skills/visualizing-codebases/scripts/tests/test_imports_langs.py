"""Imports per language: separator-aware prefixes, internal names, group roots, standard libraries, uses-code."""
import pytest

from vizcode import stack, structure
from vizcode.assemble import assemble


def unrec(s) -> set[tuple[str, str]]:
    return {(u["lang"], u["prefix"]) for u in s["stack"]["unrecognised"]}


def uses(s) -> set[tuple[str, str]]:
    return {(r["from"], r["to"]) for r in s["relations"] if r["kind"] == "uses-code"}


def test_prefix_match_per_separator():
    assert stack.prefix_match("a", "a.b") and not stack.prefix_match("a", "ab")       # python/scala unchanged
    assert stack.prefix_match("react", "react/jsx-runtime", "/") and stack.prefix_match("react", "react", "/")
    assert not stack.prefix_match("react", "react-dom", "/") and not stack.prefix_match("react", "react.x", "/")
    assert stack.prefix_match("node:", "node:fs", "/")                # a scheme prefix covers what follows it
    assert stack.prefix_match("tokio", "tokio::sync", "::") and not stack.prefix_match("tokio", "tokio_x", "::")
    assert stack.prefix_match("Illuminate", "Illuminate\\Support", "\\")


@pytest.mark.parametrize("lang,target,root", [
    ("python", "a.b.c", "a"),
    ("scala", "org.http4s.dsl", "org.http4s"),
    ("java", "org.springframework.web.bind", "org.springframework"),
    ("kotlin", "kotlinx.coroutines.flow", "kotlinx.coroutines"),
    ("csharp", "Microsoft.Extensions.Logging", "Microsoft.Extensions"),
    ("typescript", "@tanstack/react-query", "@tanstack/react-query"),
    ("typescript", "react-dom/client", "react-dom"),
    ("javascript", "express", "express"),
    ("go", "github.com/jackc/pgx/v5/pgxpool", "github.com/jackc/pgx"),
    ("go", "net/http", "net"),
    ("rust", "tokio::sync::mpsc", "tokio"),
    ("php", "Illuminate\\Support\\Facades\\Route", "Illuminate\\Support"),
    ("ruby", "rails/all", "rails"),
])
def test_group_roots_per_language(lang, target, root):
    assert stack._prefix(lang, target) == root


def test_packs_ignore_standard_libraries():
    st = stack.load(None)
    for lang, std, lib in [("java", "java.util", "org.slf4j"), ("java", "javax.inject", "jakarta.mail"),
                           ("java", "jakarta.inject", "jakarta.mail"),
                           ("kotlin", "kotlin.collections", "kotlinx.coroutines"), ("kotlin", "java.time", "arrow.core"),
                           ("csharp", "System.Linq", "Newtonsoft.Json"),
                           ("typescript", "node:fs", "react"), ("typescript", "path", "pathe"),
                           ("javascript", "child_process", "lodash"), ("rust", "std::collections", "serde"),
                           ("rust", "core::fmt", "anyhow"), ("ruby", "net/http", "nokogiri"),
                           ("ruby", "securerandom", "rack")]:
        assert stack.covered(st, lang, std), (lang, std)
        assert not stack.covered(st, lang, lib), (lang, lib)
    assert stack.LANGS[:2] == ("python", "scala") and {"go", "php", "tsx"} & set(stack.LANGS) == {"go", "php"}


def test_java_imports(make_repo):
    s = structure.build(make_repo({
        "pom.xml": "<project><modules><module>api</module><module>common</module></modules></project>",
        "api/pom.xml": "<project/>", "common/pom.xml": "<project/>",
        "common/src/main/java/com/acme/common/Db.java": "package com.acme.common;\npublic class Db {}\n",
        "api/src/main/java/com/acme/api/Api.java":
            "package com.acme.api;\nimport com.acme.common.Db;\nimport com.acme.api.util.*;\nimport java.util.List;\n"
            "import javax.inject.Inject;\nimport org.springframework.web.bind.annotation.GetMapping;\n"
            "import static org.springframework.http.HttpStatus.OK;\nimport static org.slf4j.LoggerFactory.getLogger;\n"
            "public class Api {}\n",
    }), "docs/viz-code")
    # Spring's wiring is the Java pack's to ignore; a library no pack covers is listed by its group
    assert unrec(s) == {("java", "org.slf4j")}
    assert uses(s) == {("mod:api", "mod:common")}


def test_kotlin_imports(make_repo):
    s = structure.build(make_repo({
        "settings.gradle.kts": 'include(":app", ":lib")\n',
        "lib/src/main/kotlin/com/acme/lib/Util.kt": "package com.acme.lib\n\nfun util() = 1\n",
        "app/src/main/kotlin/com/acme/app/Main.kt":
            "package com.acme.app\n\nimport com.acme.lib.util\nimport kotlin.collections.List\nimport java.time.Instant\n"
            "import kotlinx.coroutines.flow.Flow\nimport io.ktor.server.application.Application\n\nfun main() = util()\n",
    }), "docs/viz-code")
    assert unrec(s) == {("kotlin", "kotlinx.coroutines")}   # io.ktor.server: the Kotlin pack (http-in)
    assert uses(s) == {("mod:app", "mod:lib")}


def test_csharp_imports(make_repo):
    s = structure.build(make_repo({
        "Common/Common.csproj": "<Project/>", "Orders/Orders.csproj": "<Project/>",
        "Common/Db.cs": "namespace Acme.Common;\npublic class Db {}\n",
        "Orders/Api.cs": "using System;\nusing System.Linq;\nusing Acme.Common;\nusing Acme.Orders.Domain;\n"
                         "using Microsoft.Extensions.Logging;\nusing Npgsql;\nusing Serilog;\n\nnamespace Acme.Orders;\npublic class Api {}\n",
    }), "docs/viz-code")
    # Microsoft.Extensions (wiring) and Npgsql (sql-db) are the pack's; Serilog is not
    assert unrec(s) == {("csharp", "Serilog")}
    assert uses(s) == {("mod:Orders", "mod:Common")}


NPM = {
    "package.json": '{"private": true, "workspaces": ["packages/*"]}',
    "packages/shared/package.json": '{"name": "@acme/shared"}',
    "packages/shared/src/utils.ts": "export const u = 1;\n",
    "packages/web/package.json": '{"name": "@acme/web"}',
    "packages/web/tsconfig.json": '{\n  // aliases\n  "compilerOptions": {"paths": {"@/*": ["./src/*"], "~cfg": ["./src/cfg.ts"]}}\n}\n',
    "packages/web/src/app.tsx":
        'import React from "react";\nimport { useQuery } from "@tanstack/react-query";\nimport fs from "node:fs";\n'
        'import path from "path";\nimport { x } from "./local";\nimport { u } from "@acme/shared/src/utils";\n'
        'import { b } from "@/components/Button";\nimport cfg from "~cfg";\n'
        'import "./app.css";\nexport const App = () => null;\n',
    "packages/web/src/local.ts": "export const x = 1;\n",
    "packages/admin/package.json": '{"name": "admin"}',
    "packages/admin/src/main.ts": 'import { u } from "../../shared/src/utils";\nimport axios from "axios";\nimport dayjs from "dayjs";\n',
}


def test_typescript_imports(make_repo):
    s = structure.build(make_repo(NPM), "docs/viz-code")
    # axios is the pack's (http-out); dayjs is not
    assert unrec(s) == {("typescript", "react"), ("typescript", "@tanstack/react-query"), ("typescript", "dayjs")}
    # by workspace package name (web) and by a relative path into another workspace (admin)
    assert uses(s) == {("mod:packages/web", "mod:packages/shared"), ("mod:packages/admin", "mod:packages/shared")}


def test_javascript_imports(make_repo):
    s = structure.build(make_repo({
        "package.json": '{"workspaces": ["api", "lib"]}',
        "lib/package.json": '{"name": "acme-lib"}', "lib/index.js": "module.exports = {};\n",
        "api/package.json": '{"name": "api"}',
        "api/server.js": 'const express = require("express");\nconst fs = require("fs");\n'
                         'const lib = require("acme-lib");\nconst h = require("./handlers");\n'
                         'import("child_process");\n',
        "api/handlers/index.js": 'const { Pool } = require("pg");\nconst _ = require("lodash/fp");\n',
    }), "docs/viz-code")
    # express and pg are the pack's; lodash is not
    assert unrec(s) == {("javascript", "lodash")}
    assert uses(s) == {("mod:api", "mod:lib")}


def test_go_imports(make_repo):
    s = structure.build(make_repo({
        "common/go.mod": "module github.com/acme/shop/common\n\ngo 1.22\n",
        "common/db/db.go": "package db\n\nfunc Open() {}\n",
        "orders/go.mod": "// orders\nmodule github.com/acme/shop/orders\n",
        "orders/main.go": 'package main\n\nimport (\n\t"fmt"\n\t"net/http"\n\tpgx "github.com/jackc/pgx/v5/pgxpool"\n'
                          '\t"github.com/sirupsen/logrus"\n\t"github.com/acme/shop/common/db"\n\t"github.com/acme/shop/orders/internal/x"\n)\n\nfunc main() {}\n',
        "orders/internal/x/x.go": "package x\n",
    }), "docs/viz-code")
    # pgx is the pack's (sql-db); logrus is not
    assert unrec(s) == {("go", "github.com/sirupsen/logrus")}
    assert uses(s) == {("mod:orders", "mod:common")}


def test_rust_imports(make_repo):
    s = structure.build(make_repo({
        "Cargo.toml": '[workspace]\nmembers = ["api", "core"]\n',
        "core/Cargo.toml": '[package]\nname = "shop-core"\n',
        "core/src/lib.rs": "pub mod model;\n",
        "core/src/model.rs": "pub struct Order;\n",
        "api/Cargo.toml": '[package]\nname = "shop-api"\n',
        "api/src/main.rs": "mod handlers;\nuse std::collections::HashMap;\nuse core::fmt;\nuse serde::{Deserialize, Serialize};\n"
                           "use tokio::sync::mpsc;\nuse crate::handlers::x;\nuse handlers::y;\nuse shop_core::model::Order;\n"
                           "fn main() {}\n",
        "api/src/handlers.rs": "use super::*;\npub fn x() {}\npub fn y() {}\n",
    }), "docs/viz-code")
    assert unrec(s) == {("rust", "serde"), ("rust", "tokio")}
    assert uses(s) == {("mod:api", "mod:core")}


def test_ruby_imports(make_repo):
    s = structure.build(make_repo({
        "gems/core/Gemfile": "", "gems/core/lib/core.rb": "module Core; end\n",
        "gems/core/lib/core/order.rb": "module Core\n  class Order; end\nend\n",
        "gems/tools/Gemfile": "", "gems/tools/lib/tools.rb": "module Tools; end\n",
        "app/Gemfile": "",
        "app/main.rb": 'require "json"\nrequire "net/http"\nrequire "rails/all"\nrequire "sinatra"\nrequire "nokogiri"\n'
                       'require "core/order"\nrequire_relative "helpers"\nrequire_relative "../gems/tools/lib/tools"\n',
        "app/helpers.rb": "def help; end\n",
    }), "docs/viz-code")
    # rails and sinatra are the pack's (http-in); nokogiri is not
    assert unrec(s) == {("ruby", "nokogiri")}
    assert uses(s) == {("mod:app", "mod:gems/core"), ("mod:app", "mod:gems/tools")}


def test_php_imports(make_repo):
    s = structure.build(make_repo({
        "common/composer.json": "{}", "api/composer.json": "{}",
        "common/src/Db.php": "<?php\nnamespace Acme\\Common;\n\nclass Db {}\n",
        "api/src/Api.php": "<?php\nnamespace Acme\\Api;\n\nuse Acme\\Common\\Db;\nuse Acme\\Api\\Http\\Kernel;\n"
                           "use Illuminate\\Support\\Facades\\Route;\nuse Psr\\Log\\{LoggerInterface, NullLogger};\n\n"
                           "class Api {}\n",
    }), "docs/viz-code")
    # Illuminate is the pack's (the Route facade: http-in); Psr\\Log is not
    assert unrec(s) == {("php", "Psr\\Log")}
    assert uses(s) == {("mod:api", "mod:common")}


def _calls(repo, modules: list[str]) -> set[tuple[str, str, str]]:
    s = structure.build(repo, "docs/viz-code")
    meaning = {"nodes": [{"id": "svc:a", "kind": "service", "name": "a", "modules": modules,
                          "evidence": [{"file": next(iter(s["files"])), "line": 1}]}]}
    cmap = assemble(s, meaning)
    return {(r["from"].split("::", 1)[1], r["to"].split("::", 1)[1], r["confidence"])
            for r in cmap["relations"] if r["kind"] == "calls"}


def test_go_named_receiver_is_the_callers_own_object(make_repo):
    got = _calls(make_repo({
        "go.mod": "module shop\n",
        "repo.go": "package shop\n\ntype Repo struct{}\n\nfunc (r *Repo) Find() {}\n"
                   "func (r *Repo) Save() { r.Find() }\n\ntype Other struct{}\n\nfunc (o Other) Find() {}\n"
                   "func (o Other) Run() { o.Find() }\n",
    }), ["."])
    assert ("Repo#Save/0", "Repo#Find/0", "confirmed") in got
    assert ("Other#Run/0", "Other#Find/0", "confirmed") in got
    assert not any(c[0] == "Repo#Save/0" and "Other" in c[1] for c in got)


@pytest.mark.parametrize("files,cls", [
    ({"composer.json": "{}", "A.php": "<?php\nnamespace App;\nclass A {\n  function find() {}\n"
      "  function save() { $this->find(); }\n}\nclass B {\n  function find() {}\n}\n"}, "App.A"),
    ({"Cargo.toml": '[package]\nname = "a"\n', "lib.rs": "struct A;\nimpl A {\n  fn find(&self) {}\n"
      "  fn save(&self) { self.find() }\n}\nstruct B;\nimpl B {\n  fn find(&self) {}\n}\n"}, "lib.A"),
    ({"Gemfile": "", "a.rb": "class A\n  def find; end\n  def save\n    self.find\n  end\nend\n"
      "class B\n  def find; end\nend\n"}, "A"),
])
def test_php_rust_ruby_self_is_the_callers_own_object(make_repo, files, cls):
    got = _calls(make_repo(files), ["."])
    assert (f"{cls}#save/0", f"{cls}#find/0", "confirmed") in got, got
    assert not any(c[0] == f"{cls}#save/0" and c[1] != f"{cls}#find/0" for c in got), got


def test_ruby_scoped_class_name(make_repo):
    s = structure.build(make_repo({"app/Gemfile": "", "app/x.rb": "class Acme::Orders::Repo\n  def find; end\nend\n",
                                   "app/y.rb": "module Billing\n  class Api::Client; end\nend\n"}), "docs/viz-code")
    classes = {n["id"]: n["name"] for n in s["nodes"] if n["kind"] == "class"}
    assert classes == {"app::Acme.Orders.Repo": "Acme.Orders.Repo", "app::Billing.Api.Client": "Api.Client"}
    assert "app::Acme.Orders.Repo#find/0" in {n["id"] for n in s["nodes"]}
