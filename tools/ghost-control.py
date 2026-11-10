# 最小透明窗口对照；不读写桌宠会话。
import sys, time, os
from pathlib import Path
kind=sys.argv[1]
asset=str(Path(__file__).resolve().parents[1]/'assets/neutral-N.png')
start=time.monotonic()
if kind in ('gtk','webkit'):
    import gi, cairo
    gi.require_version('Gtk','3.0')
    from gi.repository import Gtk,Gdk,GLib
    w=Gtk.Window(title='ghost-control-'+kind); w.set_decorated(False); w.set_keep_above(True)
    w.set_app_paintable(True); w.set_visual(w.get_screen().get_rgba_visual()); w.set_default_size(200,240)
    pic=cairo.ImageSurface.create_from_png(asset)
    def paint(w,c):
        c.set_operator(cairo.OPERATOR_SOURCE); c.set_source_rgba(0,0,0,0); c.paint()
        c.set_operator(cairo.OPERATOR_OVER); c.set_source_surface(pic,4,32); c.paint()
        if int(time.monotonic()-start)%4<2:
            c.set_source_rgba(1,0,1,1); c.rectangle(8,4,184,22); c.fill()
        return False
    if kind=='webkit':
        if os.environ.get('GHOST_CLEAR'):
            def clear_parent(_,c):
                c.set_operator(cairo.OPERATOR_CLEAR);c.paint();c.set_operator(cairo.OPERATOR_OVER);return False
            w.connect('draw',clear_parent)
        import base64
        # 使用系统 4.1 C ABI，避免以 4.0 GI 绑定替代。
        import ctypes as C
        wk=C.CDLL('libwebkit2gtk-4.1.so.0'); gt=C.CDLL('libgtk-3.so.0')
        wk.webkit_web_view_new.restype=C.c_void_p
        wk.webkit_web_view_set_background_color.argtypes=[C.c_void_p,C.c_void_p]
        wk.webkit_web_view_load_html.argtypes=[C.c_void_p,C.c_char_p,C.c_char_p]
        gt.gtk_container_add.argtypes=[C.c_void_p,C.c_void_p]
        capsule=C.pythonapi.PyCapsule_GetPointer; capsule.argtypes=[C.py_object,C.c_char_p]; capsule.restype=C.c_void_p
        view=wk.webkit_web_view_new(); rgba=(C.c_double*4)(0,0,0,0);wk.webkit_web_view_set_background_color(view,C.byref(rgba))
        wk.webkit_web_view_get_settings.argtypes=[C.c_void_p];wk.webkit_web_view_get_settings.restype=C.c_void_p
        wk.webkit_settings_set_enable_write_console_messages_to_stdout.argtypes=[C.c_void_p,C.c_int]
        wk.webkit_settings_set_enable_write_console_messages_to_stdout(wk.webkit_web_view_get_settings(view),1)
        data=base64.b64encode(Path(asset).read_bytes()).decode()
        html="""<style>html,body{margin:0;background:transparent;overflow:hidden}canvas{width:100vw;height:100vh;will-change:transform}</style><canvas id=c width=200 height=240></canvas><script>let c=document.querySelector('canvas'),x=c.getContext('2d',{willReadFrequently:true}),i=new Image();i.src='data:image/png;base64,"""+data+"""';i.onload=()=>setInterval(()=>{x.clearRect(0,0,200,240);x.drawImage(i,4,32);if(Math.floor(performance.now()/1000)%4<2){x.fillStyle='#f0f';x.fillRect(8,4,184,22)}let a=x.getImageData(20,10,1,1).data[3];x.fillStyle=a?'red':'cyan';x.fillRect(0,230,10,10);if(window.lastA!==a){console.log('气泡alpha='+a);window.lastA=a}},50)</script>"""
        if os.environ.get('GHOST_NO_LAYER'):html=html.replace('will-change:transform','')
        wk.webkit_web_view_load_html(view,html.encode(),b'file:///')
        gt.gtk_container_add(capsule(w.__gpointer__,None),view)
        class Button(C.Structure):
            _fields_=[('type',C.c_int),('window',C.c_void_p),('send_event',C.c_byte),('time',C.c_uint),('x',C.c_double),('y',C.c_double),('axes',C.c_void_p),('state',C.c_uint),('button',C.c_uint),('device',C.c_void_p),('x_root',C.c_double),('y_root',C.c_double)]
        @C.CFUNCTYPE(C.c_int,C.c_void_p,C.POINTER(Button),C.c_void_p)
        def pressed(_,event,data):
            e=event.contents;w.begin_move_drag(1,int(e.x_root),int(e.y_root),e.time);print('系统拖动',flush=True);return 1
        go=C.CDLL('libgobject-2.0.so.0');go.g_signal_connect_data.argtypes=[C.c_void_p,C.c_char_p,C.c_void_p,C.c_void_p,C.c_void_p,C.c_int]
        go.g_signal_connect_data(view,b'button-press-event',pressed,None,None,0)
    else:w.connect('draw',paint)
    w.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
    w.connect('button-press-event',lambda w,e:w.begin_move_drag(1,int(e.x_root),int(e.y_root),e.time))
    w.connect('destroy',Gtk.main_quit); w.move(3000,3800); w.show_all()
    GLib.timeout_add(50,lambda:(w.queue_draw(),True)[1]); Gtk.main()
else:
    from PyQt5.QtWidgets import QApplication,QWidget
    from PyQt5.QtGui import QPainter,QPixmap,QColor
    from PyQt5.QtCore import Qt,QTimer
    QApplication.setAttribute(Qt.AA_DisableHighDpiScaling)
    app=QApplication([])
    class Pet(QWidget):
        def __init__(self):
            super().__init__(None,Qt.FramelessWindowHint|Qt.WindowStaysOnTopHint|Qt.Tool)
            self.setWindowTitle('ghost-control-qt'); self.setAttribute(Qt.WA_TranslucentBackground)
            self.resize(200,240); self.move(3000,3800); self.pic=QPixmap(asset)
        def paintEvent(self,e):
            p=QPainter(self); p.setCompositionMode(QPainter.CompositionMode_Source); p.fillRect(self.rect(),Qt.transparent)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver); p.drawPixmap(4,32,self.pic)
            if int(time.monotonic()-start)%4<2:p.fillRect(8,4,184,22,QColor(255,0,255))
        def mousePressEvent(self,e):
            print('系统拖动',self.windowHandle().startSystemMove(),flush=True)
    w=Pet(); w.show(); timer=QTimer(); timer.timeout.connect(w.update); timer.start(50); app.exec_()
