# SOAR Lab – Quy trình triển khai end-to-end

> Tài liệu tổng hợp toàn bộ quá trình dựng lab SOAR, từ hạ tầng đến khi chạy
> được chuỗi tự động phát hiện – phản ứng, kèm kết quả kiểm thử.
> Đề tài: *Nghiên cứu ứng dụng tự động hóa trong vận hành an ninh mạng nhằm nâng
> cao năng lực phát hiện và phản ứng sự cố trong hệ thống SOC.*
> Chi tiết từng lệnh nằm ở các doc 01–07; đây là mạch xuyên suốt + lý do + bằng chứng.
> Cập nhật: 2026-10-09

---

## 0. Tổng quan & kiến trúc

Lab mô phỏng một SOC thu nhỏ: thu thập log từ nhiều nguồn về một SIEM (Wazuh),
khi có cảnh báo nghiêm trọng thì một bộ điều phối (n8n) tự động tạo hồ sơ sự cố
(TheHive), làm giàu dữ liệu (Cortex: AbuseIPDB, VirusTotal) và ra quyết định
chặn IP tấn công trên tường lửa (pfSense) — không cần analyst thao tác tay.

```
            Internet(giả lập)         WAN 192.168.210.0/24 (VMnet8 NAT)
            Kali 192.168.210.130 ─────┐
                                      ▼
                              ┌────────────────┐
                              │   pfSense FW   │  Suricata IDS (DMZ, CLIENT)
                              │  + Suricata    │
                              └──┬────┬────┬───┘
                 DMZ 172.16.10/24│    │    │10.10.20/24 CLIENT
                  (VMnet2)       │    │    │ (VMnet3)
                      ┌──────────┘    │    └──────────┐
                      ▼               │               ▼
               DVWA 172.16.10.10      │        Win10 10.10.20.100
               (web server)           │        (+ Sysmon, Wazuh agent)
                                      │        SOC 10.10.99/24 (VMnet4)
                                      ▼
                         Host Windows 10.10.99.1  (Docker Desktop + WSL2)
             ┌──────────────────────────────────────────────────────────┐
             │  Wazuh(SIEM)  ·  n8n(SOAR)  ·  TheHive(SIRP)  ·  Cortex  │
             └──────────────────────────────────────────────────────────┘
```

**Phân vùng mạng (zero-trust theo zone):**

| Zone | VMnet | Subnet | pfSense IF | Thành phần |
|---|---|---|---|---|
| WAN | VMnet8 (NAT) | 192.168.210.0/24 | em0 (DHCP .132) | Kali (attacker) |
| DMZ | VMnet2 | 172.16.10.0/24 | em1 = DMZ .1 | DVWA |
| CLIENT | VMnet3 | 10.10.20.0/24 | em2 = CLIENT .1 | Windows 10 |
| SOC/MGMT | VMnet4 | 10.10.99.0/24 | em3 = LAN/SOC .254 | Host + Docker stack (host .1) |

**Phiên bản:** Wazuh 4.14.8 · TheHive 5.8.0 · Cortex 4.1.0 · n8n latest · pfSense
CE 2.8.1 + Suricata 7.0.9 · DVWA (PHP 8.3/Apache/MariaDB trên Ubuntu 24.04) ·
Windows 10 22H2 + Sysmon (config SwiftOnSecurity).

**Nguyên tắc thiết kế xuyên suốt:**
- Mỗi zone tách biệt, firewall mặc định chặn, chỉ mở đúng luồng cần.
- Tấn công từ "Internet" phải đi qua NAT + firewall như thật (Suricata thấy IP
  thật hai đầu nhờ đặt IDS ở DMZ/CLIENT chứ không ở WAN).
- SOAR hành động theo nguyên tắc **least privilege** và **không bao giờ chặn IP
  nội bộ**.

---

## 1. Nền tảng Docker trên host (doc 01)

Toàn bộ lớp SOC chạy bằng Docker trên host Windows (Docker Desktop, backend
WSL2). Lý do bố trí:

