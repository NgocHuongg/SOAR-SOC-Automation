# SOAR Lab – Phần 7: SOAR flow (Wazuh → n8n → TheHive/Cortex → chặn IP trên pfSense)

## Quyết định đã chốt (2026-10-04)

| Câu hỏi | Chọn | Lý do |
|---|---|---|
| Chặn IP trên pfSense | **SSH + `easyrule block WAN <ip>`** | Có sẵn trong pfSense, không cài thêm gói bên thứ ba |
| Alert đẩy sang n8n | **Level ≥ 10** | Bắt mọi nguồn có mức nghiêm trọng cao. Cần nâng level alert Suricata theo severity (bước 4) |
| Analyzer của Cortex | **AbuseIPDB + VirusTotal** | Cần đăng ký 2 API key miễn phí |
| Cách chạy Cortex (chốt 2026-10-08) | **n8n gọi API Cortex tự động** sau khi tạo alert TheHive, chờ kết quả, ghi điểm vào alert | Đúng tinh thần SOAR, không cần analyst bấm tay |
| Chính sách tự chặn IP (chốt 2026-10-08) | Chặn khi **level ≥ 12** HOẶC **AbuseIPDB score ≥ 50** HOẶC **VirusTotal có engine báo malicious**; **luôn bỏ qua** IP thuộc zone nội bộ SOC 10.10.99.0/24, DMZ 172.16.10.0/24, CLIENT 10.10.20.0/24 và gateway NAT 192.168.210.1–2 | Kali dùng IP nội bộ 192.168.210.x nên điểm uy tín luôn = 0; nếu chỉ dựa vào điểm uy tín thì Kali không bao giờ bị chặn |

## Luồng tổng thể

```
pfSense/Suricata/agent ──► Wazuh (alert level ≥ 10)
                              │ integration webhook
                              ▼
                             n8n ──► TheHive: tạo alert + observable IP
                              │            │
                              │            ▼
                              │         Cortex: AbuseIPDB, VirusTotal
                              ▼
                     SSH pfSense: easyrule block WAN <ip>
```

## Checklist

- [x] 1. TheHive (2026-10-08): org `SOAR-Lab`; user `huong@soar.internal` (Normal, org-admin); user `n8n@soar.internal` (Service, analyst) + API key. Cả 2 user chỉ thuộc SOAR-Lab, đã xoá dòng org `admin` trong form. TheHive 5.8 tạo user ở Administration → Users, chọn profile cho từng org ngay trong form
- [x] 2. Cortex
  - [x] 2a. Org `SOAR-Lab`; user `huong@soar.internal` (read, analyze, orgadmin); user `thehive@soar.internal` (read, analyze) + API key (2026-10-08)
  - [x] 2b. Đăng ký API key AbuseIPDB và VirusTotal (2026-10-08, lưu ở doc 00)
  - [x] 2c. Bật analyzer AbuseIPDB_2_0 và VirusTotal_GetReport_3_1 (đăng nhập huong@soar.internal → Organization → Analyzers → Enable, điền key)
    - **Lỗi:** job chạy thử đều `Failure`, lỗi chỉ hiện `/tmp/cortex-jobs/cortex-job-...`. Log `docker logs cortex` → `java.nio.file.AccessDeniedException: /tmp/cortex-jobs/cortex-job-...`
    - Root cause: `/tmp/cortex-jobs` là bind mount từ `/home/ngochuong/soar-lab/thehive-cortex/testing/cortex/cortex-jobs`. Docker tự tạo thư mục này với chủ **root:root** (755), còn tiến trình Java của Cortex chạy bằng UID **1001** (entrypoint khởi động bằng root rồi hạ quyền), nên không tạo được thư mục job. `docker exec cortex id` trả 0:0 là sai lệch: `docker exec` mặc định chạy bằng root, không phản ánh user của tiến trình Java
    - Cách xử lý (Ubuntu WSL):
      ```bash
      SRC=/home/ngochuong/soar-lab/thehive-cortex/testing/cortex/cortex-jobs
      JUID=$(docker exec cortex sh -c 'for p in /proc/[0-9]*; do [ "$(cat $p/comm 2>/dev/null)" = "java" ] && stat -c %u:%g $p && break; done')
      docker run --rm -v "$SRC":/x alpine chown -R "$JUID" /x
      docker exec cortex ls -ldn /tmp/cortex-jobs   # → 1001 1001
      ```
    - Sau khi sửa: New Analysis ip `217.160.0.187` với 2 analyzer → cả 2 job **Success**
