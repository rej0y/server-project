#!/usr/bin/env python3
"""Long-running, unprivileged Internet connection monitor."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import datetime as dt
import html
import ipaddress
import json
import math
import os
import pathlib
import re
import shlex
import shutil
import signal
import socket
import statistics
import subprocess
import sys
import threading
import time
import tomllib
from typing import Any, Callable, Iterable


UTC = dt.timezone.utc
SCRIPT_PATH = pathlib.Path(__file__).resolve()
DEFAULT_CONFIG = pathlib.Path(
    os.environ.get("NETPROBE_DEFAULT_CONFIG", str(SCRIPT_PATH.parent.parent / "netprobe.example.toml"))
)
REQUIRED_COMMANDS = ["curl", "dig", "ip", "iperf3", "iw", "mtr", "ping", "systemctl", "systemd-run"]


def utc_now() -> str:
    return dt.datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_time(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-")
    return cleaned or "target"


def truncate(value: str, limit: int = 1000) -> str:
    value = value.strip()
    return value if len(value) <= limit else value[:limit] + "...[truncated]"


def run_command(command: list[str], timeout: float) -> dict[str, Any]:
    started = time.monotonic()
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "duration_ms": round((time.monotonic() - started) * 1000, 3),
        }
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout.decode() if isinstance(error.stdout, bytes) else (error.stdout or "")
        stderr = error.stderr.decode() if isinstance(error.stderr, bytes) else (error.stderr or "")
        return {
            "returncode": None,
            "stdout": stdout,
            "stderr": stderr,
            "duration_ms": round((time.monotonic() - started) * 1000, 3),
            "timeout": True,
        }
    except OSError as error:
        return {
            "returncode": None,
            "stdout": "",
            "stderr": str(error),
            "duration_ms": round((time.monotonic() - started) * 1000, 3),
        }


def load_config(path: pathlib.Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        config = tomllib.load(handle)

    probe = config.setdefault("probe", {})
    defaults = {
        "ping_interval": 2,
        "ping_timeout": 1,
        "dns_interval": 60,
        "http_interval": 60,
        "link_interval": 10,
        "route_interval": 300,
        "mtr_interval": 3600,
        "public_ip_interval": 300,
        "throughput_interval": 21600,
        "throughput_bytes": "50M",
        "throughput_timeout": 300,
        "iperf_host": "",
        "iperf_port": 5201,
        "mtr_cycles": 20,
        "public_ip_url": "https://api.ipify.org",
    }
    for key, value in defaults.items():
        probe.setdefault(key, value)

    for key in (
        "ping_interval",
        "ping_timeout",
        "dns_interval",
        "http_interval",
        "link_interval",
        "route_interval",
        "mtr_interval",
        "public_ip_interval",
        "throughput_interval",
        "throughput_timeout",
        "iperf_port",
        "mtr_cycles",
    ):
        if not isinstance(probe[key], (int, float)) or probe[key] <= 0:
            raise ValueError(f"probe.{key} must be a positive number")

    for section in ("ping_targets", "dns_tests", "http_tests", "mtr_targets"):
        config.setdefault(section, [])
        if not isinstance(config[section], list):
            raise ValueError(f"{section} must contain an array of tables")

    if not config["ping_targets"]:
        raise ValueError("At least one [[ping_targets]] entry is required")
    for target in config["ping_targets"]:
        for key in ("label", "address", "scope"):
            if not target.get(key):
                raise ValueError(f"Each ping target requires {key}")
        if target["scope"] not in ("gateway", "internet"):
            raise ValueError("ping target scope must be 'gateway' or 'internet'")

    return config


def json_command(command: list[str], timeout: float = 10) -> tuple[Any | None, dict[str, Any]]:
    result = run_command(command, timeout)
    try:
        return json.loads(result["stdout"]), result
    except (json.JSONDecodeError, TypeError):
        return None, result


def default_route() -> dict[str, Any]:
    routes, result = json_command(["ip", "-4", "-json", "route", "show", "default"])
    if result["returncode"] == 0 and routes:
        route = routes[0]
        return {
            "gateway": route.get("gateway"),
            "interface": route.get("dev"),
            "source": route.get("prefsrc"),
            "raw": route,
        }
    return {"gateway": None, "interface": None, "source": None, "raw": None}


class EventWriter:
    def __init__(self, path: pathlib.Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a", encoding="utf-8", buffering=1)
        self.lock = threading.Lock()
        self.last_fsync = time.monotonic()

    def write(self, event: dict[str, Any]) -> None:
        event.setdefault("timestamp", utc_now())
        event.setdefault("host", socket.gethostname())
        line = json.dumps(event, separators=(",", ":"), sort_keys=True)
        with self.lock:
            self.handle.write(line + "\n")
            self.handle.flush()
            if time.monotonic() - self.last_fsync >= 30:
                os.fsync(self.handle.fileno())
                self.last_fsync = time.monotonic()

    def close(self) -> None:
        with self.lock:
            self.handle.flush()
            os.fsync(self.handle.fileno())
            self.handle.close()


class Collector:
    def __init__(self, config: dict[str, Any], writer: EventWriter):
        self.config = config
        self.probe = config["probe"]
        self.writer = writer
        self.stop_event = threading.Event()
        self.stop_signal: int | None = None
        self.route = default_route()
        self.ping_targets = [dict(target) for target in config["ping_targets"]]
        self.refresh_default_route()

    def stop(self, signum: int | None = None, _frame: Any = None) -> None:
        self.stop_signal = signum
        self.stop_event.set()

    def refresh_default_route(self) -> dict[str, Any]:
        route = default_route()
        if route.get("gateway") or route.get("interface"):
            self.route = route

        gateway = self.route.get("gateway")
        if not gateway:
            return self.route

        gateway_target = {"label": "local-gateway", "address": gateway, "scope": "gateway"}
        for target in self.ping_targets:
            if target.get("label") == "local-gateway" or target.get("scope") == "gateway":
                target.update(gateway_target)
                break
        else:
            self.ping_targets.insert(0, gateway_target)
        return self.route

    def ping_one(self, target: dict[str, str]) -> dict[str, Any]:
        address = target["address"]
        family = "-6" if ":" in address else "-4"
        timeout = max(1, math.ceil(float(self.probe["ping_timeout"])))
        result = run_command(
            ["ping", family, "-n", "-c", "1", "-W", str(timeout), address],
            timeout + 2,
        )
        combined = result["stdout"] + "\n" + result["stderr"]
        match = re.search(r"time[=<]([0-9.]+)\s*ms", combined)
        latency = float(match.group(1)) if match else None
        success = result["returncode"] == 0 and latency is not None
        return {
            "label": target["label"],
            "address": address,
            "scope": target["scope"],
            "success": success,
            "latency_ms": latency,
            "command_duration_ms": result["duration_ms"],
            "detail": "" if success else truncate(combined, 500),
        }

    def ping_batch(self) -> dict[str, Any]:
        self.refresh_default_route()
        timestamp = utc_now()
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(16, len(self.ping_targets))) as pool:
            results = list(pool.map(self.ping_one, self.ping_targets))
        return {"type": "ping_batch", "timestamp": timestamp, "results": results}

    def dns_batch(self) -> dict[str, Any]:
        timestamp = utc_now()
        results = []
        timeout = max(1, math.ceil(float(self.probe["ping_timeout"]) * 2))
        for test in self.config["dns_tests"]:
            command = [
                "dig",
                f"+time={timeout}",
                "+tries=1",
                "+noall",
                "+comments",
                "+answer",
                "+stats",
                test["name"],
            ]
            if test.get("resolver"):
                command.append("@" + test["resolver"])
            result = run_command(command, timeout + 3)
            output = result["stdout"] + "\n" + result["stderr"]
            status_match = re.search(r"status:\s*([A-Z]+)", output)
            query_match = re.search(r"Query time:\s*([0-9]+)\s*msec", output)
            status = status_match.group(1) if status_match else None
            results.append(
                {
                    "label": test["label"],
                    "resolver": test.get("resolver") or "system",
                    "name": test["name"],
                    "success": result["returncode"] == 0 and status == "NOERROR",
                    "status": status,
                    "query_ms": int(query_match.group(1)) if query_match else None,
                    "detail": truncate(output, 1000),
                }
            )
        return {"type": "dns_batch", "timestamp": timestamp, "results": results}

    def http_batch(self) -> dict[str, Any]:
        timestamp = utc_now()
        results = []
        timeout = max(5, math.ceil(float(self.probe["ping_timeout"]) * 5))
        write_out = (
            '{"remote_ip":"%{remote_ip}","http_code":%{http_code},'
            '"time_namelookup":%{time_namelookup},"time_connect":%{time_connect},'
            '"time_appconnect":%{time_appconnect},"time_starttransfer":%{time_starttransfer},'
            '"time_total":%{time_total},"size_download":%{size_download}}'
        )
        for test in self.config["http_tests"]:
            result = run_command(
                [
                    "curl",
                    "-4",
                    "--silent",
                    "--show-error",
                    "--location",
                    "--max-time",
                    str(timeout),
                    "--output",
                    "/dev/null",
                    "--write-out",
                    write_out,
                    test["url"],
                ],
                timeout + 3,
            )
            try:
                metrics = json.loads(result["stdout"])
            except json.JSONDecodeError:
                metrics = {}
            code = int(metrics.get("http_code", 0))
            results.append(
                {
                    "label": test["label"],
                    "url": test["url"],
                    "success": result["returncode"] == 0 and 200 <= code < 400,
                    "metrics": metrics,
                    "detail": truncate(result["stderr"], 1000),
                }
            )
        return {"type": "http_batch", "timestamp": timestamp, "results": results}

    def link_stats(self) -> dict[str, Any]:
        timestamp = utc_now()
        self.refresh_default_route()
        interface = self.route.get("interface")
        if not interface:
            return {
                "type": "link_stats",
                "timestamp": timestamp,
                "success": False,
                "detail": "No default-route interface found",
            }
        data, result = json_command(["ip", "-json", "-stats", "link", "show", "dev", interface])
        wireless = None
        if (pathlib.Path("/sys/class/net") / interface / "wireless").exists():
            iw_result = run_command(["iw", "dev", interface, "link"], 10)
            signal_match = re.search(r"signal:\s*(-?[0-9]+)\s*dBm", iw_result["stdout"])
            wireless = {
                "success": iw_result["returncode"] == 0,
                "signal_dbm": int(signal_match.group(1)) if signal_match else None,
                "detail": truncate(iw_result["stdout"] or iw_result["stderr"], 2000),
            }
        return {
            "type": "link_stats",
            "timestamp": timestamp,
            "success": result["returncode"] == 0 and bool(data),
            "interface": interface,
            "data": data[0] if data else None,
            "wireless": wireless,
            "detail": truncate(result["stderr"], 1000),
        }

    def route_snapshot(self) -> dict[str, Any]:
        timestamp = utc_now()
        current = self.refresh_default_route()
        routes = []
        for target in self.ping_targets:
            data, result = json_command(["ip", "-4", "-json", "route", "get", target["address"]])
            routes.append(
                {
                    "label": target["label"],
                    "address": target["address"],
                    "success": result["returncode"] == 0 and bool(data),
                    "route": data[0] if data else None,
                    "detail": truncate(result["stderr"], 500),
                }
            )
        return {
            "type": "route_snapshot",
            "timestamp": timestamp,
            "default": current,
            "routes": routes,
        }

    def public_ip(self) -> dict[str, Any]:
        timestamp = utc_now()
        url = self.probe.get("public_ip_url", "")
        if not url:
            return {"type": "public_ip", "timestamp": timestamp, "success": False, "detail": "disabled"}
        result = run_command(
            ["curl", "-4", "--silent", "--show-error", "--max-time", "10", url],
            13,
        )
        value = result["stdout"].strip()
        try:
            ipaddress.ip_address(value)
            valid = True
        except ValueError:
            valid = False
        return {
            "type": "public_ip",
            "timestamp": timestamp,
            "success": result["returncode"] == 0 and valid,
            "address": value if valid else None,
            "detail": truncate(result["stderr"] or result["stdout"], 500),
        }

    def mtr_snapshots(self) -> dict[str, Any]:
        timestamp = utc_now()
        results = []
        cycles = int(self.probe["mtr_cycles"])
        for target in self.config["mtr_targets"]:
            result = run_command(
                [
                    "mtr",
                    "--report",
                    "--json",
                    "--no-dns",
                    "--report-cycles",
                    str(cycles),
                    target["address"],
                ],
                max(60, cycles * 3),
            )
            try:
                report = json.loads(result["stdout"])
            except json.JSONDecodeError:
                report = None
            results.append(
                {
                    "label": target["label"],
                    "address": target["address"],
                    "success": result["returncode"] == 0 and report is not None,
                    "report": report,
                    "detail": truncate(result["stderr"] or result["stdout"], 2000),
                }
            )
        return {"type": "mtr_batch", "timestamp": timestamp, "results": results}

    def throughput_tests(self) -> list[dict[str, Any]]:
        host = str(self.probe.get("iperf_host", "")).strip()
        if not host:
            return []
        events = []
        for direction in ("upload", "download"):
            timestamp = utc_now()
            command = [
                "iperf3",
                "--client",
                host,
                "--port",
                str(int(self.probe["iperf_port"])),
                "--json",
                "--bytes",
                str(self.probe["throughput_bytes"]),
            ]
            if direction == "download":
                command.append("--reverse")
            result = run_command(command, float(self.probe["throughput_timeout"]))
            try:
                report = json.loads(result["stdout"])
            except json.JSONDecodeError:
                report = None
            end = report.get("end", {}) if report else {}
            sent = end.get("sum_sent", {})
            received = end.get("sum_received", {})
            selected = sent if direction == "upload" else received
            events.append(
                {
                    "type": "throughput",
                    "timestamp": timestamp,
                    "ended_at": utc_now(),
                    "direction": direction,
                    "host_address": host,
                    "port": int(self.probe["iperf_port"]),
                    "success": result["returncode"] == 0 and report is not None and "error" not in report,
                    "bits_per_second": selected.get("bits_per_second"),
                    "retransmits": sent.get("retransmits"),
                    "seconds": selected.get("seconds"),
                    "report": report,
                    "detail": truncate(result["stderr"] or result["stdout"], 2000),
                }
            )
            if self.stop_event.wait(3):
                break
        return events

    def run(self) -> None:
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)
        self.writer.write(
            {
                "type": "collector_started",
                "default_route": self.route,
                "ping_targets": self.ping_targets,
            }
        )

        tasks: dict[str, tuple[float, Callable[[], Any]]] = {
            "ping": (float(self.probe["ping_interval"]), self.ping_batch),
            "dns": (float(self.probe["dns_interval"]), self.dns_batch),
            "http": (float(self.probe["http_interval"]), self.http_batch),
            "link": (float(self.probe["link_interval"]), self.link_stats),
            "route": (float(self.probe["route_interval"]), self.route_snapshot),
            "mtr": (float(self.probe["mtr_interval"]), self.mtr_snapshots),
            "public_ip": (float(self.probe["public_ip_interval"]), self.public_ip),
        }
        if str(self.probe.get("iperf_host", "")).strip():
            tasks["throughput"] = (float(self.probe["throughput_interval"]), self.throughput_tests)

        due = {name: time.monotonic() for name in tasks}
        active: dict[str, concurrent.futures.Future[Any]] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(4, len(tasks))) as pool:
            while not self.stop_event.is_set():
                now = time.monotonic()
                for name, future in list(active.items()):
                    if not future.done():
                        continue
                    del active[name]
                    try:
                        value = future.result()
                        if isinstance(value, list):
                            for event in value:
                                self.writer.write(event)
                        elif value:
                            self.writer.write(value)
                    except Exception as error:  # Keep the monitor alive after an individual test failure.
                        self.writer.write({"type": "task_error", "task": name, "error": repr(error)})

                for name, (interval, function) in tasks.items():
                    if now < due[name] or name in active:
                        continue
                    active[name] = pool.submit(function)
                    while due[name] <= now:
                        due[name] += interval
                self.stop_event.wait(0.1)

        self.writer.write({"type": "collector_stopped", "signal": self.stop_signal})


def create_run_dir(data_dir: pathlib.Path, requested: pathlib.Path | None = None) -> pathlib.Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    if requested:
        run_dir = requested
    else:
        stamp = dt.datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        run_dir = data_dir / f"{slug(socket.gethostname())}-{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    current = data_dir / "current"
    if current.is_symlink():
        current.unlink()
    elif current.exists() and current.resolve() != run_dir.resolve():
        raise RuntimeError(f"{current} exists and is not a symlink")
    if not current.exists():
        current.symlink_to(run_dir.resolve(), target_is_directory=True)
    return run_dir.resolve()


def write_metadata(run_dir: pathlib.Path, config_path: pathlib.Path, config: dict[str, Any]) -> None:
    path = run_dir / "metadata.json"
    if path.exists():
        return
    metadata = {
        "started_at": utc_now(),
        "hostname": socket.gethostname(),
        "config_path": str(config_path),
        "config": config,
        "kernel": os.uname().release,
        "system": os.uname().sysname,
    }
    path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def iter_events(path: pathlib.Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                print(f"warning: skipped invalid JSON at {path}:{line_number}", file=sys.stderr)


def percentile(values: list[float], percent: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def fmt_number(value: float | int | None, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}"


def fmt_duration(seconds: float) -> str:
    seconds = max(0, seconds)
    if seconds < 60:
        return f"{seconds:.1f}s"
    if seconds < 3600:
        return f"{seconds / 60:.1f}m"
    if seconds < 86400:
        return f"{seconds / 3600:.2f}h"
    return f"{seconds / 86400:.2f}d"


def csv_write(path: pathlib.Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def in_intervals(timestamp: dt.datetime, intervals: list[tuple[dt.datetime, dt.datetime]]) -> bool:
    return any(start <= timestamp <= end for start, end in intervals)


def downsample(points: list[tuple[dt.datetime, float | None]], limit: int = 2500) -> list[tuple[dt.datetime, float | None]]:
    if len(points) <= limit:
        return points
    width = math.ceil(len(points) / limit)
    sampled = []
    for index in range(0, len(points), width):
        bucket = points[index:index + width]
        failures = [point for point in bucket if point[1] is None]
        successes = [point for point in bucket if point[1] is not None]
        if failures:
            sampled.append(failures[0])
        if successes:
            sampled.append(max(successes, key=lambda point: float(point[1])))
    return sampled[: limit * 2]


def write_latency_svg(path: pathlib.Path, label: str, points: list[tuple[dt.datetime, float | None]]) -> None:
    points = downsample(points)
    if not points:
        return
    width, height = 1200, 340
    left, right, top, bottom = 70, 30, 30, 75
    start = points[0][0].timestamp()
    end = max(points[-1][0].timestamp(), start + 1)
    values = [float(value) for _, value in points if value is not None]
    ceiling = max(10.0, percentile(values, 99.5) or 10.0)
    duration = end - start
    point_data = [
        [int(when.timestamp() * 1000), None if value is None else round(float(value), 3)]
        for when, value in points
    ]
    point_json = json.dumps(point_data, separators=(",", ":"))

    def x_position(when: dt.datetime) -> float:
        return left + (when.timestamp() - start) / (end - start) * (width - left - right)

    def y_position(value: float) -> float:
        capped = min(value, ceiling)
        return top + (1 - capped / ceiling) * (height - top - bottom)

    def format_tick(when: dt.datetime) -> str:
        local = when.astimezone()
        if duration >= 86400:
            return local.strftime("%m/%d %H:%M")
        return local.strftime("%H:%M")

    tick_count = 6
    ticks = []
    for index in range(tick_count):
        offset = duration * index / (tick_count - 1)
        when = dt.datetime.fromtimestamp(start + offset, UTC)
        ticks.append((when, format_tick(when)))
    tick_lines = "\n".join(
        f'<line x1="{x_position(when):.1f}" y1="{height - bottom}" x2="{x_position(when):.1f}" '
        f'y2="{height - bottom + 6}" stroke="#64748b"/>'
        for when, _ in ticks
    )
    tick_labels = "\n".join(
        f'<text x="{x_position(when):.1f}" y="{height - bottom + 22}" '
        f'font-family="sans-serif" font-size="12" text-anchor="middle">{html.escape(text)}</text>'
        for when, text in ticks
    )
    success_points = " ".join(
        f"{x_position(when):.1f},{y_position(float(value)):.1f}"
        for when, value in points
        if value is not None
    )
    failures = "\n".join(
        f'<line x1="{x_position(when):.1f}" y1="{top}" x2="{x_position(when):.1f}" '
        f'y2="{height - bottom}" stroke="#dc2626" stroke-width="1"/>'
        for when, value in points
        if value is None
    )
    escaped = html.escape(label)
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">
<rect width="{width}" height="{height}" fill="white"/>
<text x="{left}" y="20" font-family="sans-serif" font-size="15">{escaped} latency (red = failed ping; drag/hover for time)</text>
<line x1="{left}" y1="{height - bottom}" x2="{width - right}" y2="{height - bottom}" stroke="#64748b"/>
<line x1="{left}" y1="{top}" x2="{left}" y2="{height - bottom}" stroke="#64748b"/>
<text x="5" y="{top + 5}" font-family="sans-serif" font-size="12">{ceiling:.1f} ms</text>
<text x="35" y="{height - bottom + 5}" font-family="sans-serif" font-size="12">0 ms</text>
{tick_lines}
{tick_labels}
<text x="{(left + width - right) / 2:.1f}" y="{height - 18}" font-family="sans-serif" font-size="12" text-anchor="middle">Local time</text>
<polyline points="{success_points}" fill="none" stroke="#2563eb" stroke-width="1"/>
{failures}
<line id="cursor-line" x1="{left}" y1="{top}" x2="{left}" y2="{height - bottom}" stroke="#111827" stroke-width="1.5" stroke-dasharray="4 3" visibility="hidden"/>
<circle id="cursor-dot" cx="{left}" cy="{height - bottom}" r="4" fill="#2563eb" stroke="white" stroke-width="1.5" visibility="hidden"/>
<g id="tooltip" visibility="hidden">
<rect id="tooltip-bg" x="0" y="0" width="158" height="52" rx="5" fill="#111827" opacity="0.92"/>
<text id="tooltip-time" x="10" y="20" font-family="sans-serif" font-size="13" fill="white"></text>
<text id="tooltip-value" x="10" y="40" font-family="sans-serif" font-size="13" fill="white"></text>
</g>
<rect id="hit-area" x="{left}" y="{top}" width="{width - left - right}" height="{height - top - bottom}" fill="transparent" pointer-events="all" style="cursor: crosshair;"/>
<script><![CDATA[
(function () {{
  const points = {point_json};
  const bounds = {{
    left: {left}, right: {right}, top: {top}, bottom: {bottom},
    width: {width}, height: {height},
    start: {int(start * 1000)}, end: {int(end * 1000)}, ceiling: {ceiling:.6f}
  }};
  const svg = document.documentElement;
  const hitArea = document.getElementById("hit-area");
  const cursorLine = document.getElementById("cursor-line");
  const cursorDot = document.getElementById("cursor-dot");
  const tooltip = document.getElementById("tooltip");
  const tooltipTime = document.getElementById("tooltip-time");
  const tooltipValue = document.getElementById("tooltip-value");
  const plotWidth = bounds.width - bounds.left - bounds.right;
  const plotHeight = bounds.height - bounds.top - bounds.bottom;
  let dragging = false;

  function clamp(value, low, high) {{
    return Math.min(Math.max(value, low), high);
  }}

  function xFor(ms) {{
    return bounds.left + ((ms - bounds.start) / (bounds.end - bounds.start)) * plotWidth;
  }}

  function yFor(value) {{
    const capped = Math.min(value, bounds.ceiling);
    return bounds.top + (1 - capped / bounds.ceiling) * plotHeight;
  }}

  function eventX(event) {{
    const matrix = svg.getScreenCTM();
    if (!matrix) {{
      return bounds.left;
    }}
    const point = svg.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    return point.matrixTransform(matrix.inverse()).x;
  }}

  function nearestIndex(ms) {{
    let low = 0;
    let high = points.length - 1;
    while (low < high) {{
      const mid = Math.floor((low + high) / 2);
      if (points[mid][0] < ms) {{
        low = mid + 1;
      }} else {{
        high = mid;
      }}
    }}
    if (low > 0 && Math.abs(points[low - 1][0] - ms) < Math.abs(points[low][0] - ms)) {{
      return low - 1;
    }}
    return low;
  }}

  function formatTime(ms) {{
    const date = new Date(ms);
    const pad = (value) => String(value).padStart(2, "0");
    const month = pad(date.getMonth() + 1);
    const day = pad(date.getDate());
    const hours = pad(date.getHours());
    const minutes = pad(date.getMinutes());
    const seconds = pad(date.getSeconds());
    if ((bounds.end - bounds.start) >= 86400000) {{
      return `${{month}}/${{day}} ${{hours}}:${{minutes}}`;
    }}
    return `${{hours}}:${{minutes}}:${{seconds}}`;
  }}

  function update(event) {{
    const x = clamp(eventX(event), bounds.left, bounds.width - bounds.right);
    const ms = bounds.start + ((x - bounds.left) / plotWidth) * (bounds.end - bounds.start);
    const point = points[nearestIndex(ms)];
    const pointX = xFor(point[0]);
    const failed = point[1] === null;
    const pointY = failed ? bounds.top : yFor(point[1]);
    const tooltipX = clamp(pointX + 10, bounds.left, bounds.width - bounds.right - 158);
    const tooltipY = clamp(pointY - 62, bounds.top, bounds.height - bounds.bottom - 56);

    cursorLine.setAttribute("x1", pointX);
    cursorLine.setAttribute("x2", pointX);
    cursorLine.setAttribute("visibility", "visible");
    cursorDot.setAttribute("cx", pointX);
    cursorDot.setAttribute("cy", pointY);
    cursorDot.setAttribute("fill", failed ? "#dc2626" : "#2563eb");
    cursorDot.setAttribute("visibility", "visible");
    tooltipTime.textContent = formatTime(point[0]);
    tooltipValue.textContent = failed ? "failed ping" : `${{Number(point[1]).toFixed(1)}} ms`;
    tooltip.setAttribute("transform", `translate(${{tooltipX}}, ${{tooltipY}})`);
    tooltip.setAttribute("visibility", "visible");
  }}

  function hide() {{
    if (dragging) {{
      return;
    }}
    cursorLine.setAttribute("visibility", "hidden");
    cursorDot.setAttribute("visibility", "hidden");
    tooltip.setAttribute("visibility", "hidden");
  }}

  hitArea.addEventListener("pointermove", update);
  hitArea.addEventListener("pointerdown", (event) => {{
    dragging = true;
    hitArea.setPointerCapture(event.pointerId);
    update(event);
  }});
  hitArea.addEventListener("pointerup", (event) => {{
    dragging = false;
    hitArea.releasePointerCapture(event.pointerId);
    update(event);
  }});
  hitArea.addEventListener("pointercancel", () => {{
    dragging = false;
    hide();
  }});
  hitArea.addEventListener("pointerleave", hide);
}})();
]]></script>
</svg>
"""
    path.write_text(svg, encoding="utf-8")


