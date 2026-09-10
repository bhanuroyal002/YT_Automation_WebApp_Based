# YTS Automation Web Interface

Flask web interface for running YouTube Certification/YTS tests against Android/Android TV devices connected through ADB.

## Supported platforms
- Windows
- Ubuntu/Linux
- WSL2

The app uses the native ADB client of the environment where it runs. WSL does not attempt to execute Windows `adb.exe`.

## Requirements

### Windows
Install Python 3, Node.js/npm and Android SDK Platform Tools (`adb`) and ensure they are on `PATH`.

```powershell
start_app.bat
```

### Ubuntu/Linux/WSL

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

Start:

```bash
chmod +x start_app.sh
./start_app.sh
```

Open `http://127.0.0.1:5000`.

## ADB configuration

The application automatically selects a working native ADB client. Override it when required:

```bash
export ADB_PATH=/path/to/adb
```

For a network-connected DUT:

```bash
export ADB_DEVICE=192.168.1.7:5555
./start_app.sh
```

The application runs `adb connect` in the current OS environment. Windows and WSL therefore do not need to share an ADB server.

## Runtime YTS CLI

YTS CLI is intentionally **not bundled** with this repository.

At startup the app downloads `yts_server.zip` from `YTS_DOWNLOAD_URL` (default: `http://yts.devicecertification.youtube/yts_server.zip`), extracts it into a private temporary directory, and uses that copy for the session.

On shutdown, active YTS processes are terminated and the temporary runtime directory is removed.

Optional settings:

```bash
export YTS_DOWNLOAD_URL='http://yts.devicecertification.youtube/yts_server.zip'
export YTS_DOWNLOAD_TIMEOUT=120
```

## Test execution

The web UI loads the test definitions from `YTS_TEST_COMMANDS` in `yts_automation.py`. Device discovery uses ADB and `yts discover`, then the selected test command is launched with the discovered YTS short ID. Output is streamed to the UI and results are stored in the local SQLite database under `data/`.

## Configuration

```bash
export HOST=127.0.0.1
export PORT=5000
export ADB_PATH=/path/to/adb
export ADB_DEVICE=192.168.1.7:5555
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
├── start_app.bat
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

### WSL ADB fails

```bash
sudo apt install -y adb
/usr/bin/adb version
/usr/bin/adb connect 192.168.1.7:5555
/usr/bin/adb devices
```

If `/usr/local/bin/adb` is a broken Windows wrapper, the application prefers a working native `/usr/bin/adb`.

### Python dependencies missing

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
```

### Port is already in use

```bash
export PORT=5001
./start_app.sh
```

## Git hygiene

Do not commit `.venv/`, databases, logs, `.env`/secrets, downloaded YTS runtime files, or the old bundled `google3/` tree.