- [x] 3. Nối TheHive ↔ Cortex (2026-10-08): đăng nhập admin@thehive.local → Platform Management → Connectors → Cortex → nút **+** cạnh Servers. Server `Cortex-Local`, URL `http://cortex:9001/cortex` (tên container, vì TheHive gọi Cortex trong mạng Docker), API key của `thehive@soar.internal`
- [x] 4. Nâng level alert Suricata theo severity (2026-10-08). Thêm vào `config\custom\suricata_rules.xml` rồi `docker cp` + chown/chmod + restart:
  - `100112` level 12: `<if_sid>100111</if_sid>` + `<field name="alert.severity">^1$</field>`
  - `100113` level 10: `<if_sid>100111</if_sid>` + `<field name="alert.severity">^2$</field>`
  - Severity 3 giữ `100111` level 3, không đẩy sang n8n
  - Logtest dòng SID 2100498 (severity 2) → `100113` level 10, "Suricata: Medium severity alert - GPL ATTACK_RESPONSE id check returned root" ✔
- [x] 5. Wazuh → n8n: integration webhook cho alert level ≥ 10 (chi tiết ở cuối file)
  - [x] 5a. n8n workflow `SOAR - Wazuh alert intake`: node Webhook POST, path `wazuh-alert`, Respond Immediately, đã Publish/Active (2026-10-08). Test từ host (`Invoke-RestMethod` → `Workflow was started`) ✔, test từ trong container Wazuh (`curl http://host.docker.internal:5678/webhook/wazuh-alert`) ✔
    - Lưu ý: node Webhook lúc đầu bị **disabled** ("This node is disabled") → bấm nút nguồn trên node để bật lại
    - Test URL `/webhook-test/` chỉ nghe 1 request sau khi bấm "Listen for test event"; Wazuh phải dùng Production URL `/webhook/` (workflow phải Active)
  - [x] 5b. Script integration `custom-n8n` + block `<integration>` (2026-10-08). Kết quả: Win10 `curl.exe -s http://testmyids.com` → alert 100113 → n8n Execution `executionMode: production`, body có `decoder.name: suricata-bsd`, `data.alert.signature_id: 2100498`, `location: 172.22.0.1` ✔

- [x] 6. n8n workflow 1: nhận alert → tạo alert TheHive kèm observable IP nguồn (2026-10-08, chi tiết ở cuối file)
  - Workflow `SOAR - Wazuh alert intake`: `Webhook` → `Parsing Alert` (Code, JS) → `Tao alert TheHive` (HTTP Request)
  - Chạy thử với dữ liệu ghim: TheHive trả `_id ~12464`, `_createdBy n8n@soar.internal`, `severityLabel MEDIUM`, `observableCount 1` ✔
  - Test thật sau khi Publish: Win10 `curl.exe -s http://testmyids.com` → alert mới trong TheHive (org SOAR-Lab), sourceRef `1791462299.695795`, lúc 19:25 ✔. TheHive hiện 2 alert
