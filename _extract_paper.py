# -*- coding: utf-8 -*-
import sys
try:
    import fitz  # PyMuPDF
except Exception as e:
    print("NO_FITZ:", e)
    sys.exit(2)

src = r"D:\桌面\HKUST\DISC毕设\brickqa.pdf"
out = r"D:\桌面\HKUST\Brickqa\BrickQA\_paper_text.txt"

doc = fitz.open(src)
parts = []
for i, page in enumerate(doc):
    parts.append(f"\n\n===== PAGE {i+1} =====\n")
    parts.append(page.get_text())
text = "".join(parts)
with open(out, "w", encoding="utf-8") as f:
    f.write(text)
print(f"OK pages={len(doc)} chars={len(text)}")
