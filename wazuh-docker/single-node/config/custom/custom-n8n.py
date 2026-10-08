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