- [x] 7. Cortex phân tích observable IP (n8n gọi API Cortex), xong 2026-10-08
  - [x] 7a. Cortex: user `n8n@soar.internal` (read, analyze) + API key (doc 00); test `docker exec n8n wget -qO- --header "Authorization: Bearer <API key n8n@soar.internal>" http://host.docker.internal:9001/cortex/api/analyzer/type/ip` → 2 analyzer (2026-10-08) ✔
    - `AbuseIPDB_2_0` id `8638bd735613f64fce26775e1a9e1199`, image `ghcr.io/thehive-project/abuseipdb:2`
    - `VirusTotal_GetReport_3_1` id `fedb201f989c884cde6a23acc44b3018`, image `ghcr.io/thehive-project/virustotal_getreport:3`
    - Lỗi đã gặp: dùng nhầm API key của TheHive → Cortex trả `401 Unauthorized`. TheHive và Cortex quản lý user/key riêng
  - [x] 7b. n8n: bỏ qua IP nội bộ (2026-10-08). Tên node thật trong workflow: `Create Alert TheHive` → `WhiteList Check` (Code) → `IP ngoai?` (If, `{{ $json.is_internal }}` Boolean **is false**) → nhánh true đi tiếp, nhánh false dừng. Test IP 217.160.0.187 → `is_internal: false` → True Branch ✔
    - Code `WhiteList Check` lấy IP/level từ `$('Parsing Alert').item.json`, regex nội bộ: `^10\.10\.99\.`, `^172\.16\.10\.`, `^10\.10\.20\.`, `^192\.168\.210\.(1|2|132)$`, `^127\.`
    - Lỗi đã gặp 1: chạy thử node sau → n8n chạy lại node tạo alert → TheHive `Alert wazuh-alert:Wazuh:<id> already exists` (chống trùng nhờ sourceRef). Xử lý: đổi `body.id` trong dữ liệu mẫu (`...test0002`), chạy node tạo alert 1 lần rồi **Pin data** node đó
    - Lỗi đã gặp 2: If báo `Wrong type: ' false' is a string but was expecting a boolean` do ô value1 có dấu cách trước `{{` → n8n ghép thành chuỗi. Xử lý: xoá trắng ô, gõ đúng `{{ $json.is_internal }}`
  - [x] 7c. n8n: lấy danh sách analyzer cho IP → chạy job → chờ report (2026-10-08). Credential riêng `Cortex - n8n key` (Header Auth `Authorization: Bearer <API key n8n@soar.internal>`)
    - `Lay analyzer IP`: GET `http://host.docker.internal:9001/cortex/api/analyzer/type/ip` → 2 item
    - `Chay analyzer`: POST `.../cortex/api/analyzer/{{ $json.id }}/run`, JSON `{{ JSON.stringify({ data: $('WhiteList Check').item.json.src_ip, dataType: 'ip', tlp: 2, pap: 2, message: 'n8n SOAR - TheHive ' + $('WhiteList Check').item.json.thehive_alert_id }) }}` → 2 job `Waiting`, createdBy `n8n@soar.internal`
    - `Cho ket qua`: GET `.../cortex/api/job/{{ $json.id }}/waitreport?atMost=1minute` → 2 job `Success` ✔
    - Kết quả thật IP 217.160.0.187: AbuseIPDB `abuseConfidenceScore` **12**, totalReports 2 (DE, IONOS SE, CDN); VirusTotal `last_analysis_stats.malicious` **0**/92
    - Vị trí dữ liệu: AbuseIPDB `report.full.values[0].data.abuseConfidenceScore`; VirusTotal `report.full.attributes.last_analysis_stats.malicious`
    - Lưu ý: taxonomy của VT gắn level `malicious` cho "200 resolution(s)" (số domain trỏ về IP), **không** có nghĩa IP độc hại → quyết định dựa trên số liệu gốc, không dựa vào level taxonomy
  - [x] 7d. n8n: tổng hợp điểm + quyết định chặn → cập nhật alert TheHive (2026-10-08)
    - `Tong hop quyet dinh` (Code, **Run Once for All Items**): đọc AbuseIPDB score, VT malicious, áp chính sách (level ≥ 12 / score ≥ 50 / VT malicious > 0) → `block`, `verdict` BLOCK/MONITOR, `reasons`, `thehive_update` (description + tags). Analyzer lỗi ghi vào danh sách `failed`, không làm dừng workflow
    - `Cap nhat alert TheHive`: PATCH `http://host.docker.internal:9000/thehive/api/v1/alert/{{ $json.thehive_alert_id }}`, credential `TheHive - n8n key`, JSON `{{ JSON.stringify($json.thehive_update) }}` → TheHive trả 204, n8n hiện `[{}]` (bình thường)
    - Kết quả alert ~12448: tags thêm `abuseipdb:12`, `vt-malicious:0`, `soar:monitor`; description thêm mục "Kết quả phân tích tự động (Cortex)" và "Quyết định SOAR: MONITOR - chưa đủ điều kiện chặn tự động" ✔
