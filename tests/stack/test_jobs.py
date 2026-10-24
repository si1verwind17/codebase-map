"""Job systems from the packs' `jobs` group: where a job is defined, enqueued and scheduled, each enqueue paired in
summary.md with the definitions of its job (references/interactions.md § Queues in a store or a job system)."""
from vizcode import structure


def jobs(s, f):
    return sorted((j["side"], j["job"], j["pattern"]) for j in s["facts"][f].get("jobs", []))


def test_celery_sidekiq_laravel_and_hangfire(make_repo):
    files = {
        "app/__init__.py": "", "app/worker.py": "from celery import Celery\n\napp = Celery('app')\n",
        "app/tasks.py": "from app.worker import app\n\n\n@app.task(bind=True)\ndef send_receipt(self, order_id):\n"
                        "    return order_id\n",
        "app/orders.py": "from app import tasks\n\n\ndef place(order_id):\n    tasks.send_receipt.delay(order_id)\n",
        "app/beat.py": "SCHEDULE = {'nightly': {'task': 'app.tasks.send_receipt', 'schedule': 3600}}\n",
        "Gemfile": "gem 'rails'\n",
        "app/jobs/sync_job.rb": "class SyncJob < ApplicationJob\n  queue_as :default\n  def perform(id)\n  end\nend\n",
        "app/models/account.rb": "class Account\n  def sync\n    SyncJob.perform_later(id)\n    HardJob.perform_async(id)\n  end\nend\n",
        "app/workers/hard_job.rb": "class HardJob\n  include Sidekiq::Job\n\n  def perform(id)\n  end\nend\n",
        "composer.json": "{}\n",
        "src/Jobs/Notify.php": "<?php\nnamespace App\\Jobs;\nuse Illuminate\\Contracts\\Queue\\ShouldQueue;\n"
                               "class Notify implements ShouldQueue\n{\n    public function handle() {}\n}\n",
        "src/Http/Ctl.php": "<?php\nnamespace App\\Http;\nuse App\\Jobs\\Notify;\nclass Ctl\n{\n"
                            "    public function store() { Notify::dispatch(1); }\n}\n",
        "Svc/Svc.csproj": "<Project/>\n",
        "Svc/Tasks.cs": "using Hangfire;\nnamespace Svc;\npublic class Tasks\n{\n    public void Start()\n    {\n"
                        "        BackgroundJob.Enqueue(() => scanner.ScanLibraries(true));\n"
                        "        RecurringJob.AddOrUpdate(\"cleanup\", () => cleaner.Cleanup(), Cron.Daily);\n    }\n}\n",
        "Svc/Scanner.cs": "namespace Svc;\npublic class Scanner\n{\n    public void ScanLibraries(bool force) {}\n}\n"}
    s = structure.build(make_repo(files))
    assert jobs(s, "app/tasks.py") == [("define", "send_receipt", "celery-task")]
    assert jobs(s, "app/orders.py") == [("enqueue", "send_receipt", "celery-enqueue")]
    assert jobs(s, "app/beat.py") == [("schedule", "send_receipt", "celery-beat")]
    assert jobs(s, "app/jobs/sync_job.rb") == [("define", "SyncJob", "active-job")]
    assert jobs(s, "app/models/account.rb") == [("enqueue", "HardJob", "job-enqueue"), ("enqueue", "SyncJob", "job-enqueue")]
    assert jobs(s, "app/workers/hard_job.rb") == [("define", "HardJob", "sidekiq-job")]
    assert jobs(s, "src/Jobs/Notify.php") == [("define", "Notify", "laravel-job")]
    assert jobs(s, "src/Http/Ctl.php") == [("enqueue", "Notify", "laravel-dispatch")]
    assert jobs(s, "Svc/Tasks.cs") == [("enqueue", "ScanLibraries", "hangfire-enqueue"),
                                       ("schedule", "Cleanup", "hangfire-recurring")]
    md = structure.summary_md(s)
    assert "celery-enqueue `send_receipt` ← app::app.orders#place/1 (app/orders.py:5) → app::app.tasks#send_receipt/2" in md
    assert "hangfire-enqueue `ScanLibraries` ← " in md and "→ a method of that name: " in md
    assert "Job patterns:" in md


