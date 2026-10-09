# SOAR Lab


**Quy ước nơi chạy lệnh:**
- `[HOST-PS]` = PowerShell trên Windows host (một số lệnh cần **Run as Administrator**).
- `[WSL]` = terminal Ubuntu-24.04 trong WSL2.
- `[VM-xxx]` = trong VM (DVWA/Win10) qua SSH hoặc console.
- `[pfSense-GUI]` / `[pfSense-SSH]` = Web GUI hoặc SSH vào pfSense.
- `<...>` = giá trị thật tra ở `00-tai-khoan.md`, không ghi cứng secret vào đây.

Thông số cố định của lab: host SOC `10.10.99.1`, pfSense `10.10.99.254`,
DVWA `172.16.10.10`, Win10 `10.10.20.100`, Kali `192.168.210.130`,
WAN pfSense `192.168.210.132`.

---

# A. Nền tảng Docker trên host

### A1. Cài WSL2 + Docker Desktop
```powershell
# [HOST-PS] (Administrator)
wsl --install -d Ubuntu-24.04      # xong khởi động lại, đặt user/pass Ubuntu
winget install -e --id Docker.DockerDesktop
```
Docker Desktop → Settings → General: tick **Use the WSL 2 based engine**;
Resources → WSL integration: bật **Ubuntu-24.04**.

### A2. Cấu hình WSL (RAM + max_map_count cho Elasticsearch)
```powershell
# [HOST-PS]
@"
[wsl2]
memory=16GB
processors=8
swap=4GB
kernelCommandLine = "sysctl.vm.max_map_count=262144"
"@ | Set-Content -Encoding ascii "$env:USERPROFILE\.wslconfig"
wsl --shutdown
```
Mở lại Docker Desktop, rồi kiểm tra:
```bash
# [WSL]
docker version && docker compose version
cat /proc/sys/vm/max_map_count     # phải = 262144
sudo apt update && sudo apt install -y git openssl
mkdir -p ~/soar-lab
```

### A3. Wazuh single-node (chạy từ Windows, thư mục F:)
```bash
# [WSL] clone (hoặc clone thẳng vào F: cũng được)
cd ~/soar-lab
git clone https://github.com/wazuh/wazuh-docker.git -b v4.14.8
cd wazuh-docker/single-node
docker compose -f generate-indexer-certs.yml run --rm generator   # tạo chứng chỉ TRƯỚC
docker compose up -d
docker compose ps
```
> Thực tế Wazuh đặt ở `F:\SOAR_Project\wazuh-docker\single-node`, chạy bằng
> CMD/PowerShell. Chờ 1–3 phút → mở **https://localhost** → `admin / SecretPassword`.

### A4. TheHive + Cortex (StrangeBee testing, trong WSL)
```bash
# [WSL]
cd ~/soar-lab
git clone https://github.com/StrangeBeeCorp/docker.git thehive-cortex
cd thehive-cortex/testing
bash ./scripts/init.sh -y                 # sinh secret, .env, sửa permission
docker compose up -d cassandra elasticsearch thehive cortex   # BỎ nginx (trùng 443)
docker compose ps
```
- TheHive: **http://localhost:9000/thehive** → `admin@thehive.local / secret` → đổi mật khẩu.
- Cortex: **http://localhost:9001/cortex** → **Update database** → tạo superadmin.

### A5. n8n (trong WSL)
```bash
# [WSL]
mkdir -p ~/soar-lab/n8n && cd ~/soar-lab/n8n
cat > docker-compose.yml <<'EOF'
services:
  n8n:
    image: docker.n8n.io/n8nio/n8n:latest
    container_name: n8n
    restart: unless-stopped
    ports: ["5678:5678"]
    environment:
      - TZ=Asia/Ho_Chi_Minh
      - GENERIC_TIMEZONE=Asia/Ho_Chi_Minh
      - N8N_SECURE_COOKIE=false
    volumes:
      - n8n_data:/home/node/.n8n
volumes:
  n8n_data:
EOF
docker compose up -d
```
Mở **http://localhost:5678** → tạo tài khoản owner.

### A6. Kiểm tra tổng
```bash
# [WSL]
docker ps --format "table {{.Names}}\t{{.Status}}"
```
Phải đủ 8 container Up: 3 Wazuh + cassandra + elasticsearch + thehive + cortex + n8n.

