# SOAR Lab – Phần 3: Mạng VMware + pfSense

## Chọn phiên bản pfSense
- Dùng: **pfSense CE 2.7.2 amd64** (full ISO, cài offline được). Cài xong **nâng cấp lên bản 2.8.x hiện hành** (System → Update) **trước khi cài Suricata**. Nâng từ 2.7.2 lên 2.8.x là đường nâng cấp chính thức. 
## Bảng mạng

| VMnet | Kiểu | Subnet | Zone | DHCP VMware | Host adapter |
|---|---|---|---|---|---|
| VMnet8 | NAT (có sẵn) | 192.168.210.0/24 | WAN | Giữ nguyên | Giữ nguyên (host 192.168.210.1) |
| VMnet2 | Host-only | 172.16.10.0/24 | DMZ | **Tắt** | **Bỏ tick** |
| VMnet3 | Host-only | 10.10.20.0/24 | LAN (client) | **Tắt** | **Bỏ tick** |
| VMnet4 | Host-only | 10.10.99.0/24 | SOC/MGMT | **Tắt** | **Giữ tick** → host = 10.10.99.1 |

## Bảng gán interface trong pfSense

| Card VMware | pfSense NIC | Interface pfSense | Đổi tên thành | IP | DHCP |
|---|---|---|---|---|---|
| Adapter 1 – NAT | em0 | WAN | WAN | DHCP (192.168.210.x) | – |
| Adapter 4 – VMnet4 | em3 | **LAN** | **SOC** | 10.10.99.254/24 | Tắt |
| Adapter 2 – VMnet2 | em1 | OPT1 | **DMZ** | 172.16.10.1/24 | Tắt (IP tĩnh) |
| Adapter 3 – VMnet3 | em2 | OPT2 | **CLIENT** | 10.10.20.1/24 | Bật .100–.200 |

Vì sao gán interface "LAN" của pfSense vào em3 (SOC): pfSense chỉ cho vào Web GUI từ interface LAN (có rule anti-lockout). Host Windows nằm ở zone SOC, nên gán SOC làm LAN thì host vào GUI được ngay. Thực tế doanh nghiệp cũng quản trị firewall từ mạng quản trị riêng. Zone client đổi tên thành `CLIENT` vì tên "LAN" đã dành cho interface này.

## Checklist

- [x] 1. Tạo VMnet2/3/4 trong Virtual Network Editor (2026-10-02). VMnet2/3 kiểu Custom, không gắn host, không DHCP. VMnet4 Host-only, có gắn host, không DHCP. VMnet0/1/8 giữ nguyên
  - Lỗi đã gặp: lần đầu VMnet4 bị bỏ tick host adapter, phải tick lại
- [x] 2. Tạo VM pfSense có 4 card mạng (Adapter1 NAT, Adapter2 VMnet2, Adapter3 VMnet3, Adapter4 VMnet4)
- [x] 3. Cài pfSense 2.7.2 từ ISO (ZFS stripe trên da0). Sau khi cài, pfSense tự gán WAN=em0 (DHCP 192.168.210.132) và LAN=em1 → phải gán lại
  - Lỗi đã gặp: `stripe: Not enough disks selected` do chưa nhấn Space để chọn da0
- [x] 4. Gán interface, đặt IP từng zone (2026-10-02): WAN em0 DHCP 192.168.210.132, LAN(SOC) em3 10.10.99.254/24, OPT1(DMZ) em1 172.16.10.1/24, OPT2(CLIENT) em2 10.10.20.1/24 + DHCP .100–.200. Đã gán WAN=em0, LAN(SOC)=em3, OPT1(DMZ)=em1, OPT2(CLIENT)=em2. LAN đã có IP 10.10.99.254/24
  - Lỗi đã gặp: ping 10.10.99.254 từ host báo `Reply from 10.100.0.254: Destination net unreachable`. Root cause: card VMnet4 trên Windows để chế độ DHCP và xin được IP 192.168.1.100 từ DHCP mặc định của pfSense LAN (192.168.1.1) ngay sau khi gán LAN=em3. Đổi LAN sang 10.10.99.254 xong thì host vẫn giữ IP cũ, không có route tới 10.10.99.0/24 nên đẩy ra default gateway. Cách sửa (PowerShell Admin): `Set-NetIPInterface -InterfaceAlias "VMware Network Adapter VMnet4" -Dhcp Disabled` rồi `New-NetIPAddress -InterfaceAlias "VMware Network Adapter VMnet4" -IPAddress 10.10.99.1 -PrefixLength 24`. Lỗi `Remove-NetIPAddress ... No matching` là vô hại, vì tắt DHCP đã xoá IP cũ
  - Lỗi đã gặp: LAN mất IP sau khi cấu hình OPT1/OPT2, console báo GUI ở https://10.10.20.1. Nguyên nhân khả năng cao: chọn nhầm interface LAN rồi nhấn Enter ở câu hỏi nhập IP (bỏ trống = xoá IP). Cách sửa: menu 2 → 2 (LAN) → nhập lại 10.10.99.254/24
