import ctypes as C, sys, time
x=C.cdll.LoadLibrary('libX11.so.6'); t=C.cdll.LoadLibrary('libXtst.so.6')
x.XOpenDisplay.restype=C.c_void_p; d=C.c_void_p(x.XOpenDisplay(None))
def mv(px,py): t.XTestFakeMotionEvent(d,-1,px,py,0); x.XFlush(d)
def btn(down): t.XTestFakeButtonEvent(d,1,down,0); x.XFlush(d)
cmds=sys.argv[1:]
for c in cmds:
    k,*a=c.split(':')
    if k=='mv': mv(*map(int,a[0].split(',')))
    elif k=='down': btn(1)
    elif k=='up': btn(0)
    elif k=='sleep': time.sleep(float(a[0]))
