# YTS Automation Web Interface

Flask-based web interface for running YouTube Certification/YTS tests against Android/Android TV devices connected through **Linux ADB**.

## Platform

This project is intentionally **Linux-only**. It is designed for Ubuntu/Linux hosts and uses the native Linux `adb` client. Windows, WSL, and Windows `adb.exe` are not supported.

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

The launcher verifies Linux, checks Python/Node/npm/ADB, creates `.venv`, installs Python dependencies, and starts the Flask application.

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

The application uses the native Linux `adb` command. You may override it with:

```bash
export ADB_PATH=/path/to/adb
```

## Runtime YTS CLI

The YTS package is **not stored in this repository**. On application startup, a fresh YTS package is downloaded from:

```text
http://yts.devicecertification.youtube/yts_server.zip
```

Override the URL when required:

```bash
export YTS_DOWNLOAD_URL="<YTS_PACKAGE_URL>"
```

The package is extracted into a private temporary directory and removed when the application exits. Active YTS child processes are also terminated during cleanup.

## Manual run

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

## Useful environment variables

```bash
export HOST=127.0.0.1
export PORT=5000
export ADB_PATH=/path/to/adb
export ADB_DEVICE=192.168.1.7:5555
export YTS_DOWNLOAD_TIMEOUT=120
export FLASK_SECRET_KEY='replace-with-a-long-random-value'
export ALLOWED_ORIGINS='http://127.0.0.1:5000,http://localhost:5000'
export LOG_LEVEL=INFO
export MAX_COMPLETED_SESSIONS=200
```

## Project layout

```text
YT_Automation_WebApp_Based/
├── app.py
├── yts_automation.py
├── adb_platform.py
├── requirements.txt
├── start_app.sh
├── .gitignore
├── README.md
├── data/
│   └── .gitkeep
├── static/
│   ├── css/
│   └── js/
└── templates/
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

If you use a custom ADB binary:

```bash
export ADB_PATH=/path/to/adb
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

Verify that the YTS server is reachable from the Linux host and that `YTS_DOWNLOAD_URL` points to the correct package.

### Port is already in use

```bash
export PORT=5001
./start_app.sh
```

## Git hygiene

Do not commit `.venv/`, databases, logs, `.env`/secrets, downloaded YTS runtime files, or the bundled `google3/` YTS tree.
