# YouTube Automation & Distributed Task Worker

Automated YouTube channel performance testing, video interaction workflow, and headless browser automation runner for Linux instances.

## Overview

This project provides an automated client for executing scheduled browser workflows and YouTube channel engagement testing (views, natural watch time, interactive liking, commenting). It connects securely to an authorized controller using token-based authentication.

## Features

- **Automated Web Interactions**: Headless browsing workflows using Playwright Chromium.
- **YouTube Session Runner**: Searches for keywords, navigates to videos, performs natural watch time (5-10 minutes), with interactive likes and comments.
- **System Metrics Monitoring**: Reports CPU load, memory utilization, and uptime telemetry.
- **Secure Token Authentication**: Tasks and commands require authorization keys (`AGENT_AUTH_KEY`).
- **Resilient Connection**: Automatically reconnects if network connectivity drops.

## Installation

```bash
git clone https://github.com/makassartoraja936-max/vps-channel-worker.git ~/workspace/vps-channel-worker
cd ~/workspace/vps-channel-worker
bash setup.sh
```

## Running the Worker

```bash
python3 worker.py
```

To run in background:
```bash
nohup python3 worker.py > worker.log 2>&1 &
```

## Security & Configuration

The worker validates all incoming tasks against a pre-configured secret authentication key:
- Task commands require matching authorization tokens.
- Telemetry reporting uses secure WebSocket channels.
- Configurable via `~/workspace/.worker_id` and `~/workspace/.vps_name`.

## License

MIT License
