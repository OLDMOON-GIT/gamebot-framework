import sqlite3, shutil, sys, os

def hosts(db_path, label):
    tmp = db_path + ".rocopy"
    try:
        shutil.copy2(db_path, tmp)
        con = sqlite3.connect(tmp)
        rows = [r[0] for r in con.execute("SELECT DISTINCT host_key FROM cookies")]
        con.close()
        nc = [h for h in rows if "plaync" in h or "ncsoft" in h or "purple" in h]
        print(f"{label}: 총 {len(rows)}개 도메인, NC 관련: {nc if nc else '없음'}")
    except Exception as e:
        print(f"{label}: 읽기 실패 {e}")
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)

hosts(r"C:\Users\moony\AppData\Local\Google\Chrome\User Data\Default\Network\Cookies", "메인크롬")
hosts(r"C:\Users\moony\linc-bot\chrome-profile\Default\Network\Cookies", "봇크롬")
hosts(r"C:\Users\moony\AppData\Local\Microsoft\Edge\User Data\Default\Network\Cookies", "엣지")
