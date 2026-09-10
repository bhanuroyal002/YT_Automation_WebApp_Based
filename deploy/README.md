# AWS EC2 deployment

This project is a Linux-only Flask/YTS application. For production, run Flask behind Gunicorn and Nginx. Tomcat is not required because the application is Python/Flask.

## Architecture

```text
Users -> Route 53 -> EC2 :443 -> Nginx -> Gunicorn/Flask :5000 -> YTS/ADB -> DUTs
                                      |
                                      +-> SQLite data/
```

The EC2 instance must have network connectivity to the DUT/ADB subnet. Private addresses such as `192.168.x.x:5555` are not reachable from EC2 unless the office/LAN network is connected to AWS, for example with a site-to-site VPN or another private network path.

## 1. Create the EC2 instance

Use a current Ubuntu LTS AMI. Assign an Elastic IP to the instance so its public address remains stable.

Security group baseline:

- TCP 22: only from the administrator's IP or corporate VPN.
- TCP 80: public only if needed for initial certificate setup.
- TCP 443: users/corporate network as appropriate.
- Do **not** expose TCP 5000.
- Do **not** expose ADB TCP 5555 to the Internet.

## 2. Clone and install

On the EC2 host:

```bash
git clone https://github.com/bhanuroyal002/YT_Automation_WebApp_Based.git /tmp/yts-automation-src
cd /tmp/yts-automation-src
sudo DOMAIN=yts.example.com bash deploy/install_ec2.sh
```

Replace `yts.example.com` with the real hostname.

The installer creates:

- `/opt/yts-automation` - application
- `/etc/yts-automation/yts-automation.env` - production environment
- `yts-automation.service` - systemd service
- Nginx reverse proxy on port 80

## 3. DNS

Create an A record in the public Route 53 hosted zone:

```text
Name: yts
Type: A
Value: <EC2 Elastic IP>
```

If the domain is registered outside Route 53, delegate the domain's DNS to the Route 53 hosted zone name servers or otherwise configure the required DNS record at the current DNS provider.

## 4. HTTPS

After DNS resolves to the EC2 host, install and configure a TLS certificate. For a single EC2 host, Certbot with the Nginx plugin is a straightforward option:

```bash
sudo apt-get update
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d yts.example.com
```

Verify renewal with:

```bash
sudo certbot renew --dry-run
```

After HTTPS is enabled, confirm `/etc/yts-automation/yts-automation.env` contains:

```text
ALLOWED_ORIGINS=https://yts.example.com
```

Restart the application after environment changes:

```bash
sudo systemctl restart yts-automation
```

## 5. Check the application

```bash
sudo systemctl status yts-automation
sudo journalctl -u yts-automation -f
sudo nginx -t
curl -I http://127.0.0.1:5000/
curl http://127.0.0.1:5000/api/health
```

The public application should then be available at:

```text
https://yts.example.com
```

## 6. Updating the application

```bash
cd /opt/yts-automation
sudo -u yts git fetch origin
sudo -u yts git reset --hard origin/main
sudo -u yts /opt/yts-automation/.venv/bin/pip install -r requirements.txt
sudo systemctl restart yts-automation
```

## 7. DUT connectivity

Before attempting certification tests, verify ADB from EC2:

```bash
adb devices
adb connect <DUT_PRIVATE_IP>:5555
adb -s <DUT_PRIVATE_IP>:5555 shell getprop ro.product.model
```

If the DUTs remain on the office network, establish a private network path first. Do not solve this by opening TCP 5555 to `0.0.0.0/0`.

## 8. Tomcat

Tomcat is intentionally not used for this application. The application is Flask/Python. If an organization requires Tomcat for another Java application, it can coexist with Nginx on the same EC2 instance, but Flask should remain behind Gunicorn.
