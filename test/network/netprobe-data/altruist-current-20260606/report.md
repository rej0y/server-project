# Internet Stability Report

- Host: `altruist`
- Measurement window: `2026-06-04T20:34:41.704000+00:00` to `2026-06-06T18:24:00.453000+00:00`
- Monitoring duration: 1.91d
- Report generated: `2026-06-06T18:24:03.961Z`
- All-target Internet outages: 624 totaling 25.0m
- Longest all-target outage: 17.9s
- Monitoring-process gaps: 1
- Public IP changes observed: 0
- Default route changes observed: 2
- Wi-Fi signal average/minimum: -56.12 / -61.00 dBm
- Local interface RX/TX errors: 0 / 0
- Local interface RX/TX drops: 0 / 0
- Collector task errors: 0

## Technician Summary

- Grouped incidents: 138 using a 120-second merge window.
- Worst grouped incident: 3.6m outage time across 96 outages.
- Local gateway packet loss/p95/p99: 2.0855% / 31.90 ms / 335.00 ms.
- Wi-Fi signal average/minimum during report: -56.12 / -61.00 dBm.
- If local gateway loss is nonzero while Wi-Fi signal is acceptable, check the router/AP, Wi-Fi channel/interference, modem/ONT handoff, and upstream error counters.

## Worst Grouped Incidents

| Local Start | Local End | Elapsed | Outage Time | Outages | Primary | Local/Gateway | Upstream |
|---|---|---:|---:|---:|---|---:|---:|
| 2026-06-05 00:42:43 MDT | 2026-06-05 01:12:59 MDT | 30.3m | 3.6m | 96 | local/gateway | 88 | 8 |
| 2026-06-05 08:51:45 MDT | 2026-06-05 09:01:39 MDT | 9.9m | 1.5m | 25 | local/gateway | 25 | 0 |
| 2026-06-04 21:39:59 MDT | 2026-06-04 21:44:09 MDT | 4.2m | 1.4m | 22 | local/gateway | 16 | 6 |
| 2026-06-05 01:19:21 MDT | 2026-06-05 01:30:45 MDT | 11.4m | 1.2m | 32 | local/gateway | 26 | 6 |
| 2026-06-04 21:05:25 MDT | 2026-06-04 21:10:29 MDT | 5.1m | 60.0s | 19 | local/gateway | 16 | 3 |
| 2026-06-05 08:25:01 MDT | 2026-06-05 08:38:21 MDT | 13.3m | 54.1s | 27 | local/gateway | 27 | 0 |
| 2026-06-04 15:51:14 MDT | 2026-06-04 15:57:44 MDT | 6.5m | 48.1s | 20 | local/gateway | 17 | 3 |
| 2026-06-04 14:39:10 MDT | 2026-06-04 14:47:48 MDT | 8.6m | 42.0s | 21 | local/gateway | 17 | 4 |
| 2026-06-05 07:35:15 MDT | 2026-06-05 07:40:35 MDT | 5.3m | 40.1s | 17 | local/gateway | 17 | 0 |
| 2026-06-04 15:15:28 MDT | 2026-06-04 15:20:16 MDT | 4.8m | 38.1s | 15 | local/gateway | 14 | 1 |

## Worst Packet-Loss Hours

| Local Hour | Target | Samples | Loss % |
|---|---|---:|---:|
| 2026-06-05 01:00:00 MDT | vps | 1800 | 12.6111 |
| 2026-06-05 01:00:00 MDT | cloudflare | 1800 | 12.3333 |
| 2026-06-05 01:00:00 MDT | quad9 | 1800 | 12.2778 |
| 2026-06-05 00:00:00 MDT | local-gateway | 1800 | 11.4444 |
| 2026-06-05 01:00:00 MDT | local-gateway | 1800 | 11.3889 |
| 2026-06-05 00:00:00 MDT | vps | 1800 | 11.1111 |
| 2026-06-05 01:00:00 MDT | google | 1800 | 11.0556 |
| 2026-06-05 00:00:00 MDT | quad9 | 1800 | 10.8333 |
| 2026-06-04 21:00:00 MDT | quad9 | 1800 | 10.6667 |
| 2026-06-05 00:00:00 MDT | google | 1800 | 10.3333 |

## Ping Summary

| Target | Scope | Samples | Loss % | Average ms | p95 ms | p99 ms | Max ms | Idle p95 | Loaded p95 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| local-gateway | gateway | 78830 | 2.0855 | 13.22 | 31.90 | 335.00 | 1000.00 | 31.80 | 448.85 |
| vps | internet | 79103 | 2.4942 | 51.49 | 86.10 | 396.71 | 998.00 | 85.95 | 449.90 |
| cloudflare | internet | 79103 | 2.5334 | 26.42 | 60.30 | 408.00 | 999.00 | 60.10 | 461.15 |
| google | internet | 79103 | 1.9923 | 30.15 | 60.77 | 429.00 | 992.00 | 60.50 | 538.05 |
| quad9 | internet | 79103 | 2.4677 | 37.10 | 73.90 | 446.00 | 1000.00 | 73.75 | 449.05 |

## Interpretation

- An `upstream/internet` outage means every configured Internet target failed while the local gateway still answered.
- A `local/gateway` outage means the local gateway and every Internet target failed together; investigate the router, cabling, Wi-Fi, or local interface.
- Isolated loss to one target can be ICMP rate limiting and is weaker evidence than simultaneous DNS, HTTP, VPS, and multi-target failures.
- Monitoring gaps are reported separately and must not be presented as Internet outages.

Raw evidence is retained in `events.jsonl`; CSV files and SVG charts in this directory are derived from it.