- [x] 5. Truy cập Web GUI https://10.10.99.254 từ host, chạy setup wizard xong (2026-10-02): hostname pfSense, domain soar.internal, DNS 1.1.1.1/8.8.8.8, TZ Asia/Ho_Chi_Minh, WAN bỏ chặn RFC1918 + bogon, đã đổi mật khẩu admin
- [x] 6. Đổi tên interface (LAN→SOC, OPT1→DMZ, OPT2→CLIENT). Nâng cấp 2.7.2 → **2.8.1-RELEASE** (FreeBSD 15.0) xong ngày 2026-10-03 qua System → Update, branch Latest stable
  - Sau khi nâng cấp, Dashboard báo có **2.9.0**. Chọn **ở lại 2.8.1**. Điều kiện: vào System → Package Manager → Available Packages, nếu vẫn thấy `suricata` thì dùng 2.8.1. Nếu không thấy package thì mới nâng lên 2.9.0
  - Đã kiểm tra: Package Manager trên 2.8.1 vẫn có `suricata` 7.0.9, nên **giữ 2.8.1**
  - Timezone đặt lại `Asia/Ho_Chi_Minh` trong System → General Setup, vì sau khi nâng cấp Dashboard hiện giờ UTC (2026-10-03)
- [x] 7. DHCP cho CLIENT (.100–.200) đã bật từ console, DNS Resolver bật mặc định, NTP mặc định
- [x] 8. Thêm route trên Windows host (`route -p add 172.16.10.0/24` và `10.10.20.0/24` qua 10.10.99.254). Mở Windows Firewall: rule `SOAR - Wazuh agent (1514-1515/TCP)` cho 3 zone lab, rule `SOAR - Wazuh syslog (514/UDP)` chỉ từ 10.10.99.254 (2026-10-03)
- [x] 9. Firewall rule giữa các zone + port forward WAN:80 → DVWA (2026-10-03): 5 alias, 5 rule DMZ, 6 rule CLIENT, NAT port forward `WAN:80 → DVWA` kèm filter rule tự sinh trên WAN
  - Đã sửa: rule 2–3 DMZ đổi Destination `DMZ subnets` → `DMZ address`. Rule 5 CLIENT đổi mô tả thành `Block CLIENT to internal`, vì mô tả này hiện trong firewall log
  - Lưu ý: rule trên tab DMZ chỉ kiểm soát kết nối **do DVWA khởi tạo**. Chiều Internet → DVWA nằm ở tab WAN (port forward). Gói trả về được cho qua tự động vì pfSense stateful
  - DMZ không có rule cho ICMP, nên DVWA ping gateway 172.16.10.1 sẽ **bị chặn** (rule Block RFC1918). Đây là hành vi đúng
- [x] 10. Chuyển DVWA sang DMZ và kiểm tra (2026-10-03). Kết quả:
  - DVWA → Internet qua 443: `curl -sI https://ubuntu.com` → `HTTP/2 200` ✔ (DNS qua pfSense và rule WEB_PORTS chạy đúng)
  - DVWA → Wazuh 10.10.99.1:1514: `nc` succeeded ✔
  - DVWA → ping 10.10.99.1: 100% loss ✔ (bị rule `Block DMZ to internal` chặn và ghi log)
  - Host (SOC) → ping 172.16.10.10: reply, TTL=63 ✔ (đi qua pfSense 1 hop, route host chạy đúng)
  - Kali (WAN) → `curl -I http://192.168.210.132/dvwa/login.php` → `HTTP/1.1 200 OK` ✔ (port forward chạy đúng)
  - Lưu ý: DVWA mặc định security level `impossible`. Khi tập tấn công phải vào DVWA Security để chỉnh xuống Low/Medium

