# System Design Knowledge Base

Reference numbers, formulas, and patterns for senior-level distributed-systems
design. Capacity numbers MUST be DERIVED (show the arithmetic) — never asserted.

## Back-of-envelope constants
- Seconds per day ≈ 86,400 (~10^5). Per month ≈ 2.5 × 10^6.
- 1 KB ≈ 10^3 B, 1 MB ≈ 10^6 B, 1 GB ≈ 10^9 B, 1 TB ≈ 10^12 B, 1 PB ≈ 10^15 B.
- Read:write ratios are workload-specific — state your assumption (e.g., 100:1 for a
  social feed, 10:1 for e-commerce).
- Peak QPS is typically 2×–10× the average; state the peak factor you assume.

## Capacity formulas (always show the substitution)
- **Average QPS** = total requests per day ÷ 86,400.
  - e.g., 1 billion req/day ÷ 86,400 ≈ 11,574 QPS average; at 5× peak ≈ ~58k QPS.
- **Storage/day** = writes/day × bytes/write. **Storage/year** = storage/day × 365.
  - e.g., 10M writes/day × 1 KB = 10 GB/day ≈ 3.65 TB/year (before replication).
- **Replicated storage** = raw storage × replication factor (e.g., ×3).
- **Cache memory** = hot-set fraction × dataset size (often the 20% serving 80% of reads).
- **Bandwidth** = QPS × payload size. **Servers** = peak QPS ÷ per-server throughput.
- **Number of shards** = total storage ÷ per-shard capacity (and recheck against per-shard QPS).

## Latency / availability targets (state them)
- "Nines": 99.9% ≈ 8.7h/yr down, 99.99% ≈ 52min/yr, 99.999% ≈ 5min/yr.
- Typical p99 targets: < 100–300 ms for interactive APIs.

## Core building blocks
- **API Gateway / Load Balancer** for routing, TLS, rate limiting, auth.
- **Stateless services** behind the LB so they scale horizontally.
- **Database**: SQL (strong consistency, joins, transactions) vs NoSQL (horizontal
  scale, flexible schema, high write throughput). Justify the choice.
- **Sharding** for write/storage scale; **read replicas** for read scale (mind lag).
- **Cache (Redis)** in front of hot reads; define eviction (LRU/LFU) + invalidation.
- **Message queue (Kafka)** to decouple producers/consumers, smooth spikes, enable
  event-driven flows; reason about partitions, consumer groups, ordering, retention.
- **CDN** for static/media; **object store (S3)** for blobs, with metadata in DB.

## Canonical designs (key ideas)
- **URL shortener** -> base62 of an ID (counter/Snowflake) or hash; KV store; heavy
  read cache; redirect via 301/302. ~Read-heavy, tiny payloads.
- **News feed** -> fan-out on write (push) for most users, fan-out on read (pull) for
  celebrities; precompute timelines in cache.
- **Chat/messaging** -> WebSocket gateway, per-conversation partitioned store, fan-out
  via queue, delivery receipts; ordering per conversation.
- **Rate limiter** -> token/leaky bucket in Redis, sliding window counters; distributed
  with Lua scripts for atomicity.
- **Video streaming (Netflix/YouTube)** -> upload -> transcode pipeline (queue) ->
  store renditions in object store -> serve via CDN; metadata in DB.
- **Typeahead/search** -> Trie / inverted index, prefix sharding, heavy caching.

## Domain deep-dive playbooks
When the prompt matches one of these domains, the design MUST address every core
challenge below — a generic Redis/Kafka/DB/Load-Balancer diagram is an automatic reject.

### Social feed (Instagram / Facebook / Twitter / LinkedIn)
- **Feed Generation:** assemble a user's timeline from the people they follow; precompute
  vs. build on the fly. **Feed Ranking:** score by recency + affinity + engagement (ML
  ranker), not pure chronological order.
- **Fan-out on Write (push):** on post, append the post-id to each follower's timeline
  cache (e.g., Redis list) — fast reads, expensive for huge follower counts.
- **Fan-out on Read (pull):** build the timeline at read time by merging recent posts from
  followees — cheap writes, heavier reads.
- **Celebrity Handling:** millions of followers make write fan-out explode; do NOT fan-out
  celebrity posts — merge them at read time (HYBRID push/pull), cap fan-out, do it async via Kafka.
- **Media Storage:** blobs in an object store (S3) + metadata in the DB; never the blob in the RDBMS.
- **CDN Strategy:** serve images/video from an edge CDN; signed URLs; cache-control; origin shield.
- **Search Architecture:** inverted index (Elasticsearch) for users/hashtags; typeahead via a
  prefix index; async indexing pipeline.

### Messaging (WhatsApp / chat)
- **Presence Service:** online/last-seen via heartbeats + TTL keys in Redis; pub/sub fan-out of
  status to contacts.
- **Message Ordering:** per-conversation monotonic sequence numbers (or Lamport/Snowflake);
  ordering is guaranteed within a conversation, not globally.
- **End-to-End Encryption:** Signal protocol / double ratchet; the server stores ciphertext
  only; keys never leave devices.
- **Delivery Guarantees:** persist-then-ack; sent/delivered/read receipts; at-least-once with
  idempotent dedupe; offline queue until delivered.
- **Group Fan-out:** fan the message out to each member's inbox/queue; large groups handled
  async via Kafka; per-device delivery.
- **Media Pipeline:** upload to object store, transcode/thumbnail async, then send a link + key
  over the message channel (not the raw bytes).
- **Multi Device Sync:** per-device sessions/keys; a server-side sync log (or per-device queues)
  fans each message to every linked device; resolve ordering and reconcile read state across
  devices; companion devices link via the primary.

### E-commerce (Amazon / shop)
- **Inventory Consistency:** atomic stock decrement (row locks / conditional updates /
  time-boxed reservations); avoid oversell under concurrency; saga across services.
- **Checkout Flow:** cart -> reserve inventory -> payment (idempotency key) -> order created
  -> confirmation; handle payment failure/timeout; exactly-once order creation.
- **Recommendation System:** collaborative filtering / content-based; offline model + online
  feature store; "customers also bought"; served from a low-latency cache.

## Consistency & failure
- State CAP/PACELC stance: AP (e.g., Dynamo-style) vs CP (e.g., consensus) and why.
- Idempotency keys for retried writes; outbox pattern for reliable event publishing.
- Disaster recovery: multi-AZ first, multi-region for high availability; define RPO/RTO,
  backups, and failover. Avoid single points of failure.

## Required answer hygiene
- Numbers in Capacity Calculations must follow from Scale Estimation (show ÷ 86,400,
  × bytes/write, × 365, × replication). An average QPS that is orders of magnitude away
  from (requests/day ÷ 86,400) is WRONG.
- Server/fleet counts MUST be derived: servers = peak QPS ÷ per-server throughput — never an
  arbitrary round number. Costs MUST be derived: resource quantity × unit price (instance-hours
  × $/hr, GB-months × $/GB, egress GB × $/GB) — never an invented monthly/annual total.
- The architecture diagram MUST trace all seven tiers: Client → API Gateway → Services → Cache
  → Queue → Database → Storage.
- This is a DESIGN: short schema/API snippets only — never a full application code dump.
