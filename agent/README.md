# YTS Linux Agent

The Linux Agent is the local execution component for YTS Automation. The central web application can run on AWS EC2, while this agent runs on the user's Linux workstation that is physically/network-connected to the DUT.

## Requirements

- Native Linux only
- Python 3
- Node.js
- Native Linux ADB
- Network ADB enabled on the DUT
- The Linux host and DUT must be on the same local IP subnet

The agent does **not** assume a fixed subnet such as `192.168.2.x`. It reads the Linux host's active IPv4 interfaces and accepts a network ADB DUT only when its IPv4 address belongs to one of those local subnets.

## Start

From the repository root:

```bash
chmod +x agent/start_agent.sh
YTS_SERVER_URL=https://yts.webautomation.com bash agent/start_agent.sh
```

For initial HTTP testing against the EC2 public IP, include that browser origin:

```bash
YTS_SERVER_URL=http://3.82.165.58 \
YTS_AGENT_ALLOWED_ORIGINS=http://3.82.165.58 \
bash agent/start_agent.sh
```

The agent listens only on `127.0.0.1:8765`; it is not exposed to the LAN or Internet.

## Verify

```bash
curl http://127.0.0.1:8765/api/health
```

Then use **Discover Devices** in the web application. Device discovery, device details, individual tests, suites, and test status are executed by the local Linux agent.

## Network behavior

A DUT such as `192.168.10.50:5555` is accepted when the Linux host has an active interface such as `192.168.10.25/24`.

A DUT on a different subnet is rejected by the agent before YTS execution.

The agent intentionally does not open ADB ports or proxy the DUT through AWS.
