# SOAR Lab – Phần 4 & 6b: Wazuh agent + Sysmon

> Wazuh manager: 10.10.99.1 (Docker trên host), phiên bản **4.14.8**. Agent phải cùng phiên bản hoặc cũ hơn manager.

## Checklist

- [x] A1. Windows client: cài Sysmon (config SwiftOnSecurity)
- [x] A2. Windows client: cài Wazuh agent `win10-client`: agent ID 001, IP 10.10.20.100, alert đầu tiên (rule 60608, kênh Application) về index `wazuh-alerts-4.x-2026.10.03` (2026-10-03)
- [x] A3. Windows client: cho agent đọc log Sysmon. ossec.log báo `(1951): Analyzing event log: 'Microsoft-Windows-Sysmon/Operational'` (2026-10-03 13:55)
- [x] A4. Agent `win10-client` Active, đọc được Application/Security/System + Sysmon
- [x] B1. DVWA: cài Wazuh agent `dvwa-web` 4.14.8-1 (đã hold), active, `Connected to the server ([10.10.99.1]:1514/tcp)` (2026-10-03 13:58)
- [x] B2. DVWA: thu log Apache access/error. Bộ cài Wazuh **tự thêm sẵn** 2 localfile apache2 vào ossec.conf (dòng 198, 203), nên `grep` tìm thấy và lệnh `cat >>` không chạy, không bị trùng. Logcollector báo `Analyzing file: '/var/log/apache2/access.log'` + `error.log` (2026-10-03 14:07)
- [x] B3. Kiểm tra agent Active + có log web
- [x] C. Snapshot các VM (`DVWA-agent`, `Win10-agent`), 2026-10-03

---

## A. Windows client (PowerShell **Run as Administrator** trong VM Windows)

### A1. Sysmon
Sysmon (Sysinternals) ghi chi tiết process creation, network connection, registry, file create... Security log mặc định của Windows không có những thông tin này. Config SwiftOnSecurity là bộ lọc phổ biến, đã lọc bớt nhiễu.
```powershell
$ProgressPreference = 'SilentlyContinue'
mkdir C:\Tools -Force | Out-Null; cd C:\Tools
Invoke-WebRequest https://download.sysinternals.com/files/Sysmon.zip -OutFile Sysmon.zip
Expand-Archive Sysmon.zip -DestinationPath C:\Tools\Sysmon -Force
Invoke-WebRequest https://raw.githubusercontent.com/SwiftOnSecurity/sysmon-config/master/sysmonconfig-export.xml -OutFile C:\Tools\Sysmon\sysmonconfig.xml
C:\Tools\Sysmon\Sysmon64.exe -accepteula -i C:\Tools\Sysmon\sysmonconfig.xml
Get-Service Sysmon64
```
Kết quả: service `Sysmon64` ở trạng thái Running.

### A2. Wazuh agent
```powershell
Invoke-WebRequest https://packages.wazuh.com/4.x/windows/wazuh-agent-4.14.8-1.msi -OutFile $env:TEMP\wazuh-agent.msi
msiexec.exe /i $env:TEMP\wazuh-agent.msi /q WAZUH_MANAGER='10.10.99.1' WAZUH_AGENT_NAME='win10-client'
Start-Sleep 10
NET START WazuhSvc
```
- `WAZUH_MANAGER`: agent đăng ký qua 1515 và gửi log qua 1514 tới host. Firewall pfSense (rule CLIENT → SOC_SERVER:WAZUH_PORTS) và Windows Firewall trên host đều đã mở.
- `WAZUH_AGENT_NAME`: tên hiển thị trên dashboard. Giữ hostname gốc của máy.

### A3. Cho agent đọc log Sysmon
Mặc định agent Windows chỉ đọc Application/Security/System. Thêm một khối `<ossec_config>` mới vào **cuối** file ossec.conf (Wazuh cho phép nhiều khối `<ossec_config>` trong cùng một file):
```powershell
$conf = "C:\Program Files (x86)\ossec-agent\ossec.conf"
Copy-Item $conf "$conf.bak" -Force
$add = @"

<ossec_config>
  <localfile>
    <location>Microsoft-Windows-Sysmon/Operational</location>
    <log_format>eventchannel</log_format>
  </localfile>
</ossec_config>
"@
Add-Content -Path $conf -Value $add -Encoding ASCII
Restart-Service WazuhSvc
Start-Sleep 5
Select-String -Path "C:\Program Files (x86)\ossec-agent\ossec.log" -Pattern "Sysmon"
```
Kết quả đúng: có dòng `Analyzing event log: 'Microsoft-Windows-Sysmon/Operational'`.