---

# B. Mạng VMware + pfSense

### B1. Tạo VMnet (VMware → Edit → Virtual Network Editor → Change Settings)
- **VMnet2 (DMZ):** Host-only, **bỏ** host adapter, **bỏ** DHCP, subnet `172.16.10.0/24`.
- **VMnet3 (CLIENT):** Host-only, **bỏ** host adapter, **bỏ** DHCP, subnet `10.10.20.0/24`.
- **VMnet4 (SOC):** Host-only, **giữ** host adapter, **bỏ** DHCP, subnet `10.10.99.0/24`.

### B2. Đặt IP tĩnh cho card VMnet4 trên host
```powershell
# [HOST-PS] (Administrator)
Set-NetIPInterface -InterfaceAlias "VMware Network Adapter VMnet4" -Dhcp Disabled
New-NetIPAddress -InterfaceAlias "VMware Network Adapter VMnet4" -IPAddress 10.10.99.1 -PrefixLength 24
```

### B3. Tạo VM pfSense (4 card, đúng thứ tự)
New VM → Typical → *I will install the OS later* → Guest **FreeBSD 14 64-bit** →
`F:\VMs\pfSense`, disk 20GB, RAM 2048MB, CPU 2. Card theo thứ tự:
Adapter1 **NAT** (em0=WAN), Adapter2 **VMnet2** (em1=DMZ), Adapter3 **VMnet3**
(em2=CLIENT), Adapter4 **VMnet4** (em3=SOC). CD = ISO pfSense 2.7.2.

### B4. Cài pfSense + gán interface
Cài ZFS stripe trên da0 (nhớ **Space** chọn đĩa). Sau cài, ở console gán:
```
WAN   = em0 (DHCP, ra 192.168.210.132)
LAN   = em3  → 10.10.99.254/24   (đặt làm SOC để host vào được GUI)
OPT1  = em1  → 172.16.10.1/24    (DMZ, IP tĩnh, không DHCP)
OPT2  = em2  → 10.10.20.1/24     (CLIENT, DHCP .100–.200)
```
Kiểm tra từ host: `ping 10.10.99.254` → mở `https://10.10.99.254`.

### B5. Setup wizard + đổi tên + nâng cấp
`[pfSense-GUI]`: wizard đặt hostname `pfSense`, domain `soar.internal`, DNS
1.1.1.1/8.8.8.8, TZ Asia/Ho_Chi_Minh, WAN bỏ chặn RFC1918+bogon, đổi mật khẩu admin.
Đổi tên interface **LAN→SOC, OPT1→DMZ, OPT2→CLIENT**. System → Update: nâng
**2.7.2 → 2.8.1** (giữ 2.8.1 vì Package Manager còn `suricata`).

### B6. DHCP / DNS / NTP
Services → DHCP Server → **CLIENT**: Enable, range `10.10.20.100–200`.
DNS Resolver: Enable (mặc định). NTP: mặc định.

### B7. Route trên host + Windows Firewall
```powershell
# [HOST-PS] (Administrator)
route -p add 172.16.10.0 mask 255.255.255.0 10.10.99.254
route -p add 10.10.20.0  mask 255.255.255.0 10.10.99.254
# Mở cổng Wazuh cho 3 zone, syslog chỉ từ pfSense
New-NetFirewallRule -DisplayName "SOAR - Wazuh agent (1514-1515/TCP)" -Direction Inbound -Protocol TCP -LocalPort 1514,1515 -RemoteAddress 172.16.10.0/24,10.10.20.0/24,10.10.99.0/24 -Action Allow
New-NetFirewallRule -DisplayName "SOAR - Wazuh syslog (514/UDP)" -Direction Inbound -Protocol UDP -LocalPort 514 -RemoteAddress 10.10.99.254 -Action Allow
```

### B8. Alias + Firewall rule + NAT (Firewall → Aliases / Rules / NAT)
**Aliases:** `SOC_SERVER`=10.10.99.1 · `DVWA`=172.16.10.10 · `RFC1918`=10/8,172.16/12,192.168/16 ·
`WAZUH_PORTS`=1514,1515 · `WEB_PORTS`=80,443.