def test_no_job_from_look_alikes(make_repo):
    """Airflow's `@task`/`@dag.task`, a lazy-import map's `"task"` key, a timer's `.delay`, a Set's `.add` in a
    file importing bullmq, Symfony's event dispatcher: none is a job."""
    files = {"dags/__init__.py": "", "dags/etl.py": "from airflow.decorators import task\n\n\n@task\ndef extract():\n    return 1\n"
                                                    "\n\n@dag.task\ndef load():\n    return 2\n",
             "dags/lazy.py": "MAP = {'task': '.definitions.decorators', 'dag': '.definitions.dag'}\n",
             "ui/__init__.py": "", "ui/btn.py": "class B:\n    def go(self):\n        self.timer.delay(5)\n",
             "package.json": '{"name": "w"}\n',
             "src/a.ts": "import { Queue } from 'bullmq'\nconst tags = new Set()\ntags.add('urgent')\n",
             "composer.json": "{}\n",
             "src/Shop.php": "<?php\nclass Shop\n{\n    public function buy() { $this->dispatcher->dispatch(new OrderPlaced()); }\n}\n"}
    s = structure.build(make_repo(files))
    assert all(not ff.get("jobs") for ff in s["facts"].values())


def test_aliased_tasks_namespaced_jobs_mailers_and_controller_dispatch(make_repo):
    files = {
        "app/__init__.py": "", "app/worker.py": "from celery import Celery\n\napp = Celery('app')\n",
        "app/tasks.py": "from app.worker import app\n\n\n@app.task\ndef email_send(email_id):\n    return email_id\n",
        "app/services.py": "from app.tasks import email_send as email_send_task\n\n\n"
                           "def send_all(ids):\n    for i in ids:\n        email_send_task.delay(i)\n",
        "Gemfile": "gem 'rails'\n",
        "app/jobs/billing/add_job.rb": "class Billing::AddJob < Billing::BaseJob\n  def perform(id)\n  end\nend\n",
        "app/filters/filter.rb": "class Filter < GoodJob::JobsFilter\nend\nclass JobTest < ActiveJob::TestCase\nend\n",
        "app/models/user.rb": "class User\n  def signup\n    UserMailer.welcome(self).deliver_later\n"
                              "    Billing::AddJob.set(wait: 5).perform_later(id)\n  end\nend\n",
        "composer.json": "{}\n",
        "src/Http/Ctl.php": "<?php\nnamespace App\\Http;\nclass Ctl\n{\n"
                            "    public function store($r) { $this->dispatchSync(CreateReply::fromRequest($r)); }\n"
                            "    public function update() { $this->dispatch(new UpdateReply(1)); }\n}\n",
        "src/Jobs/UpdateReply.php": "<?php\nnamespace App\\Jobs;\nfinal class UpdateReply\n{\n    public function handle() {}\n}\n"}
    s = structure.build(make_repo(files))
    assert jobs(s, "app/services.py") == [("enqueue", "email_send", "celery-enqueue")]
    assert jobs(s, "app/jobs/billing/add_job.rb") == [("define", "AddJob", "active-job")]
    assert jobs(s, "app/filters/filter.rb") == []   # a namespace ending in `Job` is no job base
    assert jobs(s, "app/models/user.rb") == [("enqueue", "AddJob", "job-enqueue"),
                                             ("enqueue", "welcome", "mailer-deliver-later")]
    assert jobs(s, "src/Http/Ctl.php") == [("enqueue", "CreateReply", "laravel-dispatch-new"),
                                           ("enqueue", "UpdateReply", "laravel-dispatch-new")]
    assert "laravel-dispatch-new `UpdateReply` ← " in (md := structure.summary_md(s))
    assert "→ a class of that name: " in md.split("laravel-dispatch-new `UpdateReply`")[1].split("\n")[0]