- [x] 8. Chặn IP trên pfSense bằng `easyrule` qua SSH (least privilege), xong 2026-10-08
  - [x] 8a. (2026-10-08) SSH key ed25519 `F:\SOAR_Project\keys\n8n_pfsense` (đã bỏ passphrase bằng `ssh-keygen -p`); pfSense: cài package `sudo`; user `soar-n8n` (**không** vào group admins, privilege **User - System: Shell account access**, Authorized SSH Keys = public key); System → Sudo thêm dòng `soar-n8n` / Run As root / No Password ✅ / Command `/usr/local/bin/easyrule` (giữ 3 dòng mặc định root, admin, admins); System → Advanced → Admin Access: Enable Secure Shell, SSHd Key Only = Public Key Only
  - [x] 8b. Test thủ công từ host (2026-10-08), lệnh `ssh -i F:\SOAR_Project\keys\n8n_pfsense soar-n8n@10.10.99.254 "<lệnh>"`:
    - `whoami; sudo -l` → `soar-n8n`, `(root) NOPASSWD: /usr/local/bin/easyrule` ✔ (lần đầu gõ `yes` để lưu fingerprint ED25519 `SHA256:unNUW+aUd1SwqEe1NzI7t11WroQShzYubH2wV5ILnmA`)
    - `sudo /bin/ls /root` → `sudo: a password is required` (lệnh ngoài danh sách NOPASSWD bị chặn; với `ssh -t` + mật khẩu user sẽ ra "not allowed") ✔
    - `sudo /usr/local/bin/easyrule block wan 203.0.113.50` → `Block added successfully` ✔ (203.0.113.0/24 = TEST-NET-3, IP dành cho thử nghiệm)
    - `sudo /usr/local/bin/easyrule unblock wan 203.0.113.50` → `Entry unblocked successfully` ✔
    - Container n8n: `docker exec n8n sh -c "nc -zv -w 3 10.10.99.254 22"` → `open` ✔
  - [x] 8c. n8n: IF `block` → SSH `sudo /usr/local/bin/easyrule block wan <ip>` → cập nhật tag TheHive `soar:blocked` (node `Gan tag blocked`: PATCH alert với tags cũ `.concat(['soar:blocked'])`); đã gỡ chặn IP thử nghiệm và Publish workflow
    - Tên node tổng hợp thật trong workflow: **`Compilation of decisions`**; node PATCH TheHive: `Alert TheHive`
    - IF `Blocked`: `{{ $('Compilation of decisions').item.json.block }}` Boolean **is true** AND `{{ $('Compilation of decisions').item.json.src_ip }}` String **matches regex** `^(\d{1,3}\.){3}\d{1,3}$` (chống command injection: chỉ IPv4 hợp lệ mới được ghép vào lệnh SSH). Dữ liệu mẫu level 10 → False Branch ✔
    - SSH `Chan IP pfSense`: credential **SSH Private Key** `pfSense - soar-n8n SSH` (Host 10.10.99.254, user soar-n8n, passphrase trống; lưu ý mặc định n8n tạo kiểu SSH Password → phải đổi sang Private Key), Command `sudo /usr/local/bin/easyrule block wan {{ $('Compilation of decisions').item.json.src_ip }}`
    - Test: sửa dữ liệu ghim Webhook `level 12`, `src_ip 203.0.113.50` → SSH output `code 0`, `stdout: Block added successfully` ✔ (2026-10-08 22:51)
  - Lý do không dùng `admin`/`root`: admin bị menu console chặn lệnh có tham số; root qua SSH tự động là rủi ro. Thiết kế theo khuyến nghị trên Netgate forum: user riêng + sudo chỉ cho phép easyrule + SSH key