**Rules → DMZ** (trên xuống): (1) Pass TCP DMZ→`SOC_SERVER`:`WAZUH_PORTS` ·
(2) Pass DMZ→DMZ address:53 · (3) Pass UDP DMZ→DMZ address:123 ·
(4) **Block + Log** DMZ→`RFC1918` · (5) Pass TCP DMZ→any:`WEB_PORTS`.

**Rules → CLIENT:** (1) Pass CLIENT→`SOC_SERVER`:`WAZUH_PORTS` · (2) DNS · (3) NTP ·
(4) Pass CLIENT→`DVWA`:`WEB_PORTS` · (5) **Block + Log** CLIENT→`RFC1918` ·
(6) Pass CLIENT→any (ra Internet).

**NAT → Port Forward:** WAN / TCP / Dest `WAN address`:80 → target `DVWA`:80,
*Add associated filter rule*.

---

# C. DVWA (DMZ)

### C1. Cài LAMP + DVWA (khi còn ở NAT để có Internet)
```bash
# [VM-DVWA]
sudo apt install -y apache2 mariadb-server php libapache2-mod-php php-mysql php-gd git
sudo mysql -e "CREATE DATABASE dvwa; CREATE USER 'dvwa'@'localhost' IDENTIFIED BY 'p@ssw0rd'; GRANT ALL PRIVILEGES ON dvwa.* TO 'dvwa'@'localhost'; FLUSH PRIVILEGES;"
cd /var/www/html
sudo git clone https://github.com/digininja/DVWA.git dvwa
sudo cp dvwa/config/config.inc.php.dist dvwa/config/config.inc.php
sudo chown -R www-data:www-data dvwa/hackable/uploads dvwa/config
PHPINI=$(ls /etc/php/*/apache2/php.ini)
sudo sed -i 's/^allow_url_include = Off/allow_url_include = On/; s/^display_errors = Off/display_errors = On/' $PHPINI
sudo systemctl restart apache2
```

### C2. Setup DVWA
Mở `http://<IP>/dvwa/setup.php` → **Create / Reset Database** → login `admin / password`.

### C3. Chuyển sang DMZ + IP tĩnh
VM Settings → Network → **VMnet2**. Trong VM (NetworkManager):
```bash
# [VM-DVWA]
sudo nmcli con mod "<ten-con-ens33>" ipv4.method manual ipv4.addresses 172.16.10.10/24 ipv4.gateway 172.16.10.1 ipv4.dns 172.16.10.1
sudo nmcli con up "<ten-con-ens33>"
```

### C4. Kiểm tra
```bash
# [VM-DVWA]
curl -sI https://ubuntu.com | head -1       # HTTP/2 200 (ra Internet 443)
nc -zv -w3 10.10.99.1 1514                   # succeeded (gửi Wazuh)
ping -c2 -W2 10.10.99.1                       # 100% loss (bị firewall chặn - ĐÚNG)
```

---

# D. Windows 10 client

### D1–D2. VM + cấu hình cơ bản
Tạo VM Win10 (VMnet3, RAM 4GB), tài khoản local `NgocHuong`. Trong VM:
```powershell
# [VM-Win10] (Administrator)
Set-TimeZone -Id "SE Asia Standard Time"
w32tm /config /manualpeerlist:"10.10.20.1" /syncfromflags:manual /update; Restart-Service w32time; w32tm /resync
Rename-Computer -NewName "WIN11-CLIENT01" -Restart   # (tên hiển thị tuỳ chọn)
```
Giữ **Defender bật** (giống máy nhân viên thật).

### D3. Sysmon
```powershell
# [VM-Win10] (Administrator)
$ProgressPreference='SilentlyContinue'; mkdir C:\Tools -Force | Out-Null; cd C:\Tools
Invoke-WebRequest https://download.sysinternals.com/files/Sysmon.zip -OutFile Sysmon.zip
Expand-Archive Sysmon.zip -DestinationPath C:\Tools\Sysmon -Force
Invoke-WebRequest https://raw.githubusercontent.com/SwiftOnSecurity/sysmon-config/master/sysmonconfig-export.xml -OutFile C:\Tools\Sysmon\sysmonconfig.xml
C:\Tools\Sysmon\Sysmon64.exe -accepteula -i C:\Tools\Sysmon\sysmonconfig.xml
```