def test_broker_messages_are_published_and_consumed_by_topic_and_paired(make_repo):
    """A Spring Kafka send and listener, a pika publish read through a constant, a Go amqp consume, a C# topic with
    a literal default, and a topic only a runtime value names (`$topic`, listed, never paired)."""
    files = {
        "pom.xml": "<project/>\n",
        "orders/src/main/java/a/Orders.java": "package a;\nimport org.springframework.kafka.core.KafkaTemplate;\n"
                                              "public class Orders {\n    private KafkaTemplate<String, String> kafkaTemplate;\n"
                                              "    public void place() { kafkaTemplate.send(\"order.created\", \"x\"); }\n}\n",
        "billing/src/main/java/b/Listener.java": "package b;\nimport org.springframework.kafka.annotation.KafkaListener;\n"
                                                 "public class Listener {\n    @KafkaListener(topics = \"order.created\")\n"
                                                 "    public void on(String m) {}\n}\n",
        "pay/requirements.txt": "pika\n", "pay/app/__init__.py": "",
        "pay/app/mq.py": "import pika\n\nROUTING_KEY = 'payments'\n\n\nclass P:\n    def send(self, ch, body):\n"
                         "        ch.basic_publish(exchange='', routing_key=ROUTING_KEY, body=body)\n",
        "go.mod": "module shop\n",
        "dispatch/main.go": "package main\n\nimport \"github.com/rabbitmq/amqp091-go\"\n\nfunc run(ch *amqp091.Channel, topic string) {\n"
                            "\tch.Consume(\"payments\", \"\", true, false, false, false, nil)\n\tch.Consume(topic, \"\", true, false, false, false, nil)\n}\n",
    }
    s = structure.build(make_repo(files))
    assert jobs(s, "orders/src/main/java/a/Orders.java") == [("publish", "order.created", "spring-kafka-send")]
    assert jobs(s, "billing/src/main/java/b/Listener.java") == [("consume", "order.created", "spring-kafka-listener")]
    assert jobs(s, "pay/app/mq.py") == [("publish", "payments", "pika-publish")]
    assert jobs(s, "dispatch/main.go") == [("consume", "$topic", "amqp091-consume"), ("consume", "payments", "amqp091-consume")]
    md = structure.summary_md(s)
    topics = sorted(l.split("`")[1] for l in md.split("\n") if l.startswith("- topic `"))
    assert topics == ["order.created", "payments"]
    assert "messages published" in md and "messages consumed" in md


def test_a_topic_name_comes_from_its_own_function_or_the_files_top(make_repo):
    files = {"requirements.txt": "confluent-kafka\n", "app/__init__.py": "",
             "app/k.py": "import confluent_kafka\n\nTOPIC = 'audit'\n\n\ndef orders(p, d):\n    topic = 'orders'\n"
                         "    p.produce(topic, d)\n\n\ndef payments(p, d):\n    topic = 'payments'\n    p.produce(topic, d)\n\n\n"
                         "def audit(p, d):\n    p.produce(TOPIC, d)\n\n\ndef given(p, topic, d):\n    p.produce(topic, d)\n\n\n"
                         "def name(user):\n    topic = user.get('name', 'anonymous')\n    return topic\n",
             "pom.xml": "<project/>\n",
             "src/main/java/a/Notify.java": "package a;\nimport org.springframework.scheduling.annotation.Scheduled;\n"
                                            "public class Notify {\n    @Override\n    @Scheduled(cron = \"0 0 * * *\")\n"
                                            "    public void send() {}\n}\n"}
    s = structure.build(make_repo(files))
    assert sorted(j[1] for j in jobs(s, "app/k.py")) == ["$topic", "audit", "orders", "payments"]
    nodes = [j.get("node") for j in s["facts"]["src/main/java/a/Notify.java"].get("jobs", [])]
    assert nodes and all(n.endswith("#send/0") for n in nodes), nodes


def test_a_topic_constant_of_a_class_and_no_java_method_local(make_repo):
    files = {"requirements.txt": "pika\n", "app/__init__.py": "",
             "app/mq.py": "import pika\n\n\nclass P:\n    ROUTING_KEY = 'orders'\n\n    def send(self, ch, b):\n"
                          "        ch.basic_publish(exchange='', routing_key=self.ROUTING_KEY, body=b)\n",
             "pom.xml": "<project/>\n",
             "src/main/java/a/P.java": "package a;\nimport org.springframework.kafka.core.KafkaTemplate;\npublic class P {\n"
                                       "    private KafkaTemplate<String, String> kafkaTemplate;\n"
                                       "    void b() {\n        final String topic = \"local-b\";\n"
                                       "        kafkaTemplate.send(topic, \"x\");\n    }\n"
                                       "    void c(String topic) { kafkaTemplate.send(topic, \"x\"); }\n}\n"}
    s = structure.build(make_repo(files))
    assert jobs(s, "app/mq.py") == [("publish", "orders", "pika-publish")]
    assert sorted(j[1] for j in jobs(s, "src/main/java/a/P.java")) == ["$topic", "local-b"]


