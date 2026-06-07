# Module 3 Report Draft

Use this file as a draft for the W07-Prove submission answers.

## Question 1 - GitHub Link

Recommended link:

```text
https://github.com/rej0y/server-project
```

Also mention the live NixOS configuration repository if needed:

```text
https://github.com/rej0y/server
```

Both repositories are public.

## Question 2 - Video Link

```text
https://youtu.be/WnRHmD0_Yu4
```

The video should show:

- Code walkthrough of `nixos/modules/atm10.nix`.
- Code walkthrough of `nixos/modules/frp.nix`.
- `atm10.service` running.
- ATM10 client joining or already connected.
- CPU/network test evidence.

## Question 3 - Requirements Report

My five requirements were:

1. Install and configure NixOS on my home server with SSH, users, firewall/networking, and required packages.

Completed. I installed NixOS on the physical server named `altruist`, created the `rej0y` user, enabled SSH, disabled password and keyboard-interactive authentication, and configured the machine with a flake-based NixOS setup.

2. Enable a persistent Minecraft server deployment.

Completed with a design change. My original plan mentioned Docker and Docker Compose, but I learned that a native NixOS systemd service was cleaner. I created an ATM10 module that downloads the server pack, creates the service user, installs files into persistent state, writes JVM args and server properties, and starts the server through systemd.

3. Configure persistent world storage so data survives restarts and redeployments.

Completed for the ATM10 test server. The service uses systemd `StateDirectory = "atm10"`, so server state is stored under `/var/lib/atm10`. The world is stored at `/var/lib/atm10/world`.

4. Test local stability, including hardware stress, network reliability, uptime, and client connection.

Partially completed. CPU stress testing completed successfully for 4 hours with 24 workers and 0 failures. I also created a long-running network monitor and captured a 1.52-day report. The ATM10 server accepted a real player login. Full RAM validation is not complete because one 32 GB stick is defective and does not boot.

5. Configure my VPS as a reverse proxy or tunnel endpoint so outside players can reach the server safely.

Completed for TCP access. The Ubuntu VPS runs `frps.service`. The NixOS server runs `frp-ssh.service` for SSH and `frp-atm10.service` for Minecraft TCP port `25565`. The FRP logs show both proxies logged in and started successfully.

Requirements not completed:

- Full RAM testing is not complete because one RAM stick is defective.
- I did not build my final personal modded Minecraft server profile yet because hardware issues and server stability work took priority.
- Automated Minecraft backups were not finished during this sprint.

## Question 4 - Stretch Challenge

I partially completed a stretch challenge. I did not finish automated world backups, but I did create monitoring and validation tooling beyond the basic server setup. I used a CPU stress-test flake/service and a long-running network monitor to collect evidence about server stability and apartment internet reliability. The network monitor produced reports, CSV files, and charts showing outages, packet loss, latency, public IP changes, throughput, DNS checks, and HTTP checks.

## Question 5 - README

Answer:

```text
Yes
```

Use this answer after confirming the final README and video link are in the GitHub repository.

## Question 6 - Sprint Time Log

Upload:

```text
sprint_time_log.md
```

The log includes individual module work, SideDoor team-project work, and class meeting time.

## Question 7 - Time Spent

Based on the reconstructed sprint log, individual module time is over 10 hours. The current IM total in `sprint_time_log.md` is:

```text
41:14
```

The full reconstructed sprint total is:

```text
49:14
```

Select the option that matches more than 10 hours or the highest available bracket if the assignment uses ranges.

## Question 8 - Reflection

My sprint goal was to make consistent progress on the home server project without getting stuck trying to make every part perfect at once. I made real progress toward that goal because the server hardware was assembled, NixOS was installed, SSH and FRP access were configured, and I successfully created a working ATM10 systemd service. The most successful strategy was breaking the project into small pieces: base NixOS setup first, CPU testing next, network testing next, then the Minecraft service. I also made better decisions as I learned, especially changing from Docker/Compose to a native NixOS service because it fit the system better. The hardest parts were hardware problems, including the hazy front glass, one bad RAM stick, and the VGA light when booting headless. For the team project, I worked as the database/GitHub manager on SideDoor, tested the backend API against Postgres output, and helped the backend team reason about running the Node API persistently. For the next sprint, I want to replace or resolve the bad RAM, add automated backups, test Ethernet stability, and improve the production plan for the server.