> **Lỗi đã gặp (2026-10-03):** cách cũ dùng `-replace '</ossec_config>\s*$'` không ăn, vì ossec.conf trên Windows kết thúc bằng comment `<!-- END of Default Configuration. -->` nằm **sau** `</ossec_config>`. Regex neo ở cuối file nên không khớp, file không đổi, agent không đọc Sysmon (ossec.log không có dòng Sysmon). Đã đổi sang cách thêm khối mới ở cuối file.

### A4. Kiểm tra
- Wazuh Dashboard (https://localhost) → **Agents management → Summary**: `win10-client` ở trạng thái **Active**, IP 10.10.20.100.
- **Threat Hunting → Events**: lọc theo agent `win10-client`, tìm `data.win.system.channel: "Microsoft-Windows-Sysmon/Operational"`. Mở Notepad hoặc cmd trên Windows sẽ thấy event Sysmon (Event ID 1 – Process Create).
- Log agent nếu lỗi: `Get-Content "C:\Program Files (x86)\ossec-agent\ossec.log" -Tail 30`

### Lưu ý khi kiểm tra Sysmon
- Event Sysmon bình thường (mở Notepad...) phần lớn khớp rule **level 0**, nên **không được lưu thành alert** và không hiện ở Threat Hunting. Đây là hành vi mặc định của Wazuh: chỉ lưu alert, không lưu toàn bộ event.
- Cách chắc chắn nhất để biết agent đã đọc kênh Sysmon: xem `ossec.log` trên agent, phải có dòng `Analyzing event log: 'Microsoft-Windows-Sysmon/Operational'`.
- Alert Sysmon có level cao hơn (hành vi đáng ngờ) sẽ hiện khi lọc `rule.groups: sysmon`.


---

## B. DVWA (Ubuntu 24.04, zone DMZ, chạy bằng root)

DMZ được ra Internet qua 443 (alias WEB_PORTS), nên tải được trực tiếp từ kho apt của Wazuh.

### B1. Cài agent `dvwa-web` (bản 4.14.8, cùng phiên bản manager)
```bash
apt-get install -y gnupg apt-transport-https
curl -s https://packages.wazuh.com/key/GPG-KEY-WAZUH | gpg --no-default-keyring --keyring gnupg-ring:/usr/share/keyrings/wazuh.gpg --import && chmod 644 /usr/share/keyrings/wazuh.gpg
echo "deb [signed-by=/usr/share/keyrings/wazuh.gpg] https://packages.wazuh.com/4.x/apt/ stable main" > /etc/apt/sources.list.d/wazuh.list
apt-get update
WAZUH_MANAGER="10.10.99.1" WAZUH_AGENT_NAME="dvwa-web" apt-get install -y wazuh-agent=4.14.8-1
apt-mark hold wazuh-agent
systemctl daemon-reload
systemctl enable --now wazuh-agent
systemctl status wazuh-agent --no-pager | head -5
```
`apt-mark hold` giữ agent ở 4.14.8. Nếu không giữ, `apt upgrade` có thể nâng agent lên bản mới hơn manager, và agent mới hơn manager sẽ không kết nối được.

### B2. Thu log Apache
```bash
grep -n "apache2" /var/ossec/etc/ossec.conf || cat >> /var/ossec/etc/ossec.conf <<'EOF2'

<ossec_config>
  <localfile>
    <log_format>apache</log_format>
    <location>/var/log/apache2/access.log</location>
  </localfile>
  <localfile>
    <log_format>apache</log_format>
    <location>/var/log/apache2/error.log</location>
  </localfile>
</ossec_config>
EOF2
systemctl restart wazuh-agent
grep -i "apache2" /var/ossec/logs/ossec.log | tail -3
```
Kết quả đúng: ossec.log có dòng `Analyzing file: '/var/log/apache2/access.log'`.

### B3. Kiểm tra
Wazuh Dashboard → Agents management → Summary: `dvwa-web` (172.16.10.10) **Active**.
