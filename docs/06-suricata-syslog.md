# SOAR Lab – Phần 5: Suricata trên pfSense + đẩy log pfSense/Suricata về Wazuh

> pfSense 2.8.1, package suricata 7.0.x, Wazuh manager 4.14.8 (Docker trên host 10.10.99.1)

## Mục tiêu

- Suricata chạy chế độ **IDS** (chỉ phát hiện, chưa chặn) trên interface **DMZ** (em1) và **CLIENT** (em2).
- Alert Suricata (EVE JSON) cùng firewall log của pfSense được gửi qua **syslog UDP 514** tới Wazuh trên host.
- Vì sao chạy trên DMZ/CLIENT mà không chạy trên WAN: trên WAN, mọi đích đều là IP WAN của pfSense (trước NAT). Trên DMZ, alert ghi đúng IP thật của DVWA (172.16.10.10), vẫn giữ IP nguồn của Kali vì port forward chỉ đổi IP đích.

## Checklist

- [x] 1. Cài package Suricata (pfSense-pkg-suricata 7.0.9, engine suricata 7.0.11), ngày 2026-10-03
  - Lỗi đã gặp: cài qua GUI bị treo ở `Fetching hyperscan-5.4.2.pkg` (mạng tới server Netgate chập chờn, pfSense vẫn ping 8.8.8.8 được). Cách xử lý: console → 8 (Shell) → `pkill -f pkg-static; rm -f /var/cache/pkg/hyperscan*; pkg-static install -y pfSense-pkg-suricata`
  - SSH vào pfSense bị timeout vì SSH mặc định tắt (pfSense bỏ qua kết nối tới cổng đóng thay vì báo refused). Bật ở System → Advanced → Admin Access → Enable Secure Shell
- [x] 2. Tắt hardware offloading: tick thêm *Disable hardware checksum offload*. TSO và LRO đã được tick sẵn mặc định. Save + reboot
- [x] 3. Global Settings: bật ETOpen (chỉ ETOpen), update 12h. Tải rule thành công 2026-10-03 23:46, MD5 c9f5b0df001cee9f406347acd840d033
- [x] 4. Interface DMZ (em1) `DMZ_IDS`: đang chạy (✔ xanh), Blocking DISABLED (IDS), Pattern Match AUTO (2026-10-04)
  - EVE: SYSLOG/LOCAL1/NOTICE, **chỉ log Alerts**. Payload = NO, bỏ packet dump và App Layer metadata, giữ *Log additional HTTP data*. Bỏ tick hết EVE Logged Traffic/Info/Extended, bỏ EVE Log Drops
  - Lý do giảm kích thước: syslog trên pfSense có giới hạn độ dài dòng. Alert kèm payload base64 dài vài KB có thể bị cắt, JSON hỏng và Wazuh không decode được
  - Lưu ý dễ nhầm: menu **Interfaces** trên thanh trên cùng là cấu hình card mạng của pfSense, còn tab **Interfaces** bên trong Services → Suricata mới là của Suricata
- [x] 5. Interface CLIENT (em2) `CLIENT_IDS`: đang chạy (✔ xanh), Blocking DISABLED (IDS), Pattern Match AUTO, EVE ra syslog giống DMZ (2026-10-04)
- [x] 6. pfSense Remote Logging → 10.10.99.1:514 (Source SOC, BSD RFC 3164, Everything). Xác nhận qua archives.log: log tới từ 172.22.0.1 (Docker NAT)
- [x] 7. Wazuh manager nhận syslog UDP 514: `Listening on port 514/UDP (syslog)` lúc 2026-10-04 00:26 (phải chép config bằng `cp` vì `restart` không áp dụng, xem mục 7)
- [x] 8. Kiểm tra alert pfSense + Suricata trên Wazuh Dashboard (2026-10-04)
  - [x] 8a. pfSense: sau khi thêm decoder/rule riêng, chạy `ping -n 30 -w 500 10.10.99.1` từ Win10 thì `alerts.json` có 1 alert **100102** (2026-10-04 01:08)
    - Trên Dashboard (Threat Hunting → Events, `rule.id: 100102`): 1 hit lúc 01:07:41, agent.name `wazuh.manager`, level 10, "pfSense: multiple firewall blocks from same source 10.10.20.100."
    - Lưu ý: log syslog gắn với **agent 000 (`wazuh.manager`)**. Nếu đang ghim một agent khác (ví dụ win10-client 001) thì sẽ không thấy alert, phải bỏ ghim trước.
  - [x] 8b. Suricata: sau khi thêm decoder/rule riêng, Dashboard có alert **100111** level 3 "Suricata: Alert - GPL ATTACK_RESPONSE id check returned root", agent `wazuh.manager`, lúc 2026-10-04 01:23:56
    - `testmynids.org/uid/index.html` không trả về nội dung, phải dùng `curl.exe -s http://testmyids.com` (trả về `uid=0(root)...`) → alert SID **2100498** "GPL ATTACK_RESPONSE id check returned root" trên em2
    - Log EVE tới Wazuh nguyên vẹn, JSON không bị cắt:
      `Oct  4 01:17:13 suricata[38808]: {"timestamp":...,"event_type":"alert",...}`
    - Cùng lỗi thiếu hostname: logtest báo `hostname: 'suricata[38808]:'`, `No decoder matched`, rơi vào rule 1002 level 2 (từ "Bad" trong category), nên không có alert
    - Cách xử lý: decoder `suricata-bsd` bóc phần `suricata[pid]: ` rồi giao JSON cho `JSON_Decoder` (`offset="after_prematch"`), cùng rule riêng 100110–100111 mô phỏng 86600–86601

