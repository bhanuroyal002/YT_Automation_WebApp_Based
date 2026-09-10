# YTS Automation Tool

A Linux-only web interface for running YouTube TV certification/YTS tests against Android/Android TV DUTs connected through native Linux ADB.

## Design

This project is intended to run **locally on the Linux machine that has network/USB access to the DUTs**.

```text
Linux workstation
      │
      ├── YTS Automation Tool
      ├── Native Linux ADB
      └── YTS CLI (downloaded at runtime)
              │
              ▼
          Android TV DUT
```

There is no cloud server, local agent, browser extension, Windows component, WSL component, or separate deployment service required.

## Platform

**Linux only.** Ubuntu/Debian is recommended. Windows, WSL, and Windows `adb.exe` are not supported.

## Requirements

The launcher automatically installs missing Ubuntu/Debian system packages when `sudo` access is available:

- Python 3
- Python venv/pip
- Node.js
- npm
- Android Debug Bridge (`adb`)

Python application dependencies are installed automatically into the project's `.venv`.

## Clone and run — one command

On a fresh Ubuntu/Debian Linux machine, use:

```bash
git clone https://github.com/bhanuroyal002/YT_Automation_WebApp_Based.git && cd YT_Automation_WebApp_Based && chmod +x start_app.sh && ./start_app.sh
```

That's the complete setup and start command.

The launcher will:

1. Verify the host is Linux.
2. Install missing Ubuntu/Debian system dependencies.
3. Create the project's Python virtual environment.
4. Install/update Python dependencies from `requirements.txt`.
5. Verify native Linux ADB.
6. Prepare the runtime YTS package.
7. Start the application.

Open:

```text
http://127.0.0.1:5000
```

Press `Ctrl+C` to stop the application.

## Existing checkout

If the project is already cloned:

```bash
cd ~/YT_Automation_WebApp_Based
git pull origin main
chmod +x start_app.sh
./start_app.sh
```

No manual Python package installation is required.

## Connect a DUT

### Network ADB

The supported network DUT range is the complete `192.168.0.0/16` private range, not a single hard-coded subnet.

Examples:

```bash
adb connect 192.168.2.12:5555
adb connect 192.168.10.50:5555
adb connect 192.168.100.25:5555
adb devices
```

The application can therefore be used on different user networks such as `192.168.1.x`, `192.168.2.x`, `192.168.10.x`, or `192.168.50.x` without changing the application code.

### USB ADB

USB ADB remains supported:

```bash
adb devices
```

Authorize USB debugging on the DUT if it appears as `unauthorized`.

## Application features

- Discover ADB-connected DUTs.
- Run `yts discover` and map DUTs to YTS short IDs.
- Select a DUT from the web interface.
- View device information.
- Select certification tests.
- Display the detailed certification instructions automatically when a test is selected.
- Identify manual tests and warn before execution.
- Run individual YTS tests.
- Run test suites through the API.
- Stream YTS output/logs to the browser.
- Store test results/statistics in SQLite.
- Download YTS at runtime rather than storing the YTS package in Git.
- Clean up the temporary YTS runtime when the application exits.

## Runtime YTS

The YTS package is not committed to this repository.

By default the application downloads:

```text
http://yts.devicecertification.youtube/yts_server.zip
```

Override it when required:

```bash
export YTS_DOWNLOAD_URL="<YTS_PACKAGE_URL>"
./start_app.sh
```

The downloaded package is extracted into a temporary runtime directory and cleaned up when the application exits.

## Useful environment variables

```bash
HOST=127.0.0.1
PORT=5000
ADB_DEVICE=192.168.2.12:5555
YTS_DOWNLOAD_TIMEOUT=120
LOG_LEVEL=INFO
```

For a network DUT you can optionally let the launcher connect it automatically:

```bash
ADB_DEVICE=192.168.2.12:5555 ./start_app.sh
```

## Project structure

```text
YT_Automation_WebApp_Based/
├── app.py
├── yts_automation.py
├── test_instructions.json
├── update_test_instructions.py
├── start_app.sh
├── requirements.txt
├── README.md
├── templates/
├── static/
└── data/
```

## Troubleshooting

### ADB is not found

Run:

```bash
adb version
which adb
```

The launcher attempts to install ADB automatically on Ubuntu/Debian. If it still cannot find ADB:

```bash
sudo apt update
sudo apt install -y adb
```

Make sure the Linux executable is being used and not a Windows/WSL wrapper.

### DUT is not listed

Restart ADB:

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

Confirm that the DUT IP is in `192.168.0.0/16`.

### YTS discovery hangs

YTS discovery can emit the DUT mapping and then remain alive because of its MQTT component. The application contains bounded discovery/process handling so the useful discovery output can still be consumed without waiting indefinitely.

### YTS download fails

Verify that the Linux machine can reach the YTS package server. If your environment uses a different approved YTS package location, set `YTS_DOWNLOAD_URL` before starting the application.

## Updating the project

Pull the latest version and start it again:

```bash
cd ~/YT_Automation_WebApp_Based
git pull origin main
./start_app.sh
```

The launcher automatically reconciles Python dependencies on every start.