def test_a_constant_cased_local_stays_local_and_a_one_line_body_keeps_its_binding(make_repo):
    files = {"requirements.txt": "confluent-kafka\n", "app/__init__.py": "",
             "app/k.py": "import confluent_kafka\n\n\ndef a(p):\n    TOPIC = 'local-a'\n    p.produce(TOPIC, 1)\n\n\n"
                         "def b(p, TOPIC):\n    p.produce(TOPIC, 1)\n\n\ndef c(p):\n    log(\n        topic='debug')\n"
                         "    p.produce(topic, 1)\n",
             "build.gradle.kts": "dependencies {}\n",
             "src/main/kotlin/a/P.kt": "package a\nimport org.springframework.kafka.core.KafkaTemplate\nclass P(val kafkaTemplate: "
                                       "KafkaTemplate<String, String>) {\n    fun a() { val topic = \"oneline\"; "
                                       "kafkaTemplate.send(topic, \"x\") }\n}\n"}
    s = structure.build(make_repo(files))
    assert sorted(j[1] for j in jobs(s, "app/k.py")) == ["$TOPIC", "$topic", "local-a"]
    assert [j[1] for j in jobs(s, "src/main/kotlin/a/P.kt")] == ["oneline"]


def test_a_class_head_or_a_control_statement_is_no_function_head():
    from vizcode.stack import FUNCTION_HEAD
    for head in ("open class P(val t: String) {", "data class P(val t: String) {", "abstract class P(x: Int) {",
                 "public record P(String t) {", "public class Orders(IBus bus) {", "if ready(x):", "while (go(x)) {",
                 "for (x in xs) {"):
        assert not FUNCTION_HEAD.match(head), head
    for head in ("def send(self):", "public void send(String t) {", "fun send(t: String): Unit {", "send(t) {"):
        assert FUNCTION_HEAD.match(head), head


def test_a_method_named_like_a_keyword_and_a_block_inside_a_function():
    from vizcode.stack import FUNCTION_HEAD, file_literals
    for head in ("public void record(Event e) {", "record(event) {", "object(x) {", "match(path) {", "catch(onRejected) {"):
        assert FUNCTION_HEAD.match(head), head
    # a block inside a method or a function holds the method's locals, not the file's
    assert file_literals('class A {\n    void m() {\n        if (x) {\n            String BASE = "/api/local";\n'
                         '        }\n    }\n}\n') == {}
    assert file_literals('def f(x):\n    with open(x):\n        TOPIC = "local"\n') == {}
    assert file_literals('if ready():\n    TOPIC = "orders"\n') == {"TOPIC": "orders"}


def test_a_class_extending_a_call_and_a_loop_over_a_keyword_named_value():
    from vizcode.stack import file_literals
    assert file_literals('export class Foo extends mixin(Base) {\n  static readonly TOPIC = "orders"\n}\n') == {
        "TOPIC": "orders"}
    assert file_literals('class Foo extends Bar(x) {\n  val TOPIC = "orders"\n}\n') == {"TOPIC": "orders"}
    assert file_literals('def f(mods):\n    for module in mods:\n        TOPIC = "l"\n') == {}


def test_more_class_modifiers_and_a_kotlin_fun_interface():
    from vizcode.stack import CLASS_HEAD, FUNCTION_HEAD
    for head in ("public readonly record struct P(int X) {", "declare class X {", "const enum E {", "expect class P {",
                 "public readonly struct P {"):
        assert CLASS_HEAD.match(head), head
    assert not FUNCTION_HEAD.match("fun interface Handler {") and FUNCTION_HEAD.match("fun interfaceFor(x) {")