`suricata_decoders.xml`:
```xml
<!-- pfSense Suricata EVE via BSD syslog without hostname -->
<decoder name="suricata-bsd">
  <prematch type="pcre2">(?:suricata\[\d+\]: |^)(?=\{"timestamp")</prematch>
  <plugin_decoder offset="after_prematch">JSON_Decoder</plugin_decoder>
</decoder>
```

`suricata_rules.xml`:
```xml
<group name="ids,suricata,">
  <rule id="100110" level="0">
    <decoded_as>suricata-bsd</decoded_as>
    <field name="event_type">\.+</field>
    <description>Suricata messages (pfSense, BSD syslog).</description>
  </rule>

  <rule id="100111" level="3">
    <if_sid>100110</if_sid>
    <field name="event_type">^alert$</field>
    <description>Suricata: Alert - $(alert.signature)</description>
  </rule>
</group>
```
  - [x] Tắt `logall` sau khi test xong (2026-10-04 01:28). Sửa file trên host bằng PowerShell `[IO.File]::WriteAllText(...)` (Notepad lần đầu chưa lưu), rồi `cp` + restart

**Phase 5 hoàn tất (2026-10-04).** File decoder/rule riêng nằm trong `/var/ossec/etc/decoders|rules/` (named volume) và có bản gốc trên host tại `config\custom\`

---

### 1. Cài Suricata
**System → Package Manager → Available Packages** → tìm `suricata` → **Install** → **Confirm**. Chờ báo `Success`.

### 2. Tắt hardware offloading
**System → Advanced → tab Networking**, kéo xuống mục *Network Interfaces*, tick cả 3 ô:
- ☑ Disable hardware checksum offload
- ☑ Disable hardware TCP segmentation offload
- ☑ Disable hardware large receive offload

**Save**, rồi **Diagnostics → Reboot** pfSense.

Lý do: khi bật offload, card mạng (kể cả card ảo e1000) gộp hoặc để card tính checksum hộ. Suricata khi đó đọc phải gói "chưa hoàn chỉnh", sinh cảnh báo checksum sai và bỏ sót tấn công. Netgate khuyến nghị tắt khi dùng Suricata/Snort.

### 3. Global Settings
**Services → Suricata → tab Global Settings**:
- ☑ **Install ETOpen Emerging Threats rules** (miễn phí, không cần key)
- Update Interval: **12 HOURS**
- ☑ Live Rule Swap on Update
- **Save**

Sang tab **Updates** → bấm **Update** → chờ đến khi dòng ETOpen hiện ngày giờ và MD5. Lần đầu tải khoảng 1–3 phút.

### 4. Interface DMZ
**Services → Suricata → tab Interfaces → Add**:

| Mục | Giá trị |
|---|---|
| Enable | ☑ |
| Interface | **DMZ** |
| Description | `DMZ_IDS` |
| Block Offenders | ☐ (không tick, chỉ IDS) |
| EVE JSON Log | ☑ **Enable EVE JSON log** |
| EVE Output Type | **SYSLOG** |
| EVE Syslog Output Facility | **LOCAL1** |
| EVE Syslog Output Priority | **NOTICE** |
| EVE Logged Info | Chỉ tick **Alerts** (tránh quá tải log) |

**Save**. Sau đó vào tab **DMZ Categories** của interface này và tick các bộ rule:
`emerging-web_server`, `emerging-web_specific_apps`, `emerging-sql`, `emerging-exploit`, `emerging-attack_response`, `emerging-scan`, `emerging-shellcode`.
**Save**.

Quay lại tab **Interfaces** → bấm ▶️ (Start) ở dòng DMZ. Biểu tượng chuyển xanh là chạy.

### 5. Interface CLIENT
Làm giống bước 4 với Interface **CLIENT**, Description `CLIENT_IDS`, EVE xuất SYSLOG/LOCAL1/NOTICE, chỉ log Alerts.
Categories: `emerging-malware`, `emerging-phishing`, `emerging-coinminer`, `emerging-policy`, `emerging-dns`, `emerging-attack_response`.
Save → Start.

### 6. pfSense gửi log về Wazuh
**Status → System Logs → tab Settings**, kéo xuống *Remote Logging Options*:
- ☑ Enable Remote Logging
- Source Address: **SOC** (10.10.99.254)
- IP Protocol: IPv4
- Remote log servers: `10.10.99.1:514`
- Remote Syslog Contents: ☑ **Everything**
- Log Message Format: **syslog (RFC 3164)** (định dạng Wazuh decode sẵn)
- **Save**

### 7. Wazuh manager nhận syslog
Trên host (PowerShell), mở file cấu hình manager:
```powershell
notepad F:\SOAR_Project\wazuh-docker\single-node\config\wazuh_cluster\wazuh_manager.conf
```
Tìm khối `<remote>` có sẵn (connection `secure`, port 1514). Ngay **bên dưới** khối đó, thêm:
```xml
  <remote>
    <connection>syslog</connection>
    <port>514</port>
    <protocol>udp</protocol>
    <allowed-ips>0.0.0.0/0</allowed-ips>
  </remote>