### D4. Wazuh agent + đọc kênh Sysmon
```powershell
# [VM-Win10] (Administrator)
Invoke-WebRequest https://packages.wazuh.com/4.x/windows/wazuh-agent-4.14.8-1.msi -OutFile $env:TEMP\wazuh-agent.msi
msiexec.exe /i $env:TEMP\wazuh-agent.msi /q WAZUH_MANAGER='10.10.99.1' WAZUH_AGENT_NAME='win10-client'
Start-Sleep 10; NET START WazuhSvc
# Thêm khối đọc Sysmon vào CUỐI ossec.conf (không sửa thẻ đóng cũ)
$conf="C:\Program Files (x86)\ossec-agent\ossec.conf"; Copy-Item $conf "$conf.bak" -Force
@"

<ossec_config>
  <localfile>
    <location>Microsoft-Windows-Sysmon/Operational</location>
    <log_format>eventchannel</log_format>
  </localfile>
</ossec_config>
"@ | Add-Content -Path $conf -Encoding ASCII
Restart-Service WazuhSvc
Select-String -Path "C:\Program Files (x86)\ossec-agent\ossec.log" -Pattern "Sysmon"
```
Đúng khi `ossec.log` có `Analyzing event log: 'Microsoft-Windows-Sysmon/Operational'`.

### D5. Kiểm tra
```powershell
# [VM-Win10]
Test-NetConnection 10.10.99.1 -Port 1514     # True
Test-NetConnection 172.16.10.10 -Port 80     # True
Test-NetConnection 10.10.99.254 -Port 443    # False (bị chặn - ĐÚNG)
```
Dashboard → Agents: `win10-client` **Active**.

---

# E. Wazuh agent trên DVWA

### E1. Cài agent + thu log Apache
```bash
# [VM-DVWA] (root)
apt-get install -y gnupg apt-transport-https
curl -s https://packages.wazuh.com/key/GPG-KEY-WAZUH | gpg --no-default-keyring --keyring gnupg-ring:/usr/share/keyrings/wazuh.gpg --import && chmod 644 /usr/share/keyrings/wazuh.gpg
echo "deb [signed-by=/usr/share/keyrings/wazuh.gpg] https://packages.wazuh.com/4.x/apt/ stable main" > /etc/apt/sources.list.d/wazuh.list
apt-get update
WAZUH_MANAGER="10.10.99.1" WAZUH_AGENT_NAME="dvwa-web" apt-get install -y wazuh-agent=4.14.8-1
apt-mark hold wazuh-agent
systemctl enable --now wazuh-agent
# Thu log Apache (bộ cài có thể đã thêm sẵn, lệnh cat chỉ chạy nếu chưa có)
grep -n "apache2" /var/ossec/etc/ossec.conf || cat >> /var/ossec/etc/ossec.conf <<'EOF2'
<ossec_config>
  <localfile><log_format>apache</log_format><location>/var/log/apache2/access.log</location></localfile>
  <localfile><log_format>apache</log_format><location>/var/log/apache2/error.log</location></localfile>
</ossec_config>
EOF2
systemctl restart wazuh-agent
```

---

# F. Suricata + đẩy log về Wazuh

### F1–F3. Cài + cấu hình Suricata `[pfSense-GUI]`
- System → Package Manager → cài **suricata**.
- System → Advanced → Networking: tick cả 3 **Disable hardware offload** → Save → Reboot.
- Services → Suricata → Global Settings: tick **ETOpen**, Update 12h, Live Rule Swap → Save → tab Updates → **Update**.

### F4. Interface DMZ (IDS)
Services → Suricata → Interfaces → Add: Enable, Interface **DMZ**, Desc `DMZ_IDS`,
**không** tick Block Offenders, EVE JSON **Enable** / Output **SYSLOG** / Facility
**LOCAL1** / Priority **NOTICE**, Logged Info **chỉ Alerts**. Save → tab **DMZ
Categories** tick: `emerging-web_server, emerging-web_specific_apps, emerging-sql,
emerging-exploit, emerging-attack_response, emerging-scan, emerging-shellcode` →
Save → **Start** (▶ xanh).