def local_time_label(when: dt.datetime, duration_seconds: float) -> str:
    local = when.astimezone()
    if duration_seconds >= 86400:
        return local.strftime("%m/%d %H:%M")
    return local.strftime("%H:%M")


def local_table_time(value: str | dt.datetime) -> str:
    when = parse_time(value) if isinstance(value, str) else value
    return when.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def svg_time_ticks(
    start: dt.datetime,
    end: dt.datetime,
    width: int,
    height: int,
    left: int,
    right: int,
    bottom: int,
    tick_count: int = 6,
) -> str:
    start_ts = start.timestamp()
    end_ts = max(end.timestamp(), start_ts + 1)
    duration = end_ts - start_ts

    def x_position(when: dt.datetime) -> float:
        return left + (when.timestamp() - start_ts) / duration * (width - left - right)

    parts = []
    for index in range(tick_count):
        offset = duration * index / (tick_count - 1)
        when = dt.datetime.fromtimestamp(start_ts + offset, UTC)
        x_value = x_position(when)
        text = local_time_label(when, duration)
        parts.append(
            f'<line x1="{x_value:.1f}" y1="{height - bottom}" x2="{x_value:.1f}" '
            f'y2="{height - bottom + 6}" stroke="#64748b"/>'
        )
        parts.append(
            f'<text x="{x_value:.1f}" y="{height - bottom + 22}" '
            f'font-family="sans-serif" font-size="12" text-anchor="middle">{html.escape(text)}</text>'
        )
    parts.append(
        f'<text x="{(left + width - right) / 2:.1f}" y="{height - 16}" '
        'font-family="sans-serif" font-size="12" text-anchor="middle">Local time</text>'
    )
    return "\n".join(parts)


def svg_json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":")).replace("</", "<\\/").replace("]]>", "]]\\u003e")


def svg_inspector(
    points: list[dict[str, Any]],
    width: int,
    height: int,
    left: int,
    right: int,
    top: float,
    bottom: int,
    *,
    tooltip_width: int = 260,
) -> str:
    if not points:
        return ""
    max_lines = max(1, min(5, max(len(point.get("lines", [])) for point in points)))
    tooltip_height = 18 + max_lines * 18
    text_nodes = "\n".join(
        f'<text id="inspect-line-{index}" x="10" y="{20 + index * 18}" '
        'font-family="sans-serif" font-size="13" fill="white"></text>'
        for index in range(max_lines)
    )
    return f"""<line id="inspect-cursor-line" x1="0" y1="{top:.1f}" x2="0" y2="{height - bottom}" stroke="#111827" stroke-width="1" stroke-dasharray="4 4" visibility="hidden" pointer-events="none"/>
<circle id="inspect-cursor-dot" cx="0" cy="0" r="5" fill="#2563eb" stroke="white" stroke-width="2" visibility="hidden" pointer-events="none"/>
<g id="inspect-tooltip" visibility="hidden" pointer-events="none">
<rect id="inspect-tooltip-bg" x="0" y="0" width="{tooltip_width}" height="{tooltip_height}" rx="5" fill="#111827" opacity="0.92"/>
{text_nodes}
</g>
<rect id="inspect-hit-area" x="{left}" y="{top:.1f}" width="{width - left - right}" height="{height - bottom - top:.1f}" fill="transparent" pointer-events="all"/>
<script><![CDATA[
(() => {{
  const points = {svg_json(points)};
  if (!points.length) {{
    return;
  }}
  const bounds = {{
    width: {width},
    height: {height},
    left: {left},
    right: {right},
    top: {top:.1f},
    bottom: {bottom},
    tooltipWidth: {tooltip_width},
    tooltipHeight: {tooltip_height}
  }};
  const svg = document.documentElement;
  const hitArea = document.getElementById("inspect-hit-area");
  const cursorLine = document.getElementById("inspect-cursor-line");
  const cursorDot = document.getElementById("inspect-cursor-dot");
  const tooltip = document.getElementById("inspect-tooltip");
  const textNodes = Array.from({{length: {max_lines}}}, (_, index) => document.getElementById(`inspect-line-${{index}}`));
  let dragging = false;

  function clamp(value, minimum, maximum) {{
    return Math.min(Math.max(value, minimum), maximum);
  }}

  function eventPoint(event) {{
    const matrix = svg.getScreenCTM();
    if (!matrix) {{
      return null;
    }}
    const point = svg.createSVGPoint();
    point.x = event.clientX;
    point.y = event.clientY;
    return point.matrixTransform(matrix.inverse());
  }}

  function nearestPoint(x, y) {{
    let best = points[0];
    let bestScore = Infinity;
    for (const point of points) {{
      const dx = Math.abs(point.x - x);
      const dy = Math.abs(point.y - y);
      const score = dx + dy * 0.45;
      if (score < bestScore) {{
        best = point;
        bestScore = score;
      }}
    }}
    return best;
  }}

  function update(event) {{
    const eventSvgPoint = eventPoint(event);
    if (!eventSvgPoint) {{
      return;
    }}
    const x = clamp(eventSvgPoint.x, bounds.left, bounds.width - bounds.right);
    const y = clamp(eventSvgPoint.y, bounds.top, bounds.height - bounds.bottom);
    const point = nearestPoint(x, y);
    const pointX = Number(point.x);
    const pointY = Number(point.y);
    const tooltipX = clamp(pointX + 12, bounds.left, bounds.width - bounds.right - bounds.tooltipWidth);
    const tooltipY = clamp(pointY - bounds.tooltipHeight - 12, bounds.top, bounds.height - bounds.bottom - bounds.tooltipHeight);

    cursorLine.setAttribute("x1", pointX);
    cursorLine.setAttribute("x2", pointX);
    cursorLine.setAttribute("visibility", "visible");
    cursorDot.setAttribute("cx", pointX);
    cursorDot.setAttribute("cy", pointY);
    cursorDot.setAttribute("fill", point.color || "#2563eb");
    cursorDot.setAttribute("visibility", "visible");

    const lines = point.lines || [];
    textNodes.forEach((node, index) => {{
      node.textContent = lines[index] || "";
      node.setAttribute("visibility", lines[index] ? "visible" : "hidden");
      node.setAttribute("font-weight", index === 0 ? "700" : "400");
    }});
    tooltip.setAttribute("transform", `translate(${{tooltipX}}, ${{tooltipY}})`);
    tooltip.setAttribute("visibility", "visible");
  }}

  function hide() {{
    if (dragging) {{
      return;
    }}
    cursorLine.setAttribute("visibility", "hidden");
    cursorDot.setAttribute("visibility", "hidden");
    tooltip.setAttribute("visibility", "hidden");
  }}

  hitArea.addEventListener("pointermove", update);
  hitArea.addEventListener("pointerdown", (event) => {{
    dragging = true;
    hitArea.setPointerCapture(event.pointerId);
    update(event);
  }});
  hitArea.addEventListener("pointerup", (event) => {{
    dragging = false;
    hitArea.releasePointerCapture(event.pointerId);
    update(event);
  }});
  hitArea.addEventListener("pointercancel", () => {{
    dragging = false;
    hide();
  }});
  hitArea.addEventListener("pointerleave", hide);
}})();
]]></script>"""


