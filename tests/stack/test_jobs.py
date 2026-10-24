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
