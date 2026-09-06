import sys, time
sys.path.insert(0, r"C:\Users\moony\linc-bot")
from cdp import find_page_session, screenshot_b64

s = find_page_session(9333, "plaync")
r = s.call("Runtime.evaluate", {"expression": """
(() => {
  const links = [...document.querySelectorAll('a,button')].map(e => (e.innerText||'').trim() + ' | ' + (e.href||'')).filter(t => t.length > 2);
  const html = document.body.innerHTML;
  return JSON.stringify({
    url: location.href,
    buttons: links.slice(0, 40),
    purpleMention: html.toLowerCase().includes('purple'),
    bodyH: document.body.scrollHeight
  });
})()
""", "returnByValue": True})
print(r["result"]["value"][:3000])
s.close()