def write_outage_timeline_svg(
    path: pathlib.Path,
    outages: list[dict[str, Any]],
    first_time: dt.datetime | None,
    last_time: dt.datetime | None,
) -> None:
    if not first_time or not last_time:
        return
    width, height = 1200, 260
    left, right, top, bottom = 145, 30, 35, 65
    lanes = ["local/gateway", "upstream/internet", "unknown"]
    colors = {
        "local/gateway": "#dc2626",
        "upstream/internet": "#f59e0b",
        "unknown": "#64748b",
    }
    start_ts = first_time.timestamp()
    end_ts = max(last_time.timestamp(), start_ts + 1)
    duration = end_ts - start_ts
    lane_height = (height - top - bottom) / len(lanes)

    def x_position(when: dt.datetime) -> float:
        return left + (when.timestamp() - start_ts) / duration * (width - left - right)

    lane_backgrounds = []
    lane_labels = []
    for index, lane in enumerate(lanes):
        y_value = top + index * lane_height
        lane_backgrounds.append(
            f'<rect x="{left}" y="{y_value:.1f}" width="{width - left - right}" '
            f'height="{lane_height:.1f}" fill="{"#f8fafc" if index % 2 == 0 else "#eef2ff"}"/>'
        )
        lane_labels.append(
            f'<text x="{left - 10}" y="{y_value + lane_height / 2 + 4:.1f}" '
            f'font-family="sans-serif" font-size="12" text-anchor="end">{html.escape(lane)}</text>'
        )

    outage_marks = []
    inspect_points = []
    for outage in outages:
        original_classification = str(outage.get("classification", "unknown"))
        classification = original_classification.replace(" (ongoing at report time)", "")
        classification = classification.replace(" (ended at monitoring gap)", "")
        if classification not in lanes:
            classification = "unknown"
        start = parse_time(str(outage["start"]))
        end = parse_time(str(outage["end"]))
        lane_index = lanes.index(classification)
        x_start = x_position(start)
        x_end = max(x_start + 2, x_position(end))
        y_start = top + lane_index * lane_height + 8
        outage_marks.append(
            f'<rect x="{x_start:.1f}" y="{y_start:.1f}" width="{x_end - x_start:.1f}" '
            f'height="{lane_height - 16:.1f}" fill="{colors[classification]}" opacity="0.85">'
            f'<title>{html.escape(classification)} {html.escape(str(outage["start"]))} '
            f'for {fmt_duration(float(outage["duration_seconds"]))}</title></rect>'
        )
        midpoint = start + (end - start) / 2
        inspect_points.append(
            {
                "x": round(x_position(midpoint), 1),
                "y": round(y_start + (lane_height - 16) / 2, 1),
                "color": colors[classification],
                "lines": [
                    html.unescape(original_classification),
                    f"{local_time_label(start, duration)} - {local_time_label(end, duration)}",
                    f"Duration: {fmt_duration(float(outage['duration_seconds']))}",
                ],
            }
        )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">
<rect width="{width}" height="{height}" fill="white"/>
<text x="{left}" y="22" font-family="sans-serif" font-size="15">Outage timeline</text>
{"".join(lane_backgrounds)}
{"".join(lane_labels)}
<line x1="{left}" y1="{height - bottom}" x2="{width - right}" y2="{height - bottom}" stroke="#64748b"/>
{svg_time_ticks(first_time, last_time, width, height, left, right, bottom)}
{"".join(outage_marks)}
{svg_inspector(inspect_points, width, height, left, right, top, bottom, tooltip_width=330)}
</svg>
"""
    path.write_text(svg, encoding="utf-8")


def write_hourly_loss_svg(path: pathlib.Path, hourly_rows: list[dict[str, Any]], labels: list[str]) -> None:
    if not hourly_rows:
        return
    width, height = 1200, 340
    left, right, top, bottom = 70, 180, 35, 75
    colors = ["#111827", "#2563eb", "#16a34a", "#f59e0b", "#7c3aed", "#dc2626"]
    first = parse_time(str(hourly_rows[0]["hour_start"]))
    last = parse_time(str(hourly_rows[-1]["hour_start"])) + dt.timedelta(hours=1)
    start_ts = first.timestamp()
    end_ts = max(last.timestamp(), start_ts + 1)
    duration = end_ts - start_ts
    max_loss = max(float(row["packet_loss_percent"]) for row in hourly_rows) if hourly_rows else 0
    ceiling = max(5.0, min(100.0, math.ceil(max_loss + 1)))

    def x_position(when: dt.datetime) -> float:
        return left + (when.timestamp() - start_ts) / duration * (width - left - right)

    def y_position(loss: float) -> float:
        return top + (1 - min(loss, ceiling) / ceiling) * (height - top - bottom)

    by_label: dict[str, list[dict[str, Any]]] = {label: [] for label in labels}
    for row in hourly_rows:
        by_label.setdefault(str(row["label"]), []).append(
            {
                "when": parse_time(str(row["hour_start"])) + dt.timedelta(minutes=30),
                "loss": float(row["packet_loss_percent"]),
                "samples": int(row["samples"]),
            }
        )

    lines = []
    legend = []
    inspect_points = []
    for index, label in enumerate(labels):
        points = by_label.get(label, [])
        if not points:
            continue
        color = colors[index % len(colors)]
        polyline = " ".join(
            f"{x_position(point['when']):.1f},{y_position(point['loss']):.1f}" for point in points
        )
        lines.append(f'<polyline points="{polyline}" fill="none" stroke="{color}" stroke-width="2"/>')
        for point in points:
            inspect_points.append(
                {
                    "x": round(x_position(point["when"]), 1),
                    "y": round(y_position(point["loss"]), 1),
                    "color": color,
                    "lines": [
                        str(label),
                        local_time_label(point["when"], duration),
                        f"Packet loss: {point['loss']:.2f}%",
                        f"Samples: {point['samples']}",
                    ],
                }
            )
        legend_y = top + index * 20
        legend.append(f'<rect x="{width - right + 25}" y="{legend_y - 10}" width="12" height="12" fill="{color}"/>')
        legend.append(
            f'<text x="{width - right + 43}" y="{legend_y}" font-family="sans-serif" font-size="12">'
            f'{html.escape(label)}</text>'
        )

    y_grid = []
    for value in (0, ceiling / 2, ceiling):
        y_value = y_position(value)
        y_grid.append(f'<line x1="{left}" y1="{y_value:.1f}" x2="{width - right}" y2="{y_value:.1f}" stroke="#e2e8f0"/>')
        y_grid.append(
            f'<text x="{left - 8}" y="{y_value + 4:.1f}" font-family="sans-serif" font-size="12" '
            f'text-anchor="end">{value:.1f}%</text>'
        )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">
<rect width="{width}" height="{height}" fill="white"/>
<text x="{left}" y="22" font-family="sans-serif" font-size="15">Packet loss by hour</text>
{"".join(y_grid)}
<line x1="{left}" y1="{height - bottom}" x2="{width - right}" y2="{height - bottom}" stroke="#64748b"/>
<line x1="{left}" y1="{top}" x2="{left}" y2="{height - bottom}" stroke="#64748b"/>
{svg_time_ticks(first, last, width, height, left, right, bottom)}
{"".join(lines)}
{"".join(legend)}
{svg_inspector(inspect_points, width, height, left, right, top, bottom, tooltip_width=280)}
</svg>
"""
    path.write_text(svg, encoding="utf-8")


def write_throughput_svg(path: pathlib.Path, throughput_rows: list[dict[str, Any]]) -> None:
    if not throughput_rows:
        return
    width, height = 1200, 460
    left, right, top, bottom = 100, 155, 40, 82
    panel_gap = 34
    panel_height = (height - top - bottom - panel_gap) / 2
    rows = [
        row for row in throughput_rows
        if row.get("timestamp") and (row.get("mbps") is not None or row.get("success") is False)
    ]
    if not rows:
        return
    first = parse_time(str(rows[0]["timestamp"]))
    last = parse_time(str(rows[-1].get("ended_at") or rows[-1]["timestamp"]))
    start_ts = first.timestamp()
    end_ts = max(last.timestamp(), start_ts + 1)
    duration = end_ts - start_ts
    max_mbps = max((float(row["mbps"]) for row in rows if row.get("mbps") is not None), default=1)
    max_retransmits = max((int(row["retransmits"]) for row in rows if row.get("retransmits") is not None), default=0)
    mbps_ceiling = max(10.0, math.ceil(max_mbps * 1.1))
    retransmit_ceiling = max(1, math.ceil(max_retransmits * 1.1))

    def x_position(when: dt.datetime) -> float:
        return left + (when.timestamp() - start_ts) / duration * (width - left - right)

    def panel_top(direction: str) -> float:
        return top if direction == "upload" else top + panel_height + panel_gap

    def panel_bottom(direction: str) -> float:
        return panel_top(direction) + panel_height

    def y_mbps(value: float, direction: str) -> float:
        return panel_top(direction) + (1 - min(value, mbps_ceiling) / mbps_ceiling) * panel_height

    def y_retransmits(value: int, direction: str) -> float:
        return panel_top(direction) + (1 - min(value, retransmit_ceiling) / retransmit_ceiling) * panel_height

    bar_width = 12
    colors = {"upload": "#2563eb", "download": "#16a34a"}
    labels = {"upload": "UPLOAD", "download": "DOWNLOAD"}
    bars = []
    throughput_points: dict[str, list[tuple[float, float]]] = {"upload": [], "download": []}
    retransmit_points: dict[str, list[tuple[float, float, int]]] = {"upload": [], "download": []}
    inspect_points = []
    for row in rows:
        when = parse_time(str(row["timestamp"]))
        x_value = x_position(when)
        direction = str(row.get("direction"))
        if direction not in colors:
            continue
        color = colors[direction]
        if row.get("mbps") is not None:
            y_value = y_mbps(float(row["mbps"]), direction)
            throughput_points[direction].append((x_value, y_value))
            bars.append(
                f'<rect x="{x_value - bar_width / 2:.1f}" y="{y_value:.1f}" width="{bar_width}" '
                f'height="{panel_bottom(direction) - y_value:.1f}" fill="{color}" opacity="0.65">'
                f'<title>{html.escape(labels[direction])}: {row["mbps"]} Mbps at '
                f'{html.escape(local_time_label(when, duration))}</title></rect>'
            )
            detail_lines = [
                labels[direction],
                local_time_label(when, duration),
                f"Throughput: {float(row['mbps']):.2f} Mbps",
            ]
            if row.get("retransmits") is not None:
                detail_lines.append(f"TCP retransmits: {int(row['retransmits'])}")
            if row.get("seconds") is not None:
                detail_lines.append(f"Duration: {float(row['seconds']):.1f}s")
            inspect_points.append(
                {
                    "x": round(x_value, 1),
                    "y": round(y_value, 1),
                    "color": color,
                    "lines": detail_lines,
                }
            )
        else:
            failed_y = panel_bottom(direction) - 8
            bars.append(
                f'<text x="{x_value:.1f}" y="{failed_y:.1f}" '
                f'font-family="sans-serif" font-size="18" fill="#dc2626" text-anchor="middle">x'
                f'<title>FAILED {html.escape(labels[direction])} at '
                f'{html.escape(local_time_label(when, duration))}</title></text>'
            )
            inspect_points.append(
                {
                    "x": round(x_value, 1),
                    "y": round(failed_y, 1),
                    "color": "#dc2626",
                    "lines": [
                        f"FAILED {labels[direction]}",
                        local_time_label(when, duration),
                        "No throughput result",
                    ],
                }
            )
        retransmits = row.get("retransmits")
        if retransmits is not None:
            retransmit_points[direction].append((x_value, y_retransmits(int(retransmits), direction), int(retransmits)))

    panel_backgrounds = []
    y_grid = []
    for direction in ("upload", "download"):
        y_top = panel_top(direction)
        y_bottom = panel_bottom(direction)
        panel_backgrounds.append(
            f'<rect x="{left}" y="{y_top:.1f}" width="{width - left - right}" height="{panel_height:.1f}" '
            f'fill="{"#eff6ff" if direction == "upload" else "#f0fdf4"}"/>'
        )
        panel_backgrounds.append(
            f'<text x="{left - 14}" y="{y_top + panel_height / 2 + 5:.1f}" '
            f'font-family="sans-serif" font-size="14" font-weight="700" fill="{colors[direction]}" '
            f'text-anchor="end">{labels[direction]}</text>'
        )
        for value in (0, mbps_ceiling / 2, mbps_ceiling):
            y_value = y_mbps(value, direction)
            y_grid.append(
                f'<line x1="{left}" y1="{y_value:.1f}" x2="{width - right}" y2="{y_value:.1f}" stroke="#dbeafe"/>'
            )
            y_grid.append(
                f'<text x="{left - 8}" y="{y_value + 4:.1f}" font-family="sans-serif" font-size="11" '
                f'text-anchor="end">{value:.0f}</text>'
            )
        for value in (0, retransmit_ceiling):
            y_value = y_retransmits(value, direction)
            y_grid.append(
                f'<text x="{width - right + 8}" y="{y_value + 4:.1f}" font-family="sans-serif" font-size="11">'
                f'{value}</text>'
            )
        y_grid.append(f'<line x1="{left}" y1="{y_bottom:.1f}" x2="{width - right}" y2="{y_bottom:.1f}" stroke="#64748b"/>')
        y_grid.append(f'<line x1="{left}" y1="{y_top:.1f}" x2="{left}" y2="{y_bottom:.1f}" stroke="#64748b"/>')
        y_grid.append(f'<line x1="{width - right}" y1="{y_top:.1f}" x2="{width - right}" y2="{y_bottom:.1f}" stroke="#64748b"/>')

    throughput_lines = []
    for direction, points in throughput_points.items():
        if len(points) < 2:
            continue
        point_text = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
        throughput_lines.append(
            f'<polyline points="{point_text}" fill="none" stroke="{colors[direction]}" stroke-width="3"/>'
        )

    retransmit_lines = []
    for direction, points in retransmit_points.items():
        if not points:
            continue
        if len(points) > 1:
            point_text = " ".join(f"{x:.1f},{y:.1f}" for x, y, _ in points)
            retransmit_lines.append(
                f'<polyline points="{point_text}" fill="none" stroke="#dc2626" stroke-width="2" stroke-dasharray="5 4"/>'
            )
        retransmit_lines.append(
            "".join(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="#dc2626">'
                f'<title>{html.escape(labels[direction])}: {value} retransmits</title></circle>'
                for x, y, value in points
            )
        )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">
