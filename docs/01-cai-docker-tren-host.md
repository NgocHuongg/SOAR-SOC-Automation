# SOAR Lab – Bước 1: Cài stack Docker trên host Windows

## Kiến trúc

| # | Thành phần | Nằm ở | Mạng | IP |
|---|---|---|---|---|
| 1 | Docker: Wazuh, TheHive, Cortex, n8n | Host Windows (Docker Desktop + WSL2) | SOC: card ảo VMnet4 trên host | 10.10.99.1 |
| 2 | DVWA (Ubuntu Server) | VMware | DMZ: VMnet2 | 172.16.10.10 |
| 3 | Windows client (+ Sysmon) | VMware | LAN: VMnet3 | DHCP từ pfSense |
| 4 | pfSense + Suricata | VMware, 4 NIC | WAN VMnet8 / DMZ VMnet2 / LAN VMnet3 / SOC VMnet4 | .1 / .1 / .254 |
| 5 | Kali (attacker) | VMware | WAN: VMnet8 (NAT) | DHCP VMware |

## Phiên bản dùng

| Thành phần | Version |
|---|---|
| Wazuh (wazuh-docker) | v4.14.8 |
| TheHive | 5.8.0 |
| Cortex | 4.1.0 |
| Cassandra / Elasticsearch (cho TheHive + Cortex) | 4.1.12 / 8.19.22 |
| n8n | latest |

## Port

| Port | Dịch vụ |
|---|---|
| 443 | Wazuh Dashboard |
| 1514/tcp, 1515/tcp | Wazuh agent gửi log và đăng ký |
| 514/udp | Wazuh nhận syslog (pfSense, Suricata) |
| 55000 | Wazuh API |
| 9200 | Wazuh Indexer |
| 9000 | TheHive |
| 9001 | Cortex |
| 5678 | n8n |

## Checklist

- [x] 0. Cài Docker Desktop (WSL2 backend). Đã cài thêm distro **Ubuntu-24.04** (user Linux: `ngochuong`) riêng cho stack TheHive/Cortex/n8n. Kali WSL (`kali-linux`) giữ riêng cho tấn công
- [x] 0b. Bật WSL integration cho Ubuntu-24.04 trong Docker Desktop. Ubuntu đã thấy container Wazuh qua `docker ps`
- [x] 0c. Chuyển ổ dữ liệu Docker Desktop sang `F:\DockerData\DockerDesktopWSL` (Settings → Resources → Advanced → Disk image location). Giới hạn đĩa khoảng 1TB, xem ở thanh trạng thái dưới đáy Docker Desktop. Thanh "X GB / Y GB in use" trong tab Images chỉ là dung lượng image, không phải giới hạn
  - Gặp lỗi `The command 'docker' could not be found in this WSL 2 distro`: do Ubuntu cài sau Docker Desktop. Cách xử lý: Settings → Resources → WSL integration → Refresh, bật Ubuntu-24.04 → Apply & restart → chạy `wsl --terminate Ubuntu-24.04` rồi mở lại Ubuntu
- [x] 1. Cài Wazuh single-node: xong ngày 2026-10-02, chạy từ `F:\SOAR_Project\wazuh-docker\single-node` (CMD Windows)
- [x] 2. Cài TheHive và Cortex: 4 service healthy ngày 2026-10-02, chạy trong Ubuntu ở `~/soar-lab/thehive-cortex/testing`
  - Gặp `TLS handshake timeout` khi pull Elasticsearch: lỗi mạng tạm thời. Chạy `docker compose pull ...` lại là được
- [x] 3. Cài n8n: chạy ngày 2026-10-02, trong Ubuntu ở `~/soar-lab/n8n`. Lần đầu pull gặp `502 Bad Gateway` từ Docker Hub, chạy `docker compose pull` lại là được
- [x] 4. Kiểm tra toàn bộ: đủ 8 container Up, đăng nhập được cả 4 UI (Wazuh, TheHive, Cortex, n8n). Port 443/1514/1515/5678/9000/9001/55000 đều listen trên `0.0.0.0` (process Docker Desktop). Các dòng `127.0.0.1` / `[::1]` của PID khác là `wslrelay` của WSL, vô hại

---

### Bước 0: Chuẩn bị (PowerShell chạy bằng quyền Administrator)

```powershell
wsl --install -d Ubuntu-24.04
```
Khởi động lại máy, mở Ubuntu và đặt username/password.

```powershell
winget install -e --id Docker.DockerDesktop
```
Mở Docker Desktop:
- Settings → General: tick **Use the WSL 2 based engine**.
- Settings → Resources → WSL integration: bật **Ubuntu-24.04**.