```
Lưu file rồi chép config vào container và restart Wazuh bên trong:
```powershell
cd F:\SOAR_Project\wazuh-docker\single-node
docker exec single-node-wazuh.manager-1 cp /wazuh-config-mount/etc/ossec.conf /var/ossec/etc/ossec.conf
docker exec single-node-wazuh.manager-1 chown root:wazuh /var/ossec/etc/ossec.conf
docker exec single-node-wazuh.manager-1 chmod 660 /var/ossec/etc/ossec.conf
docker exec single-node-wazuh.manager-1 /var/ossec/bin/wazuh-control restart
docker exec single-node-wazuh.manager-1 grep -i "514/UDP" /var/ossec/logs/ossec.log
```
Kết quả đúng: `Listening on port 514/UDP (syslog)`.

**Lỗi đã gặp (2026-10-04): `docker compose restart` không áp dụng config mới.**
- Hiện tượng: sau restart, remoted chỉ mở 1514/TCP, không có dòng 514/UDP.
- Kiểm tra: file trên host và `/wazuh-config-mount/etc/ossec.conf` đều có block syslog (dòng 35), nhưng `/var/ossec/etc/ossec.conf` thì không có.
- Nguyên nhân: file `wazuh_manager.conf` được mount vào `/wazuh-config-mount`, chỉ được chép vào `/var/ossec/etc` lúc container khởi tạo. `/var/ossec/etc` lại nằm trong named volume nên giữ bản cũ, `restart` không chép lại.
- Cách xử lý: tự chép file bằng `cp` như trên rồi chạy `wazuh-control restart`.
- Áp dụng cho mọi lần sửa `wazuh_manager.conf` sau này (thêm decoder, rule, active response...).

**Kiểm tra bước 8 (2026-10-04 00:33):**
- Đã bật `<logall>yes</logall>` tạm thời.
- Log pfSense **đã tới** Wazuh: `archives.log` có 4 dòng `filterlog`.
- IP nguồn trong archives là `172.22.0.1`, tức IP gateway của Docker, xác nhận Docker Desktop NAT địa chỉ nguồn. Vì vậy `allowed-ips` phải để 0.0.0.0/0.
- Ví dụ dòng log thô:
  `Oct  4 00:32:39 filterlog[79644]: 103,,,1791007077,em2,match,block,in,4,0x0,,128,1719,0,none,1,icmp,60,10.10.20.100,10.10.99.1,request,1,1640`
- Nhưng `alerts.json` không có `pfsense`, nghĩa là log tới nơi mà không thành alert.
- **Nguyên nhân là thiết kế của Wazuh, không phải lỗi.** Trong ruleset `0540-pfsense_rules.xml`:
  - Rule **87700** (level 0) gom mọi log `filterlog`.
  - Rule **87701** (level 5, "pfSense firewall drop event") có `<options>no_log</options>`, nên từng gói bị chặn **không** tạo alert, để tránh ngập alert.
  - Rule **87702** (level 10, "Multiple pfSense firewall blocks events from same source", MITRE T1110) chỉ tạo alert khi có **18 lần chặn trong 45 giây từ cùng một IP nguồn**.
  - Ping thường của Windows bị chặn thì mỗi gói mất khoảng 5 giây (chờ timeout), nên không đủ 18 lần trong 45 giây.
- Cách test: trên Win10 chạy `ping -n 30 -w 500 10.10.99.1` (timeout 0,5 giây) → rule 87702 bắn alert.
- **Thực tế 87702 vẫn ra 0, nên kiểm tra bằng `wazuh-logtest`:** kết quả `hostname: 'filterlog[79644]:'` và `No decoder matched`.

**Lỗi đã gặp (2026-10-04): decoder pfSense mặc định không khớp log của pfSense 2.8**
- Root cause: pfSense gửi BSD syslog (RFC 3164) **không có trường hostname**:
  `Oct  4 00:32:39 filterlog[79644]: 103,,,...`
  Predecoder của Wazuh luôn coi token sau timestamp là hostname, nên `filterlog[79644]:` bị gán vào hostname và `program_name` bị trống (lệch cột). Decoder `pf` mặc định cần `<program_name>filterlog</program_name>` nên không khớp. Rule 87700/87701/87702 cũng không bao giờ chạy.
- Cách xử lý: viết decoder riêng nhận diện log filterlog bằng nội dung (`,match,block|pass,in|out,4,`) thay vì program_name, cùng bộ rule riêng 100100–100102 mô phỏng lại 87700–87702.
- File gốc lưu trên host tại `F:\SOAR_Project\wazuh-docker\single-node\config\custom\`, rồi `docker cp` vào `/var/ossec/etc/decoders/` và `/var/ossec/etc/rules/` (thư mục nằm trong named volume nên không mất khi restart).

`pfsense_decoders.xml`:
```xml
<!-- pfSense 2.8 BSD syslog has no hostname: predecoder puts "filterlog[pid]:" into hostname -->
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

