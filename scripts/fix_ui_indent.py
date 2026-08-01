from pathlib import Path
import ast

path = Path("media_studio/ui.py")
lines = path.read_text(encoding="utf-8").splitlines(True)

start = None
for i, L in enumerate(lines):
    if L.startswith("def _build_studio_tab"):
        start = i
        break

body_start = None
for i in range(start, len(lines)):
    if lines[i].lstrip().startswith("with gr.Row():"):
        body_start = i
        break

out = lines[:body_start]
i = body_start
out.append(lines[i])  # with gr.Row():
i += 1

while i < len(lines):
    L = lines[i]
    if L.lstrip().startswith("# --- events ---"):
        break
    if L.strip() == "":
        out.append(L)
        i += 1
        continue
    if L.startswith("            "):  # >=12 spaces
        out.append(L[4:])
    else:
        out.append(L)
    i += 1

while i < len(lines):
    L = lines[i]
    if L.strip() == "":
        out.append(L)
        i += 1
        continue
    if L.startswith("        "):
        out.append(L[4:])
    else:
        out.append(L)
    i += 1

path.write_text("".join(out), encoding="utf-8")
ast.parse(path.read_text(encoding="utf-8"))
print("syntax OK")