Giới hạn RAM cho WSL2 và đặt `vm.max_map_count`. Wazuh Indexer và Elasticsearch bắt buộc giá trị này là 262144.
```powershell
@"
[wsl2]
memory=16GB
processors=8
swap=4GB
kernelCommandLine = "sysctl.vm.max_map_count=262144"
"@ | Set-Content -Encoding ascii "$env:USERPROFILE\.wslconfig"

wsl --shutdown
```
Mở lại Docker Desktop.

Kiểm tra trong terminal Ubuntu:
```bash
docker version
docker compose version
cat /proc/sys/vm/max_map_count      # phải ra 262144
free -h                             # tổng RAM khoảng 16G
sudo apt update && sudo apt install -y git openssl
mkdir -p ~/soar-lab
```

### Bước 1: Wazuh single-node
```bash
cd ~/soar-lab
git clone https://github.com/wazuh/wazuh-docker.git -b v4.14.8
cd wazuh-docker/single-node
docker compose -f generate-indexer-certs.yml run --rm generator
docker compose up -d
docker compose ps
```
- Lệnh `generator` tạo chứng chỉ SSL cho indexer, manager và dashboard. Phải chạy lệnh này trước `up`.
- Chờ 1–3 phút rồi mở **https://localhost**, chấp nhận chứng chỉ tự ký.
- Đăng nhập: `admin` / `SecretPassword`.
- Nếu không lên, xem log: `docker compose logs -f wazuh.indexer`

### Bước 2: TheHive và Cortex

Dùng repo Docker chính thức của StrangeBee, profile `testing`.
```bash
cd ~/soar-lab
git clone https://github.com/StrangeBeeCorp/docker.git thehive-cortex
cd thehive-cortex/testing
bash ./scripts/init.sh -y
docker compose up -d cassandra elasticsearch thehive cortex
docker compose ps
```
- `init.sh` sinh mật khẩu Elasticsearch, secret cho TheHive/Cortex, file `.env` (UID/GID, version) và sửa permission thư mục.
- Chỉ bật 4 service, bỏ `nginx`, vì nginx chiếm port 443 trùng với Wazuh.
- Chờ 2–4 phút, Cassandra khởi động lâu nhất.
- **TheHive:** http://localhost:9000/thehive, đăng nhập `admin@thehive.local` / `secret`, đổi mật khẩu ngay.
- **Cortex:** http://localhost:9001/cortex. Lần đầu bấm **Update database**, rồi tạo tài khoản superadmin.
- Nếu không lên, xem log: `docker compose logs -f thehive` hoặc `docker compose logs -f cortex`
- Lưu ý: analyzer của Cortex chạy dạng container (mount docker.sock). Trên Docker Desktop có thể cần chỉnh đường dẫn job directory. Phần này xử lý ở bước cấu hình Cortex sau.

### Bước 3: n8n

```bash
mkdir -p ~/soar-lab/n8n && cd ~/soar-lab/n8n
cat > docker-compose.yml <<'EOF'
services:
  n8n:
    image: docker.n8n.io/n8nio/n8n:latest
    container_name: n8n
    restart: unless-stopped
    ports:
      - "5678:5678"
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
- `N8N_SECURE_COOKIE=false` cho phép đăng nhập qua http bằng IP (ví dụ 10.10.99.1:5678). Thiếu biến này thì n8n chỉ cho đăng nhập qua localhost.
- Mở **http://localhost:5678** và tạo tài khoản owner.

### Bước 4: Kiểm tra tổng

```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```
Phải có các container: `single-node-wazuh.manager-1`, `single-node-wazuh.indexer-1`, `single-node-wazuh.dashboard-1`, `cassandra`, `elasticsearch`, `thehive`, `cortex`, `n8n`. Tất cả ở trạng thái Up (healthy).

Kiểm tra trên PowerShell của Windows rằng các port đã mở trên host:
```powershell
netstat -ano | findstr "LISTENING" | findstr ":443 :1514 :1515 :9000 :9001 :5678 :55000"
```

## Lệnh vận hành hay dùng

Chạy trong thư mục của từng stack (`wazuh-docker/single-node`, `thehive-cortex/testing`, `n8n`):
```bash
docker compose stop        # tắt, giữ dữ liệu
docker compose start       # bật lại
docker compose logs -f     # xem log
docker compose down        # xoá container, giữ volume/dữ liệu
```

## Bước tiếp theo

Bước 2 của lab: cấu hình VMnet trong VMware (VMnet2/3/4) và cài pfSense.
