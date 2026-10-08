# SOAR Lab – Tự động hóa phát hiện & phản ứng sự cố SOC

Lab mô phỏng một SOC thu nhỏ: **Wazuh** (SIEM) + **Suricata/pfSense** (IDS/FW) →
**n8n** (SOAR) → **TheHive/Cortex** (quản lý sự cố + làm giàu) → tự động **chặn
IP tấn công** trên pfSense.

> Tài liệu triển khai đầy đủ nằm trong `docs/`. Bắt đầu từ
> `docs/10-quy-trinh-trien-khai.md` (mạch xuyên suốt), rồi `docs/01`→`07` cho chi
> tiết từng phase.

## Kiến trúc mạng

| Zone | Subnet | Thành phần |
|---|---|---|
| WAN (NAT) | 192.168.210.0/24 | Kali (attacker) |
| DMZ | 172.16.10.0/24 | DVWA (172.16.10.10) |
| CLIENT | 10.10.20.0/24 | Windows 10 (+ Sysmon, Wazuh agent) |
| SOC/MGMT | 10.10.99.0/24 | Host (10.10.99.1) + Docker stack; pfSense .254 |

Phiên bản: Wazuh 4.14.8 · TheHive 5.8 · Cortex 4.1 · n8n latest · pfSense 2.8.1 +
Suricata 7.0.9.

## Bố cục thư mục

```
SOAR_Project/
├─ docs/                 # Toàn bộ tài liệu triển khai (01–07, 10, 11)
├─ wazuh-docker/         # Stack Wazuh (chạy từ Windows) — single-node/
│  └─ single-node/config/custom/   # decoder & rule riêng, script integration n8n
├─ stacks/               # (gom về) config các stack chạy trong WSL
│  ├─ thehive-cortex/    # chỉ compose + .env.example (DATA ở WSL, xem ghi chú)
│  └─ n8n/               # compose n8n
├─ n8n_workflow_backup/  # export workflow SOAR (không chứa secret)
├─ keys/                 # ⚠ SSH key pfSense — KHÔNG commit lên GitHub
├─ Image/                # ảnh minh hoạ cho báo cáo (Video/ để ngoài repo, file quá lớn)
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
