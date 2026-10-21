# VPS Channel & Web Automation Worker

Automated web browsing, YouTube channel task runner, and background process supervisor for Linux VPS instances.

## Overview

This project provides an automated task worker client designed to run on Ubuntu Linux instances. It communicates with a central controller to perform scheduled web workflows, YouTube video interactions (automated watch sessions, liking, commenting), and local process management.

## Features

- **Automated Web Interactions**: Headless browsing via Playwright Chromium.
- **YouTube Session Runner**: Searches for keywords, navigates to videos, performs natural watch time (5-10 minutes), with interactive likes and comments.
- **System Metrics**: Reports live RAM, CPU, and uptime metrics.
- **Auto-Recovery**: Recovers and reconnects automatically if network connectivity is interrupted.

## Installation

### Prerequisites
- Python 3.10+
- pip

### Setup
```bash
git clone https://github.com/sainalsaputra19-hub/vps-channel-worker.git ~/workspace/vps-channel-worker
cd ~/workspace/vps-channel-worker
bash setup.sh
```

## Running Manually
```bash
python3 worker.py
```

## Configuration

The worker can be configured via environment files in `~/workspace`:
- `~/workspace/.vps_name`: Custom identifier for the VPS instance (e.g., `Muse-01`).
- `~/workspace/.hub_url`: Central WebSocket endpoint (default: `wss://hub.databaru.my.id`).

## License
MIT License