- [x] 9. Kiểm chứng và sao lưu + test end-to-end THẬT (2026-10-09)
  - [x] 9a. **End-to-end tấn công thật từ Kali (2026-10-09 00:46):** 1 request SQLi từ Kali `192.168.210.130` vào IP WAN `192.168.210.132` (NAT → DVWA). Chuỗi: Suricata *ET WEB_SERVER SELECT USER SQL Injection Attempt in URI* (High/severity 1) → Wazuh **rule 100112 level 12** (Detection < 1s) → n8n → TheHive alert `~720928` → Cortex (AbuseIPDB 0, VT 0 vì IP private) → **BLOCK** (level 12 ≥ 12) → tag `soar:block` + `soar:blocked`. Minh chứng policy "level ≥ 12 HOẶC reputation" hoạt động đúng với IP private
  - [ ] 9c. Chụp ảnh trước/sau: Kali bị chặn sau phản ứng (nmap/curl → timeout)
  - [x] 9b. Export workflow (2026-10-08): `F:\SOAR_Project\n8n\soar-workflow.json`, bản sao trong project `soar-lab/n8n/soar-wazuh-alert-intake.json`. Đã quét: file chỉ chứa tham chiếu credential (id + tên), không có API key/private key
    - Tên node cuối cùng: `Webhook` → `Parsing Alert` → `Create Alert TheHive` → `WhiteList Check` → `If` → `Collect analyzer IP` → `Run analyzer` → `Wait for output` → `Compilation of decisions` → `Alert TheHive` → `Blocked` → `Block IP pfSense` → `Tag blocked`
    - Nhận xét khi review file: node `Tag blocked` chạy cả khi lệnh SSH trả mã lỗi (node SSH không tự báo lỗi khi `code ≠ 0`) → nên thêm IF kiểm tra `code = 0` trước khi gắn `soar:blocked`; dữ liệu ghim của Webhook vẫn là bản test (level 12, IP 203.0.113.50), không ảnh hưởng production

---

### Chi tiết bước 5b

`config\custom\custom-n8n.py` (chép vào `/var/ossec/integrations/`, thư mục này là named volume nên không mất):
```python
#!/usr/bin/env python3
# Wazuh integration: forward the full alert JSON to an n8n webhook
import json
import sys

import requests

alert_file = sys.argv[1]   # Wazuh passes the alert file path
hook_url = sys.argv[3]     # value of <hook_url> in ossec.conf

with open(alert_file) as f:
    alert = json.load(f)

r = requests.post(hook_url, json=alert, timeout=10)
if r.status_code >= 400:
    print(f"n8n webhook error {r.status_code}: {r.text}", file=sys.stderr)
    sys.exit(1)
```

Cài đặt:
```powershell
docker cp config\custom\custom-n8n.py single-node-wazuh.manager-1:/var/ossec/integrations/custom-n8n.py
docker exec single-node-wazuh.manager-1 cp /var/ossec/integrations/shuffle /var/ossec/integrations/custom-n8n
docker exec single-node-wazuh.manager-1 chown root:wazuh /var/ossec/integrations/custom-n8n /var/ossec/integrations/custom-n8n.py
docker exec single-node-wazuh.manager-1 chmod 750 /var/ossec/integrations/custom-n8n /var/ossec/integrations/custom-n8n.py
```
- `custom-n8n` là bản sao file khởi chạy của integration `shuffle`: một shell script chung, chỉ gọi `framework/python/bin/python3 <tên-file>.py`. Tên integration tự viết bắt buộc bắt đầu bằng `custom-`.

Block thêm vào `wazuh_manager.conf` (dưới block `<remote>` syslog), rồi `cp` + restart như mọi lần sửa config:
```xml
  <integration>
    <name>custom-n8n</name>
    <hook_url>http://host.docker.internal:5678/webhook/wazuh-alert</hook_url>
    <level>10</level>
    <alert_format>json</alert_format>
  </integration>
```
- `host.docker.internal`: tên do Docker Desktop cung cấp để container gọi ra cổng đã publish trên host. n8n nằm ở stack compose khác, không chung mạng Docker với Wazuh.
- `<level>10</level>`: chỉ gửi alert level ≥ 10 (100102 pfSense, 100112/100113 Suricata, alert agent mức cao).
- Xem dữ liệu nhận được: n8n → workflow → tab **Executions** (không phải nút "Listen for test event").

### Chi tiết bước 6

Kiểm tra n8n gọi được TheHive: `docker exec n8n wget -qO- http://host.docker.internal:9000/thehive/api/status` → JSON có `"TheHive":"5.8.0-1"`, `authType` có `key`.

**Dữ liệu mẫu:** Executions → copy JSON output của Webhook (alert 100113 thật) → Editor → node Webhook → **set mock data** → dán → Save (dữ liệu được ghim 📌). Lỗi đã gặp: `JSON.parse: unexpected non-whitespace character after JSON data` do ô soạn thảo còn sót nội dung cũ → Ctrl+A, Delete cho trống rồi dán lại. Dữ liệu ghim chỉ dùng khi chạy thử trong editor, không ảnh hưởng production.

