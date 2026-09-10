# YTS Automation Web Interface — Ubuntu

Flask web interface for running YouTube Certification/YTS tests against Android/Android TV devices connected through ADB.

## Supported platform

This project is intended for **Ubuntu/Linux only**.

Windows/PowerShell launch scripts are intentionally not included.

## Requirements

Install these system packages if they are not already available:

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

## First run

From the project directory:

```bash
chmod +x start_app.sh
./start_app.sh
```

The launcher automatically:

- checks Python, Node.js, npm and ADB
- creates `.venv` when required
- installs Python dependencies
- makes the bundled YTS executable
- checks the YTS CLI
- displays connected ADB devices
- starts the web application

Open:

```text
http://127.0.0.1:5000
```

## Manual run

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

## ADB

Check connected devices:

```bash
adb devices
```

The device should appear as:

```text
SERIAL    device
```

If it shows `unauthorized`, authorize USB debugging on the Android device.

## YTS CLI

The bundled executable is:

```text
google3/video/youtube/testing/ytlr_cert/yts_server/yts
```

Check it:

```bash
./google3/video/youtube/testing/ytlr_cert/yts_server/yts --help
```

If necessary:

```bash
chmod +x google3/video/youtube/testing/ytlr_cert/yts_server/yts
```

## Configuration

Optional environment variables:

```bash
export HOST=127.0.0.1
export PORT=5000
export FLASK_SECRET_KEY='replace-with-a-long-random-value'
export ALLOWED_ORIGINS='http://127.0.0.1:5000,http://localhost:5000'
```

For a workstation used by multiple machines on the same LAN, explicitly set `HOST=0.0.0.0` and restrict access with your firewall.

## Runtime data

Runtime databases/logs belong under:

```text
data/
```

They are excluded from Git.

## Project layout

```text
YT_WebApp/
├── app.py
├── yts_automation.py
├── requirements.txt
├── start_app.sh
├── .gitignore
├── README.md
├── data/
├── google3/
├── static/
│   ├── css/
│   └── js/
└── templates/
```

## Troubleshooting

### `ModuleNotFoundError: No module named 'flask'`

Activate the virtual environment:

```bash
source .venv/bin/activate
```

Then:

```bash
python -m pip install -r requirements.txt
```

### `python3 -m venv` fails

Install:

```bash
sudo apt install -y python3-venv python3-full
```

Then recreate:

```bash
rm -rf .venv
python3 -m venv .venv
```

### YTS permission denied

```bash
chmod +x google3/video/youtube/testing/ytlr_cert/yts_server/yts
```

### ADB device is missing

```bash
adb kill-server
adb start-server
adb devices
```

Then reconnect/authorize the device.

## Important

Do not commit:

- `.venv/`
- runtime databases
- logs
- local credentials
- secrets

The YTS test definitions and bundled YTS files remain version controlled.

## Runtime YTS CLI

The YTS CLI is intentionally not bundled with this application. On startup, the application downloads `yts_server.zip` from `YTS_DOWNLOAD_URL` (default: `http://yts.devicecertification.youtube/yts_server.zip`), extracts it into a private temporary directory, and uses that copy for all YTS commands during the session.

The temporary YTS directory is removed when the application exits. Set `YTS_DOWNLOAD_URL` to a different package URL if required.

## Cross-platform ADB

The application uses the native ADB client of the environment where it runs:

- Windows: `adb.exe` from PATH or `ADB_PATH`.
- Linux/WSL: Linux `adb` from PATH or `ADB_PATH`.
- WSL never attempts to execute a Windows `.exe` as its ADB client.

For a network-connected DUT, you can set:

```bash
export ADB_DEVICE=192.168.1.7:5555
./start_app.sh
```

Use your own DUT address in place of the example. The application runs `adb connect` in the current OS environment, so Windows and WSL can each maintain their own ADB client/server without sharing a Windows ADB server.

On native Windows, run `start_app.bat` from Command Prompt or PowerShell.
