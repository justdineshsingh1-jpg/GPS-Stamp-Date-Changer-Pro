import os
import sys
import io

# Fix PyInstaller --windowed NoneType stdout/stderr isatty issue
class SafeOutputWriter:
    def write(self, text):
        pass
    def flush(self):
        pass
    def isatty(self):
        return False

if sys.stdout is None or not hasattr(sys.stdout, 'isatty'):
    sys.stdout = SafeOutputWriter()
if sys.stderr is None or not hasattr(sys.stderr, 'isatty'):
    sys.stderr = SafeOutputWriter()

import time
import socket
import threading
import subprocess
import uvicorn

# Ensure project root is in sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app import app


def find_free_port(start_port: int = 8000) -> int:
    """Finds an available TCP port starting from start_port."""
    port = start_port
    while port < 65535:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('127.0.0.1', port))
                return port
            except OSError:
                port += 1
    return 8000


def wait_for_server(port: int, timeout: float = 10.0) -> bool:
    """Waits until the server is accepting HTTP connections."""
    start = time.time()
    while time.time() - start < timeout:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.connect(('127.0.0.1', port))
                return True
            except OSError:
                time.sleep(0.15)
    return False


def start_server_thread(port: int):
    """Starts Uvicorn server in a background daemon thread."""
    config = uvicorn.Config(
        app=app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
        log_config=None
    )
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    return server


def open_browser_app_mode(url: str):
    """
    Opens the URL in native application window mode using Microsoft Edge or Google Chrome
    (without browser address bar or tabs, looking like a native desktop app).
    """
    # 1. Check Microsoft Edge (pre-installed on all Windows 10/11)
    edge_paths = [
        os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe")
    ]
    for p in edge_paths:
        if os.path.exists(p):
            subprocess.Popen([p, f"--app={url}", "--window-size=1280,860"])
            return

    # 2. Check Google Chrome
    chrome_paths = [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")
    ]
    for p in chrome_paths:
        if os.path.exists(p):
            subprocess.Popen([p, f"--app={url}", "--window-size=1280,860"])
            return

    # 3. Fallback to default browser
    import webbrowser
    webbrowser.open(url)


class DesktopBridge:
    def __init__(self, port: int):
        self.port = port
        self.window = None

    def save_file(self, rel_url: str, default_filename: str = ""):
        """
        Invoked from JavaScript when the user clicks any Download button.
        Opens native Windows Save File dialog, streams the file directly to the chosen path,
        and highlights the saved file in Windows Explorer.
        """
        try:
            full_url = f"http://127.0.0.1:{self.port}{rel_url}" if rel_url.startswith("/") else rel_url
            
            save_path = None
            if self.window:
                import webview
                res = self.window.create_file_dialog(
                    webview.SAVE_DIALOG,
                    save_filename=default_filename or "downloaded_file"
                )
                if res:
                    save_path = res if isinstance(res, str) else res[0]
            
            if not save_path:
                return {"success": False, "cancelled": True}

            import requests
            with requests.get(full_url, stream=True, timeout=180) as r:
                r.raise_for_status()
                with open(save_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=131072):
                        f.write(chunk)

            try:
                subprocess.Popen(f'explorer /select,"{os.path.normpath(save_path)}"')
            except Exception:
                pass

            return {"success": True, "path": save_path}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def open_external(self, url: str = ""):
        import webbrowser
        target = url or f"http://127.0.0.1:{self.port}"
        webbrowser.open(target)
        return {"success": True}


def main():
    port = find_free_port(8000)
    print(f"Starting GPS Stamp Date Changer Pro engine on port {port}...")
    server = start_server_thread(port)

    # Wait for server readiness
    if not wait_for_server(port):
        print("Warning: Server initialization took longer than expected.")

    app_url = f"http://127.0.0.1:{port}"

    # Try pywebview for native window
    has_webview = False
    try:
        import webview
        has_webview = True
    except ImportError:
        has_webview = False

    if has_webview:
        try:
            print("Launching native desktop window...")
            webview.settings['ALLOW_DOWNLOADS'] = True
            bridge = DesktopBridge(port)
            window = webview.create_window(
                title="GPS Stamp Date Changer Pro",
                url=app_url,
                width=1280,
                height=860,
                min_size=(1024, 680),
                resizable=True,
                confirm_close=True,
                js_api=bridge
            )
            bridge.window = window
            webview.start(debug=False)
            sys.exit(0)
        except Exception as e:
            print(f"Native webview fallback triggered: {e}")

    # Fallback to standalone app-mode window
    print(f"Launching desktop application window at {app_url}...")
    open_browser_app_mode(app_url)

    # Keep main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Shutting down GPS Stamp Date Changer Pro...")


if __name__ == "__main__":
    main()
