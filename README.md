# YTS Automation Web Interface

Flask-based web interface for running YouTube Certification/YTS tests against Android/Android TV devices connected through **Linux ADB**.

## Platform

This project is intentionally **Linux-only**. It is designed for Ubuntu/Linux hosts and uses the native Linux `adb` client. Windows, WSL, and Windows `adb.exe` are not supported by this project.

## What this project does

- Discovers ADB-connected DUTs.
- Runs `yts discover` and maps the DUT to its YTS short ID.
- Starts configured YTS tests from the browser.
- Streams test output to the web UI.
- Stores test results and statistics in SQLite.
- Downloads a fresh YTS CLI package at application startup.
- Removes the temporary YTS package when the application exits.

## Requirements

- Ubuntu/Linux
- Python 3.9+
- Python venv/pip
- Node.js 18+ and npm
- Android SDK Platform-Tools / Linux `adb`
- USB or network access to the DUT

Install the dependencies on Ubuntu:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nodejs npm adb
```

Verify:

```bash
python3 --version
node --version
npm --version
adb version
```

## Setup and start

```bash
chmod +x start_app.sh
./start_app.sh
```

The launcher creates `.venv`, installs Python dependencies, verifies Linux ADB, and starts the Flask application.

Open:

```text
http://127.0.0.1:5000
```

## Connect a DUT

### USB

```bash
adb devices
```

Authorize USB debugging on the DUT if it appears as `unauthorized`.

### Network ADB

```bash
adb connect <DUT_IP>:5555
adb devices
```

Or configure the device before starting the application:

```bash
export ADB_DEVICE=<DUT_IP>:5555
./start_app.sh
```

The application uses the native Linux `adb` command from PATH.

## Manual run

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

## Runtime YTS

The YTS package is **not stored in this repository**. On startup the application downloads it from:

```text
http://yts.devicecertification.youtube/yts_server.zip
```

You can override the URL if required:

```bash
export YTS_DOWNLOAD_URL="<YTS_PACKAGE_URL>"
```

The package is extracted into a temporary directory and deleted when the application exits.

## Useful environment variables

```bash
export HOST=127.0.0.1
export PORT=5000
export ADB_DEVICE=192.168.1.7:5555
export YTS_DOWNLOAD_TIMEOUT=120
export LOG_LEVEL=INFO
```

## Project structure

```text
YT_Automation_WebApp_Based-main/
├── app.py
├── yts_automation.py
├── start_app.sh
├── requirements.txt
├── README.md
├── templates/
├── static/
└── data/
```

## Troubleshooting

### ADB not found

```bash
which adb
adb version
```

Install it with:

```bash
sudo apt install -y adb
```

### DUT not listed

```bash
adb kill-server
adb start-server
adb devices
```

For a network DUT:

```bash
adb connect <DUT_IP>:5555
adb devices
```

### YTS download fails

Verify the YTS server is reachable from the Linux host and optionally set `YTS_DOWNLOAD_URL` to the appropriate package URL.
