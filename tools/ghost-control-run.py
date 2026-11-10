# 必须由 flock 持锁运行，每次 <60 秒；只终止自己创建的子进程。
import subprocess as S,sys,time,os,re,json
from pathlib import Path
from PIL import Image
root=Path(__file__).resolve().parents[1]; out=root/'ghost-report'; kind=sys.argv[1]; trial=sys.argv[2]
log=open(out/f'{kind}-{trial}.log','w'); env=dict(os.environ,GDK_SCALE='1',QT_SCALE_FACTOR='1',QT_AUTO_SCREEN_SCALE_FACTOR='0')
p=S.Popen(['/usr/bin/python3','-I',str(root/'tools/ghost-control.py'),kind],env=env,stdout=log,stderr=log)
def geometry():
    s=S.check_output(['xwininfo','-name','ghost-control-'+kind],text=True)
    v=[int(re.search(k+r':\s+(-?\d+)',s).group(1)) for k in ['Absolute upper-left X','Absolute upper-left Y','Width','Height']]
    log.write(s); log.flush(); return v
try:
    time.sleep(1.5)
    for n in range(3):
        x,y,w,h=geometry(); cx=x+100;cy=y+150; direction=-1 if n%2==0 else 1
        args=[f'mv:{cx},{cy}','sleep:0.2','down','sleep:0.1']
        for j in range(1,13):args.extend([f'mv:{cx+direction*j*12},{cy}','sleep:0.08'])
        args+=['up','sleep:0.4','mv:2700,3700']
        S.run(['/usr/bin/python3','-I',str(root/'tools/mouse.py'),*args],check=True)
        for phase in range(2):
            time.sleep(1.1); name=f'{kind}-{trial}-{n}-{phase}'; full=out/(name+'-full.png')
            S.run(['spectacle','-b','-n','-f','-o',str(full)],check=True,stdout=log,stderr=log,timeout=10)
            x,y,w,h=geometry(); im=Image.open(full); im.crop((x-180,y-30,x+w+180,y+h+30)).save(out/(name+'-crop.png'))
            log.write(json.dumps({'截图':name,'窗口':[x,y,w,h],'时间':time.time()},ensure_ascii=False)+'\n');log.flush()
finally:
    p.terminate()
    try:p.wait(timeout=3)
    except S.TimeoutExpired:p.kill();p.wait()
    log.close()