- **Wazuh single-node** chạy từ `F:\SOAR_Project\wazuh-docker\single-node`
  (CMD/PowerShell). Config chỉ là XML/YAML, dữ liệu nằm trong Docker named
  volume nên chạy từ Windows không vấn đề.
- **TheHive + Cortex** (bộ compose chính thức của StrangeBee, profile
  `testing`) và **n8n** chạy trong distro **Ubuntu-24.04 (WSL2)** ở
  `~/soar-lab/`.

**Vì sao TheHive/Cortex/n8n đặt trong WSL ext4 chứ không trên ổ `F:` (NTFS):**
Cassandra và Elasticsearch ghi dữ liệu cần đúng quyền sở hữu Linux (uid/gid).
Trên ext4 của WSL thì nhanh và đúng permission; nếu để trên NTFS/DrvFs (`/mnt/f`)
thì chậm và hay lỗi phân quyền, database không khởi động được. Đây cũng là lý do
không gom nguyên các stack này sang `F:` (xem mục 8).

**Cổng mở trên host:** 443 (Wazuh Dashboard), 1514/1515 (agent), 514/udp
(syslog), 55000 (Wazuh API), 9000 (TheHive), 9001 (Cortex), 5678 (n8n). Bỏ
container nginx của bộ TheHive/Cortex vì nó chiếm 443 trùng Wazuh.

**Lỗi & xử lý tiêu biểu:**
- `docker could not be found in this WSL 2 distro`: Ubuntu cài sau Docker Desktop
  → bật lại WSL integration, `wsl --terminate Ubuntu-24.04`.
- Elasticsearch yêu cầu `vm.max_map_count=262144` → đặt trong `.wslconfig`.

Kết quả mốc: đủ 8 container Up, đăng nhập được cả 4 UI (2026-10-02).

---

## 2. Mạng VMware + pfSense (doc 03)

**Tạo 3 VMnet host-only** (VMnet2/3 không gắn host, không DHCP; VMnet4 giữ host
adapter = 10.10.99.1). Bỏ host adapter ở DMZ/CLIENT để host không thành "cửa
sau" đi vòng qua firewall — đúng mô hình thật.

**Gán interface pfSense:** cố ý đặt interface **LAN của pfSense vào zone SOC**
(em3), vì pfSense chỉ cho vào Web GUI từ interface LAN (anti-lockout rule), mà
host quản trị nằm ở SOC. Zone client đổi tên thành CLIENT.

**Firewall theo zone** (mặc định chặn, chỉ mở đúng luồng) — alias + rule:
- DMZ: chỉ cho ra Wazuh (1514/1515), DNS/NTP tới pfSense, ra Internet 80/443;
  **chặn + log** mọi truy cập vào RFC1918 (nếu DVWA bị chiếm cũng không pivot
  được vào SOC/CLIENT).
- CLIENT: tương tự, thêm cho vào DVWA 80/443; ra Internet tự do (giả lập nhân
  viên); chặn + log vào các vùng nội bộ khác.
- **NAT port forward `WAN:80 → DVWA`**: Kali chỉ thấy IP WAN pfSense, mọi tấn
  công web đi qua NAT + firewall như thật.

**Root cause đáng nhớ:** sau khi gán LAN=em3, host không ping được 10.10.99.254
(`Destination net unreachable`) vì card VMnet4 trên Windows còn giữ IP DHCP cũ
(192.168.1.100) từ DHCP mặc định của pfSense → đặt tĩnh 10.10.99.1/24 cho card
VMnet4 là hết.

Nâng pfSense 2.7.2 → **2.8.1** (giữ 2.8.1 vì Package Manager còn `suricata
7.0.9`; 2.9.0 có thể chưa có package).

---

## 3. DVWA – web server DMZ (doc 02)

Ubuntu 24.04 + Apache + MariaDB + PHP 8.3 + DVWA (`digininja/DVWA`). Cài khi còn
ở NAT (cần Internet), test xong mới chuyển sang **VMnet2, IP tĩnh
172.16.10.10/24**, gateway/DNS 172.16.10.1 (pfSense).

