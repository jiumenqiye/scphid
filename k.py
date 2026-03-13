import tkinter as tk
import serial
import struct
import glob
import time
import threading
import queue
import random
import subprocess
from io import BytesIO

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = None
    ImageTk = None

# --- 核心配置 ---
BAUD_RATE = 2000000           
REAL_W, REAL_H = 1280, 2772   
DISPLAY_SCALE = 0.3           
DEVICE_DELAY_RANGE = (0.5, 1.0) 

class DeviceWorker(threading.Thread):
    def __init__(self, port, baud, device_index):
        super().__init__()
        self.port = port
        self.baud = baud
        self.device_index = device_index
        self.action_queue = queue.Queue() 
        self.daemon = True
        self.ser = None
        self._init_serial() # 初始连接

    def _init_serial(self):
        """完全重置物理链路，解决假死的核心函数"""
        try:
            if self.ser and self.ser.is_open:
                self.ser.close()
            
            # 增加 write_timeout，这是防止脚本被死锁设备拖垮的关键
            self.ser = serial.Serial(self.port, self.baud, timeout=0, write_timeout=0.05)
            
            # 物理层 Reset：强制 ESP32 重新枚举 USB
            self.ser.setDTR(False)
            time.sleep(0.1)
            self.ser.setDTR(True)
            
            # 必须死等：给 Android 系统 1.5 秒来识别这个“新插入”的触控板
            time.sleep(1.5)
            
            # 清空残留缓冲区
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
            
            print(f"[SYS] ✅ 设备 {self.port} 物理重置并激活成功")
            return True
        except Exception as e:
            print(f"[SYS] ❌ 设备 {self.port} 重置失败: {e}")
            return False

    def run(self):
        while True:
            # 阻塞等待新动作序列
            action_sequence, start_delay = self.action_queue.get()
            
            # 1. 阶梯延迟等待
            if start_delay > 0:
                time.sleep(start_delay)
            
            # 2. 动作回放
            print(f"[DEBUG] 手机端 [{self.port}] 准备回放轨迹 (序列长度: {len(action_sequence)})")
            
            success = True
            last_time = action_sequence[0][0]
            
            for timestamp, packet in action_sequence:
                interval = timestamp - last_time
                if interval > 0:
                    time.sleep(min(interval, 0.05)) 
                
                try:
                    if not self.ser or not self.ser.is_open:
                        raise serial.SerialException("Port not open")
                    
                    self.ser.write(packet)
                    self.ser.flush()
                except Exception as e:
                    print(f"[ERROR] 设备 {self.port} 链路假死: {e}，正在强制重启硬件...")
                    self._init_serial() # 发现坏死立刻重启物理层
                    success = False
                    break # 中断当前回放，保护后续指令
                
                last_time = timestamp
                
            if success:
                print(f"[INFO] 手机端 [{self.port}] 动作执行完毕 ✓")
            else:
                print(f"[WARN] 手机端 [{self.port}] 动作因假死被中断，硬件已重连")

