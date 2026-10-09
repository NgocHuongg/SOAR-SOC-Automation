# SOAR Lab – Phần 6a: VM Windows client (zone CLIENT)

## Vị trí trong kiến trúc

| Thuộc tính | Giá trị |
|---|---|
| Zone | CLIENT – VMnet3 – 10.10.20.0/24 |
| IP | DHCP từ pfSense (10.10.20.100–200), gateway và DNS là 10.10.20.1 |
| Hostname | `WIN11-CLIENT01` |
| User | Tài khoản local, giả lập nhân viên (ví dụ `user01`) |
| Được phép (theo rule pfSense) | Ra Internet thoải mái, vào DVWA cổng 80/443, gửi log Wazuh 10.10.99.1:1514-1515, DNS/NTP tới 10.10.20.1 |
| Bị chặn | Mọi kết nối khác vào dải RFC1918 (SOC, DMZ, ping host...) |

## Chọn bản Windows

- ISO **Windows 10 22H2**

## Checklist

- [x] 1–4. Cài Windows 10 22H2 (build 19045.2006), tài khoản local `NgocHuong` (2026-10-03). Nhận DHCP 10.10.20.100/24, gateway 10.10.20.1, DNS suffix `soar.internal`. `ping 8.8.8.8` OK, `curl http://172.16.10.10/dvwa` trả 301 (DVWA truy cập được)
- [x] 5. VMware Tools: đã có sẵn từ lúc cài (Easy Install)
- [x] 6. Bỏ qua: giờ đã khớp máy thật (Windows tự sync qua Internet), **giữ nguyên hostname**. Khi cài Wazuh agent sẽ đặt tên agent `win10-client` để dễ phân biệt trên dashboard
- [x] 7. Kiểm tra mạng (2026-10-03): 10.10.99.1:1514 → True ✔; 10.10.99.254:443 → False ✔ (bị chặn); ping 10.10.99.1 → timed out ✔ (bị chặn)
- [x] 8. Snapshot `Win11-clean`
- [x] 9. Cài Sysmon + Wazuh agent

---

### 2. Tạo VM trong VMware Workstation

1. **File → New Virtual Machine → Typical**.
2. Chọn **I will install the operating system later**.
3. Guest OS: **Microsoft Windows** → Version **Windows 11 x64**.
4. Tên `Win11-Client`, Location `F:\VMs\Win11-Client`.
5. **Encryption** (chỉ hiện với Windows 11): chọn **Only the files needed to support a TPM are encrypted**, đặt mật khẩu và **ghi lại** (mất mật khẩu thì không mở được VM). Bản VMware cũ không có lựa chọn này thì phải mã hoá toàn bộ VM.
6. Disk **64GB**, chọn **Store virtual disk as a single file**.
7. **Customize Hardware**:
   - Memory **4096MB**, Processors **2**
   - New CD/DVD → **Use ISO image file** → ISO Windows 11
   - Network Adapter → **Custom: VMnet3**
   - Xoá Printer. Sound Card để hay xoá đều được
8. Finish. Vào **VM → Settings → Options → Advanced**, kiểm tra Firmware type là **UEFI** và có tick **Enable secure boot**. Mục **Trusted Platform Module** phải có trong tab Hardware.

### 3. Cài Windows 11

1. Bật VM. Màn hình hiện **"Press any key to boot from CD or DVD…"** thì **nhấn phím bất kỳ ngay**. Nếu lỡ thì VM báo lỗi boot, khi đó chọn VM → Power → Restart Guest rồi thử lại.
2. Language: English (United States). Time and currency format: Vietnamese (Vietnam) hoặc English. Keyboard: US → Next.
3. Chọn **Install Windows 11**, tick đồng ý → Next.
4. Bản Evaluation không hỏi key. Đồng ý điều khoản (Accept).
5. Chọn ổ **Disk 0 Unallocated Space (64GB)** → Next. Máy cài khoảng 10–20 phút và tự reboot vài lần. Lúc này **không nhấn phím** khi máy hỏi boot from CD nữa.

### 4. OOBE – tạo tài khoản local

1. Region: Vietnam → Yes. Keyboard: US → Yes. Bỏ qua bàn phím thứ hai (Skip).
2. Máy có Internet qua pfSense (rule 6 của CLIENT) nên có thể tự tải cập nhật, cứ chờ.
3. Máy hỏi "How would you like to set up this device?" thì chọn **Set up for work or school** → **Sign-in options** → **Domain join instead**. Đây là cách tạo tài khoản local trên bản Enterprise.
4. Tên user: `user01` (giả lập nhân viên). Đặt mật khẩu và 3 câu hỏi bảo mật.
5. Privacy settings: tắt hết → Accept.

### 5. VMware Tools

VMware → **VM → Install VMware Tools** → trong Windows mở ổ DVD → chạy `setup64.exe` → **Typical** → Finish → Restart. Cài xong mới copy-paste và đổi độ phân giải được.

### 6. Cấu hình cơ bản (PowerShell **Run as Administrator** trong VM)

```powershell
# Giờ Việt Nam + đồng bộ NTP với pfSense (log khớp giờ với Wazuh)
Set-TimeZone -Id "SE Asia Standard Time"
w32tm /config /manualpeerlist:"10.10.20.1" /syncfromflags:manual /update
Restart-Service w32time
w32tm /resync
w32tm /query /status | findstr /C:"Source"

# Đổi tên máy (máy tự restart)
Rename-Computer -NewName "WIN11-CLIENT01" -Restart
```
Windows Defender **giữ bật**, vì máy người dùng thật luôn có antivirus.

### 7. Kiểm tra mạng (PowerShell trong VM)

```powershell
ipconfig | findstr /C:"IPv4" /C:"Gateway"
Resolve-DnsName google.com | Select-Object -First 1
Test-NetConnection 10.10.99.1 -Port 1514        # TcpTestSucceeded : True  (gửi log Wazuh)
Test-NetConnection 172.16.10.10 -Port 80        # TcpTestSucceeded : True  (vào DVWA)
Test-NetConnection 10.10.99.254 -Port 443       # False (bị chặn, không vào được GUI pfSense)
ping 10.10.99.1                                 # Request timed out (bị chặn)
```

| Lệnh | Kết quả đúng |
|---|---|
| ipconfig | IPv4 `10.10.20.1xx`, Gateway `10.10.20.1` |
| Resolve-DnsName | Ra IP của google.com |
| Port 1514 tới SOC | True |
| Port 80 tới DVWA | True |
| Port 443 tới pfSense GUI | False |
| ping 10.10.99.1 | Timed out |

Kết quả `False` / `timed out` là đúng thiết kế, vì máy user không được vào vùng quản trị. Mỗi lần bị chặn, pfSense ghi log với mô tả `Block CLIENT to internal`.

### 8. Snapshot

VMware → VM → Snapshot → Take Snapshot → `Win11-clean`.