---

### 1. Tạo VMnet trong Virtual Network Editor

VMware Workstation → **Edit → Virtual Network Editor** → bấm **Change Settings** (cần quyền admin).

Lặp lại 3 lần, mỗi lần **Add Network…** rồi chọn số VMnet:

**VMnet2 (DMZ)**
- Chọn **Host-only**
- **Bỏ tick** "Connect a host virtual adapter to this network"
- **Bỏ tick** "Use local DHCP service to distribute IP address to VMs"
- Subnet IP: `172.16.10.0`, Subnet mask: `255.255.255.0`

**VMnet3 (LAN client)**
- **Host-only**, **bỏ tick** host adapter, **bỏ tick** DHCP
- Subnet IP: `10.10.20.0`, mask `255.255.255.0`

**VMnet4 (SOC/MGMT)**
- **Host-only**, **giữ tick** host adapter, **bỏ tick** DHCP
- Subnet IP: `10.10.99.0`, mask `255.255.255.0`

Bấm **Apply → OK**. Không sửa VMnet8.

Kiểm tra trên PowerShell:
```powershell
ipconfig | findstr /C:"VMnet" /C:"IPv4"
```
Phải có **VMware Network Adapter VMnet4** với IPv4 `10.10.99.1`. **Không được** có card VMnet2 và VMnet3.

Vì sao bỏ host adapter ở DMZ và LAN: nếu host cắm vào 2 zone này thì nó thành cửa sau đi vòng qua firewall, sai với mô hình thực tế.

### 2. Tạo VM pfSense

1. File → New Virtual Machine → **Typical**.
2. Chọn **I will install the operating system later**.
3. Guest OS: **Other** → **FreeBSD 14 64-bit**. Không có bản 14 thì chọn FreeBSD 13 64-bit hoặc FreeBSD 64-bit.
4. Tên VM: `pfSense`, lưu ở `F:\VMs\pfSense`.
5. Disk **20GB**, chọn single file.
6. **Customize Hardware:**
   - Memory **2048MB** (Suricata cần RAM), Processors **2**
   - CD/DVD → ISO `pfSense-CE-2.7.2-RELEASE-amd64.iso`
   - **Network Adapter** (card có sẵn) → **NAT** → sẽ thành `em0` = WAN
   - **Add… → Network Adapter** → **Custom: VMnet2** → `em1` = DMZ
   - **Add… → Network Adapter** → **Custom: VMnet3** → `em2` = LAN client
   - **Add… → Network Adapter** → **Custom: VMnet4** → `em3` = SOC
   - Xoá Sound Card, Printer, USB Controller
7. Finish. **Chưa bật VM**, chờ bước 3.

Thứ tự thêm card phải đúng như trên thì tên `em0 → em3` mới khớp với zone.


---

### 7. Kiểm tra DHCP / DNS / NTP (chỉ cần xác nhận)

- **Services → DHCP Server → CLIENT**: Enable đã tick, range `10.10.20.100–10.10.20.200`. Ô DNS servers để trống (pfSense tự cấp DNS là chính nó, 10.10.20.1).
- **Services → DNS Resolver**: Enable đã tick (mặc định).
- **Services → NTP**: để mặc định (lắng nghe trên mọi interface). Các máy trong lab sync giờ về IP của pfSense trong zone của mình.

### 9. Firewall rule giữa các zone

Nguyên tắc: pfSense lọc traffic **khi đi vào interface**, xét rule từ trên xuống, gặp rule khớp đầu tiên thì dừng. Interface mới (DMZ, CLIENT) mặc định **chặn hết**.

**9a. Tạo Alias (Firewall → Aliases)**

| Tab | Name | Type | Giá trị |
|---|---|---|---|
| IP | `SOC_SERVER` | Host(s) | `10.10.99.1` |
| IP | `DVWA` | Host(s) | `172.16.10.10` |
| IP | `RFC1918` | Network(s) | `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16` |
| Ports | `WAZUH_PORTS` | Port(s) | `1514`, `1515` |
| Ports | `WEB_PORTS` | Port(s) | `80`, `443` |