`pfsense_rules.xml`:
```xml
<group name="pfsense,">
  <rule id="100100" level="0">
    <decoded_as>pfsense-bsd</decoded_as>
    <description>pfSense filterlog (BSD syslog without hostname).</description>
  </rule>

  <rule id="100101" level="5">
    <if_sid>100100</if_sid>
    <action>block</action>
    <options>no_log</options>
    <description>pfSense firewall drop event.</description>
    <group>firewall_block,</group>
  </rule>

  <rule id="100102" level="10" frequency="18" timeframe="45" ignore="240">
    <if_matched_sid>100101</if_matched_sid>
    <same_source_ip />
    <description>pfSense: multiple firewall blocks from same source $(srcip).</description>
    <mitre>
      <id>T1110</id>
    </mitre>
    <group>multiple_blocks,</group>
  </rule>
</group>
```

Kết quả logtest sau khi cài (2026-10-04 01:06):
- Decoder `pfsense-bsd` tách đủ các trường action=block, srcip=10.10.20.100, dstip=10.10.99.1, interface=em2, protocol=icmp.
- Khớp rule `100101` level 5.
- Logtest vẫn in "Alert to be generated" vì nó bỏ qua `no_log`; trên hệ thống thật rule 100101 không ghi alert.

Cài vào container:
```powershell
cd F:\SOAR_Project\wazuh-docker\single-node
docker cp config\custom\pfsense_decoders.xml single-node-wazuh.manager-1:/var/ossec/etc/decoders/pfsense_decoders.xml
docker cp config\custom\pfsense_rules.xml single-node-wazuh.manager-1:/var/ossec/etc/rules/pfsense_rules.xml
docker exec single-node-wazuh.manager-1 chown root:wazuh /var/ossec/etc/decoders/pfsense_decoders.xml /var/ossec/etc/rules/pfsense_rules.xml
docker exec single-node-wazuh.manager-1 chmod 660 /var/ossec/etc/decoders/pfsense_decoders.xml /var/ossec/etc/rules/pfsense_rules.xml
docker exec single-node-wazuh.manager-1 /var/ossec/bin/wazuh-control restart
```
Vì sao `allowed-ips` là `0.0.0.0/0`: Docker Desktop trên Windows NAT gói tin vào container, nên Wazuh thấy IP nguồn là IP nội bộ của Docker chứ không phải 10.10.99.254. Nếu chỉ cho phép 10.10.99.254, Wazuh sẽ loại bỏ log. Việc giới hạn nguồn đã do Windows Firewall đảm nhận (rule `SOAR - Wazuh syslog (514/UDP)` chỉ cho 10.10.99.254), đây là biện pháp bù trừ.

### 8. Kiểm tra
- pfSense: **Status → System Logs → Firewall** có log chặn. Từ Win10 chạy `ping 10.10.99.1` để tạo log chặn.
- Wazuh Dashboard → Threat Hunting → Events: tìm `rule.groups: pfsense` (log firewall) và `rule.groups: suricata` (alert IDS).