<rect width="{width}" height="{height}" fill="white"/>
<text x="{left}" y="24" font-family="sans-serif" font-size="15">VPS throughput and TCP retransmits</text>
<text x="{left - 8}" y="37" font-family="sans-serif" font-size="11" text-anchor="end">Mbps</text>
<text x="{width - right + 8}" y="37" font-family="sans-serif" font-size="11">retransmits</text>
{"".join(panel_backgrounds)}
{"".join(y_grid)}
{svg_time_ticks(first, last, width, height, left, right, bottom)}
{"".join(bars)}
{"".join(throughput_lines)}
{"".join(retransmit_lines)}
<rect x="{width - right + 24}" y="{top + 58}" width="12" height="12" fill="#2563eb" opacity="0.65"/><text x="{width - right + 42}" y="{top + 68}" font-family="sans-serif" font-size="12">upload Mbps</text>
<rect x="{width - right + 24}" y="{top + 78}" width="12" height="12" fill="#16a34a" opacity="0.65"/><text x="{width - right + 42}" y="{top + 88}" font-family="sans-serif" font-size="12">download Mbps</text>
<line x1="{width - right + 24}" y1="{top + 106}" x2="{width - right + 36}" y2="{top + 106}" stroke="#dc2626" stroke-width="2" stroke-dasharray="5 4"/><circle cx="{width - right + 30}" cy="{top + 106}" r="4" fill="#dc2626"/><text x="{width - right + 42}" y="{top + 110}" font-family="sans-serif" font-size="12">TCP retransmits</text>
{svg_inspector(inspect_points, width, height, left, right, top, bottom, tooltip_width=300)}
</svg>
"""
    path.write_text(svg, encoding="utf-8")


def write_wifi_gateway_svg(path: pathlib.Path, rows: list[dict[str, Any]]) -> None:
    rows = [row for row in rows if row.get("gateway_p95_ms") is not None or row.get("wifi_avg_dbm") is not None]
    if not rows:
        return
    width, height = 1200, 360
    left, right, top, bottom = 75, 105, 35, 75
    first = parse_time(str(rows[0]["bucket_start"]))
    last = parse_time(str(rows[-1]["bucket_start"])) + dt.timedelta(minutes=10)
    start_ts = first.timestamp()
    end_ts = max(last.timestamp(), start_ts + 1)
    duration = end_ts - start_ts
    max_latency = max((float(row["gateway_p95_ms"]) for row in rows if row.get("gateway_p95_ms") is not None), default=10)
    latency_ceiling = max(10.0, math.ceil(max_latency * 1.1))
    signals = [float(row["wifi_avg_dbm"]) for row in rows if row.get("wifi_avg_dbm") is not None]
    signal_min = min(-90.0, min(signals) - 5) if signals else -90.0
    signal_max = max(-30.0, max(signals) + 5) if signals else -30.0

    def x_position(when: dt.datetime) -> float:
        return left + (when.timestamp() - start_ts) / duration * (width - left - right)

    def y_latency(value: float) -> float:
        return top + (1 - min(value, latency_ceiling) / latency_ceiling) * (height - top - bottom)

    def y_signal(value: float) -> float:
        return top + (signal_max - value) / (signal_max - signal_min) * (height - top - bottom)

    gateway_points = []
    signal_points = []
    loss_marks = []
    inspect_points = []
    for row in rows:
        when = parse_time(str(row["bucket_start"])) + dt.timedelta(minutes=5)
        x_value = x_position(when)
        if row.get("gateway_p95_ms") is not None:
            latency = float(row["gateway_p95_ms"])
            y_value = y_latency(latency)
            gateway_points.append((x_value, y_value))
            inspect_points.append(
                {
                    "x": round(x_value, 1),
                    "y": round(y_value, 1),
                    "color": "#2563eb",
                    "lines": [
                        "Gateway latency",
                        local_time_label(when, duration),
                        f"p95: {latency:.1f} ms",
                        f"Loss: {fmt_number(row.get('gateway_loss_percent'))}%",
                        f"Samples: {row.get('gateway_samples', 'n/a')}",
                    ],
                }
            )
        if row.get("wifi_avg_dbm") is not None:
            signal = float(row["wifi_avg_dbm"])
            y_value = y_signal(signal)
            signal_points.append((x_value, y_value))
            inspect_points.append(
                {
                    "x": round(x_value, 1),
                    "y": round(y_value, 1),
                    "color": "#16a34a",
                    "lines": [
                        "Wi-Fi signal",
                        local_time_label(when, duration),
                        f"Average: {signal:.1f} dBm",
                        f"Minimum: {fmt_number(row.get('wifi_min_dbm'))} dBm",
                        f"Gateway loss: {fmt_number(row.get('gateway_loss_percent'))}%",
                    ],
                }
            )
        loss = row.get("gateway_loss_percent")
        if loss is not None and float(loss) > 0:
            loss_marks.append(
                f'<line x1="{x_value:.1f}" y1="{top}" x2="{x_value:.1f}" y2="{height - bottom}" '
                f'stroke="#dc2626" opacity="{min(0.9, 0.2 + float(loss) / 20):.2f}" stroke-width="2">'
                f'<title>{float(loss):.2f}% gateway loss</title></line>'
            )

    gateway_line = " ".join(f"{x:.1f},{y:.1f}" for x, y in gateway_points)
    signal_line = " ".join(f"{x:.1f},{y:.1f}" for x, y in signal_points)

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">
<rect width="{width}" height="{height}" fill="white"/>
<text x="{left}" y="22" font-family="sans-serif" font-size="15">Wi-Fi signal vs gateway latency</text>
{"".join(loss_marks)}
<line x1="{left}" y1="{height - bottom}" x2="{width - right}" y2="{height - bottom}" stroke="#64748b"/>
<line x1="{left}" y1="{top}" x2="{left}" y2="{height - bottom}" stroke="#64748b"/>
<line x1="{width - right}" y1="{top}" x2="{width - right}" y2="{height - bottom}" stroke="#64748b"/>
<text x="{left - 8}" y="{top + 4}" font-family="sans-serif" font-size="12" text-anchor="end">{latency_ceiling:.0f} ms</text>
<text x="{width - right + 8}" y="{top + 4}" font-family="sans-serif" font-size="12">{signal_max:.0f} dBm</text>
<text x="{width - right + 8}" y="{height - bottom + 4}" font-family="sans-serif" font-size="12">{signal_min:.0f} dBm</text>
{svg_time_ticks(first, last, width, height, left, right, bottom)}
<polyline points="{gateway_line}" fill="none" stroke="#2563eb" stroke-width="2"/>
<polyline points="{signal_line}" fill="none" stroke="#16a34a" stroke-width="2"/>
<rect x="{width - right + 20}" y="{top + 24}" width="12" height="12" fill="#2563eb"/><text x="{width - right + 38}" y="{top + 34}" font-family="sans-serif" font-size="12">gateway p95</text>
<rect x="{width - right + 20}" y="{top + 44}" width="12" height="12" fill="#16a34a"/><text x="{width - right + 38}" y="{top + 54}" font-family="sans-serif" font-size="12">Wi-Fi dBm</text>
<line x1="{width - right + 20}" y1="{top + 68}" x2="{width - right + 32}" y2="{top + 68}" stroke="#dc2626" stroke-width="2"/><text x="{width - right + 38}" y="{top + 72}" font-family="sans-serif" font-size="12">gateway loss</text>
{svg_inspector(inspect_points, width, height, left, right, top, bottom, tooltip_width=300)}
</svg>
"""
    path.write_text(svg, encoding="utf-8")


def series_color(index: int) -> str:
    colors = ["#2563eb", "#16a34a", "#f59e0b", "#7c3aed", "#0f766e", "#db2777", "#111827"]
    return colors[index % len(colors)]


def write_service_timeseries_svg(
    path: pathlib.Path,
    title: str,
    rows: list[dict[str, Any]],
    value_key: str,
    *,
    unit: str,
    y_label: str,
) -> None:
    rows = [row for row in rows if row.get("timestamp")]
    if not rows:
        return
    rows = sorted(rows, key=lambda row: str(row["timestamp"]))
    width, height = 1200, 360
    left, right, top, bottom = 80, 190, 35, 75
    first = parse_time(str(rows[0]["timestamp"]))
    last = parse_time(str(rows[-1]["timestamp"]))
    start_ts = first.timestamp()
    end_ts = max(last.timestamp(), start_ts + 1)
    duration = end_ts - start_ts
    labels = list(dict.fromkeys(str(row.get("label", "unknown")) for row in rows))
    values = [float(row[value_key]) for row in rows if row.get(value_key) is not None]
    ceiling = max(1.0, math.ceil((percentile(values, 99) or max(values, default=1)) * 1.25))

    def x_position(when: dt.datetime) -> float:
        return left + (when.timestamp() - start_ts) / duration * (width - left - right)

    def y_position(value: float) -> float:
        return top + (1 - min(value, ceiling) / ceiling) * (height - top - bottom)

    lines = []
    marks = []
    legend = []
    inspect_points = []
    for label_index, label in enumerate(labels):
        color = series_color(label_index)
        label_rows = [row for row in rows if str(row.get("label", "unknown")) == label]
        success_points = []
        for row in label_rows:
            when = parse_time(str(row["timestamp"]))
            x_value = x_position(when)
            success = bool(row.get("success"))
            value = row.get(value_key)
            if success and value is not None:
                y_value = y_position(float(value))
                success_points.append((x_value, y_value))
                marks.append(f'<circle cx="{x_value:.1f}" cy="{y_value:.1f}" r="2.5" fill="{color}" opacity="0.75"/>')
                detail = f"{float(value):.1f} {unit}"
            else:
                y_value = height - bottom - 4
                marks.append(
                    f'<text x="{x_value:.1f}" y="{y_value:.1f}" font-family="sans-serif" font-size="16" '
                    f'fill="#dc2626" text-anchor="middle">x</text>'
                )
                detail = "failed"
            extra = []
            if row.get("status"):
                extra.append(f"Status: {row['status']}")
            if row.get("http_code") is not None:
                extra.append(f"HTTP: {row['http_code']}")
            inspect_points.append(
                {
                    "x": round(x_value, 1),
                    "y": round(y_value, 1),
                    "color": "#dc2626" if not success else color,
                    "lines": [
                        label,
                        local_time_label(when, duration),
                        detail,
                        *extra[:2],
                    ],
                }
            )
        if len(success_points) > 1:
            point_text = " ".join(f"{x:.1f},{y:.1f}" for x, y in success_points)
            lines.append(f'<polyline points="{point_text}" fill="none" stroke="{color}" stroke-width="2"/>')
        legend_y = top + label_index * 20
        legend.append(f'<rect x="{width - right + 24}" y="{legend_y - 10}" width="12" height="12" fill="{color}"/>')
        legend.append(
            f'<text x="{width - right + 42}" y="{legend_y}" font-family="sans-serif" font-size="12">'
            f'{html.escape(label)}</text>'
        )

    grid = []
    for value in (0, ceiling / 2, ceiling):
        y_value = y_position(value)
        grid.append(f'<line x1="{left}" y1="{y_value:.1f}" x2="{width - right}" y2="{y_value:.1f}" stroke="#e2e8f0"/>')
        grid.append(
            f'<text x="{left - 8}" y="{y_value + 4:.1f}" font-family="sans-serif" font-size="12" '
            f'text-anchor="end">{value:.0f}</text>'
        )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">