Kiểm chứng sau khi vào DMZ: DVWA ra Internet 443 OK; gửi được Wazuh 1514;
**ping SOC thất bại** (bị rule Block chặn + ghi log — đúng thiết kế); từ Kali
`curl http://<WAN>/dvwa/login.php` → 200 (NAT chạy đúng). Lưu ý DVWA mặc định
security `impossible`, khi tấn công phải hạ xuống Low/Medium.

---

## 4. Windows client + Sysmon + Wazuh agent (doc 04, 05)

Windows 10 22H2, tài khoản local `NgocHuong`, nhận DHCP 10.10.20.100 (zone
CLIENT). Giữ Defender bật (giống máy nhân viên thật). Đồng bộ NTP về pfSense để
log khớp giờ.

- **Sysmon** (config SwiftOnSecurity): ghi process create, network, registry,
  file create — những thứ Security log mặc định không có.
- **Wazuh agent** `win10-client` (4.14.8): đăng ký qua 1515, gửi log 1514. Thêm
  khối `<ossec_config>` đọc kênh `Microsoft-Windows-Sysmon/Operational`.
  - *Root cause đã gặp:* cách cũ dùng regex thay `</ossec_config>` không ăn vì
    file kết thúc bằng comment nằm **sau** thẻ đóng → đổi sang thêm khối mới ở
    cuối file (Wazuh cho nhiều khối `<ossec_config>`).

**DVWA agent** `dvwa-web` (4.14.8, `apt-mark hold` để không bị nâng vượt
manager) + thu log Apache access/error.

Lưu ý khi kiểm chứng Sysmon: event thường khớp rule level 0 nên Wazuh **không
lưu** thành alert — cách chắc chắn để biết agent đọc được kênh là xem dòng
`Analyzing event log: 'Microsoft-Windows-Sysmon/Operational'` trong `ossec.log`.

---

## 5. Suricata + đẩy log pfSense/Suricata về Wazuh (doc 06)

Suricata chạy **IDS** (chỉ phát hiện) trên **DMZ (em1)** và **CLIENT (em2)**,
bộ rule ETOpen. Đặt ở DMZ/CLIENT chứ không ở WAN để alert giữ đúng IP thật hai
đầu (trên WAN mọi đích đều là IP WAN trước NAT). EVE JSON xuất qua **syslog
UDP 514** về Wazuh; tắt payload/packet dump để dòng syslog không bị cắt làm hỏng
JSON. Tắt hardware offload (Netgate khuyến nghị, nếu không Suricata đọc gói
"chưa hoàn chỉnh" → cảnh báo checksum giả + bỏ sót).

**Root cause lớn của phase này — decoder mặc định không khớp pfSense 2.8:**
pfSense gửi BSD syslog (RFC 3164) **không có trường hostname**:
`Oct 4 00:32:39 filterlog[79644]: 103,,,...`. Predecoder của Wazuh luôn coi token
sau timestamp là hostname → `filterlog[79644]:` bị nuốt vào hostname, lệch cột,
decoder `pf`/`suricata` mặc định (cần `program_name`) không khớp → rule
87700/87701/87702 và 86600 không bao giờ chạy.

**Cách xử lý:** viết **decoder + rule riêng** nhận diện log bằng *nội dung* thay
vì program_name:
- `pfsense-bsd` (prematch `,match,(block|pass),(in|out),4,`) + rule 100100–100102
  (mô phỏng 87700–87702; 100102 gom "nhiều block cùng nguồn", MITRE T1110).
- `suricata-bsd` (bóc `suricata[pid]: ` rồi giao JSON cho `JSON_Decoder`) + rule
  100110/100111 (mô phỏng 86600/86601).

