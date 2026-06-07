# Internet Stability Report

- Host: `altruist`
- Measurement window: `2026-06-04T20:34:41.704000+00:00` to `2026-06-07T07:22:50.491000+00:00`
- Monitoring duration: 2.45d
- Report generated: `2026-06-07T07:22:55.846Z`
- All-target Internet outages: 651 totaling 26.1m
- Longest all-target outage: 17.9s
- Monitoring-process gaps: 1
- Public IP changes observed: 0
- Default route changes observed: 2
- Wi-Fi signal average/minimum: -56.08 / -61.00 dBm
- Local interface RX/TX errors: 0 / 0
- Local interface RX/TX drops: 0 / 0
- Collector task errors: 0

## Technician Summary

- Grouped incidents: 157 using a 120-second merge window.
- Worst grouped incident: 3.6m outage time across 96 outages.
- Local gateway packet loss/p95/p99: 1.6332% / 30.20 ms / 308.00 ms.
- Wi-Fi signal average/minimum during report: -56.08 / -61.00 dBm.
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
| local-gateway | gateway | 102195 | 1.6332 | 12.38 | 30.20 | 308.00 | 1000.00 | 30.20 | 439.00 |
| vps | internet | 102468 | 2.2261 | 56.43 | 92.40 | 376.00 | 998.00 | 92.30 | 446.50 |
| cloudflare | internet | 102468 | 2.1090 | 25.14 | 54.00 | 370.00 | 999.00 | 53.90 | 454.00 |
| google | internet | 102468 | 1.5800 | 28.85 | 55.10 | 387.00 | 992.00 | 54.90 | 505.60 |
| quad9 | internet | 102468 | 2.0670 | 35.87 | 66.80 | 413.00 | 1000.00 | 66.71 | 425.50 |

## Interpretation

- An `upstream/internet` outage means every configured Internet target failed while the local gateway still answered.
- A `local/gateway` outage means the local gateway and every Internet target failed together; investigate the router, cabling, Wi-Fi, or local interface.
- Isolated loss to one target can be ICMP rate limiting and is weaker evidence than simultaneous DNS, HTTP, VPS, and multi-target failures.
- Monitoring gaps are reported separately and must not be presented as Internet outages.

Raw evidence is retained in `events.jsonl`; CSV files and SVG charts in this directory are derived from it.