<rect width="{width}" height="{height}" fill="white"/>
<text x="{left}" y="22" font-family="sans-serif" font-size="15">{html.escape(title)}</text>
<text x="{left - 8}" y="{top - 4}" font-family="sans-serif" font-size="12" text-anchor="end">{html.escape(y_label)}</text>
{"".join(grid)}
<line x1="{left}" y1="{height - bottom}" x2="{width - right}" y2="{height - bottom}" stroke="#64748b"/>
<line x1="{left}" y1="{top}" x2="{left}" y2="{height - bottom}" stroke="#64748b"/>
{svg_time_ticks(first, last, width, height, left, right, bottom)}
{"".join(lines)}
{"".join(marks)}
{"".join(legend)}
{svg_inspector(inspect_points, width, height, left, right, top, bottom, tooltip_width=330)}
</svg>
"""
    path.write_text(svg, encoding="utf-8")


def write_link_counters_svg(path: pathlib.Path, rows: list[dict[str, Any]]) -> None:
    rows = [row for row in rows if row.get("timestamp")]
    if len(rows) < 2:
        return
    rows = sorted(rows, key=lambda row: str(row["timestamp"]))
    intervals = []
    previous = rows[0]
    for row in rows[1:]:
        start = parse_time(str(previous["timestamp"]))
        end = parse_time(str(row["timestamp"]))
        seconds = max(0.001, (end - start).total_seconds())
        rx_bytes = int(row.get("rx_bytes") or 0) - int(previous.get("rx_bytes") or 0)
        tx_bytes = int(row.get("tx_bytes") or 0) - int(previous.get("tx_bytes") or 0)
        rx_packets = int(row.get("rx_packets") or 0) - int(previous.get("rx_packets") or 0)
        tx_packets = int(row.get("tx_packets") or 0) - int(previous.get("tx_packets") or 0)
        rx_errors = max(0, int(row.get("rx_errors") or 0) - int(previous.get("rx_errors") or 0))
        tx_errors = max(0, int(row.get("tx_errors") or 0) - int(previous.get("tx_errors") or 0))
        rx_dropped = max(0, int(row.get("rx_dropped") or 0) - int(previous.get("rx_dropped") or 0))
        tx_dropped = max(0, int(row.get("tx_dropped") or 0) - int(previous.get("tx_dropped") or 0))
        intervals.append(
            {
                "timestamp": row["timestamp"],
                "rx_mbps": max(0.0, rx_bytes * 8 / seconds / 1_000_000),
                "tx_mbps": max(0.0, tx_bytes * 8 / seconds / 1_000_000),
                "rx_pps": max(0.0, rx_packets / seconds),
                "tx_pps": max(0.0, tx_packets / seconds),
                "errors": rx_errors + tx_errors,
                "drops": rx_dropped + tx_dropped,
            }
        )
        previous = row
    if not intervals:
        return

    width, height = 1200, 430
    left, right, top, bottom = 85, 140, 35, 75
    panel_gap = 32
    panel_height = (height - top - bottom - panel_gap) / 2
    first = parse_time(str(intervals[0]["timestamp"]))
    last = parse_time(str(intervals[-1]["timestamp"]))
    start_ts = first.timestamp()
    end_ts = max(last.timestamp(), start_ts + 1)
    duration = end_ts - start_ts
    max_mbps = max(max(float(row["rx_mbps"]), float(row["tx_mbps"])) for row in intervals)
    max_faults = max(max(int(row["errors"]), int(row["drops"])) for row in intervals)
    mbps_ceiling = max(1.0, math.ceil(max_mbps * 1.15))
    fault_ceiling = max(1, math.ceil(max_faults * 1.15))

    def x_position(when: dt.datetime) -> float:
        return left + (when.timestamp() - start_ts) / duration * (width - left - right)

    def y_rate(value: float) -> float:
        return top + (1 - min(value, mbps_ceiling) / mbps_ceiling) * panel_height

    def y_fault(value: float) -> float:
        panel_top = top + panel_height + panel_gap
        return panel_top + (1 - min(value, fault_ceiling) / fault_ceiling) * panel_height

    rx_points = []
    tx_points = []
    error_points = []
    drop_points = []
    inspect_points = []
    for row in intervals:
        when = parse_time(str(row["timestamp"]))
        x_value = x_position(when)
        rx_y = y_rate(float(row["rx_mbps"]))
        tx_y = y_rate(float(row["tx_mbps"]))
        err_y = y_fault(float(row["errors"]))
        drop_y = y_fault(float(row["drops"]))
        rx_points.append((x_value, rx_y))
        tx_points.append((x_value, tx_y))
        error_points.append((x_value, err_y))
        drop_points.append((x_value, drop_y))
        inspect_points.append(
            {
                "x": round(x_value, 1),
                "y": round(rx_y, 1),
                "color": "#2563eb",
                "lines": [
                    "Link counters",
                    local_time_label(when, duration),
                    f"RX/TX: {row['rx_mbps']:.2f}/{row['tx_mbps']:.2f} Mbps",
                    f"RX/TX pps: {row['rx_pps']:.0f}/{row['tx_pps']:.0f}",
                    f"Errors/Drops: {row['errors']}/{row['drops']}",
                ],
            }
        )

    def polyline(points: list[tuple[float, float]], color: str, dash: str = "") -> str:
        text = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        return f'<polyline points="{text}" fill="none" stroke="{color}" stroke-width="2"{dash_attr}/>'

    rate_bottom = top + panel_height
    fault_top = top + panel_height + panel_gap
    fault_bottom = fault_top + panel_height
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">
<rect width="{width}" height="{height}" fill="white"/>
<text x="{left}" y="22" font-family="sans-serif" font-size="15">Local interface counters</text>
<rect x="{left}" y="{top}" width="{width - left - right}" height="{panel_height}" fill="#eff6ff"/>
<rect x="{left}" y="{fault_top}" width="{width - left - right}" height="{panel_height}" fill="#fff7ed"/>
<line x1="{left}" y1="{rate_bottom}" x2="{width - right}" y2="{rate_bottom}" stroke="#64748b"/>
<line x1="{left}" y1="{fault_bottom}" x2="{width - right}" y2="{fault_bottom}" stroke="#64748b"/>
<line x1="{left}" y1="{top}" x2="{left}" y2="{fault_bottom}" stroke="#64748b"/>
<text x="{left - 8}" y="{top + 4}" font-family="sans-serif" font-size="12" text-anchor="end">{mbps_ceiling:.0f} Mbps</text>
<text x="{left - 8}" y="{fault_top + 4}" font-family="sans-serif" font-size="12" text-anchor="end">{fault_ceiling} faults</text>
{svg_time_ticks(first, last, width, height, left, right, bottom)}
{polyline(rx_points, "#2563eb")}
{polyline(tx_points, "#16a34a")}
{polyline(error_points, "#dc2626", "5 4")}
{polyline(drop_points, "#f59e0b", "5 4")}
<rect x="{width - right + 20}" y="{top + 20}" width="12" height="12" fill="#2563eb"/><text x="{width - right + 38}" y="{top + 30}" font-family="sans-serif" font-size="12">RX Mbps</text>
<rect x="{width - right + 20}" y="{top + 40}" width="12" height="12" fill="#16a34a"/><text x="{width - right + 38}" y="{top + 50}" font-family="sans-serif" font-size="12">TX Mbps</text>
<line x1="{width - right + 20}" y1="{top + 70}" x2="{width - right + 32}" y2="{top + 70}" stroke="#dc2626" stroke-width="2" stroke-dasharray="5 4"/><text x="{width - right + 38}" y="{top + 74}" font-family="sans-serif" font-size="12">errors</text>
<line x1="{width - right + 20}" y1="{top + 90}" x2="{width - right + 32}" y2="{top + 90}" stroke="#f59e0b" stroke-width="2" stroke-dasharray="5 4"/><text x="{width - right + 38}" y="{top + 94}" font-family="sans-serif" font-size="12">drops</text>
{svg_inspector(inspect_points, width, height, left, right, top, bottom, tooltip_width=340)}
</svg>
"""
    path.write_text(svg, encoding="utf-8")


def write_timeline_events_svg(
    path: pathlib.Path,
    rows: list[dict[str, Any]],
    first_time: dt.datetime | None,
    last_time: dt.datetime | None,
) -> None:
    if not first_time or not last_time or not rows:
        return
    width, height = 1200, 310
    left, right, top, bottom = 150, 35, 35, 70
    lanes = ["public_ip", "default_route", "monitoring_gap"]
    labels = {"public_ip": "Public IP", "default_route": "Default route", "monitoring_gap": "Monitor gap"}
    colors = {"public_ip": "#2563eb", "default_route": "#16a34a", "monitoring_gap": "#dc2626"}
    start_ts = first_time.timestamp()
    end_ts = max(last_time.timestamp(), start_ts + 1)
    duration = end_ts - start_ts
    lane_height = (height - top - bottom) / len(lanes)

    def x_position(when: dt.datetime) -> float:
        return left + (when.timestamp() - start_ts) / duration * (width - left - right)

    lane_markup = []
    marks = []
    inspect_points = []
    for index, lane in enumerate(lanes):
        y_value = top + index * lane_height
        lane_markup.append(
            f'<rect x="{left}" y="{y_value:.1f}" width="{width - left - right}" height="{lane_height:.1f}" '
            f'fill="{"#f8fafc" if index % 2 == 0 else "#eef2ff"}"/>'
        )
        lane_markup.append(
            f'<text x="{left - 10}" y="{y_value + lane_height / 2 + 4:.1f}" font-family="sans-serif" '
            f'font-size="12" text-anchor="end">{labels[lane]}</text>'
        )
    for row in rows:
        kind = str(row.get("kind"))
        if kind not in lanes:
            continue
        when = parse_time(str(row["timestamp"]))
        x_value = x_position(when)
        lane_index = lanes.index(kind)
        y_value = top + lane_index * lane_height + lane_height / 2
        value = str(row.get("value", ""))
        detail = str(row.get("detail", ""))
        if kind == "monitoring_gap" and row.get("end"):
            end = parse_time(str(row["end"]))
            x_end = max(x_value + 2, x_position(end))
            marks.append(
                f'<rect x="{x_value:.1f}" y="{y_value - 9:.1f}" width="{x_end - x_value:.1f}" height="18" '
                f'fill="{colors[kind]}" opacity="0.8"/>'
            )
            point_x = (x_value + x_end) / 2
        else:
            marks.append(f'<circle cx="{x_value:.1f}" cy="{y_value:.1f}" r="6" fill="{colors[kind]}" opacity="0.85"/>')
            point_x = x_value
        inspect_points.append(
            {
                "x": round(point_x, 1),
                "y": round(y_value, 1),
                "color": colors[kind],
                "lines": [
                    labels[kind],
                    local_time_label(when, duration),
                    value[:72] or "sample recorded",
                    detail[:72],
                ],
            }
        )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">
<rect width="{width}" height="{height}" fill="white"/>
<text x="{left}" y="22" font-family="sans-serif" font-size="15">Public IP, default route, and monitor gaps</text>
{"".join(lane_markup)}
<line x1="{left}" y1="{height - bottom}" x2="{width - right}" y2="{height - bottom}" stroke="#64748b"/>
{svg_time_ticks(first_time, last_time, width, height, left, right, bottom)}
{"".join(marks)}
{svg_inspector(inspect_points, width, height, left, right, top, bottom, tooltip_width=390)}
</svg>
"""
    path.write_text(svg, encoding="utf-8")


def write_mtr_quality_svg(path: pathlib.Path, mtr_rows: list[dict[str, Any]]) -> None:
    if not mtr_rows:
        return
    snapshots: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in mtr_rows:
        if row.get("timestamp") and row.get("target"):
            snapshots.setdefault((str(row["timestamp"]), str(row["target"])), []).append(row)
    quality_rows = []
    for (timestamp, target), hops in snapshots.items():
        sorted_hops = sorted(hops, key=lambda row: int(row.get("hop") or 0))
        destination = sorted_hops[-1]
        max_loss_hop = max(sorted_hops, key=lambda row: float(row.get("loss_percent") or 0))
        quality_rows.append(
            {
                "timestamp": timestamp,
                "target": target,
                "destination_avg_ms": destination.get("average_ms"),
                "destination_loss_percent": destination.get("loss_percent"),
                "max_hop_loss_percent": max_loss_hop.get("loss_percent"),
                "max_hop": max_loss_hop.get("hop"),
                "max_hop_host": max_loss_hop.get("host"),
            }
        )
    quality_rows = sorted(quality_rows, key=lambda row: str(row["timestamp"]))
    if not quality_rows:
        return

    width, height = 1200, 420
    left, right, top, bottom = 85, 175, 35, 75
    panel_gap = 32
    panel_height = (height - top - bottom - panel_gap) / 2
    first = parse_time(str(quality_rows[0]["timestamp"]))
    last = parse_time(str(quality_rows[-1]["timestamp"]))
    start_ts = first.timestamp()
    end_ts = max(last.timestamp(), start_ts + 1)
    duration = end_ts - start_ts
    targets = list(dict.fromkeys(str(row["target"]) for row in quality_rows))
    latency_values = [float(row["destination_avg_ms"]) for row in quality_rows if row.get("destination_avg_ms") is not None]
    latency_ceiling = max(10.0, math.ceil((percentile(latency_values, 99) or max(latency_values, default=10)) * 1.25))

    def x_position(when: dt.datetime) -> float:
        return left + (when.timestamp() - start_ts) / duration * (width - left - right)

    def y_latency(value: float) -> float:
        return top + (1 - min(value, latency_ceiling) / latency_ceiling) * panel_height

    def y_loss(value: float) -> float:
        panel_top = top + panel_height + panel_gap
        return panel_top + (1 - min(value, 100) / 100) * panel_height

    lines = []
    marks = []
    legend = []
    inspect_points = []
    for target_index, target in enumerate(targets):
        color = series_color(target_index)
        points = []
        for row in quality_rows:
            if str(row["target"]) != target:
                continue
            when = parse_time(str(row["timestamp"]))
            x_value = x_position(when)
            if row.get("destination_avg_ms") is not None:
                y_value = y_latency(float(row["destination_avg_ms"]))
                points.append((x_value, y_value))
                marks.append(f'<circle cx="{x_value:.1f}" cy="{y_value:.1f}" r="3" fill="{color}"/>')
                inspect_points.append(
                    {
                        "x": round(x_value, 1),
                        "y": round(y_value, 1),
                        "color": color,
                        "lines": [
                            f"MTR {target}",
                            local_time_label(when, duration),
                            f"Destination avg: {float(row['destination_avg_ms']):.1f} ms",
                            f"Destination loss: {fmt_number(row.get('destination_loss_percent'))}%",
                            f"Max hop loss: {fmt_number(row.get('max_hop_loss_percent'))}% hop {row.get('max_hop')}",
                        ],
                    }
                )
            loss = row.get("max_hop_loss_percent")
            if loss is not None:
                loss_y = y_loss(float(loss))
                marks.append(
                    f'<rect x="{x_value - 4:.1f}" y="{loss_y:.1f}" width="8" '
                    f'height="{top + panel_height + panel_gap + panel_height - loss_y:.1f}" fill="{color}" opacity="0.35"/>'
                )
        if len(points) > 1:
            text = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
            lines.append(f'<polyline points="{text}" fill="none" stroke="{color}" stroke-width="2"/>')
        legend_y = top + target_index * 20
        legend.append(f'<rect x="{width - right + 24}" y="{legend_y - 10}" width="12" height="12" fill="{color}"/>')
        legend.append(
            f'<text x="{width - right + 42}" y="{legend_y}" font-family="sans-serif" font-size="12">{html.escape(target)}</text>'
        )

    loss_top = top + panel_height + panel_gap
    loss_bottom = loss_top + panel_height
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">
<rect width="{width}" height="{height}" fill="white"/>
<text x="{left}" y="22" font-family="sans-serif" font-size="15">MTR destination latency and worst hop loss</text>
<rect x="{left}" y="{top}" width="{width - left - right}" height="{panel_height}" fill="#eff6ff"/>
<rect x="{left}" y="{loss_top}" width="{width - left - right}" height="{panel_height}" fill="#fff7ed"/>
<line x1="{left}" y1="{top + panel_height}" x2="{width - right}" y2="{top + panel_height}" stroke="#64748b"/>
<line x1="{left}" y1="{loss_bottom}" x2="{width - right}" y2="{loss_bottom}" stroke="#64748b"/>
<line x1="{left}" y1="{top}" x2="{left}" y2="{loss_bottom}" stroke="#64748b"/>
<text x="{left - 8}" y="{top + 4}" font-family="sans-serif" font-size="12" text-anchor="end">{latency_ceiling:.0f} ms</text>
<text x="{left - 8}" y="{loss_top + 4}" font-family="sans-serif" font-size="12" text-anchor="end">100% loss</text>
{svg_time_ticks(first, last, width, height, left, right, bottom)}
{"".join(lines)}
{"".join(marks)}
{"".join(legend)}
{svg_inspector(inspect_points, width, height, left, right, top, bottom, tooltip_width=360)}
</svg>
"""
    path.write_text(svg, encoding="utf-8")


def table_html(headers: list[str], rows: list[list[Any]]) -> str:
    head = "".join(f"<th>{html.escape(str(value))}</th>" for value in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(value))}</td>" for value in row) + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def clean_outage_classification(value: str) -> str:
    return (
        value.replace(" (ongoing at report time)", "")
        .replace(" (ended at monitoring gap)", "")
        .strip()
    )


def build_incident_summary(outages: list[dict[str, Any]], merge_gap_seconds: float = 120.0) -> list[dict[str, Any]]:
    incidents: list[dict[str, Any]] = []
    for outage in sorted(outages, key=lambda row: parse_time(str(row["start"]))):
        start = parse_time(str(outage["start"]))
        end = parse_time(str(outage["end"]))
        duration_seconds = float(outage["duration_seconds"])
        classification = clean_outage_classification(str(outage.get("classification", "unknown")))

        if not incidents or (start - incidents[-1]["end_dt"]).total_seconds() > merge_gap_seconds:
            incidents.append(
                {
                    "start_dt": start,
                    "end_dt": end,
                    "outages": 0,
                    "outage_seconds": 0.0,
                    "longest_outage_seconds": 0.0,
                    "local_gateway_outages": 0,
                    "upstream_internet_outages": 0,
                    "unknown_outages": 0,
                }
            )

        incident = incidents[-1]
        incident["end_dt"] = max(incident["end_dt"], end)
        incident["outages"] += 1
        incident["outage_seconds"] += duration_seconds
        incident["longest_outage_seconds"] = max(incident["longest_outage_seconds"], duration_seconds)
        if classification == "local/gateway":
            incident["local_gateway_outages"] += 1
        elif classification == "upstream/internet":
            incident["upstream_internet_outages"] += 1
        else:
            incident["unknown_outages"] += 1

    rows = []
    for incident in incidents:
        counts = {
            "local/gateway": int(incident["local_gateway_outages"]),
            "upstream/internet": int(incident["upstream_internet_outages"]),
            "unknown": int(incident["unknown_outages"]),
        }
        primary = max(counts.items(), key=lambda item: item[1])[0] if counts else "unknown"
        elapsed = (incident["end_dt"] - incident["start_dt"]).total_seconds()
        rows.append(
            {
                "start": incident["start_dt"].isoformat(),
                "end": incident["end_dt"].isoformat(),
                "elapsed_seconds": round(elapsed, 3),
                "outage_seconds": round(float(incident["outage_seconds"]), 3),
                "outage_count": int(incident["outages"]),
                "longest_outage_seconds": round(float(incident["longest_outage_seconds"]), 3),
                "primary_classification": primary,
                "local_gateway_outages": counts["local/gateway"],
                "upstream_internet_outages": counts["upstream/internet"],
                "unknown_outages": counts["unknown"],
            }
        )
    return rows


