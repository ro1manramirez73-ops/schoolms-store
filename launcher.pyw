import os, sys, subprocess, threading, time, webbrowser, socket, urllib.parse
import tkinter as tk

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_PY  = os.path.join(BASE_DIR, '.venv', 'Scripts', 'pythonw.exe')
if not os.path.exists(VENV_PY):
    VENV_PY = os.path.join(BASE_DIR, '.venv', 'Scripts', 'python.exe')
if not os.path.exists(VENV_PY):
    VENV_PY = sys.executable

ICO  = os.path.join(BASE_DIR, 'files', 'static', 'icons', 'schoolms.ico')
PORT = 5000
URL  = f'http://127.0.0.1:{PORT}/home'
proc = None

def _get_lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


def _start():
    global proc
    try:
        proc = subprocess.Popen(
            [VENV_PY, os.path.join(BASE_DIR, 'wsgi.py')],
            cwd=BASE_DIR,
            env=os.environ.copy(),
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception as e:
        root.after(0, lambda: _set_error(str(e)))
        return

    import urllib.request
    for _ in range(40):
        try:
            urllib.request.urlopen(f'http://127.0.0.1:{PORT}/home', timeout=1)
            break
        except Exception:
            if proc.poll() is not None:
                root.after(0, lambda: _set_error('Server stopped unexpectedly.'))
                return
            time.sleep(1)

    root.after(0, _on_ready)


def _on_ready():
    lan_ip = _get_lan_ip()
    status_var.set(f'Running  •  http://127.0.0.1:{PORT}')
    network_var.set(f'Network:  http://{lan_ip}:{PORT}')
    indicator.config(fg='#22c55e')
    network_label.config(fg='#16a34a')
    open_btn.config(state='normal')
    email_btn.config(state='normal')
    webbrowser.open(URL)


def _set_error(msg):
    status_var.set(f'Error: {msg}')
    indicator.config(fg='#ef4444')


def _quit():
    if proc and proc.poll() is None:
        proc.terminate()
    root.destroy()


root = tk.Tk()
root.title('Blairwood Academy')
root.geometry('420x210')
root.resizable(False, False)
root.configure(bg='#f1f5f9')

if os.path.exists(ICO):
    try:
        root.iconbitmap(ICO)
    except Exception:
        pass

tk.Label(root, text='Blairwood Academy', font=('Segoe UI', 13, 'bold'),
         bg='#f1f5f9', fg='#0f172a').pack(pady=(20, 0))
tk.Label(root, text='Nassau, Bahamas', font=('Segoe UI', 8),
         bg='#f1f5f9', fg='#94a3b8').pack()

row = tk.Frame(root, bg='#f1f5f9')
row.pack(pady=(8, 2))
indicator = tk.Label(row, text='●', font=('Segoe UI', 10),
                     bg='#f1f5f9', fg='#f59e0b')
indicator.pack(side='left', padx=(0, 5))
status_var = tk.StringVar(value='Starting server…')
tk.Label(row, textvariable=status_var, font=('Segoe UI', 9),
         bg='#f1f5f9', fg='#64748b').pack(side='left')

network_var = tk.StringVar(value='')
network_label = tk.Label(root, textvariable=network_var, font=('Segoe UI', 9, 'underline'),
                         bg='#f1f5f9', fg='#94a3b8', cursor='hand2')
network_label.pack()
network_label.bind('<Button-1>', lambda e: webbrowser.open(network_var.get().replace('Network:  ', '')) if network_var.get() else None)

btn_frame = tk.Frame(root, bg='#f1f5f9')
btn_frame.pack(pady=10)

open_btn = tk.Button(
    btn_frame, text='Open Browser', state='disabled',
    command=lambda: webbrowser.open(URL),
    bg='#4f46e5', fg='white', font=('Segoe UI', 9, 'bold'),
    relief='flat', padx=14, pady=6, cursor='hand2',
    activebackground='#3730a3', activeforeground='white',
)
open_btn.pack(side='left', padx=5)

def _email_link():
    lan_url = network_var.get().replace('Network:  ', '')
    if not lan_url:
        return
    subject = urllib.parse.quote('Blairwood Academy – School System Link')
    body    = urllib.parse.quote(f'Access the school system from any device on the network:\n\n{lan_url}\n\nOpen the link in your browser to log in.')
    webbrowser.open(f'mailto:?subject={subject}&body={body}')

email_btn = tk.Button(
    btn_frame, text='Email Link', state='disabled',
    command=_email_link,
    bg='#0ea5e9', fg='white', font=('Segoe UI', 9, 'bold'),
    relief='flat', padx=14, pady=6, cursor='hand2',
    activebackground='#0284c7', activeforeground='white',
)
email_btn.pack(side='left', padx=5)

tk.Button(
    btn_frame, text='Stop & Close', command=_quit,
    bg='#ef4444', fg='white', font=('Segoe UI', 9, 'bold'),
    relief='flat', padx=14, pady=6, cursor='hand2',
    activebackground='#dc2626', activeforeground='white',
).pack(side='left', padx=5)

root.protocol('WM_DELETE_WINDOW', _quit)
threading.Thread(target=_start, daemon=True).start()
root.mainloop()
