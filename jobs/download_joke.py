"""Job: Download a random joke from the internet and save to Desktop."""
import urllib.request
import json
import os

url = "https://official-joke-api.appspot.com/random_joke"
desktop = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop")
out_file = os.path.join(desktop, "joke.json")

data = json.loads(urllib.request.urlopen(url, timeout=10).read())
with open(out_file, "w") as f:
    json.dump(data, f, indent=2)

print(f"Joke saved to {out_file}")
print(f"Setup    : {data['setup']}")
print(f"Punchline: {data['punchline']}")
