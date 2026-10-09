# SOAR Lab – Phần 2a: Cài VM Ubuntu Server + DVWA

## Vị trí trong kiến trúc

| Thuộc tính | Giá trị cuối cùng | Tạm thời lúc cài |
|---|---|---|
| Zone | DMZ (VMnet2) | NAT (VMnet8), cần Internet để cài gói |
| IP | 172.16.10.10/24 tĩnh, gateway 172.16.10.1 (pfSense) | DHCP của VMware NAT |
| Hostname | `dvwa-web` | |

Lý do cài bằng NAT trước: lúc này chưa có pfSense nên VMnet2 chưa ra được Internet. Cài xong và test được thì mới chuyển sang VMnet2 + IP tĩnh. Việc này làm sau khi cài pfSense.

## Phiên bản

- Ubuntu Server **24.04 LTS** (bản point release mới nhất). Chọn 24.04 thay vì 26.04 vì Wazuh agent và DVWA hỗ trợ ổn định lâu hơn.
- DVWA: bản mới nhất trên GitHub `digininja/DVWA`
- PHP 8.3, Apache 2.4, MariaDB (theo repo Ubuntu 24.04)

## Thông số thực tế

- Dải NAT VMnet8 (cũng là WAN của lab): **192.168.210.0/24**. Theo mặc định của VMware: gateway NAT 192.168.210.2, host Windows 192.168.210.1.
- DVWA lúc cài (NAT, DHCP): **192.168.210.131**, card `ens33`. Dòng `noprefixroute` cho thấy máy dùng NetworkManager (bản Desktop).

## Checklist

- [x] A–C. Bỏ qua, dùng VM Ubuntu 24.04.4 có sẵn
- [x] D'. Cài openssh-server, đặt timezone, update/upgrade
- [x] E. Cài Apache + MariaDB + PHP 8.3.6 + DVWA
- [x] F. Setup DVWA: Create DB xong, đăng nhập admin được tại http://192.168.210.131/dvwa (2026-10-02). Setup check còn đỏ: reCAPTCHA, mod_rewrite, vendor API, display_startup_errors. Không ảnh hưởng lab chính, chỉ cần khi làm bài API
- [x] G. Chụp snapshot `DVWA-clean`
- [x] H. Chuyển card sang VMnet2, đặt IP tĩnh 172.16.10.10/24, gateway và DNS là 172.16.10.1, bằng `nmcli con mod "netplan-ens33" ...` (2026-10-03). URL mới: http://172.16.10.10/dvwa. Từ Internet (Kali): http://<IP WAN pfSense>/dvwa

---

### A. Tải ISO

Vào https://releases.ubuntu.com/24.04/ và tải file iso

### B. Cài Ubuntu Server

| Màn hình | Chọn |
|---|---|
| Language / Keyboard | English / English (US) |
| Type of installation | **Ubuntu Server** (không chọn minimized) |
| Network | Giữ DHCP, card `ens33` nhận IP dải NAT |
| Proxy | Để trống |
| Mirror | Mặc định, chờ test xong |
| Storage | Use an entire disk, giữ mặc định (LVM) |
| Profile | Your name: tuỳ ý · Server name: **`dvwa-web`** · Username/Password: tuỳ ý (ghi lại) |
| Ubuntu Pro | Skip for now |
| SSH | Tick **Install OpenSSH server** |
| Featured snaps | Không chọn gì |

Đăng nhập rồi xem IP:
```bash
ip -4 a show ens33
```

### D. SSH vào và cập nhật

Nên dùng SSH từ Windows Terminal thay vì gõ trong cửa sổ VMware, vì console của VMware không dán (paste) được lệnh.
```powershell
ssh <username>@<IP của VM>
```
Trong VM:
```bash
sudo apt update && sudo apt -y upgrade
sudo timedatectl set-timezone Asia/Ho_Chi_Minh
timedatectl
```
Timezone phải đồng nhất giữa các máy, nếu lệch giờ thì Wazuh correlate log sai.

### D'. Dùng VM Ubuntu 24.04.4 có sẵn

```bash
sudo timedatectl set-timezone Asia/Ho_Chi_Minh
sudo apt install -y openssh-server
sudo systemctl enable --now ssh
ip -4 a
```

### E. Cài LAMP + DVWA

```bash
# 1. Web server, database, PHP và các module DVWA cần
sudo apt install -y apache2 mariadb-server php libapache2-mod-php php-mysql php-gd git

# 2. Tạo database và user cho DVWA (khớp với cấu hình mặc định của DVWA)
sudo mysql -e "CREATE DATABASE dvwa; CREATE USER 'dvwa'@'localhost' IDENTIFIED BY 'p@ssw0rd'; GRANT ALL PRIVILEGES ON dvwa.* TO 'dvwa'@'localhost'; FLUSH PRIVILEGES;"

# 3. Tải DVWA về web root
cd /var/www/html
sudo git clone https://github.com/digininja/DVWA.git dvwa
sudo cp dvwa/config/config.inc.php.dist dvwa/config/config.inc.php
sudo chown -R www-data:www-data dvwa/hackable/uploads dvwa/config

# 4. Bật các tuỳ chọn PHP cho bài File Inclusion và lỗi SQL hiển thị
PHPINI=$(ls /etc/php/*/apache2/php.ini)
sudo sed -i 's/^allow_url_include = Off/allow_url_include = On/; s/^display_errors = Off/display_errors = On/' $PHPINI
grep -E "^(allow_url_include|allow_url_fopen|display_errors) " $PHPINI
sudo systemctl restart apache2
```
- Lệnh `grep` phải ra cả 3 dòng `= On`.
- Mặc định DVWA kết nối DB tại `127.0.0.1` bằng user `dvwa` / `p@ssw0rd`, nên tạo đúng user đó thì không phải sửa file config.
- Chỉ giao quyền cho `www-data` ở 2 thư mục DVWA cần ghi (`hackable/uploads` và `config`), không chown cả thư mục.

### F. Setup DVWA

1. Trên trình duyệt Windows, mở `http://<IP của VM>/dvwa/setup.php`.
2. Kiểm tra mục kiểm tra (check list) ở trang setup: các dòng PHP module, writable folder và allow_url phải màu xanh. Dòng reCAPTCHA đỏ thì bỏ qua.
3. Bấm **Create / Reset Database**, trang sẽ tự chuyển về trang login.
4. Đăng nhập bằng `admin` / `password`.
5. Vào **DVWA Security** để chỉnh mức Low/Medium/High khi làm từng bài tấn công.

### G. Snapshot

VMware → VM → Snapshot → **Take Snapshot** → đặt tên `DVWA-clean`. Sau mỗi lần tấn công làm hỏng máy có thể quay về trạng thái sạch.

### H. Chuyển sang DMZ (làm sau khi cài pfSense)

1. VM Settings → Network Adapter → **Custom: VMnet2**.
2. Đặt IP tĩnh bằng netplan. File `/etc/netplan/50-cloud-init.yaml`:
   ```yaml
   network:
     version: 2
     ethernets:
       ens33:
         dhcp4: false
         addresses: [172.16.10.10/24]
         routes:
           - to: default
             via: 172.16.10.1
         nameservers:
           addresses: [172.16.10.1]
   ```
3. Chạy `sudo netplan apply`.

Chi tiết sẽ làm cùng lúc cấu hình pfSense.
