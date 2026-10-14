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
├─ docs/
├─ wazuh-docker/
│  ├─ single-node/config/custom/
│  └─ single-node/config/wazuh_cluster/
├─ stacks/               # config stack chạy trong WSL
│  ├─ thehive-cortex/    # compose + .env.example
│  ├─ Ubuntu_WSL_Build/  # clone StrangeBeeCorp/docker — testing/ = compose + script
│  └─ n8n/               # compose n8n
├─ n8n_workflow_backup/  # export workflow SOAR
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