def generate_report(run_dir: pathlib.Path) -> pathlib.Path:
    events_path = run_dir / "events.jsonl"
    if not events_path.exists():
        raise FileNotFoundError(f"No event log found at {events_path}")

    metadata_path = run_dir / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    ping_interval = float(metadata.get("config", {}).get("probe", {}).get("ping_interval", 2))

    throughput_intervals = []
    for event in iter_events(events_path):
        if event.get("type") == "throughput":
            start = parse_time(event["timestamp"])
            end = parse_time(event.get("ended_at", event["timestamp"]))
            throughput_intervals.append((start, end))

    pings: dict[str, dict[str, Any]] = {}
    dns: dict[str, dict[str, Any]] = {}
    http_tests: dict[str, dict[str, Any]] = {}
    dns_sample_rows: list[dict[str, Any]] = []
    http_sample_rows: list[dict[str, Any]] = []
    outages: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    throughput_rows: list[dict[str, Any]] = []
    public_ips: list[tuple[str, str]] = []
    public_ip_rows: list[dict[str, Any]] = []
    route_rows: list[dict[str, Any]] = []
    timeline_rows: list[dict[str, Any]] = []
    route_signatures: list[tuple[str, str]] = []
    link_first: dict[str, Any] | None = None
    link_last: dict[str, Any] | None = None
    link_counter_rows: list[dict[str, Any]] = []
    wifi_signals: list[float] = []
    wifi_points: list[tuple[dt.datetime, float]] = []
    task_errors = 0
    mtr_total = 0
    mtr_failures = 0
    mtr_rows: list[dict[str, Any]] = []
    first_time: dt.datetime | None = None
    last_time: dt.datetime | None = None
    previous_ping: dt.datetime | None = None
    active_outage: dict[str, Any] | None = None

    for event in iter_events(events_path):
        if "timestamp" not in event:
            continue
        timestamp = parse_time(event["timestamp"])
        first_time = timestamp if first_time is None else min(first_time, timestamp)
        last_time = timestamp if last_time is None else max(last_time, timestamp)
        kind = event.get("type")

        if kind == "ping_batch":
            if previous_ping:
                gap = (timestamp - previous_ping).total_seconds()
                if gap > ping_interval * 2.5:
                    gaps.append(
                        {
                            "start": previous_ping.isoformat(),
                            "end": timestamp.isoformat(),
                            "duration_seconds": round(gap, 3),
                        }
                    )
                    timeline_rows.append(
                        {
                            "timestamp": previous_ping.isoformat(),
                            "end": timestamp.isoformat(),
                            "kind": "monitoring_gap",
                            "value": fmt_duration(gap),
                            "detail": "Collector did not write expected ping batches",
                        }
                    )
                    if active_outage is not None:
                        outages.append(
                            {
                                "start": active_outage["start_time"].isoformat(),
                                "end": previous_ping.isoformat(),
                                "duration_seconds": round(
                                    (previous_ping - active_outage["start_time"]).total_seconds(), 3
                                ),
                                "classification": active_outage["classification"] + " (ended at monitoring gap)",
                            }
                        )
                        active_outage = None
            previous_ping = timestamp
            internet_results = []
            gateway_results = []
            for result in event.get("results", []):
                label = result["label"]
                entry = pings.setdefault(
                    label,
                    {
                        "label": label,
                        "address": result.get("address"),
                        "scope": result.get("scope"),
                        "count": 0,
                        "successes": 0,
                        "latencies": [],
                        "idle_latencies": [],
                        "loaded_latencies": [],
                        "chart": [],
                    },
                )
                entry["count"] += 1
                latency = result.get("latency_ms")
                if result.get("success") and latency is not None:
                    entry["successes"] += 1
                    entry["latencies"].append(float(latency))
                    if in_intervals(timestamp, throughput_intervals):
                        entry["loaded_latencies"].append(float(latency))
                    else:
                        entry["idle_latencies"].append(float(latency))
                    entry["chart"].append((timestamp, float(latency)))
                else:
                    entry["chart"].append((timestamp, None))
                if result.get("scope") == "internet":
                    internet_results.append(result)
                elif result.get("scope") == "gateway":
                    gateway_results.append(result)

            all_internet_failed = bool(internet_results) and not any(
                result.get("success") for result in internet_results
            )
            if all_internet_failed and active_outage is None:
                gateway_ok = any(result.get("success") for result in gateway_results)
                classification = "upstream/internet" if gateway_ok else ("local/gateway" if gateway_results else "unknown")
                active_outage = {"start_time": timestamp, "classification": classification}
            elif not all_internet_failed and active_outage is not None:
                duration = (timestamp - active_outage["start_time"]).total_seconds()
                outages.append(
                    {
                        "start": active_outage["start_time"].isoformat(),
                        "end": timestamp.isoformat(),
                        "duration_seconds": round(duration, 3),
                        "classification": active_outage["classification"],
                    }
                )
                active_outage = None

        elif kind == "dns_batch":
            for result in event.get("results", []):
                label = result["label"]
                dns_sample_rows.append(
                    {
                        "timestamp": event["timestamp"],
                        "label": label,
                        "resolver": result.get("resolver"),
                        "name": result.get("name"),
                        "success": bool(result.get("success")),
                        "status": result.get("status"),
                        "query_ms": result.get("query_ms"),
                    }
                )
                entry = dns.setdefault(label, {"label": label, "count": 0, "successes": 0, "times": []})
                entry["count"] += 1
                if result.get("success"):
                    entry["successes"] += 1
                if result.get("query_ms") is not None:
                    entry["times"].append(float(result["query_ms"]))

        elif kind == "http_batch":
            for result in event.get("results", []):
                label = result["label"]
                metrics = result.get("metrics", {})
                http_sample_rows.append(
                    {
                        "timestamp": event["timestamp"],
                        "label": label,
                        "url": result.get("url"),
                        "success": bool(result.get("success")),
                        "http_code": metrics.get("http_code"),
                        "remote_ip": metrics.get("remote_ip"),
                        "time_namelookup_ms": round(float(metrics["time_namelookup"]) * 1000, 3)
                        if metrics.get("time_namelookup") is not None else None,
                        "time_connect_ms": round(float(metrics["time_connect"]) * 1000, 3)
                        if metrics.get("time_connect") is not None else None,
                        "time_appconnect_ms": round(float(metrics["time_appconnect"]) * 1000, 3)
                        if metrics.get("time_appconnect") is not None else None,
                        "time_starttransfer_ms": round(float(metrics["time_starttransfer"]) * 1000, 3)
                        if metrics.get("time_starttransfer") is not None else None,
                        "time_total_ms": round(float(metrics["time_total"]) * 1000, 3)
                        if metrics.get("time_total") is not None else None,
                    }
                )
                entry = http_tests.setdefault(
                    label, {"label": label, "count": 0, "successes": 0, "times": []}
                )
                entry["count"] += 1
                if result.get("success"):
                    entry["successes"] += 1
                total = result.get("metrics", {}).get("time_total")
                if total is not None:
                    entry["times"].append(float(total) * 1000)

        elif kind == "throughput":
            throughput_rows.append(
                {
                    "timestamp": event["timestamp"],
                    "ended_at": event.get("ended_at"),
                    "direction": event.get("direction"),
                    "success": event.get("success"),
                    "mbps": round(float(event["bits_per_second"]) / 1_000_000, 3)
                    if event.get("bits_per_second") is not None
                    else None,
                    "retransmits": event.get("retransmits"),
                    "seconds": event.get("seconds"),
                }
            )

        elif kind == "public_ip":
            value = str(event.get("address") or "")
            public_ip_rows.append(
                {
                    "timestamp": event["timestamp"],
                    "success": bool(event.get("success")),
                    "address": value if event.get("success") else "",
                    "detail": event.get("detail"),
                }
            )
            if not event.get("success"):
                continue
            if not public_ips or public_ips[-1][1] != value:
                public_ips.append((event["timestamp"], value))
                timeline_rows.append(
                    {
                        "timestamp": event["timestamp"],
                        "kind": "public_ip",
                        "value": value,
                        "detail": "changed" if len(public_ips) > 1 else "initial sample",
                    }
                )

        elif kind == "route_snapshot":
            signature = json.dumps(event.get("default", {}).get("raw"), sort_keys=True)
            default = event.get("default", {})
            route_value = (
                f"gw={default.get('gateway') or 'n/a'} dev={default.get('interface') or 'n/a'} "
                f"src={default.get('source') or 'n/a'}"
            )
            route_rows.append(
                {
                    "timestamp": event["timestamp"],
                    "gateway": default.get("gateway"),
                    "interface": default.get("interface"),
                    "source": default.get("source"),
                    "signature": signature,
                }
            )
            if not route_signatures or route_signatures[-1][1] != signature:
                route_signatures.append((event["timestamp"], signature))
                timeline_rows.append(
                    {
                        "timestamp": event["timestamp"],
                        "kind": "default_route",
                        "value": route_value,
                        "detail": "changed" if len(route_signatures) > 1 else "initial sample",
                    }
                )

        elif kind == "link_stats" and event.get("success"):
            if link_first is None:
                link_first = event
            link_last = event
            data = event.get("data", {})
            stats = data.get("stats64", {})
            rx = stats.get("rx", {})
            tx = stats.get("tx", {})
            signal_dbm = event.get("wireless", {}).get("signal_dbm") if event.get("wireless") else None
            link_counter_rows.append(
                {
                    "timestamp": event["timestamp"],
                    "interface": event.get("interface"),
                    "operstate": data.get("operstate"),
                    "mtu": data.get("mtu"),
                    "rx_bytes": rx.get("bytes"),
                    "tx_bytes": tx.get("bytes"),
                    "rx_packets": rx.get("packets"),
                    "tx_packets": tx.get("packets"),
                    "rx_errors": rx.get("errors"),
                    "tx_errors": tx.get("errors"),
                    "rx_dropped": rx.get("dropped"),
                    "tx_dropped": tx.get("dropped"),
                    "wifi_signal_dbm": signal_dbm,
                }
            )
            if signal_dbm is not None:
                wifi_signals.append(float(signal_dbm))
                wifi_points.append((timestamp, float(signal_dbm)))

        elif kind == "mtr_batch":
            for result in event.get("results", []):
                mtr_total += 1
                if not result.get("success"):
                    mtr_failures += 1
                report = result.get("report", {}).get("report", {}) if result.get("report") else {}
                for hop in report.get("hubs", []):
                    mtr_rows.append(
                        {
                            "timestamp": event["timestamp"],
                            "target": result.get("label"),
                            "target_address": result.get("address"),
                            "hop": hop.get("count"),
                            "host": hop.get("host"),
                            "loss_percent": hop.get("Loss%"),
                            "sent": hop.get("Snt"),
                            "last_ms": hop.get("Last"),
                            "average_ms": hop.get("Avg"),
                            "best_ms": hop.get("Best"),
                            "worst_ms": hop.get("Wrst"),
                            "stddev_ms": hop.get("StDev"),
                        }
                    )

        elif kind == "task_error":
            task_errors += 1

    if active_outage and last_time:
        outages.append(
            {
                "start": active_outage["start_time"].isoformat(),
                "end": last_time.isoformat(),
                "duration_seconds": round((last_time - active_outage["start_time"]).total_seconds(), 3),
                "classification": active_outage["classification"] + " (ongoing at report time)",
            }
        )

    ping_rows = []
    for entry in pings.values():
        count = entry["count"]
        successes = entry["successes"]
        values = entry["latencies"]
        idle = entry["idle_latencies"]
        loaded = entry["loaded_latencies"]
        row = {
            "label": entry["label"],
            "address": entry["address"],
            "scope": entry["scope"],
            "samples": count,
            "packet_loss_percent": round((count - successes) / count * 100, 4) if count else None,
            "min_ms": round(min(values), 3) if values else None,
            "average_ms": round(statistics.fmean(values), 3) if values else None,
            "p50_ms": round(percentile(values, 50), 3) if values else None,
            "p95_ms": round(percentile(values, 95), 3) if values else None,
            "p99_ms": round(percentile(values, 99), 3) if values else None,
            "max_ms": round(max(values), 3) if values else None,
            "idle_p95_ms": round(percentile(idle, 95), 3) if idle else None,
            "loaded_p95_ms": round(percentile(loaded, 95), 3) if loaded else None,
        }
        ping_rows.append(row)
        write_latency_svg(run_dir / f"latency-{slug(entry['label'])}.svg", entry["label"], entry["chart"])

    ping_labels = [entry["label"] for entry in pings.values()]
    hourly_buckets: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in pings.values():
        label = entry["label"]
        for when, value in entry["chart"]:
            hour = when.replace(minute=0, second=0, microsecond=0)
            bucket = hourly_buckets.setdefault(
                (hour.isoformat(), label),
                {"hour_start": hour.isoformat(), "label": label, "samples": 0, "failures": 0},
            )
            bucket["samples"] += 1
            if value is None:
                bucket["failures"] += 1
    hourly_loss_rows = []
    for bucket in sorted(hourly_buckets.values(), key=lambda row: (row["hour_start"], row["label"])):
        samples = int(bucket["samples"])
        failures = int(bucket["failures"])
        hourly_loss_rows.append(
            {
                "hour_start": bucket["hour_start"],
                "label": bucket["label"],
                "samples": samples,
                "packet_loss_percent": round(failures / samples * 100, 4) if samples else 0,
            }
        )

    gateway_entry = next((entry for entry in pings.values() if entry.get("scope") == "gateway"), None)
    wifi_gateway_buckets: dict[str, dict[str, Any]] = {}
    bucket_seconds = 600

    def bucket_start(when: dt.datetime) -> dt.datetime:
        return dt.datetime.fromtimestamp(
            math.floor(when.timestamp() / bucket_seconds) * bucket_seconds,
            UTC,
        )

    if gateway_entry:
        for when, value in gateway_entry["chart"]:
            bucket_time = bucket_start(when)
            bucket = wifi_gateway_buckets.setdefault(
                bucket_time.isoformat(),
                {
                    "bucket_start": bucket_time.isoformat(),
                    "gateway_samples": 0,
                    "gateway_failures": 0,
                    "gateway_latencies": [],
                    "wifi_signals": [],
                },
            )
            bucket["gateway_samples"] += 1
            if value is None:
                bucket["gateway_failures"] += 1
            else:
                bucket["gateway_latencies"].append(float(value))
    for when, signal in wifi_points:
        bucket_time = bucket_start(when)
        bucket = wifi_gateway_buckets.setdefault(
            bucket_time.isoformat(),
            {
                "bucket_start": bucket_time.isoformat(),
                "gateway_samples": 0,
                "gateway_failures": 0,
                "gateway_latencies": [],
                "wifi_signals": [],
            },
        )
        bucket["wifi_signals"].append(float(signal))

    wifi_gateway_rows = []
    for bucket in sorted(wifi_gateway_buckets.values(), key=lambda row: row["bucket_start"]):
        samples = int(bucket["gateway_samples"])
        failures = int(bucket["gateway_failures"])
        latencies = bucket["gateway_latencies"]
        signals = bucket["wifi_signals"]
        wifi_gateway_rows.append(
            {
                "bucket_start": bucket["bucket_start"],
                "gateway_samples": samples,
                "gateway_loss_percent": round(failures / samples * 100, 4) if samples else None,
                "gateway_p95_ms": round(percentile(latencies, 95), 3) if latencies else None,
                "gateway_max_ms": round(max(latencies), 3) if latencies else None,
                "wifi_avg_dbm": round(statistics.fmean(signals), 3) if signals else None,
                "wifi_min_dbm": round(min(signals), 3) if signals else None,
            }
        )

    dns_rows = [
        {
            "label": entry["label"],
            "samples": entry["count"],
            "failure_percent": round((entry["count"] - entry["successes"]) / entry["count"] * 100, 4),
            "average_ms": round(statistics.fmean(entry["times"]), 3) if entry["times"] else None,
            "p95_ms": round(percentile(entry["times"], 95), 3) if entry["times"] else None,
            "max_ms": round(max(entry["times"]), 3) if entry["times"] else None,
        }
        for entry in dns.values()
        if entry["count"]
    ]
    http_rows = [
        {
            "label": entry["label"],
            "samples": entry["count"],
            "failure_percent": round((entry["count"] - entry["successes"]) / entry["count"] * 100, 4),
            "average_ms": round(statistics.fmean(entry["times"]), 3) if entry["times"] else None,
            "p95_ms": round(percentile(entry["times"], 95), 3) if entry["times"] else None,
            "max_ms": round(max(entry["times"]), 3) if entry["times"] else None,
        }
        for entry in http_tests.values()
        if entry["count"]
    ]
    incident_rows = build_incident_summary(outages)
    worst_incidents = sorted(
        incident_rows,
        key=lambda row: (float(row["outage_seconds"]), int(row["outage_count"]), float(row["elapsed_seconds"])),
        reverse=True,
    )[:10]
    worst_hour_rows = sorted(
        hourly_loss_rows,
        key=lambda row: (float(row["packet_loss_percent"]), int(row["samples"])),
        reverse=True,
    )[:10]

    csv_write(
        run_dir / "ping-summary.csv",
        [
            "label",
            "address",
            "scope",
            "samples",
            "packet_loss_percent",
            "min_ms",
            "average_ms",
            "p50_ms",
            "p95_ms",
            "p99_ms",
            "max_ms",
            "idle_p95_ms",
            "loaded_p95_ms",
        ],
        ping_rows,
    )
    csv_write(
        run_dir / "outages.csv",
        ["start", "end", "duration_seconds", "classification"],
        outages,
    )
    csv_write(
        run_dir / "incident-summary.csv",
        [
            "start",
            "end",
            "elapsed_seconds",
            "outage_seconds",
            "outage_count",
            "longest_outage_seconds",
            "primary_classification",
            "local_gateway_outages",
            "upstream_internet_outages",
            "unknown_outages",
        ],
        incident_rows,
    )
    csv_write(
        run_dir / "dns-samples.csv",
        ["timestamp", "label", "resolver", "name", "success", "status", "query_ms"],
        dns_sample_rows,
    )
    csv_write(
        run_dir / "dns-summary.csv",
        ["label", "samples", "failure_percent", "average_ms", "p95_ms", "max_ms"],
        dns_rows,
    )
    csv_write(
        run_dir / "http-samples.csv",
        [
            "timestamp",
            "label",
            "url",
            "success",
            "http_code",
            "remote_ip",
            "time_namelookup_ms",
            "time_connect_ms",
            "time_appconnect_ms",
            "time_starttransfer_ms",
            "time_total_ms",
        ],
        http_sample_rows,
    )
    csv_write(
        run_dir / "http-summary.csv",
        ["label", "samples", "failure_percent", "average_ms", "p95_ms", "max_ms"],
        http_rows,
    )
    csv_write(
        run_dir / "throughput.csv",
        ["timestamp", "ended_at", "direction", "success", "mbps", "retransmits", "seconds"],
        throughput_rows,
    )
    csv_write(
        run_dir / "hourly-loss.csv",
        ["hour_start", "label", "samples", "packet_loss_percent"],
        hourly_loss_rows,
    )
    csv_write(
        run_dir / "wifi-gateway.csv",
        [
            "bucket_start",
            "gateway_samples",
            "gateway_loss_percent",
            "gateway_p95_ms",
            "gateway_max_ms",
            "wifi_avg_dbm",
            "wifi_min_dbm",
        ],
        wifi_gateway_rows,
    )
    csv_write(
        run_dir / "link-counters.csv",
        [
            "timestamp",
            "interface",
            "operstate",
            "mtu",
            "rx_bytes",
            "tx_bytes",
            "rx_packets",
            "tx_packets",
            "rx_errors",
            "tx_errors",
            "rx_dropped",
            "tx_dropped",
            "wifi_signal_dbm",
        ],
        link_counter_rows,
    )
    csv_write(
        run_dir / "public-ip-samples.csv",
        ["timestamp", "success", "address", "detail"],
        public_ip_rows,
    )
    csv_write(
        run_dir / "route-snapshots.csv",
        ["timestamp", "gateway", "interface", "source", "signature"],
        route_rows,
    )
    csv_write(
        run_dir / "route-ip-timeline.csv",
        ["timestamp", "end", "kind", "value", "detail"],
        timeline_rows,
    )
    csv_write(
        run_dir / "mtr-summary.csv",
        [
            "timestamp",
            "target",
            "target_address",
            "hop",
            "host",
            "loss_percent",
            "sent",
            "last_ms",
            "average_ms",
            "best_ms",
            "worst_ms",
            "stddev_ms",
        ],
        mtr_rows,
    )
    csv_write(
        run_dir / "monitoring-gaps.csv",
        ["start", "end", "duration_seconds"],
        gaps,
    )
    with (run_dir / "ping-samples.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["timestamp", "label", "address", "scope", "success", "latency_ms", "loaded"],
        )
        writer.writeheader()
        for event in iter_events(events_path):
            if event.get("type") != "ping_batch":
                continue
            timestamp = parse_time(event["timestamp"])
            for result in event.get("results", []):
                writer.writerow(
                    {
                        "timestamp": event["timestamp"],
                        "label": result.get("label"),
                        "address": result.get("address"),
                        "scope": result.get("scope"),
                        "success": bool(result.get("success")),
                        "latency_ms": result.get("latency_ms"),
                        "loaded": in_intervals(timestamp, throughput_intervals),
                    }
                )

    duration = (last_time - first_time).total_seconds() if first_time and last_time else 0
    outage_seconds = sum(float(outage["duration_seconds"]) for outage in outages)
    link_delta = {}
    if link_first and link_last:
        first_stats = link_first.get("data", {}).get("stats64", {})
        last_stats = link_last.get("data", {}).get("stats64", {})
        for direction in ("rx", "tx"):
            for key in ("bytes", "packets", "errors", "dropped"):
                before = first_stats.get(direction, {}).get(key)
                after = last_stats.get(direction, {}).get(key)
                if isinstance(before, int) and isinstance(after, int):
                    link_delta[f"{direction}_{key}"] = after - before

    longest_outage = max((float(item["duration_seconds"]) for item in outages), default=0)
    generated_at = utc_now()
    write_outage_timeline_svg(run_dir / "outage-timeline.svg", outages, first_time, last_time)
    write_hourly_loss_svg(run_dir / "hourly-loss.svg", hourly_loss_rows, ping_labels)
    write_throughput_svg(run_dir / "throughput.svg", throughput_rows)
    write_wifi_gateway_svg(run_dir / "wifi-gateway.svg", wifi_gateway_rows)
    write_service_timeseries_svg(
        run_dir / "dns-latency.svg",
        "DNS query latency and failures",
        dns_sample_rows,
        "query_ms",
        unit="ms",
        y_label="query ms",
    )
    write_service_timeseries_svg(
        run_dir / "http-latency.svg",
        "HTTP connectivity latency and failures",
        http_sample_rows,
        "time_total_ms",
        unit="ms",
        y_label="total ms",
    )
    write_link_counters_svg(run_dir / "link-counters.svg", link_counter_rows)
    write_timeline_events_svg(run_dir / "route-ip-timeline.svg", timeline_rows, first_time, last_time)
    write_mtr_quality_svg(run_dir / "mtr-quality.svg", mtr_rows)
    gateway_summary = next((row for row in ping_rows if row.get("scope") == "gateway"), None)
    top_ping_loss_rows = sorted(
        ping_rows,
        key=lambda row: float(row["packet_loss_percent"] or 0),
        reverse=True,
    )[:3]
    markdown_lines = [
        "# Internet Stability Report",
        "",
        f"- Host: `{metadata.get('hostname', socket.gethostname())}`",
        f"- Measurement window: `{first_time.isoformat() if first_time else 'n/a'}` to `{last_time.isoformat() if last_time else 'n/a'}`",
        f"- Monitoring duration: {fmt_duration(duration)}",
        f"- Report generated: `{generated_at}`",
        f"- All-target Internet outages: {len(outages)} totaling {fmt_duration(outage_seconds)}",
        f"- Longest all-target outage: {fmt_duration(longest_outage)}",
        f"- Monitoring-process gaps: {len(gaps)}",
        f"- Public IP changes observed: {max(0, len(public_ips) - 1)}",
        f"- Default route changes observed: {max(0, len(route_signatures) - 1)}",
        f"- Wi-Fi signal average/minimum: {fmt_number(statistics.fmean(wifi_signals) if wifi_signals else None)} / {fmt_number(min(wifi_signals) if wifi_signals else None)} dBm",
        f"- Local interface RX/TX errors: {link_delta.get('rx_errors', 'n/a')} / {link_delta.get('tx_errors', 'n/a')}",
        f"- Local interface RX/TX drops: {link_delta.get('rx_dropped', 'n/a')} / {link_delta.get('tx_dropped', 'n/a')}",
        f"- Collector task errors: {task_errors}",
        "",
        "## Technician Summary",
        "",
        f"- Grouped incidents: {len(incident_rows)} using a 120-second merge window.",
        f"- Worst grouped incident: {fmt_duration(float(worst_incidents[0]['outage_seconds'])) if worst_incidents else 'n/a'} outage time across {worst_incidents[0]['outage_count'] if worst_incidents else 0} outages.",
        f"- Local gateway packet loss/p95/p99: {fmt_number(gateway_summary.get('packet_loss_percent') if gateway_summary else None, 4)}% / {fmt_number(gateway_summary.get('p95_ms') if gateway_summary else None)} ms / {fmt_number(gateway_summary.get('p99_ms') if gateway_summary else None)} ms.",
        f"- Wi-Fi signal average/minimum during report: {fmt_number(statistics.fmean(wifi_signals) if wifi_signals else None)} / {fmt_number(min(wifi_signals) if wifi_signals else None)} dBm.",
        "- If local gateway loss is nonzero while Wi-Fi signal is acceptable, check the router/AP, Wi-Fi channel/interference, modem/ONT handoff, and upstream error counters.",
        "",
        "## Worst Grouped Incidents",
        "",
        "| Local Start | Local End | Elapsed | Outage Time | Outages | Primary | Local/Gateway | Upstream |",
        "|---|---|---:|---:|---:|---|---:|---:|",
    ]
    for row in worst_incidents:
        markdown_lines.append(
            f"| {local_table_time(str(row['start']))} | {local_table_time(str(row['end']))} | "
            f"{fmt_duration(float(row['elapsed_seconds']))} | {fmt_duration(float(row['outage_seconds']))} | "
            f"{row['outage_count']} | {row['primary_classification']} | "
            f"{row['local_gateway_outages']} | {row['upstream_internet_outages']} |"
        )
    markdown_lines.extend(
        [
            "",
            "## Worst Packet-Loss Hours",
            "",
            "| Local Hour | Target | Samples | Loss % |",
            "|---|---|---:|---:|",
        ]
    )
    for row in worst_hour_rows:
        markdown_lines.append(
            f"| {local_table_time(str(row['hour_start']))} | {row['label']} | "
            f"{row['samples']} | {fmt_number(row['packet_loss_percent'], 4)} |"
        )
    markdown_lines.extend(
        [
            "",
        "## Ping Summary",
        "",
        "| Target | Scope | Samples | Loss % | Average ms | p95 ms | p99 ms | Max ms | Idle p95 | Loaded p95 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in ping_rows:
        markdown_lines.append(
            f"| {row['label']} | {row['scope']} | {row['samples']} | "
            f"{fmt_number(row['packet_loss_percent'], 4)} | {fmt_number(row['average_ms'])} | "
            f"{fmt_number(row['p95_ms'])} | {fmt_number(row['p99_ms'])} | {fmt_number(row['max_ms'])} | "
            f"{fmt_number(row['idle_p95_ms'])} | {fmt_number(row['loaded_p95_ms'])} |"
        )
    markdown_lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- An `upstream/internet` outage means every configured Internet target failed while the local gateway still answered.",
            "- A `local/gateway` outage means the local gateway and every Internet target failed together; investigate the router, cabling, Wi-Fi, or local interface.",
            "- Isolated loss to one target can be ICMP rate limiting and is weaker evidence than simultaneous DNS, HTTP, VPS, and multi-target failures.",
            "- Monitoring gaps are reported separately and must not be presented as Internet outages.",
            "",
            "Raw evidence is retained in `events.jsonl`; CSV files and SVG charts in this directory are derived from it.",
        ]
    )
    (run_dir / "report.md").write_text("\n".join(markdown_lines) + "\n", encoding="utf-8")

    ping_table = table_html(
        ["Target", "Scope", "Samples", "Loss %", "Average ms", "p95 ms", "p99 ms", "Max ms", "Idle p95", "Loaded p95"],
        [
            [
                row["label"],
                row["scope"],
                row["samples"],
                fmt_number(row["packet_loss_percent"], 4),
                fmt_number(row["average_ms"]),
                fmt_number(row["p95_ms"]),
                fmt_number(row["p99_ms"]),
                fmt_number(row["max_ms"]),
                fmt_number(row["idle_p95_ms"]),
                fmt_number(row["loaded_p95_ms"]),
            ]
            for row in ping_rows
        ],
    )
    outage_table = table_html(
        ["Start", "End", "Duration", "Classification"],
        [
            [row["start"], row["end"], fmt_duration(float(row["duration_seconds"])), row["classification"]]
            for row in outages[:500]
        ],
    )
    incident_table = table_html(
        ["Local Start", "Local End", "Elapsed", "Outage Time", "Outages", "Primary", "Local/Gateway", "Upstream"],
        [
            [
                local_table_time(str(row["start"])),
                local_table_time(str(row["end"])),
                fmt_duration(float(row["elapsed_seconds"])),
                fmt_duration(float(row["outage_seconds"])),
                row["outage_count"],
                row["primary_classification"],
                row["local_gateway_outages"],
                row["upstream_internet_outages"],
            ]
            for row in worst_incidents
        ],
    )
    worst_hour_table = table_html(
        ["Local Hour", "Target", "Samples", "Loss %"],
        [
            [
                local_table_time(str(row["hour_start"])),
                row["label"],
                row["samples"],
                fmt_number(row["packet_loss_percent"], 4),
            ]
            for row in worst_hour_rows
        ],
    )
    dns_table = table_html(
        ["Test", "Samples", "Failure %", "Average ms", "p95 ms", "Max ms"],
        [
            [
                row["label"],
                row["samples"],
                fmt_number(row["failure_percent"], 4),
                fmt_number(row["average_ms"]),
                fmt_number(row["p95_ms"]),
                fmt_number(row["max_ms"]),
            ]
            for row in dns_rows
        ],
    )
    http_table = table_html(
        ["Test", "Samples", "Failure %", "Average ms", "p95 ms", "Max ms"],
        [
            [
                row["label"],
                row["samples"],
                fmt_number(row["failure_percent"], 4),
                fmt_number(row["average_ms"]),
                fmt_number(row["p95_ms"]),
                fmt_number(row["max_ms"]),
            ]
            for row in http_rows
        ],
    )
    chart_tags = "".join(
        f'<h3>{html.escape(entry["label"])}</h3>'
        f'<object class="latency-chart" data="latency-{slug(entry["label"])}.svg" '
        f'type="image/svg+xml" aria-label="{html.escape(entry["label"])} latency chart">'
        f'<a href="latency-{slug(entry["label"])}.svg">Open {html.escape(entry["label"])} latency chart</a>'
        f'</object>'
        for entry in pings.values()
    )
    diagnostic_chart_defs = [
        ("Outage Timeline", "outage-timeline.svg"),
        ("Packet Loss By Hour", "hourly-loss.svg"),
        ("Throughput And Retransmits", "throughput.svg"),
        ("Wi-Fi Signal Vs Gateway Latency", "wifi-gateway.svg"),
        ("DNS Query Latency", "dns-latency.svg"),
        ("HTTP Connectivity Latency", "http-latency.svg"),
        ("Local Link Counters", "link-counters.svg"),
        ("Public IP And Route Timeline", "route-ip-timeline.svg"),
        ("MTR Route Quality", "mtr-quality.svg"),
    ]
    diagnostic_charts = "".join(
        f'<h3>{html.escape(title)}</h3>'
        f'<object class="diagnostic-chart" data="{html.escape(filename)}" '
        f'type="image/svg+xml" aria-label="{html.escape(title)}">'
        f'<a href="{html.escape(filename)}">Open {html.escape(title)}</a>'
        f'</object>'
        for title, filename in diagnostic_chart_defs
        if (run_dir / filename).exists()
    )
    report_html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Internet Stability Report</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:1300px;margin:2rem auto;padding:0 1rem;color:#172033}}
