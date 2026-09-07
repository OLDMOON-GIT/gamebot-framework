"""shadow DOM 포함 전체 탐색 + 리니지 텍스트 검색."""
import sys

sys.path.insert(0, r"C:\Users\moony\linc-bot")
from cdp import find_page_session

sess = find_page_session(9222, "purple")
r = sess.call("Runtime.evaluate", {"expression": """
(() => {
  let shadowCount = 0, total = 0, lincHits = [];
  const walk = (root) => {
    const els = root.querySelectorAll('*');
    total += els.length;
    els.forEach(e => {
      if (e.shadowRoot) { shadowCount++; walk(e.shadowRoot); }
      const t = (e.childNodes.length === 1 && e.childNodes[0].nodeType === 3) ? e.textContent.trim() : '';
      if (t.includes('리니지 클래식')) lincHits.push(e.tagName + ' ' + t.slice(0, 20));
    });
  };
  walk(document);
  return JSON.stringify({total, shadowCount, lincHits: lincHits.slice(0, 5), bodyHTMLlen: document.body.innerHTML.length});
})()
""", "returnByValue": True})
print(r.get("result", {}).get("value"))
