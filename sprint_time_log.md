# CSE 310 - Sprint Time Log

Name: Shengjian Zhou

Sprint #: 3

Sprint dates: May 25, 2026 - June 6, 2026

## Instructions

Record all CSE 310 work that you do either inside class or outside of class. Include time learning, practicing, developing, testing, and documenting. It is important to update this log every day.

For the Category column, record one of the following:

* IM - You are working on your Individual Module (do not include Planning Meeting in class)
* TP - You are working on your Team Project (include Team Project Work Days)
* MTG - You are in one of the following class meetings: Planning, Stand-Up, Team Review, or Individual Review

The expected minimum amount of time each Sprint for each category is as follows:

| Category | Total Time (Hours:Minutes) |
| --- | :---: |
| IM - Individual Module | 10:00 |
| TP - Team Project | 4:00 |
| MTG - Class Meetings | 4:00 |
| **TOTAL** | **18:00** |

## Time Log

Entries marked `EST` are evidence-based estimates reconstructed from local Codex history, git history, systemd journals, and server logs. Entries marked `USER` come from my class attendance and team-project notes. The Tuesday/Thursday 12:45-14:15 class blocks are split into 60 minutes of `MTG` and 30 minutes of in-class `TP`, matching the course categories and my note that both meeting and team-project work happened during class.

| Date | Start Time | Category | Description | Total Minutes |
| --- | --- | :---: | --- | :---: |
| 2026-05-25 | 13:42 | IM | EST - Researched Minecraft/NixOS/hardware architecture and requirements. | 45 |
| 2026-05-26 | 12:45 | MTG | USER - Sprint planning/stand-up class meeting; attended the scheduled class session. | 60 |
| 2026-05-26 | 13:45 | TP | USER - In-class SideDoor team-project work; coordinated responsibilities as database specialist and GitHub manager. | 30 |
| 2026-05-26 | 21:17 | IM | EST - Follow-up hardware research and parts validation. | 18 |
| 2026-05-27 | 01:37 | IM | EST - Software architecture research: GeyserMC, VPS access, Minecraft/NixOS service plan. | 100 |
| 2026-05-28 | 12:45 | MTG | USER - Sprint stand-up/status class meeting; attended the scheduled class session. | 60 |
| 2026-05-28 | 13:45 | TP | USER - In-class SideDoor backend/database coordination and API direction discussion. | 30 |
| 2026-05-28 | 16:42 | IM | EST - Minecraft server software research and deployment planning. | 160 |
| 2026-05-29 | 01:29 | IM | EST - Minecraft server configuration research and project planning. | 149 |
| 2026-05-29 | 21:07 | TP | EST - Built SideDoor API-vs-Postgres comparison harness and report; PR #4 verified the deployed API matched direct Postgres output. | 120 |
| 2026-05-30 | 23:21 | IM | EST - Minecraft server research and planning notes. | 43 |
| 2026-05-31 | 00:19 | IM | EST - Minecraft service research, scope decision, README/project documentation. | 208 |
| 2026-06-02 | 12:45 | MTG | USER - Sprint stand-up/status class meeting; attended the scheduled class session. | 60 |
| 2026-06-02 | 13:45 | TP | USER - In-class SideDoor backend testing and process discussion, including the suggestion to keep the Node API running persistently with PM2. | 30 |
| 2026-06-03 | 00:13 | IM | EST - Assembled/brought up hardware, installed NixOS, configured base system, and performed repeated reboot/rebuild validation on `altruist`. | 240 |
| 2026-06-03 | 18:31 | IM | EST - Created and tested CPU stress-test flake/service; ran initial `stress-ng` validation and reviewed temperatures. | 180 |
| 2026-06-03 | 22:23 | IM | Automated CPU stress validation: 24 workers for 4 hours; completed June 4 at 02:23 with 24 passed and 0 failed. | 240 |
| 2026-06-04 | 12:45 | MTG | USER - Sprint review/status class meeting; attended the scheduled class session. | 60 |
| 2026-06-04 | 13:45 | TP | USER - In-class SideDoor GitHub/backend work; managed main-branch PR expectations and reviewed API/Postgres test evidence. | 30 |
| 2026-06-04 | 14:15 | IM | EST - Built network monitoring approach, configured VPS `iperf3` endpoint, hardened service, ran first apartment internet report, and downloaded evidence. | 420 |
| 2026-06-05 | 19:52 | IM | EST - Reviewed network evidence, report behavior, and VPS `iperf3` service status. | 82 |
| 2026-06-06 | 04:01 | IM | EST - Planned RAM-test flake and documented the defective second RAM stick blocking full RAM validation. | 20 |
| 2026-06-06 | 12:23 | IM | EST - Reviewed long-term network monitor, public IP behavior, FRP implications, and report interpretation. | 90 |
| 2026-06-06 | 15:00 | IM | EST - Built the ATM10 NixOS module manually in small steps: service user, Java 21, package fetch, unpack derivation, JVM args, server properties, and systemd service. | 254 |
| 2026-06-06 | 19:14 | IM | EST - Validated running ATM10 service, player login, op/command behavior, FRP public access, and live workload behavior. | 135 |
| 2026-06-06 | 21:36 | IM | EST - Gathered evidence from local repo, Codex history, NixOS server logs, VPS logs, GitHub metadata, and updated README/time-log documentation. | 90 |

## Sprint Totals

| Category | Total Time (Hours:Minutes) |
| --- | :---: |
| IM - Individual Module | 41:14 |
| TP - Team Project | 4:00 |
| MTG - Class Meetings | 4:00 |
| **TOTAL** | **49:14** |

## Evidence Notes

- CPU service evidence: `cpu-stress-test.service` ran from 2026-06-03 22:23:24 MDT to 2026-06-04 02:23:24 MDT with `stress-ng exit: 0`.
- Network evidence: `test/network/netprobe-data/altruist-latest/report.md`.
- ATM10 service evidence: `atm10.service` active since 2026-06-06 19:14:54 MDT; player `rejoyy` joined at 19:20:36 MDT.
- FRP evidence: `frp-ssh.service` and `frp-atm10.service` active on NixOS; `frps.service` active on the Ubuntu VPS.
- SideDoor team-project evidence: `~/Projects/sidedoor/README.md` lists John Zhou as database specialist, backend team member, and GitHub manager. GitHub PR #4, `Add API DB comparison test harness`, was merged on 2026-05-29 and verified the deployed API matched direct Postgres output.
