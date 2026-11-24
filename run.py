import os
import sys
import argparse
import socket
import time
import subprocess

# Add project root directory to sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

def ensure_port_available(port: int, host: str = "127.0.0.1") -> bool:
    """
    Checks if a port is already in use.
    If occupied, automatically frees the port by terminating lingering processes
    so uvicorn can bind cleanly without [Errno 10048].
    """
    # 1. Quick test if port is already free
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
        sock.close()
        return True
    except OSError:
        pass  # Port in use

    print(f"[Port Guard] Port {port} is occupied. Attempting to terminate lingering process...")
    try:
        if sys.platform == "win32":
            # Query netstat for LISTENING process on this port
            cmd = f'netstat -ano | findstr LISTENING | findstr :{port}'
            proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            pids = set()
            for line in proc.stdout.strip().splitlines():
                parts = line.split()
                if len(parts) >= 5 and f":{port}" in parts[1]:
                    pid = parts[-1]
                    if pid != "0" and int(pid) != os.getpid():
                        pids.add(pid)

            for pid in pids:
                print(f"[Port Guard] Terminating lingering process PID {pid} on port {port}...")
                subprocess.run(f"taskkill /F /PID {pid}", shell=True, capture_output=True)
            time.sleep(0.6)
        else:
            subprocess.run(f"fuser -k {port}/tcp", shell=True, capture_output=True)
            time.sleep(0.6)

        # Verify port is now free
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind((host, port))
        sock.close()
        print(f"[Port Guard] Port {port} successfully freed.")
        return True
    except Exception as e:
        print(f"[Port Guard] Warning: Could not cleanly free port {port}: {e}")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run QueryNova AI Server")
    parser.add_argument("--port", type=int, default=8002, help="Port to run server on")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host to run server on")
    args = parser.parse_args()

    # Automatically free port if lingering instance exists
    ensure_port_available(args.port, args.host)

    import config
    config.PORT = args.port
    config.HOST = args.host

    from server import app
    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, reload=False)