**9b. Rule cho DMZ (Firewall → Rules → DMZ)**, theo đúng thứ tự từ trên xuống:

| # | Action | Protocol | Source | Destination | Dest. port | Log | Description |
|---|---|---|---|---|---|---|---|
| 1 | Pass | TCP | DMZ subnets | `SOC_SERVER` | `WAZUH_PORTS` | | DMZ → Wazuh agent |
| 2 | Pass | TCP/UDP | DMZ subnets | DMZ address | 53 (DNS) | | DMZ → DNS pfSense |
| 3 | Pass | UDP | DMZ subnets | DMZ address | 123 (NTP) | | DMZ → NTP pfSense |
| 4 | Block | any | DMZ subnets | `RFC1918` | any | ✔ | Chặn DMZ vào nội bộ |
| 5 | Pass | TCP | DMZ subnets | any | `WEB_PORTS` | | DMZ ra Internet (update) |

**9c. Rule cho CLIENT (Firewall → Rules → CLIENT)**

| # | Action | Protocol | Source | Destination | Dest. port | Log | Description |
|---|---|---|---|---|---|---|---|
| 1 | Pass | TCP | CLIENT subnets | `SOC_SERVER` | `WAZUH_PORTS` | | CLIENT → Wazuh agent |
| 2 | Pass | TCP/UDP | CLIENT subnets | CLIENT address | 53 (DNS) | | CLIENT → DNS pfSense |
| 3 | Pass | UDP | CLIENT subnets | CLIENT address | 123 (NTP) | | CLIENT → NTP pfSense |
| 4 | Pass | TCP | CLIENT subnets | `DVWA` | `WEB_PORTS` | | CLIENT → web nội bộ |
| 5 | Block | any | CLIENT subnets | `RFC1918` | any | ✔ | Chặn CLIENT vào vùng khác |
| 6 | Pass | any | CLIENT subnets | any | any | | CLIENT ra Internet |

**SOC**: giữ nguyên 2 rule mặc định (Anti-Lockout và Default allow LAN to any). Zone quản trị được đi mọi nơi.

**9d. Port forward (Firewall → NAT → Port Forward → Add)**
- Interface `WAN`, Protocol `TCP`, Destination `WAN address`, Destination port `HTTP`
- Redirect target IP: `DVWA` (alias), Redirect target port `HTTP`
- Description `WAN:80 → DVWA`, Filter rule association: `Add associated filter rule`
- Save → Apply Changes

Ý nghĩa: Kali (giả lập Internet) chỉ thấy IP WAN của pfSense. Mọi tấn công web đi qua NAT và firewall, Suricata trên DMZ thấy IP thật của DVWA. Nếu DVWA bị chiếm, rule 4 của DMZ chặn nó pivot vào CLIENT/SOC, chỉ được gửi log Wazuh.

### 10. Chuyển DVWA sang DMZ

1. VM DVWA → Settings → Network Adapter → **Custom: VMnet2**.
2. Trong VM (bản Desktop dùng NetworkManager), xem tên connection rồi đặt IP tĩnh:
   ```bash
   nmcli -t -f NAME,DEVICE con show
   sudo nmcli con mod "<tên connection của ens33>" ipv4.method manual ipv4.addresses 172.16.10.10/24 ipv4.gateway 172.16.10.1 ipv4.dns 172.16.10.1
   sudo nmcli con up "<tên connection của ens33>"
   ip -4 a show ens33; ip route
   ```
3. Kiểm tra:
   - Trong DVWA: `curl -sI https://ubuntu.com | head -1` (DNS + port 443 phải chạy). `nc -zv -w3 10.10.99.1 1514` (phải succeeded). `ping -c2 -W2 10.10.99.1` (phải **thất bại**, vì bị rule Block chặn và ghi log)
   - Từ host: `ping 172.16.10.10` (host là SOC, được phép), mở http://172.16.10.10/dvwa
   - Từ Kali: `curl -I http://<IP WAN pfSense>/dvwa/login.php` → phải ra `HTTP/1.1 200 OK`