File gốc giữ ở `...\config\custom\`, nạp bằng `docker cp` vào
`/var/ossec/etc/decoders|rules/`.

**Một root cause vận hành quan trọng (dùng lại ở mọi lần sửa config manager):**
`docker compose restart` **không** áp dụng `wazuh_manager.conf` mới. File được
mount vào `/wazuh-config-mount`, chỉ chép sang `/var/ossec/etc/ossec.conf` (named
volume) lúc container **khởi tạo**. Vì vậy mỗi lần sửa phải tự
`docker cp ... :/var/ossec/etc/ossec.conf` rồi `wazuh-control restart`.

Bằng chứng: `Listening on port 514/UDP (syslog)`; alert 100102 (ping bị chặn
nhiều lần) và 100111 (`curl http://testmyids.com` → GPL ATTACK_RESPONSE).

---

## 6. SOAR flow: Wazuh → n8n → TheHive/Cortex → chặn IP pfSense (doc 07)

Đây là trọng tâm đề tài. Chuỗi tự động:

```
Wazuh (alert level ≥ 10)
   │ integration webhook (custom-n8n.py → host.docker.internal:5678)
   ▼
n8n  Webhook → Parsing Alert → Create Alert TheHive → WhiteList Check → If(IP ngoài?)
        → Collect analyzer IP → Run analyzer (Cortex) → Wait for output
        → Compilation of decisions → Alert TheHive(PATCH) → If(Blocked?)
        → Block IP pfSense (SSH easyrule) → Tag blocked
```

**6.1 Nâng level alert Suricata theo severity** (để lọc cái gì đáng đẩy sang
n8n): rule 100112 level 12 cho severity 1 (High), 100113 level 10 cho severity 2
(Medium), severity 3 giữ level 3 (không đẩy).

**6.2 Wazuh → n8n:** integration `custom-n8n` (bản sao script khởi chạy của
`shuffle`, gọi `custom-n8n.py` POST full alert JSON) + khối `<integration>` lọc
`level ≥ 10`, webhook `http://host.docker.internal:5678/webhook/wazuh-alert`
(dùng `host.docker.internal` vì n8n ở stack compose khác, không chung mạng Docker
với Wazuh).

**6.3 Tạo alert + observable trên TheHive:** node `Parsing Alert` (JS) bóc
`src_ip` (Suricata `data.src_ip`, pfSense `data.srcip`), map level→severity
TheHive, dựng mô tả + observable IP, đặt `sourceRef = id alert Wazuh` để TheHive
**chống tạo trùng**.

**6.4 Bỏ qua IP nội bộ (WhiteList Check):** regex nội bộ cho SOC/DMZ/CLIENT +
gateway NAT. `isInternal = !ip || <khớp regex>`. IP nội bộ → dừng, không enrich,
không chặn. *Đây là hàng rào an toàn cốt lõi: SOAR không bao giờ tự cắt mạng máy
nội bộ.*

**6.5 Làm giàu bằng Cortex (n8n gọi API, không cần analyst):** lấy danh sách
analyzer cho IP → chạy `AbuseIPDB_2_0` + `VirusTotal_GetReport_3_1` → chờ report.
Vị trí số liệu: AbuseIPDB `report.full.values[0].data.abuseConfidenceScore`;
VirusTotal `report.full.attributes.last_analysis_stats.malicious`.
- *Root cause job Cortex `Failure`:* `/tmp/cortex-jobs` bind-mount được Docker
  tạo bằng `root:root`, còn tiến trình Java của Cortex chạy UID 1001 →
  `AccessDeniedException`. (`docker exec cortex id` trả 0:0 gây nhầm vì exec mặc
  định là root.) Xử lý: tìm UID Java qua `/proc`, `chown -R 1001:1001` thư mục
  job.
- *Root cause 401:* ban đầu dùng nhầm API key TheHive cho Cortex — hai hệ thống
  quản lý user/key **riêng**.