table{{border-collapse:collapse;width:100%;margin:1rem 0}}th,td{{border:1px solid #cbd5e1;padding:.45rem;text-align:right}}
th:first-child,td:first-child{{text-align:left}}th{{background:#e2e8f0}}
.latency-chart{{width:100%;height:340px;border:1px solid #cbd5e1;display:block}}
.diagnostic-chart{{width:100%;height:360px;border:1px solid #cbd5e1;display:block}}
.cards{{display:flex;flex-wrap:wrap;gap:1rem}}.card{{background:#f1f5f9;padding:1rem;min-width:180px;border-radius:6px}}
code{{background:#f1f5f9;padding:.1rem .25rem}}
</style></head><body>
<h1>Internet Stability Report</h1>
<p>Host <code>{html.escape(str(metadata.get("hostname", socket.gethostname())))}</code>;
window <code>{html.escape(first_time.isoformat() if first_time else "n/a")}</code> to
<code>{html.escape(last_time.isoformat() if last_time else "n/a")}</code>.</p>
<div class="cards">
<div class="card"><strong>Duration</strong><br>{fmt_duration(duration)}</div>
<div class="card"><strong>All-target outages</strong><br>{len(outages)}</div>
<div class="card"><strong>Outage time</strong><br>{fmt_duration(outage_seconds)}</div>
<div class="card"><strong>Longest outage</strong><br>{fmt_duration(longest_outage)}</div>
<div class="card"><strong>Monitor gaps</strong><br>{len(gaps)}</div>
<div class="card"><strong>RX/TX errors</strong><br>{link_delta.get("rx_errors", "n/a")} / {link_delta.get("tx_errors", "n/a")}</div>
<div class="card"><strong>RX/TX drops</strong><br>{link_delta.get("rx_dropped", "n/a")} / {link_delta.get("tx_dropped", "n/a")}</div>
<div class="card"><strong>Wi-Fi average/min</strong><br>{fmt_number(statistics.fmean(wifi_signals) if wifi_signals else None)} / {fmt_number(min(wifi_signals) if wifi_signals else None)} dBm</div>
</div>
<h2>Technician Summary</h2>
<p>This section groups nearby short outages into incidents using a 120-second merge window, so repeated 2-second drops are easier to discuss.</p>
<ul>
<li>Grouped incidents: <strong>{len(incident_rows)}</strong></li>
<li>Worst grouped incident: <strong>{fmt_duration(float(worst_incidents[0]["outage_seconds"])) if worst_incidents else "n/a"}</strong> outage time across <strong>{worst_incidents[0]["outage_count"] if worst_incidents else 0}</strong> outages</li>
<li>Local gateway loss/p95/p99: <strong>{fmt_number(gateway_summary.get("packet_loss_percent") if gateway_summary else None, 4)}%</strong> / <strong>{fmt_number(gateway_summary.get("p95_ms") if gateway_summary else None)} ms</strong> / <strong>{fmt_number(gateway_summary.get("p99_ms") if gateway_summary else None)} ms</strong></li>
<li>Wi-Fi average/minimum: <strong>{fmt_number(statistics.fmean(wifi_signals) if wifi_signals else None)} / {fmt_number(min(wifi_signals) if wifi_signals else None)} dBm</strong></li>
</ul>
<p>If local gateway loss is nonzero while Wi-Fi signal is acceptable, check the router/AP, Wi-Fi channel/interference, modem/ONT handoff, and upstream error counters.</p>
<h2>Worst Grouped Incidents</h2>{incident_table}
<h2>Worst Packet-Loss Hours</h2>{worst_hour_table}
<h2>Ping Summary</h2>{ping_table}
<h2>Diagnostic Charts</h2><p>These charts summarize outage timing, hourly packet loss, VPS throughput quality, and the Wi-Fi-to-gateway relationship. Hover or drag across them to inspect the nearest point.</p>{diagnostic_charts}
<h2>Latency Charts</h2><p>Hover or drag across a chart to inspect the nearest timestamp and latency sample.</p>{chart_tags}
<h2>All-target Outages</h2>{outage_table}
<h2>DNS Summary</h2>{dns_table}
<h2>HTTP Summary</h2>{http_table}
<h2>Evidence Files</h2>
<ul>
<li><a href="events.jsonl">Raw event log</a></li>
<li><a href="outages.csv">Outage CSV</a></li>
<li><a href="incident-summary.csv">Grouped incident summary CSV</a></li>
<li><a href="ping-summary.csv">Ping summary CSV</a></li>
<li><a href="ping-samples.csv">Detailed ping samples CSV</a></li>
<li><a href="hourly-loss.csv">Hourly packet loss CSV</a></li>
<li><a href="dns-samples.csv">DNS sample CSV</a></li>
<li><a href="http-samples.csv">HTTP sample CSV</a></li>
<li><a href="wifi-gateway.csv">Wi-Fi vs gateway CSV</a></li>
<li><a href="link-counters.csv">Local link counters CSV</a></li>
<li><a href="public-ip-samples.csv">Public IP samples CSV</a></li>
<li><a href="route-snapshots.csv">Route snapshot CSV</a></li>
<li><a href="route-ip-timeline.csv">Route/IP/gap timeline CSV</a></li>
<li><a href="throughput.csv">Throughput CSV</a></li>
<li><a href="mtr-summary.csv">MTR hop summary CSV</a></li>
<li><a href="monitoring-gaps.csv">Monitoring gap CSV</a></li>
</ul>
<h2>Interpretation</h2>
<p>An <code>upstream/internet</code> outage means every configured Internet target failed while the local gateway
still answered. A <code>local/gateway</code> outage means the gateway and all Internet targets failed together.
Monitoring gaps are reported separately and are not Internet outages.</p>
<p>Generated at <code>{generated_at}</code>. MTR snapshots: {mtr_total}; MTR failures: {mtr_failures};
public IP changes: {max(0, len(public_ips) - 1)}; default route changes: {max(0, len(route_signatures) - 1)};
collector task errors: {task_errors}.</p>
</body></html>
"""
    report_path = run_dir / "report.html"
    report_path.write_text(report_html, encoding="utf-8")
    return report_path


def resolve_run_dir(data_dir: pathlib.Path, run_dir: pathlib.Path | None) -> pathlib.Path:
    if run_dir:
        return run_dir.expanduser().resolve()
    current = data_dir.expanduser().resolve() / "current"
    if not current.exists():
        raise FileNotFoundError(f"No current run found below {data_dir}")
    return current.resolve()


def command_init(args: argparse.Namespace) -> int:
    destination = pathlib.Path(args.config).expanduser()
    if destination.exists() and not args.force:
        raise FileExistsError(f"{destination} already exists; use --force to replace it")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(DEFAULT_CONFIG, destination)
    print(f"Created {destination}")
    return 0


def command_run(args: argparse.Namespace) -> int:
    config_path = pathlib.Path(args.config).expanduser().resolve()
    config = load_config(config_path)
    data_dir = pathlib.Path(args.data_dir).expanduser().resolve()
    requested = pathlib.Path(args.run_dir).expanduser().resolve() if args.run_dir else None
    run_dir = create_run_dir(data_dir, requested)
    write_metadata(run_dir, config_path, config)
    writer = EventWriter(run_dir / "events.jsonl")
    print(f"Collecting network evidence in {run_dir}", flush=True)
    try:
        Collector(config, writer).run()
    finally:
        writer.close()
    return 0


def systemctl_active(unit: str) -> bool:
    return run_command(["systemctl", "--user", "is-active", "--quiet", unit], 10)["returncode"] == 0


def command_start(args: argparse.Namespace) -> int:
    config_path = pathlib.Path(args.config).expanduser().resolve()
    config = load_config(config_path)
    data_dir = pathlib.Path(args.data_dir).expanduser().resolve()
    run_dir = create_run_dir(data_dir)
    write_metadata(run_dir, config_path, config)
    unit = args.unit if args.unit.endswith(".service") else args.unit + ".service"
    if systemctl_active(unit):
        raise RuntimeError(f"{unit} is already active")

    runtime_path = os.environ.get("NETPROBE_RUNTIME_PATH", os.environ.get("PATH", ""))
    command = [
        "systemd-run",
        "--user",
        "--unit",
        unit,
        "--description",
        "Long-running Internet stability monitor",
        "--property",
        "Restart=on-failure",
        "--property",
        "RestartSec=15s",
        "--setenv",
        f"PATH={runtime_path}",
        str(sys.executable),
        str(SCRIPT_PATH),
        "run",
        "--config",
        str(config_path),
        "--data-dir",
        str(data_dir),
        "--run-dir",
        str(run_dir),
    ]
    result = subprocess.run(command, text=True, check=False)
    if result.returncode != 0:
        return result.returncode

    linger = run_command(
        ["loginctl", "show-user", os.environ.get("USER", ""), "--property=Linger", "--value"],
        10,
    )
    print(f"Started {unit}; evidence directory: {run_dir}")
    if linger["stdout"].strip().lower() != "yes":
        print(
            "WARNING: user lingering is disabled. The service may stop after logout. "
            "Run `loginctl enable-linger \"$USER\"` once, then restart the service.",
            file=sys.stderr,
        )
    return 0


def command_install_service(args: argparse.Namespace) -> int:
    config_path = pathlib.Path(args.config).expanduser().resolve()
    config = load_config(config_path)
    data_dir = pathlib.Path(args.data_dir).expanduser().resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    write_metadata(create_run_dir(data_dir, data_dir / "long-term"), config_path, config)
    unit = args.unit if args.unit.endswith(".service") else args.unit + ".service"
    unit_dir = pathlib.Path.home() / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit_path = unit_dir / unit
    runtime_path = os.environ.get("NETPROBE_RUNTIME_PATH", os.environ.get("PATH", ""))
    exec_start = " ".join(
        shlex.quote(value)
        for value in (
            str(sys.executable),
            str(SCRIPT_PATH),
            "run",
            "--config",
            str(config_path),
            "--data-dir",
            str(data_dir),
            "--run-dir",
            str(data_dir / "long-term"),
        )
    )
    contents = f"""[Unit]
Description=Long-running Internet stability monitor
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
Environment=PATH={shlex.quote(runtime_path)}
ExecStart={exec_start}
Restart=always
RestartSec=15s

[Install]
WantedBy=default.target
"""
    unit_path.write_text(contents, encoding="utf-8")
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    enable_result = subprocess.run(["systemctl", "--user", "enable", unit], check=False)
    if enable_result.returncode != 0:
        return enable_result.returncode
    restart_result = subprocess.run(["systemctl", "--user", "restart", unit], check=False)
    if restart_result.returncode != 0:
        return restart_result.returncode
    linger = run_command(
        ["loginctl", "show-user", os.environ.get("USER", ""), "--property=Linger", "--value"],
        10,
    )
    print(f"Installed and started {unit}; evidence directory: {data_dir / 'long-term'}")
    if linger["stdout"].strip().lower() != "yes":
        print(
            "WARNING: enable user lingering with `loginctl enable-linger \"$USER\"` "
            "so the service runs after logout and starts at boot.",
            file=sys.stderr,
        )
    return 0


def command_stop(args: argparse.Namespace) -> int:
    unit = args.unit if args.unit.endswith(".service") else args.unit + ".service"
    return subprocess.run(["systemctl", "--user", "stop", unit], check=False).returncode


def command_status(args: argparse.Namespace) -> int:
    unit = args.unit if args.unit.endswith(".service") else args.unit + ".service"
    return subprocess.run(["systemctl", "--user", "status", "--no-pager", unit], check=False).returncode


def command_logs(args: argparse.Namespace) -> int:
    unit = args.unit if args.unit.endswith(".service") else args.unit + ".service"
    command = ["journalctl", "--user", "--unit", unit, "--lines", str(args.lines)]
    if args.follow:
        command.append("--follow")
    return subprocess.run(command, check=False).returncode


def command_report(args: argparse.Namespace) -> int:
    data_dir = pathlib.Path(args.data_dir).expanduser()
    run_dir = resolve_run_dir(data_dir, pathlib.Path(args.run_dir) if args.run_dir else None)
    report = generate_report(run_dir)
    print(f"Generated {report}")
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    config_path = pathlib.Path(args.config).expanduser().resolve()
    config = load_config(config_path)
    print(f"Config: {config_path}")
    missing = []
    for command in REQUIRED_COMMANDS:
        found = shutil.which(command)
        print(f"{command:12} {found or 'MISSING'}")
        if not found:
            missing.append(command)
    route = default_route()
    print(f"Default route: gateway={route.get('gateway')} interface={route.get('interface')}")
    print(f"Ping targets: {len(config['ping_targets'])}; DNS tests: {len(config['dns_tests'])}; HTTP tests: {len(config['http_tests'])}")
    print(f"VPS iperf target: {config['probe'].get('iperf_host') or 'disabled'}")
    linger = run_command(
        ["loginctl", "show-user", os.environ.get("USER", ""), "--property=Linger", "--value"],
        10,
    )
    print(f"User lingering: {linger['stdout'].strip() or 'unknown'}")
    return 1 if missing else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Create a starting configuration")
    init_parser.add_argument("--config", default="./netprobe.toml")
    init_parser.add_argument("--force", action="store_true")
    init_parser.set_defaults(function=command_init)

    run_parser = subparsers.add_parser("run", help="Run the collector in the foreground")
    run_parser.add_argument("--config", default="./netprobe.toml")
    run_parser.add_argument("--data-dir", default="./netprobe-data")
    run_parser.add_argument("--run-dir")
    run_parser.set_defaults(function=command_run)

    start_parser = subparsers.add_parser("start", help="Start the collector as a transient user service")
    start_parser.add_argument("--config", default="./netprobe.toml")
    start_parser.add_argument("--data-dir", default="./netprobe-data")
    start_parser.add_argument("--unit", default="netprobe")
    start_parser.set_defaults(function=command_start)

    install_parser = subparsers.add_parser(
        "install-service",
        help="Install and start a persistent user service without changing NixOS configuration",
    )
    install_parser.add_argument("--config", default="./netprobe.toml")
    install_parser.add_argument("--data-dir", default="./netprobe-data")
    install_parser.add_argument("--unit", default="netprobe")
    install_parser.set_defaults(function=command_install_service)

    stop_parser = subparsers.add_parser("stop", help="Stop the user service")
    stop_parser.add_argument("--unit", default="netprobe")
    stop_parser.set_defaults(function=command_stop)

    status_parser = subparsers.add_parser("status", help="Show user service status")
    status_parser.add_argument("--unit", default="netprobe")
    status_parser.set_defaults(function=command_status)

    logs_parser = subparsers.add_parser("logs", help="Show collector service logs")
    logs_parser.add_argument("--unit", default="netprobe")
    logs_parser.add_argument("--lines", type=int, default=100)
    logs_parser.add_argument("--follow", action="store_true")
    logs_parser.set_defaults(function=command_logs)

    report_parser = subparsers.add_parser("report", help="Generate HTML, Markdown, CSV, and SVG reports")
    report_parser.add_argument("--data-dir", default="./netprobe-data")
    report_parser.add_argument("--run-dir")
    report_parser.set_defaults(function=command_report)

    doctor_parser = subparsers.add_parser("doctor", help="Validate dependencies and configuration")
    doctor_parser.add_argument("--config", default="./netprobe.toml")
    doctor_parser.set_defaults(function=command_doctor)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.function(args))
    except (FileNotFoundError, FileExistsError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
