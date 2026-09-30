"""Paper chapter presentation for draft research settings."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageTk
from .logbook_view import LogbookView

INK, RED, MUTED = "#20150d", "#59180f", "#362417"
PAGES = ("研究策略", "注入节律", "快捷符令", "世界连接")


class SettingsBookView:
    # Share the logbook's font metrics and coordinate conversion.
    _font = LogbookView._font
    _text = LogbookView._text
    _line = LogbookView._line
    point = LogbookView.point

    def __init__(self, editor):
        self.editor = editor
        self.canvas = tk.Canvas(editor.window, bg="#090705", highlightthickness=0, takefocus=True)
        self.canvas.pack(fill="both", expand=True)
        self.family = editor.app.logbook.family
        self._fonts = {}
        self.scale, self.offset_x, self.offset_y = 1., 0., 0.
        self.focus = None
        self.hover = None
        self.targets = {}
        self._background_photo = None
        self._preview_photo = None
        self._github_photo = None
        self._background_key = None
        self.background = editor.app.logbook.background.copy().resize((1024, 681))
        mask = Image.new("L", self.background.size, 0)
        draw = ImageDraw.Draw(mask)
        draw.rectangle((90, 180, 385, 615), fill=180)
        draw.rectangle((518, 110, 892, 583), fill=200)
        mask = mask.filter(ImageFilter.GaussianBlur(28))
        self.background = Image.composite(ImageEnhance.Brightness(self.background).enhance(1.5), self.background, mask)
        paper = ImageEnhance.Brightness(self.background.crop((620, 250, 735, 289))).enhance(1.14)
        self.background.paste(paper, (767, 551))
        self.fields = {}
        for key, variable in (("delay", editor.delay), ("verify", editor.verify), ("pid", editor.pid)):
            entry = tk.Entry(self.canvas, textvariable=variable, bg="#c1a578", fg=INK,
                             insertbackground=RED, relief="flat", bd=2,
                             highlightthickness=1, highlightbackground=MUTED, highlightcolor=RED)
            self.fields[key] = entry
        self.process_combo = ttk.Combobox(self.canvas, textvariable=editor.process, state="readonly")
        self.process_combo.bind("<<ComboboxSelected>>", editor.select_process)
        self.fields["process"] = self.process_combo
        for key, field in self.fields.items():
            field.bind("<Tab>", lambda e, k=key: self.move_focus(-1 if e.state & 1 else 1, k))
            field.bind("<Shift-Tab>", lambda e, k=key: self.move_focus(-1, k))
            field.bind("<Escape>", editor.escape)
        self.canvas.bind("<Configure>", lambda e: self.draw())
        self.canvas.bind("<Motion>", self.motion)
        self.canvas.bind("<Leave>", self.leave)
        self.canvas.bind("<Button-1>", self.click)
        self.canvas.bind("<KeyPress>", self.key)
        self.canvas.bind("<Tab>", lambda e: self.move_focus(-1 if e.state & 1 else 1))
        self.canvas.bind("<Shift-Tab>", lambda e: self.move_focus(-1))
        self.canvas.bind("<Escape>", editor.escape)
        self.draw()

    def diamond(self, x, y, selected=False):
        points = [self.point(x-5,y),self.point(x,y-5),self.point(x+5,y),self.point(x,y+5)]
        self.canvas.create_polygon(*sum((list(p) for p in points), []), outline=RED,
                                   fill=RED if selected else "", width=max(1,self.scale))

    def target(self, key, box, command):
        self.targets[key] = (box, command)
        if key in (self.focus, self.hover):
            x1,y1,x2,y2 = box
            self._line(x1,y2,x2,y2,fill=RED, width=max(1,self.scale))

    def field(self, key, x, y, width):
        widget = self.fields[key]
        widget.configure(font=self._font(16))
        self.canvas.create_window(*self.point(x,y), anchor="nw", window=widget,
                                  width=round(width*self.scale), height=round(30*self.scale))
        self.targets[key] = ((x,y,x+width,y+30), widget.focus_set)

    def draw(self):
        if self.editor.closed or not self.canvas.winfo_exists():
            return
        e = self.editor
        cw,ch = self.canvas.winfo_width(),self.canvas.winfo_height()
        if cw <= 1: cw,ch = 1024,681
        self.scale = min(cw/1024,ch/681)
        self.offset_x,self.offset_y = (cw-1024*self.scale)/2,(ch-681*self.scale)/2
        size = (max(1,round(1024*self.scale)),max(1,round(681*self.scale)))
        if size != self._background_key:
            self._background_photo = ImageTk.PhotoImage(self.background.resize(size,Image.Resampling.LANCZOS),master=self.canvas)
            self._background_key = size
            self._fonts.clear()
        self.canvas.delete("all")
        self.canvas.create_image(*self.point(0,0),image=self._background_photo,anchor="nw")
        self.targets = {}
        t = self._text
        t(111,198,"研 究 配 置",23,RED)
        t(112,232,"择定研习之法，校准要素之序。",13,MUTED)
        for i,title in enumerate(PAGES):
            y = 287+i*46
            self.diamond(115,y,title==e.page)
            t(135,y,title,19,RED if title==e.page else INK)
            t(338,y,("Ⅰ","Ⅱ","Ⅲ","Ⅳ")[i],14,MUTED)
            if title==e.page: self._line(134,y+20,365,y+20,fill=RED)
            self.target(title,(106,y-18,371,y+21),lambda p=title:e.show_page(p))
        self._line(112,482,363,482,fill=MUTED)
        t(112,510,"配 置 摘 要",13,RED)
        from .gui_app import PLACEMENT_SPEED_PRESETS
        from .client_bridge import SOLVER_MODE_OPTIMAL
        mode = "精简连线" if e.mode.get()==SOLVER_MODE_OPTIMAL else "库存优先"
        t(112,540,mode+"  ·  "+PLACEMENT_SPEED_PRESETS[e.preset.get()]["label"]+"节律",14)
        t(112,564,"世界连接  ·  "+("手动指定" if e.pid.get() else "自动检测"),14)
        t(112,594,"修改将在保存后生效",12,MUTED)
        t(113,630,"‹ 返回研究手册",14,RED)
        self.target("back",(108,612,305,647),e.cancel)
        t(529,126,f"第 {PAGES.index(e.page)+1} 章  ·  研究配置",12,MUTED)
        t(529,165,e.page,27,RED)
        self._line(529,190,695,190,fill=MUTED)
        self.diamond(711,190)
        self._line(727,190,890,190,fill=MUTED)
        if e.page=="研究策略": self.strategy()
        elif e.page=="注入节律": self.rhythm()
        elif e.page=="快捷符令": self.shortcuts()
        else: self.connection()
        # Reserve two lines for actionable validation and progress feedback.
        t(529,493,e.hint.get(),12,RED,anchor="nw",width=355)
        self._line(529,539,890,539,fill=MUTED)
        t(529,572,"恢复本页默认",13,MUTED)
        self.target("reset",(524,551,644,590),e.reset_page)
        t(701,572,"取消",15)
        self.target("cancel",(683,551,740,590),e.cancel)
        for inset in (0,4):
            self.canvas.create_rectangle(*self.point(767+inset,551+inset),*self.point(882-inset,590-inset),outline=RED,width=max(1,self.scale))
        t(791,572,"保存配置",16,RED)
        self.target("save",(767,551,882,590),e.save)

    def strategy(self):
        from .client_bridge import DEFAULT_SOLVER_MODE,SOLVER_MODE_OPTIMAL
        e=self.editor
        for value,title,y,lines in ((DEFAULT_SOLVER_MODE,"库存优先",235,("优先使用储备充足的要素，","减少稀缺库存消耗与额外合成。")),
                                    (SOLVER_MODE_OPTIMAL,"精简连线",374,("优先减少连线所需的放置格数，","再兼顾库存余量与合成需求。"))):
            selected=e.mode.get()==value
            self.diamond(540,y,selected)
            self._text(559,y,title,21,RED if selected else INK)
            if selected:self._text(811,y,"已选定",12,RED)
            for i,line in enumerate(lines):self._text(559,y+42+i*25,line,16)
            self.target(value,(529,y-20,887,y+83),lambda v=value:e.mode.set(v))
        self._line(559,329,882,329,fill=MUTED)

    def rhythm(self):
        e=self.editor
        self._text(529,232,"选择要素注入的节律",16)
        for i,(value,title) in enumerate((("stable","稳定"),("balanced","标准"),("fast","快速"),("turbo","极速"))):
            x=536+i*91
            self.diamond(x,274,e.preset.get()==value)
            self._text(x+13,274,title,17,RED if e.preset.get()==value else INK)
            self.target(value,(x-8,251,x+70,296),lambda v=value:self.set_preset(v))
        self._line(529,312,889,312,fill=MUTED)
        for key,label,y,var in (("delay","要素间隔",350,e.delay),("verify","完成等待",396,e.verify)):
            self._text(529,y,label,17)
            if e.preset.get()=="custom":self.field(key,757,y-16,125)
            else:self._text(777,y,var.get()+" ms",20,RED)
        self._text(529,451,"自定义节律（毫秒） ›",16,RED)
        self.target("custom",(524,431,825,475),lambda:self.set_preset("custom"))

    def set_preset(self,value):
        self.editor.preset.set(value)
        self.editor.speed_changed()

    def shortcuts(self):
        from .gui_app import ACTION_LABELS,ACTION_ORDER
        e=self.editor
        self._text(529,232,"选择键位后，按下新的快捷键。",15)
        self._text(529,270,"研究操作",12,MUTED)
        self._text(769,270,"当前键位",12,MUTED)
        for i,key in enumerate(ACTION_ORDER):
            y=308+i*47
            self._text(529,y,ACTION_LABELS[key],16)
            label="请按键…" if e.capture_action==key else e.app._shortcut_display(e.shortcuts[key])
            self._text(769,y,label,16,RED)
            self._line(761,y+16,883,y+16,fill=MUTED)
            self.target(key,(754,y-20,890,y+20),lambda k=key:e.capture(k))

    def connection(self):
        e=self.editor
        self.diamond(540,233,not e.pid.get())
        self._text(559,233,"自动检测世界",21,RED)
        self._text(559,275,"执行研究时自动寻找游戏进程。",15)
        self.target("auto",(529,212,889,290),lambda:e.pid.set(""))
        self._line(529,309,889,309,fill=MUTED)
        self._text(529,345,"选择游戏进程",17)
        self._text(810,345,"查询中…" if e.refreshing else "刷新列表",13,RED)
        if not e.refreshing:self.target("refresh",(797,325,891,365),e.refresh_processes)
        self.field("process",529,370,360)
        self._text(529,432,"手动指定 PID  ▾",15,RED)
        self.target("manual",(524,410,755,450),e.toggle_manual)
        if e.manual_open:self.field("pid",757,420,125)
        elif e.pid.get():self._text(529,466,"当前 PID："+e.pid.get(),13)

    def hit(self,event):
        x,y=(event.x-self.offset_x)/self.scale,(event.y-self.offset_y)/self.scale
        return next((key for key,(b,_) in self.targets.items() if b[0]<=x<=b[2] and b[1]<=y<=b[3]),None)

    def motion(self,event):
        key=self.hit(event)
        if key!=self.hover:
            self.hover=key
            self.canvas.configure(cursor="hand2" if key else "")
            self.draw()

    def leave(self,event):
        self.hover=None
        self.draw()

    def click(self,event):
        key=self.hit(event)
        self.canvas.focus_set()
        if key:
            self.focus=key
            self.targets[key][1]()
            self.draw()

    def move_focus(self,step,current=None):
        keys=list(self.targets)
        focus=current or self.focus
        index=keys.index(focus) if focus in keys else (-1 if step>0 else 0)
        self.focus=keys[(index+step)%len(keys)]
        if self.focus in self.fields:self.fields[self.focus].focus_set()
        else:self.canvas.focus_set()
        self.draw()
        return "break"

    def key(self,event):
        if self.editor.capture_action:return self.editor.capture_key(event)
        if event.keysym in ("Up","Down"):return self.move_focus(-1 if event.keysym=="Up" else 1)
        if event.keysym in ("Return","space") and self.focus in self.targets:
            self.targets[self.focus][1]()
            self.draw()
        return "break"