class SmoothGroupApp:
    def __init__(self):
        self.workers = []
        self.current_action_data = [] 
        self.is_recording = False 
        
        print("\n[SYS] 启动工业级同步控制系统...")
        ports = sorted(list(set(glob.glob('/dev/ttyACM*') + glob.glob('/dev/ttyUSB*'))))
        
        for i, p in enumerate(ports):
            try:
                worker = DeviceWorker(p, BAUD_RATE, i)
                worker.start()
                self.workers.append(worker)
                print(f"[SYS] 已挂载端口: {p}")
            except Exception as e:
                print(f"[SYS] ⚠️ 跳过故障端口 {p}: {e}")

        if not self.workers:
            print("[SYS] ❌ 未发现任何有效 ESP32 设备，程序退出")
            exit()

        self.root = tk.Tk()
        self.root.title(f"同步控制中心 (稳定版) - {len(self.workers)}台")
        self.screen_running = True
        self.screen_image_ref = None
        self.screen_item_id = None
        self.screen_status_var = tk.StringVar(value="[投屏] 未启动")
        self.screen_device_id = self._get_first_adb_device()
        
        self.canvas = tk.Canvas(self.root, width=int(REAL_W*DISPLAY_SCALE), 
                               height=int(REAL_H*DISPLAY_SCALE), bg="#1a1a1a")
        self.canvas.pack(pady=10)

        tk.Label(self.root, textvariable=self.screen_status_var, fg="#39ff14", bg="#101010").pack(fill="x")

        self._start_screen_mirror()

        self.canvas.bind("<Button-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_motion)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        print(f"\n[SYS] 所有通道就绪，黑框内操作即可同步\n" + "-"*40)
        self.root.mainloop()

    def _get_first_adb_device(self):
        try:
            out = subprocess.check_output(["adb", "devices"], text=True, stderr=subprocess.STDOUT)
        except FileNotFoundError:
            self.screen_status_var.set("[投屏] adb 未安装，跳过投屏")
            return None
        except Exception as e:
            self.screen_status_var.set(f"[投屏] adb 检查失败: {e}")
            return None

        for line in out.splitlines()[1:]:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                return parts[0]

        self.screen_status_var.set("[投屏] 未发现在线 Android 设备")
        return None

    def _start_screen_mirror(self):
        if not self.screen_device_id:
            return
        if Image is None or ImageTk is None:
            self.screen_status_var.set("[投屏] 缺少 Pillow，无法显示画面")
            return

        self.screen_status_var.set(f"[投屏] 已连接设备: {self.screen_device_id}")
        threading.Thread(target=self._screen_loop, daemon=True).start()

    def _screen_loop(self):
        while self.screen_running:
            try:
                png_data = subprocess.check_output(
                    ["adb", "-s", self.screen_device_id, "exec-out", "screencap", "-p"],
                    stderr=subprocess.DEVNULL,
                    timeout=1.8,
                )
                image = Image.open(BytesIO(png_data)).convert("RGB")
                image = image.resize((int(REAL_W * DISPLAY_SCALE), int(REAL_H * DISPLAY_SCALE)))
                tk_img = ImageTk.PhotoImage(image)
                self.root.after(0, self._update_canvas_bg, tk_img)
            except Exception:
                self.root.after(0, self.screen_status_var.set, "[投屏] 抓帧失败，正在重试...")
                time.sleep(1)
                continue
            time.sleep(0.35)

    def _update_canvas_bg(self, tk_img):
        self.screen_image_ref = tk_img
        if self.screen_item_id is None:
            self.screen_item_id = self.canvas.create_image(0, 0, anchor="nw", image=tk_img)
            self.canvas.tag_lower(self.screen_item_id)
        else:
            self.canvas.itemconfig(self.screen_item_id, image=tk_img)
        self.screen_status_var.set(f"[投屏] 正在显示设备: {self.screen_device_id}")

    def on_close(self):
        self.screen_running = False
        self.root.destroy()

    def _pack_data(self, action_type, x, y):
        rx = max(0, min(REAL_W, int(x / DISPLAY_SCALE)))
        ry = max(0, min(REAL_H, int(y / DISPLAY_SCALE)))
        sx = int(rx * 0x7ffffffe / REAL_W)
        sy = int(ry * 0x7ffffffe / REAL_H)
        return struct.pack("B", 0xF4) + struct.pack("<BBIIB", action_type, 0x01, sx, sy, 0x01)

    def on_press(self, event):
        self.is_recording = True
        self.current_action_data = []
        packet = self._pack_data(0x01, event.x, event.y)
        self.current_action_data.append((time.time(), packet))

    def on_motion(self, event):
        if not self.is_recording: return
        packet = self._pack_data(0x01, event.x, event.y)
        self.current_action_data.append((time.time(), packet))

    def on_release(self, event):
        if not self.is_recording: return
        self.is_recording = False
        
        packet = self._pack_data(0x00, event.x, event.y)
        self.current_action_data.append((time.time(), packet))
        
        full_action = list(self.current_action_data)
        for i, worker in enumerate(self.workers):
            delay = 0 if i == 0 else i * random.uniform(*DEVICE_DELAY_RANGE)
            worker.action_queue.put((full_action, delay))

if __name__ == "__main__":
    SmoothGroupApp()
