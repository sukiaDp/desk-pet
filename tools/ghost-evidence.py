# 从 spectacle 的裁剪图计算可复核的色块像素数，不使用 XGetImage。
from pathlib import Path
from PIL import Image,ImageDraw
r=Path(__file__).resolve().parents[1]/'ghost-report'
lines=['# 合成截图像素核对','','青色标记表示同一次 canvas 绘制读到气泡 alpha=0；此时洋红像素应为 0。','', '|截图|青色像素|洋红像素|','|---|---:|---:|']
for trial in range(5,11):
 for p in sorted(r.glob(f'webkit-{trial}-*-crop.png')):
  colors=Image.open(p).convert('RGB').getdata()
  cyan=sum(v==(0,255,255) for v in colors);magenta=sum(v==(255,0,255) for v in colors)
  lines.append(f'|[{p.name}]({p.name})|{cyan}|{magenta}|')
(r/'像素核对.md').write_text('\n'.join(lines)+'\n')
files=[r/f'webkit-{trial}-0-1-crop.png' for trial in [5,6,7,8,9,10]]
if all(p.exists() for p in files):
 out=Image.new('RGB',(1120,990),'#eee');d=ImageDraw.Draw(out)
 for n,p in enumerate(files):
  x=n%2*560;y=n//2*330;out.paste(Image.open(p),(x,y+30));d.text((x+10,y+8),p.stem,fill='black')
 out.save(r/'透明残留对照.png')
