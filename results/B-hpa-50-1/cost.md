# Cost model — 2026-11-19T17:11:06Z .. 2026-11-19T17:21:07Z

| Metric | Value |
|---|---|
| Duration | 10.02 min (0.1669 h) |
| Node price | $0.10175/h |
| **node_cost** (real EC2 bill for this node) | **$0.0170** |
| **allocated_cost** (reserved resources) | **$0.0084** |
| idle_cost (paid but not reserved) | $0.0086 |
| avg CPU share of node | 49.3% |
| avg RAM share of node | 7.7% |
| Requests total / successful | 159 / 159 |
| Error rate | 0.00% |
| p95 latency | 24727 ms |
| **cost per 1k successful requests** | **$0.0528** |
| CPU efficiency (usage/requests) | 1.04 |
| RAM efficiency (usage/requests) | 0.22 |
| Replicas avg / max | 2.46 / 3 |
| Pending pods avg / max | 0.00 / 0 |

## Notes

- `node_cost` is what AWS charges for the instance; it does **not** change when
  HPA adds pods, because the node is already paid for.
- `allocated_cost` answers "what would the reserved CPU/RAM cost if the node
  size followed the pods". The dominant resource (`max(cpu_share, mem_share)`)
  is used because a pod is limited by whichever resource runs out first.
- Other real bill items not modelled here: EBS volume, public IPv4, egress.
