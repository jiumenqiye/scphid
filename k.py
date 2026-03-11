import tkinter as tk
import serial
import struct
import glob
import time
import threading
import queue
import random

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
        
        self.canvas = tk.Canvas(self.root, width=int(REAL_W*DISPLAY_SCALE), 
                               height=int(REAL_H*DISPLAY_SCALE), bg="#1a1a1a")
        self.canvas.pack(pady=10)

        self.canvas.bind("<Button-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_motion)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)

        print(f"\n[SYS] 所有通道就绪，黑框内操作即可同步\n" + "-"*40)
        self.root.mainloop()

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
