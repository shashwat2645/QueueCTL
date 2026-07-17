"""Job: Get weather for Mumbai and save to Desktop."""
import urllib.request
import os

url = "https://wttr.in/Mumbai?format=3"
desktop = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop")
out_file = os.path.join(desktop, "weather.txt")

req = urllib.request.Request(url, headers={"User-Agent": "curl/7.0"})
weather = urllib.request.urlopen(req, timeout=10).read().decode()

with open(out_file, "w") as f:
    f.write(weather)

print(f"Weather saved to {out_file}")
print(f"Weather: {weather.strip()}")