### F5. Interface CLIENT (IDS)
Giống F4, Desc `CLIENT_IDS`. Categories: `emerging-malware, emerging-phishing,
emerging-coinminer, emerging-policy, emerging-dns, emerging-attack_response` →
Save → Start.

### F6. pfSense gửi syslog về Wazuh
Status → System Logs → Settings → Remote Logging: Enable, Source **SOC**,
Server `10.10.99.1:514`, **Everything**, Format **syslog (RFC 3164)** → Save.

### F7. Wazuh manager nghe syslog 514
```powershell
# [HOST-PS] mở file, thêm khối <remote> syslog ngay dưới khối <remote> secure
notepad F:\SOAR_Project\wazuh-docker\single-node\config\wazuh_cluster\wazuh_manager.conf
```
```xml
  <remote>
    <connection>syslog</connection>
    <port>514</port>
    <protocol>udp</protocol>
    <allowed-ips>0.0.0.0/0</allowed-ips>
  </remote>
```
```powershell
# [HOST-PS] cp vào container rồi restart (restart thường KHÔNG áp config mới)
cd F:\SOAR_Project\wazuh-docker\single-node
docker cp config\wazuh_cluster\wazuh_manager.conf single-node-wazuh.manager-1:/var/ossec/etc/ossec.conf
docker exec single-node-wazuh.manager-1 /var/ossec/bin/wazuh-control restart
docker exec single-node-wazuh.manager-1 grep -i "514/UDP" /var/ossec/logs/ossec.log   # "Listening on port 514/UDP"
```

### F8. Decoder + rule riêng (pfSense 2.8 BSD syslog không có hostname)
Tạo 2 file trong `F:\SOAR_Project\wazuh-docker\single-node\config\custom\`:

`pfsense_decoders.xml`:
```xml
<decoder name="pfsense-bsd">
  <prematch type="pcre2">,match,(?:block|pass),(?:in|out),4,</prematch>
</decoder>
<decoder name="pfsense-bsd-fields">
  <parent>pfsense-bsd</parent>
  <regex type="pcre2">(\d+),[^,]*,[^,]*,(\d+),([^,]+),match,(block|pass),(in|out),4,[^,]*,[^,]*,\d+,\d+,\d+,[^,]*,\d+,([a-z0-9-]+),\d+,(\d+\.\d+\.\d+\.\d+),(\d+\.\d+\.\d+\.\d+)</regex>
  <order>rule_number,id,interface,action,direction,protocol,srcip,dstip</order>
</decoder>
<decoder name="pfsense-bsd-fields">
  <parent>pfsense-bsd</parent>
  <regex type="pcre2">,(?:tcp|udp),\d+,\d+\.\d+\.\d+\.\d+,\d+\.\d+\.\d+\.\d+,(\d+),(\d+),</regex>
  <order>srcport,dstport</order>
