import os
import sqlite3

for browser, base in [
    ("Edge-Admin", r"C:\Users\Administrator\AppData\Local\Microsoft\Edge\User Data"),
    ("Chrome-Admin", r"C:\Users\Administrator\AppData\Local\Google\Chrome\User Data"),
]:
    if not os.path.exists(base):
        print(browser, "프로필 없음")
        continue
    for prof in sorted(os.listdir(base)):
        ck = os.path.join(base, prof, "Network", "Cookies")
        if not os.path.exists(ck):
            continue
        try:
            uri = "file:" + ck.replace("\\", "/") + "?immutable=1"
            con = sqlite3.connect(uri, uri=True)
            rows = [r[0] for r in con.execute("SELECT DISTINCT host_key FROM cookies")]
            con.close()
            nc = [h for h in rows if "plaync" in h or "ncsoft" in h or "nclobby" in h]
            if nc:
                print(f"{browser}/{prof}: NC 발견! {nc}")
        except Exception:
            pass
print("scan done")
