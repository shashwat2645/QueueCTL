"""Job: Get my public IP address and save to Desktop."""
import urllib.request
import json
import os

url = "https://api.ipify.org?format=json"
desktop = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop")
out_file = os.path.join(desktop, "myip.json")

data = json.loads(urllib.request.urlopen(url, timeout=10).read())
with open(out_file, "w") as f:
    json.dump(data, f, indent=2)

print(f"IP saved to {out_file}")
print(f"Your public IP: {data['ip']}")
