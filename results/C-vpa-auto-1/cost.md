# Cost model — 2026-11-19T18:13:04Z .. 2026-11-19T18:23:08Z

| Metric | Value |
|---|---|
| Duration | 10.07 min (0.1678 h) |
| Node price | $0.10175/h |
| **node_cost** (real EC2 bill for this node) | **$0.0171** |
| **allocated_cost** (reserved resources) | **$0.0067** |
| idle_cost (paid but not reserved) | $0.0103 |
| avg CPU share of node | 39.5% |
| avg RAM share of node | 6.2% |
| Requests total / successful | 157 / 157 |
| Error rate | 0.00% |
| p95 latency | 31235 ms |
| **cost per 1k successful requests** | **$0.0429** |
| CPU efficiency (usage/requests) | 1.30 |
| RAM efficiency (usage/requests) | 0.36 |
| Replicas avg / max | 1.98 / 2 |
| Pending pods avg / max | 0.00 / 0 |

## Notes

- `node_cost` is what AWS charges for the instance; it does **not** change when
  HPA adds pods, because the node is already paid for.
- `allocated_cost` answers "what would the reserved CPU/RAM cost if the node
  size followed the pods". The dominant resource (`max(cpu_share, mem_share)`)
  is used because a pod is limited by whichever resource runs out first.
- Other real bill items not modelled here: EBS volume, public IPv4, egress.