**6.6 Tổng hợp quyết định (Compilation of decisions):** chính sách **chặn khi
`level ≥ 12` HOẶC AbuseIPDB `≥ 50` HOẶC VirusTotal malicious `> 0`**; luôn bỏ
qua IP nội bộ. Lý do có nhánh `level ≥ 12`: Kali dùng IP dải 192.168.210.x nên
điểm uy tín luôn 0 — nếu chỉ dựa reputation thì không bao giờ chặn được tấn công
trong lab. Ghi kết quả enrich + verdict vào alert TheHive (PATCH, thêm tag
`abuseipdb:x`, `vt-malicious:y`, `soar:block|monitor`).

**6.7 Chặn IP trên pfSense (least privilege):**
- User riêng `soar-n8n` trên pfSense: **không** vào group admins, chỉ có quyền
  shell + **sudo chỉ cho đúng `/usr/local/bin/easyrule`** (NOPASSWD), đăng nhập
  **SSH key-only**. Không dùng admin (menu console chặn tham số) hay root (rủi
  ro).
- Node If `Blocked`: `block == true` **AND** `src_ip` khớp regex IPv4
  `^(\d{1,3}\.){3}\d{1,3}$` — **chống command injection** trước khi ghép IP vào
  lệnh SSH.
- SSH chạy `sudo /usr/local/bin/easyrule block wan <ip>` → gắn tag
  `soar:blocked` trên TheHive.

*Hạn chế đã ghi nhận khi review:* node `Tag blocked` chạy cả khi SSH trả mã lỗi
(node SSH không tự báo lỗi khi `code ≠ 0`) → nên thêm If kiểm tra `code = 0`.

---

## 7. Kịch bản kiểm thử & kết quả (phase 7)

Ba kịch bản phủ 3 hướng mối đe doạ. Điểm mấu chốt: **SOAR phản ứng theo ngữ
cảnh**, không chặn mù.

### 7.1 Tấn công web đi vào — SQL Injection (full auto-response) ✔

1 request SQLi từ Kali `192.168.210.130` vào **IP WAN** `192.168.210.132` (NAT →
DVWA). Chuỗi: Suricata *ET WEB_SERVER SELECT USER SQL Injection Attempt in URI*
(severity 1) → Wazuh **rule 100112 level 12** (phát hiện < 1s) → n8n → TheHive
alert → Cortex (AbuseIPDB 0, VT 0 vì IP private) → **BLOCK** (đạt điều kiện
`level ≥ 12`) → tag `soar:block` + `soar:blocked`. Kết quả chứng minh chính sách
"`level ≥ 12` HOẶC reputation" hoạt động đúng với IP private.

*Root cause khi dựng kịch bản:* phải tấn công vào **IP WAN** (không phải thẳng
172.16.10.10), nếu không Apache thấy src là host 10.10.99.1 → bị whitelist. Cổng
80 từng `filtered` vì IP Kali còn nằm trong alias `EasyRuleBlockHostsWAN` từ test
trước (rule block đứng trên rule pass) → `easyrule unblock` — đồng thời là bằng
chứng cơ chế chặn có tác dụng thật. Dùng 1 request SQLi thay vì nikto (570 alert)
để demo gọn.

### 7.2 Malware trên endpoint — FIM + VirusTotal (detection + active response) ✔

Theo dõi `C:\Users\NgocHuong\Downloads` bằng FIM realtime (`alert_new_files` để
báo cả file mới) + tích hợp **VirusTotal** trên manager (lọc `<group>syscheck`,
tra theo hash, không upload file). Dùng file **EICAR** (chuỗi test chuẩn ngành
AV, an toàn — không phải mã độc thật).

Kết quả: VirusTotal **rule 87105 level 12 – "66 engines detected this file"** cho
`vt_test.txt`, đẩy sang TheHive. Song song, Sysmon sinh **rule 92213 level 15 –
"Executable file dropped in folder commonly used by malware"** (MITRE T1105) —
hai tầng phát hiện độc lập cho cùng một file.

