# Cost model — 2026-11-19T18:39:23Z .. 2026-11-19T18:49:26Z

| Metric | Value |
|---|---|
| Duration | 10.05 min (0.1675 h) |
| Node price | $0.10175/h |
| **node_cost** (real EC2 bill for this node) | **$0.0170** |
| **allocated_cost** (reserved resources) | **$0.0034** |
| idle_cost (paid but not reserved) | $0.0137 |
| avg CPU share of node | 20.0% |
| avg RAM share of node | 3.1% |
| Requests total / successful | 159 / 159 |
| Error rate | 0.00% |
| p95 latency | 25007 ms |
| **cost per 1k successful requests** | **$0.0213** |
| CPU efficiency (usage/requests) | 2.60 |
| RAM efficiency (usage/requests) | 0.44 |
| Replicas avg / max | 1.00 / 1 |
| Pending pods avg / max | 0.00 / 0 |

## Notes

- `node_cost` is what AWS charges for the instance; it does **not** change when
  HPA adds pods, because the node is already paid for.
- `allocated_cost` answers "what would the reserved CPU/RAM cost if the node
  size followed the pods". The dominant resource (`max(cpu_share, mem_share)`)
  is used because a pod is limited by whichever resource runs out first.
- Other real bill items not modelled here: EBS volume, public IPv4, egress.