**Node `Parsing Alert`** (Code, Run Once for Each Item, JavaScript):
```javascript
const a = $json.body;
const d = a.data || {};
const srcIp = d.src_ip || d.srcip || null;
const dstIp = d.dest_ip || d.dstip || null;
const level = Number(a.rule.level);
const severity = level >= 15 ? 4 : (level >= 12 ? 3 : 2);
const mitre = (a.rule.mitre && a.rule.mitre.id) ? a.rule.mitre.id.join(', ') : '-';
const signature = (d.alert && d.alert.signature) ? d.alert.signature : '-';

const description = [
  `**Wazuh rule:** ${a.rule.id} (level ${level})`,
  `**Mô tả:** ${a.rule.description}`,
  `**Agent:** ${a.agent.name} (${a.agent.id})`,
  `**Thời gian:** ${a.timestamp}`,
  `**IP nguồn:** ${srcIp || '-'}`,
  `**IP đích:** ${dstIp || '-'}`,
  `**Suricata signature:** ${signature}`,
  `**MITRE ATT&CK:** ${mitre}`,
].join('\n\n');

const observables = [];
if (srcIp) observables.push({ dataType: 'ip', data: srcIp, tags: ['src_ip'] });

return {
  json: {
    src_ip: srcIp,
    rule_id: a.rule.id,
    level,
    thehive_alert: {
      type: 'wazuh-alert',
      source: 'Wazuh',
      sourceRef: String(a.id),
      title: `[Wazuh ${a.rule.id}] ${a.rule.description}`,
      description,
      severity,
      tags: ['wazuh', `rule:${a.rule.id}`, `agent:${a.agent.name}`],
      observables,
    },
  },
};
```
- IP nguồn: Suricata dùng `data.src_ip`, pfSense dùng `data.srcip` → lấy cả hai.
- Severity TheHive: level 10–11 → 2 (Medium), 12–14 → 3 (High), ≥ 15 → 4 (Critical).
- `sourceRef` = id alert Wazuh → TheHive từ chối tạo trùng.

**Node `Tao alert TheHive`** (HTTP Request):
| Mục | Giá trị |
|---|---|
| Method | POST |
| URL | `http://host.docker.internal:9000/thehive/api/v1/alert` |
| Authentication | Generic Credential Type → Header Auth → nút **Connect to Header Auth** → credential `TheHive - n8n key`: Name `Authorization`, Value `Bearer <API key n8n@soar.internal>` |
| Send Body | Bật, Body Content Type JSON, Specify Body Using JSON |
| JSON | `{{ JSON.stringify($json.thehive_alert) }}` |

Sửa workflow xong phải **Save + Publish** lại thì production URL mới dùng bản mới.

---

### Lỗi đã gặp khi dựng kịch bản tấn công từ Kali (2026-10-09)

- **Kali phải tấn công vào IP WAN pfSense, không phải IP nội bộ DVWA.** Gõ thẳng `172.16.10.10` thì gói đi vòng, Apache thấy src `10.10.99.1` (host) → bị whitelist. Phải tấn công `http://192.168.210.132/dvwa/...` (IP WAN) để giữ IP Kali thật `192.168.210.130`.
- **WAN IP pfSense là DHCP, có thể đổi sau khi khởi động lại.** Kiểm tra ở Dashboard → Interfaces → WAN. Kali 192.168.210.130, pfSense WAN 192.168.210.132 (lần này không đổi).
- **Cổng 80 WAN `filtered` dù NAT port forward còn.** Nguyên nhân: IP Kali `192.168.210.130` nằm trong alias `EasyRuleBlockHostsWAN` (bị SOAR chặn từ test trước), rule block này đứng TRÊN rule pass DVWA nên drop gói trước. Gỡ: `ssh ... soar-n8n@10.10.99.254 "sudo /usr/local/bin/easyrule unblock wan 192.168.210.130"`. → đây cũng là bằng chứng cơ chế chặn hoạt động.
- **curl không đăng nhập DVWA trả rỗng** (bị redirect login), nhưng Suricata vẫn bắt vì nó match pattern trong URI, không cần DVWA xử lý thành công.
- **Payload demo ít noise:** 1 request SQLi `?id=1' UNION SELECT ...` đủ sinh alert severity 1 → BLOCK, gọn hơn nhiều so với nikto (570 alert).