*Root cause khi dựng:* (1) Defender xoá EICAR trước khi FIM kịp hash → tạm loại
trừ thư mục Downloads khỏi Defender để file sống đủ lâu. (2) Viết nguyên chuỗi
EICAR trong lệnh PowerShell bị **AMSI** chặn → tách chuỗi làm 2 biến. (3) FIM
không báo "file mới" ổn định → ép ra sự kiện "file sửa" (rule 550) bằng cách tạo
file thường rồi ghi đè thành EICAR.

**Active response (tùy chọn — đã cấu hình, cần test xác nhận):** Wazuh Active
Response `remove-threat` (script PowerShell + wrapper `.cmd` trên agent, khai báo
`<command>`/`<active-response>` `rules_id 87105`, `location local`) để agent tự
xoá file độc khi VirusTotal báo. Đây là phản ứng phía endpoint, song song với
nhánh chặn IP của tấn công web.

### 7.3 Lưu lượng C2 đi ra — malware beaconing (detection, không auto-block) ✔

Dùng một mẫu lưu lượng C2 malware để kiểm thử phát hiện chiều đi ra. Suricata
bắt *ET MALWARE* → Wazuh **rule 100112 level 12** → TheHive, **nhưng không chặn**.

Đây là hành vi **đúng thiết kế**, không phải thiếu sót: nguồn là máy **nội bộ**
đã nhiễm (10.10.20.100), đích mới là C2 bên ngoài. Workflow chỉ chặn `src_ip`;
IP nguồn nội bộ khớp whitelist → dừng. Chặn IP nguồn ở đây sẽ là tự cắt mạng máy
của mình. Phản ứng đúng cho C2 là **cô lập máy nhiễm** hoặc chặn chiều ra tới C2
— ghi ở phần giới hạn/mở rộng.

**Tổng hợp quyết định của SOAR theo kịch bản:**

| Kịch bản | Nguồn | Phát hiện | Làm giàu | Phản ứng tự động |
|---|---|---|---|---|
| Web attack (SQLi) | IP ngoài | Suricata→Wazuh 100112 | Cortex | **Chặn IP** trên pfSense |
| Endpoint malware (EICAR) | File cục bộ | FIM 554/550 + Sysmon 92213 | VirusTotal 87105 | Tạo case TheHive (+ tùy chọn tự xoá file) |
| Malware C2 | Máy nội bộ → C2 ngoài | Suricata→Wazuh 100112 | (có thể) | Tạo case TheHive (**không** chặn nguồn nội bộ) |

*Lưu ý an toàn khi thử mẫu độc thật:* cô lập VM, chụp ảnh xong revert về snapshot
sạch, không đăng nhập tài khoản thật trên VM đó.

---

## 8. Vận hành, giới hạn & hướng mở rộng

**Thứ tự bật:** Docker Desktop → (nếu thiếu container thì
`docker compose up -d` theo thứ tự Wazuh → TheHive/Cortex → n8n) → pfSense →
DVWA/Win10 → Kali (khi cần). Một số container dùng `unless-stopped` nên sau khi
`stop` tay sẽ không tự lên.

**Tắt an toàn:** tắt VM trước (pfSense cuối), rồi `docker compose stop -t 60`
(ứng dụng trước, database sau) để Elasticsearch/Cassandra ghi xong; **không**
`down -v` (xoá volume = mất dữ liệu, agent key, decoder riêng).

**Giới hạn hiện tại / hướng mở rộng:**
- Endpoint mới dừng ở phát hiện + (tùy chọn) xoá file; chưa có cô lập host.
- Chưa xử lý tự động cho C2 đi ra (cô lập máy nhiễm / chặn đích) — playbook hiện
  tập trung tấn công đi vào.
- `Tag blocked` nên có bước kiểm tra SSH `code = 0` trước khi gắn tag.
- n8n dùng SQLite nội bộ (đủ cho lab).

**Vị trí file & tài khoản:** bảng đầy đủ (API key, mật khẩu, đường dẫn key SSH)
ở doc `00-tai-khoan.md` — **chỉ dùng nội bộ, không đưa lên GitHub**.
