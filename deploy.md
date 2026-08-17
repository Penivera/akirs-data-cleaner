# Hosting a FastAPI App on IIS (Windows) â€” Setup Walkthrough

## Overview

IIS can't run Python natively. The pattern: **Uvicorn runs your FastAPI app as a background Windows service**, and **IIS reverse-proxies** incoming requests to it.

```
Browser -> IIS (port 80/443) -> web.config rewrite rule -> Uvicorn (127.0.0.1:8000) -> FastAPI app
```

---

## 1. Set Up the FastAPI App

```powershell
python -m venv venv
venv\Scripts\activate
pip install fastapi uvicorn[standard]
```

Test it runs standalone before anything else:

```powershell
uvicorn main:app --host 127.0.0.1 --port 8000
```

---

## 2. Install Required IIS Modules

- URL Rewrite Module: https://www.iis.net/downloads/microsoft/url-rewrite
- Application Request Routing (ARR) 3.0: https://www.iis.net/downloads/microsoft/application-request-routing

**After installing ARR**, enable proxying (easy to miss):
IIS Manager -> top-level server node -> **Application Request Routing Cache** -> **Server Proxy Settings** -> check **Enable proxy** -> Apply.

---

## 3. Create the IIS Site

- IIS Manager -> **Sites** -> **Add Website**
- Physical path: your project folder
- Binding: Port 80 (host name added later once domain is ready)

---

## 4. Run Uvicorn as a Windows Service (NSSM)

Download NSSM: https://nssm.cc/download. Run these **as Administrator**:

```powershell
nssm.exe install DataToolKit
```

Config values (or set individually with `nssm.exe set`):

| Setting | Value |
|---|---|
| Application | `C:\path\to\project\.venv\Scripts\uvicorn.exe` |
| AppParameters | `main:app --host 127.0.0.1 --port 8000` |
| AppDirectory | `C:\path\to\project` |

```powershell
nssm.exe start DataToolKit
nssm.exe status DataToolKit    # should say SERVICE_RUNNING
```

### Key lessons learned
- Point `Application` directly at the venv's **`uvicorn.exe`**, not `python.exe -m` (simpler, avoids `-m` argument-parsing issues).
- `AppDirectory` must be set explicitly, otherwise Python can't find `main.py`.
- Service start/stop requires an **elevated terminal**, or you'll get `Access is denied`.

### Debugging a service that won't start
```powershell
mkdir C:\nssm-logs
nssm.exe set DataToolKit AppStdout C:\nssm-logs\stdout.log
nssm.exe set DataToolKit AppStderr C:\nssm-logs\stderr.log
nssm.exe restart DataToolKit
type C:\nssm-logs\stderr.log
```
Also useful: test the exact same command manually in an activated venv terminal first. Fastest way to isolate whether it's a code issue or a service-context issue.

### Verify it's listening correctly
```powershell
netstat -ano | findstr :8000
```
You want to see **only** `127.0.0.1:8000` (not `0.0.0.0:8000`). Uvicorn should never be directly exposed; only IIS should be internet-facing. Kill any stray process on `0.0.0.0`:
```powershell
taskkill /PID <pid> /F
```

Note: `TIME_WAIT` entries in netstat are just recently-closed connections cleaning up, normal TCP behavior, not the server restarting. NSSM starts Uvicorn **once**; it stays running continuously.

---

## 5. Reverse Proxy Config (web.config)

Place in the IIS site's physical path:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<configuration>
  <system.webServer>
    <rewrite>
      <rules>
        <rule name="ReverseProxyToFastAPI" stopProcessing="true">
          <match url="(.*)" />
          <action type="Rewrite" url="http://127.0.0.1:8000/{R:1}" />
        </rule>
      </rules>
    </rewrite>
  </system.webServer>
</configuration>
```

---

## 6. Test Locally Before Using the Real Domain

Edit hosts file to simulate the domain locally:

```powershell
notepad C:\Windows\System32\drivers\etc\hosts
```

Add:
```
127.0.0.1    yourdomain.com
```

Now `http://yourdomain.com` on this machine exercises the real host-header binding.

---

## 7. Moving to Windows Server (Going Live)

This is where the app actually goes public. A real server (VPS/cloud/on-prem with a public IP) typically has a **direct public IP with no NAT**, so no port forwarding or tunneling is needed â€” just DNS, firewall, and IIS binding.

### Step 1: Get the server's public IP
On the server:
```powershell
curl -4 https://ifconfig.me
```

### Step 2: Point your domain at the server
In your DNS provider (Cloudflare, GoDaddy, Namecheap, etc.), add an **A record**:

| Type | Name | Value |
|---|---|---|
| A | `app` (or `www`, or `@` for root) | server's public IP |

Check propagation:
```powershell
nslookup app.yourdomain.com
```

### Step 3: Open the firewall on the server
```powershell
New-NetFirewallRule -DisplayName "HTTP Inbound" -Direction Inbound -Protocol TCP -LocalPort 80 -Action Allow
New-NetFirewallRule -DisplayName "HTTPS Inbound" -Direction Inbound -Protocol TCP -LocalPort 443 -Action Allow
```
If the server is cloud-hosted (Azure/AWS/GCP/DigitalOcean, etc.), also open ports 80/443 in that provider's **network security group / firewall rules** â€” the cloud-level firewall is separate from the Windows Firewall.

### Step 4: Repeat the same app setup as local
- Install URL Rewrite + ARR (same as Section 2)
- Create the IIS site (same as Section 3)
- Install and run the NSSM service (same as Section 4)
- Same `web.config` reverse proxy rule (same as Section 5)

### Step 5: Update the IIS binding to the real domain
IIS Manager -> site -> **Bindings** -> add/edit:
- Type: `http`, Port: `80`, Host name: `app.yourdomain.com`

### Step 6: Add HTTPS
Use **win-acme** (free Let's Encrypt client for Windows/IIS): https://www.win-acme.com/
It auto-detects your IIS site, issues a certificate, binds it to port 443, and can auto-renew.

### Step 7: Verify from outside
```
http://app.yourdomain.com
https://app.yourdomain.com
```
Check from your phone on cellular data, or via https://www.whatsmydns.net/ to confirm DNS has propagated globally.

---

## Quick Reference: Useful Commands

| Purpose | Command |
|---|---|
| Check service status | `nssm.exe status DataToolKit` |
| Restart service | `nssm.exe restart DataToolKit` |
| Check what's on port 8000 | `netstat -ano \| findstr :8000` |
| Kill a process | `taskkill /PID <pid> /F` |
| Check local IP | `ipconfig` |
| Check public IP (v4) | `curl -4 https://ifconfig.me` |
| Test DNS resolution | `nslookup test.yourdomain.com` |
