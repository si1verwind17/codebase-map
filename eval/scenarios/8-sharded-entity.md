# Scenario 8: a message to a sharded entity (skill arm only)

Does the agent join a route that sends a message to a cluster-sharded entity with the method the entity hands
that message to? Name matching cannot: the send is `tell(new Wallet.Deposit(..))` and the handler is registered
by a method reference.

**Fixture:** `wallet` (Java), one temp repo, `git init` + one commit of the files below, **without** a
`stack.yaml`. `pom.xml` with artifactId `wallet` and the dependencies `spring-boot-starter-web`,
`spring-boot-starter-jdbc` and `com.typesafe.akka:akka-cluster-sharding-typed_2.13`; a `Dockerfile` running the jar.

```java
// src/main/java/demo/wallet/WalletController.java
package demo.wallet;

import akka.cluster.sharding.typed.javadsl.ClusterSharding;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/wallets")
public class WalletController {
    private final ClusterSharding sharding;

    public WalletController(ClusterSharding sharding) {
        this.sharding = sharding;
    }

    @PostMapping("/{id}/deposits")
    public void deposit(@PathVariable String id, @RequestBody long amount) {
        sharding.entityRefFor(Wallet.TYPE_KEY, id).tell(new Wallet.Deposit(amount));
    }
}
```

```java
// src/main/java/demo/wallet/ShardingConfig.java
package demo.wallet;

import akka.actor.typed.ActorSystem;
import akka.actor.typed.javadsl.Behaviors;
import akka.cluster.sharding.typed.javadsl.ClusterSharding;
import akka.cluster.sharding.typed.javadsl.Entity;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.jdbc.core.JdbcTemplate;

@Configuration
public class ShardingConfig {
    @Bean
    public ActorSystem<Void> actorSystem() {
        return ActorSystem.create(Behaviors.empty(), "wallet");
    }

    @Bean
    public ClusterSharding sharding(ActorSystem<Void> system, JdbcTemplate jdbc) {
        ClusterSharding sharding = ClusterSharding.get(system);
        sharding.init(Entity.of(Wallet.TYPE_KEY, ctx -> Wallet.create(ctx.getEntityId(), jdbc)));
        return sharding;
    }
}
```

```java
// src/main/java/demo/wallet/Wallet.java
package demo.wallet;

import akka.actor.typed.Behavior;
import akka.actor.typed.javadsl.AbstractBehavior;
import akka.actor.typed.javadsl.ActorContext;
import akka.actor.typed.javadsl.Behaviors;
import akka.actor.typed.javadsl.Receive;
import akka.cluster.sharding.typed.javadsl.EntityTypeKey;
import org.springframework.jdbc.core.JdbcTemplate;

public class Wallet extends AbstractBehavior<Wallet.Command> {
    public interface Command {}

    public record Deposit(long amount) implements Command {}

    public static final EntityTypeKey<Command> TYPE_KEY = EntityTypeKey.create(Command.class, "Wallet");

    private final String walletId;
    private final JdbcTemplate jdbc;

    public static Behavior<Command> create(String walletId, JdbcTemplate jdbc) {
        return Behaviors.setup(ctx -> new Wallet(ctx, walletId, jdbc));
    }

    private Wallet(ActorContext<Command> ctx, String walletId, JdbcTemplate jdbc) {
        super(ctx);
        this.walletId = walletId;
        this.jdbc = jdbc;
    }

    @Override
    public Receive<Command> createReceive() {
        return newReceiveBuilder().onMessage(Deposit.class, this::onDeposit).build();
    }

    private Behavior<Command> onDeposit(Deposit deposit) {
        jdbc.update("UPDATE wallets SET balance = balance + ? WHERE id = ?", deposit.amount(), walletId);
        return this;
    }
}
```

**Prompt:** the shared one in [`eval/README.md`](../README.md), with the repo's path.

**Checks** (PASS/FAIL):

1. **Valid, stack resolved:** `validate.py` exits 0 and `summary.md` reads `## Stack — nothing unrecognised` (the
   two `akka` lines sorted into `stack.yaml`).
2. **The message is a request:** a `request` from `WalletController#deposit` to `Wallet#onDeposit`, key
   `akka Wallet` (the framework and the entity type; `Akka Wallet` or the type key's `Wallet.TYPE_KEY` spelling
   pass), `confidence` `confirmed`, or `inferred` with a `why`.
3. **Cited three ways:** that request's `evidence` cites the send (`WalletController.java:17`), the registration
   (`ShardingConfig.java:21`) and the dispatch (`Wallet.java:33`).
4. **Trace:** following `calls` and runtime relations downstream from `deposit` reaches the `wallets` table (a
   `db-write` on `onDeposit`, citing `Wallet.java:37`).
5. **Not a service call:** no `request` or `ext-call` from `deposit` to another service or an `external`, and no
   `problems` entry calling the entity unresolved.
6. **Reported:** the reply's counts line agrees with the map.

A miss is a SKILL.md wording fix, not a test change.
