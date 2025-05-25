#!/usr/bin/env python3
import requests

def ping_url():
    url = "https://www.google.com/gen_204"
    params = {
        "client": "mobilesearchapp",
        "oq": "longdeidhx73",
        "q": "lonhshu94376",
        "source": "mobilesearchapp",
        "sqi": "3"
    }

    try:
        resp = requests.get(url, params=params, timeout=5)
        print(f"Status Code: {resp.status_code}")
        print("Response Headers:")
        for k, v in resp.headers.items():
            print(f"  {k}: {v}")
        # gen_204 typically returns no body, but if there is one:
        if resp.text:
            print("Response Body:")
            print(resp.text)
    except requests.RequestException as e:
        print(f"Request failed: {e}")

if __name__ == "__main__":
    ping_url()
