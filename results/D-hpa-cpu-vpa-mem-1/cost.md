# Cost model — 2026-11-19T18:26:15Z .. 2026-11-19T18:36:19Z

| Metric | Value |
|---|---|
| Duration | 10.07 min (0.1678 h) |
| Node price | $0.10175/h |
| **node_cost** (real EC2 bill for this node) | **$0.0171** |
| **allocated_cost** (reserved resources) | **$0.0086** |
| idle_cost (paid but not reserved) | $0.0085 |
| avg CPU share of node | 50.2% |
| avg RAM share of node | 7.9% |
| Requests total / successful | 160 / 160 |
| Error rate | 0.00% |
| p95 latency | 40989 ms |
| **cost per 1k successful requests** | **$0.0535** |
| CPU efficiency (usage/requests) | 1.02 |
| RAM efficiency (usage/requests) | 0.27 |
| Replicas avg / max | 2.51 / 3 |
| Pending pods avg / max | 0.00 / 0 |

## Notes

- `node_cost` is what AWS charges for the instance; it does **not** change when
  HPA adds pods, because the node is already paid for.
- `allocated_cost` answers "what would the reserved CPU/RAM cost if the node
  size followed the pods". The dominant resource (`max(cpu_share, mem_share)`)
  is used because a pod is limited by whichever resource runs out first.
- Other real bill items not modelled here: EBS volume, public IPv4, egress.
