# SOAR Lab – Tự động hóa phát hiện & phản ứng sự cố SOC

## Kiến trúc mạng

| Zone | Subnet | Thành phần |
|---|---|---|
| WAN (NAT) | 192.168.210.0/24 | Kali (attacker) |
| DMZ | 172.16.10.0/24 | DVWA (172.16.10.10) |
| CLIENT | 10.10.20.0/24 | Windows 10 (+ Sysmon, Wazuh agent) |
| SOC/MGMT | 10.10.99.0/24 | Host (10.10.99.1) + Docker stack; pfSense .254 |

## Bố cục thư mục

```
SOAR_Project/
├─ docs/                 # Toàn bộ tài liệu triển khai (01–07, 10, 11)
├─ wazuh-docker/         # Bản clone wazuh/wazuh-docker v4.14.8, chạy từ Windows — single-node/
│  ├─ single-node/config/custom/       # decoder & rule riêng, script integration n8n
│  └─ single-node/config/wazuh_cluster/ # wazuh_manager.conf.example
├─ stacks/               # config các stack chạy trong WSL
│  ├─ thehive-cortex/    # compose + .env.example (DATA ở WSL)
│  ├─ Ubuntu_WSL_Build/  # clone StrangeBeeCorp/docker — testing/ = compose + script
│  └─ n8n/               # compose n8n
├─ n8n_workflow_backup/  # export workflow SOAR (không chứa secret)
├─ keys/                 # SSH key pfSense
├─ Image/                
└─ README.md
```

## Chạy lab

Thứ tự bật: Docker Desktop → pfSense → DVWA/Win10 → Kali (khi cần). Cách bật/tắt
an toàn xem `docs/10-quy-trinh-trien-khai.md` (mục 8).

| Stack | Vị trí chạy | Lệnh |
|---|---|---|
| Wazuh | Windows: `wazuh-docker/single-node` | `docker compose up -d` |
| TheHive/Cortex | WSL: `~/soar-lab/thehive-cortex/testing` | `docker compose up -d cassandra elasticsearch thehive cortex` |
| n8n | WSL: `~/soar-lab/n8n` | `docker compose up -d` |

### Vì sao TheHive/Cortex/n8n chạy trong WSL, không phải trên ổ F:

Cassandra và Elasticsearch cần đúng quyền sở hữu Linux (uid/gid) cho thư mục dữ
liệu. Trên ext4 của WSL thì đúng permission và nhanh; trên NTFS/DrvFs (`/mnt/f`)
database dễ lỗi phân quyền và chậm. Vì vậy **phần cấu hình** được gom vào
`stacks/` để quản lý/nộp bài, còn **dữ liệu vẫn nằm trong WSL / Docker named
volume** — không di chuyển.

## Bảo mật

- `keys/`, `.env`, mật khẩu/API key thật **không đưa lên GitHub** (xem
  `.gitignore`). Bảng tài khoản đầy đủ giữ riêng ở `00-tai-khoan.md` (ngoài repo).
- Nếu từng lỡ commit key lên GitHub, phải **đổi key**, vì xoá ở commit mới không
  xoá khỏi lịch sử.