</decoder>
```
`pfsense_rules.xml` (100100 gom log, 100101 drop no_log, 100102 nhiều block cùng nguồn T1110)
và `suricata_decoders.xml` / `suricata_rules.xml` (bóc `suricata[pid]:` → JSON_Decoder,
rule 100110/100111) — nội dung đầy đủ ở doc 06.

Nạp vào container:
```powershell
# [HOST-PS]
cd F:\SOAR_Project\wazuh-docker\single-node
docker cp config\custom\pfsense_decoders.xml   single-node-wazuh.manager-1:/var/ossec/etc/decoders/pfsense_decoders.xml
docker cp config\custom\pfsense_rules.xml      single-node-wazuh.manager-1:/var/ossec/etc/rules/pfsense_rules.xml
docker cp config\custom\suricata_decoders.xml  single-node-wazuh.manager-1:/var/ossec/etc/decoders/suricata_decoders.xml
docker cp config\custom\suricata_rules.xml     single-node-wazuh.manager-1:/var/ossec/etc/rules/suricata_rules.xml
docker exec single-node-wazuh.manager-1 chown root:wazuh /var/ossec/etc/decoders/*.xml /var/ossec/etc/rules/*.xml
docker exec single-node-wazuh.manager-1 chmod 660 /var/ossec/etc/decoders/*.xml /var/ossec/etc/rules/*.xml
docker exec single-node-wazuh.manager-1 /var/ossec/bin/wazuh-control restart
```

### F9. Kiểm tra
Win10 `ping -n 30 -w 500 10.10.99.1` → Dashboard (Threat Hunting) rule **100102**.
Win10 `curl.exe -s http://testmyids.com` → rule **100111**. (Nhớ bỏ ghim agent,
log syslog gắn agent 000 `wazuh.manager`.)

---

# G. SOAR flow (Wazuh → n8n → TheHive/Cortex → chặn IP)

### G1. TheHive: org + user + key
Administration → Organisations: tạo org **SOAR-Lab**. Users: `huong@soar.internal`
(Normal, org-admin SOAR-Lab) và `n8n@soar.internal` (Service, analyst) → tạo
**API key** cho n8n (lưu vào doc 00).

### G2. Cortex: org + user + key + analyzer
Org **SOAR-Lab**; user `huong@soar.internal` (orgadmin), `thehive@soar.internal`
và `n8n@soar.internal` (read, analyze) → mỗi user một **API key** (doc 00).
Đăng ký key **AbuseIPDB** + **VirusTotal** (doc 00). Organization → Analyzers →
Enable **AbuseIPDB_2_0** và **VirusTotal_GetReport_3_1**, điền key.
> Nếu job Cortex `Failure` (AccessDenied `/tmp/cortex-jobs`): chown thư mục job về UID tiến trình Java:
> ```bash
> # [WSL]
> SRC=/home/ngochuong/soar-lab/thehive-cortex/testing/cortex/cortex-jobs
> JUID=$(docker exec cortex sh -c 'for p in /proc/[0-9]*; do [ "$(cat $p/comm 2>/dev/null)" = "java" ] && stat -c %u:%g $p && break; done')
> docker run --rm -v "$SRC":/x alpine chown -R "$JUID" /x
> ```

### G3. Nối TheHive ↔ Cortex
TheHive (admin@thehive.local) → Platform Management → Connectors → Cortex → **+**:
Server `Cortex-Local`, URL `http://cortex:9001/cortex` (tên container), API key của
`thehive@soar.internal`.

### G4. Nâng level alert Suricata theo severity
Thêm vào `config\custom\suricata_rules.xml` rồi cp + restart (như F8):
```xml
<rule id="100112" level="12"><if_sid>100111</if_sid><field name="alert.severity">^1$</field>
  <description>Suricata: High severity alert - $(alert.signature)</description></rule>
<rule id="100113" level="10"><if_sid>100111</if_sid><field name="alert.severity">^2$</field>
  <description>Suricata: Medium severity alert - $(alert.signature)</description></rule>
```

### G5. Wazuh → n8n (integration webhook, level ≥ 10)
Tạo `config\custom\custom-n8n.py` (POST full alert JSON tới webhook) rồi:
```powershell
# [HOST-PS]
cd F:\SOAR_Project\wazuh-docker\single-node
docker cp config\custom\custom-n8n.py single-node-wazuh.manager-1:/var/ossec/integrations/custom-n8n.py
docker exec single-node-wazuh.manager-1 cp /var/ossec/integrations/shuffle /var/ossec/integrations/custom-n8n
docker exec single-node-wazuh.manager-1 chown root:wazuh /var/ossec/integrations/custom-n8n /var/ossec/integrations/custom-n8n.py
docker exec single-node-wazuh.manager-1 chmod 750 /var/ossec/integrations/custom-n8n /var/ossec/integrations/custom-n8n.py
```
Thêm khối vào `wazuh_manager.conf` (dưới khối `<remote>` syslog) → cp + restart:
```xml
  <integration>
    <name>custom-n8n</name>
    <hook_url>http://host.docker.internal:5678/webhook/wazuh-alert</hook_url>
    <level>10</level>
    <alert_format>json</alert_format>
  </integration>
```

### G6. n8n – node Webhook
Workflow mới `SOAR - Wazuh alert intake` → node **Webhook**: Method POST, Path
`wazuh-alert`, Respond **Immediately**. Bật node nếu bị disabled. **Save + Publish/Active**
(Wazuh phải dùng URL production `/webhook/`, không phải `/webhook-test/`).

### G7. Node `Parsing Alert` (Code, Run Once for Each Item, JS)
Bóc `src_ip`, map level→severity TheHive, dựng description + observable IP,
`sourceRef = String(a.id)` (chống trùng). Code đầy đủ ở doc 07 (mục "Chi tiết bước 6").

### G8. Node `Create Alert TheHive` (HTTP Request)
POST `http://host.docker.internal:9000/thehive/api/v1/alert`, Auth = Header Auth
credential `TheHive - n8n key` (`Authorization: Bearer <API key n8n@soar.internal>`),
Body JSON `{{ JSON.stringify($json.thehive_alert) }}`.

### G9. `WhiteList Check` (Code) + `If` (IP ngoài?)
WhiteList Check lấy IP/level từ `$('Parsing Alert').item.json`, regex nội bộ
`^10\.10\.99\.`, `^172\.16\.10\.`, `^10\.10\.20\.`, `^192\.168\.210\.(1|2|132)$`,
`^127\.`; `is_internal = !ip || khớp`. Node **If**: `{{ $json.is_internal }}`
Boolean **is false** → nhánh true đi tiếp (gõ đúng, không để dấu cách trước `{{`).

### G10. Cortex: lấy analyzer → chạy → chờ (3 node HTTP, credential `Cortex - n8n key`)
- `Collect analyzer IP`: GET `http://host.docker.internal:9001/cortex/api/analyzer/type/ip`.
- `Run analyzer`: POST `.../analyzer/{{ $json.id }}/run`, JSON
  `{{ JSON.stringify({ data: $('WhiteList Check').item.json.src_ip, dataType:'ip', tlp:2, pap:2, message:'n8n SOAR' }) }}`.
- `Wait for output`: GET `.../job/{{ $json.id }}/waitreport?atMost=1minute`.

### G11. `Compilation of decisions` (Code, Run Once for All Items) + PATCH TheHive
Đọc AbuseIPDB `report.full.values[0].data.abuseConfidenceScore` + VT
`report.full.attributes.last_analysis_stats.malicious`, áp policy **block khi
level≥12 HOẶC score≥50 HOẶC VT malicious>0**, dựng `thehive_update`
(description+tags). Node `Alert TheHive`: PATCH
`.../api/v1/alert/{{ $json.thehive_alert_id }}`, JSON `{{ JSON.stringify($json.thehive_update) }}`.

### G12. pfSense: user chặn IP (least privilege)
```powershell
# [HOST-PS] tạo SSH key cho n8n
ssh-keygen -t ed25519 -f F:\SOAR_Project\keys\n8n_pfsense -N '""'
```
`[pfSense-GUI]`: System → Package Manager cài **sudo**. User Manager: tạo
`soar-n8n` (**không** vào admins; privilege *User - System: Shell account access*;
dán **public key** vào Authorized SSH Keys). System → Sudo: thêm dòng `soar-n8n` /
Run As `root` / **No Password** / Command `/usr/local/bin/easyrule`. System →
Advanced → Admin Access: **Enable Secure Shell**, **SSHd Key Only = Public Key Only**.
Test:
```powershell
# [HOST-PS]
ssh -i F:\SOAR_Project\keys\n8n_pfsense soar-n8n@10.10.99.254 "sudo -l"
# → (root) NOPASSWD: /usr/local/bin/easyrule
```

### G13. n8n: nhánh chặn
- Node **If `Blocked`**: `{{ $('Compilation of decisions').item.json.block }}`
  Boolean **is true** AND `{{ $('Compilation of decisions').item.json.src_ip }}`
  **matches regex** `^(\d{1,3}\.){3}\d{1,3}$` (chống command injection).
- Node **SSH `Block IP pfSense`**: credential **SSH Private Key** `pfSense - soar-n8n`
  (Host 10.10.99.254, user soar-n8n, dán private key, passphrase trống — **phải đổi
  từ SSH Password sang Private Key**). Command
  `sudo /usr/local/bin/easyrule block wan {{ $('Compilation of decisions').item.json.src_ip }}`.
- Node **`Tag blocked`**: PATCH alert, tags cũ `.concat(['soar:blocked'])`.

### G14. Publish
Save + **Publish** workflow. Gỡ IP test đã chặn:
`ssh ... soar-n8n@10.10.99.254 "sudo /usr/local/bin/easyrule unblock wan <ip-test>"`.

---

# H. Kịch bản kiểm thử

### H1. Web attack – SQL Injection (full auto-response)
```bash
# [VM-Kali]  tấn công vào IP WAN (giữ IP Kali thật), 1 request đủ sinh alert
curl "http://192.168.210.132/dvwa/vulnerabilities/sqli/?id=1'+UNION+SELECT+user,password+FROM+users--+-&Submit=Submit"
```
Kết quả: Suricata SQLi (sev1) → Wazuh **100112 level 12** → n8n → TheHive →
Cortex → **BLOCK** → tag `soar:blocked`. Kiểm chứng Kali bị chặn: `nmap`/`curl`
tới WAN → timeout.
> Nếu cổng 80 `filtered`: IP Kali còn trong alias block từ test trước →
> `easyrule unblock wan 192.168.210.130`.

### H2. Endpoint malware – FIM + VirusTotal
**Bật FIM cho Downloads** (Win10, sửa `ossec.conf` trong `<syscheck>`):
```xml
    <alert_new_files>yes</alert_new_files>
    <directories realtime="yes" check_all="yes" report_changes="yes">C:\Users\NgocHuong\Downloads</directories>
```
→ `Restart-Service WazuhSvc`.
**Bật tích hợp VirusTotal trên manager** (`wazuh_manager.conf`, cp + restart):
```xml
  <integration>
    <name>virustotal</name>
    <api_key><VIRUSTOTAL_API_KEY></api_key>
    <group>syscheck</group>
    <alert_format>json</alert_format>
  </integration>
```
**Test bằng EICAR** (file test chuẩn AV, an toàn):
```powershell
# [VM-Win10] (admin) tạm loại Downloads khỏi Defender để FIM kịp hash
Add-MpPreference -ExclusionPath "C:\Users\NgocHuong\Downloads"
# tạo file thường rồi ghi đè thành EICAR (tách chuỗi để không bị AMSI chặn)
Set-Content "C:\Users\NgocHuong\Downloads\vt_test.txt" -Value "baseline" -Encoding ascii
Start-Sleep 25
$a='X5O!P%@AP[4\PZX54(P^)7CC)7}'; $b='$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*'
Set-Content "C:\Users\NgocHuong\Downloads\vt_test.txt" -Value ($a+$b) -NoNewline -Encoding ascii
```
Kết quả Wazuh: rule **550** (file modified) → **87105 level 12** "VirusTotal:
Alert – 66 engines detected" + Sysmon **92213 level 15** (file drop). Alert đẩy
sang TheHive (không chặn IP vì không có IP ngoài).
Dọn sau khi chụp ảnh: xoá file + `Remove-MpPreference -ExclusionPath "C:\Users\NgocHuong\Downloads"`.

### H3. (Tùy chọn) Active Response xoá file độc trên endpoint
Trên agent Win10 tạo `active-response\bin\remove-threat.ps1` (đọc JSON stdin, xoá
`data.virustotal.source.file`) + `remove-threat.cmd` (gọi PowerShell). Trên
manager khai báo `<command>remove-threat</command>` + `<active-response>` với
`rules_id 87105`, `location local` → cp + restart. Test: thả lại EICAR → file tự
bị xoá, `active-responses.log` ghi `removed`.

### H4. Malware C2 (detection, không auto-block)
Dùng một mẫu lưu lượng C2 để kiểm thử chiều đi ra: Suricata *ET MALWARE* → Wazuh
**100112 level 12** → TheHive. **Không chặn** vì nguồn là máy nội bộ
(10.10.20.100) khớp whitelist — chặn đúng cần cô lập máy nhiễm (hướng mở rộng).
> An toàn: cô lập VM, chụp ảnh xong revert snapshot sạch.

---

## Phụ lục – nơi lưu file quan trọng
- Decoder/rule/script riêng: `wazuh-docker\single-node\config\custom\`.
- Workflow n8n export: `n8n_workflow_backup\` (không chứa secret).
- Key SSH pfSense: `keys\` (**không** push GitHub).
- Tài khoản/API key: `00-tai-khoan.md` (**ngoài** repo).
