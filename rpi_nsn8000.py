import datetime
import socket
import time
from typing import List, Dict
import os
import psutil
import requests
from flask import Flask, render_template_string, request, redirect, url_for
import subprocess
import argparse  # used to parse command line options like --port or --production
from waitress import serve  # production-ready WSGI server

app = Flask(__name__)

# Base URL used to generate external service links. The port number for each
# service will be appended to this address when building the table.
EXTERNAL_IP = "http://193.237.136.211"

# HTML template used to display the service table. Jinja2 syntax is used to
# substitute values. Each service row includes a link to the running service.
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Running Services</title>
    <style>
        table { border-collapse: collapse; width: 100%; }
        th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
        th { background-color: #f2f2f2; }
    </style>
</head>
<body>
    <h1>Running Services</h1>
    <table>
        <tr>
            <th>Name</th>
            <th>Port</th>
            <th>Protocol</th>
            <th>Uptime</th>
            <th>CPU %</th>
            <th>RAM (MB)</th>
            <th>Forwarded</th>
            <th>External</th>
            <th>Stop</th>
            <th>Restart</th>
        </tr>
        {% for svc in services %}
        <tr>
            <td><a href="http://{{ host }}:{{ svc.port }}" target="_blank">{{ svc.name }}</a></td>
            <td>{{ svc.port }}</td>
            <td>{{ svc.protocol }}</td>
            <td>{{ svc.uptime }}</td>
            <td>{{ '{:.1f}'.format(svc.cpu) }}</td>
            <td>{{ '{:.1f}'.format(svc.mem) }}</td>
            <td>{{ 'Yes' if svc.forwarded else 'No' }}</td>
            <td><a href="{{ external_ip }}:{{ svc.port }}" target="_blank">External</a></td>
            <td>
                <form method="post" action="/stop/{{ svc.pid }}">
                    <button type="submit">Stop</button>
                </form>
            </td>
            <td>
                <form method="post" action="/restart/{{ svc.pid }}">
                    <input type="text" name="cmd" placeholder="restart command">
                    <button type="submit">Restart</button>
                </form>
            </td>
        </tr>
        {% endfor %}
        <tr>
            <td colspan="10">
                <form method="post" action="/add">
                    <input type="text" name="path" placeholder="path to new service">
                    <button type="submit">Add Service</button>
                </form>
            </td>
        </tr>
    </table>
</body>
</html>
"""


def format_uptime(seconds: float) -> str:
    """Convert seconds into a human readable H:M:S string."""
    return str(datetime.timedelta(seconds=int(seconds)))


def check_port_forwarding(public_ip: str, port: int, timeout: float = 1.0) -> bool:
    """Attempt to connect to the given public IP and port to test forwarding."""
    try:
        with socket.create_connection((public_ip, port), timeout=timeout):
            return True
    except Exception:
        return False


def get_public_ip() -> str:
    """Get the device's public IP using an external service."""
    try:
        response = requests.get("https://api.ipify.org", timeout=2)
        response.raise_for_status()
        return response.text.strip()
    except Exception:
        return ""


def get_app_name(proc: psutil.Process) -> str:
    """Return a friendlier name for a process.

    For Python processes this attempts to show the script or module being
    executed instead of the python interpreter name.
    """
    name = proc.name()
    try:
        cmdline = proc.cmdline()
        # cmdline[0] is typically the executable path. When the process is
        # a python interpreter the actual script follows as the next arg.
        if cmdline and name.lower().startswith("python"):
            if len(cmdline) > 1:
                if cmdline[1] == "-m" and len(cmdline) > 2:
                    return cmdline[2]
                return os.path.basename(cmdline[1])
    except (psutil.Error, IndexError):
        pass
    return name




def list_services() -> List[Dict]:
    """Gather information about running services that are listening on a port."""
    services = []
    seen_ports = set()
    public_ip = get_public_ip()

    # Iterate over all network connections looking for listeners.
    for conn in psutil.net_connections(kind="inet"):
        if conn.status != psutil.CONN_LISTEN:
            continue
        if not conn.laddr:
            continue
        port = conn.laddr.port
        # Avoid listing the same port multiple times.
        if port in seen_ports:
            continue
        seen_ports.add(port)

        pid = conn.pid
        if pid is None:
            continue
        try:
            proc = psutil.Process(pid)
            # Determine a human friendly name for the process. For Python
            # interpreters this will try to display the script that was run
            # instead of just the Python executable name.
            name = get_app_name(proc)
            create_time = proc.create_time()
            uptime = format_uptime(time.time() - create_time)
            cpu = proc.cpu_percent(interval=0.1)
            mem = proc.memory_info().rss / (1024 * 1024)
            protocol = "tcp" if conn.type == socket.SOCK_STREAM else "udp"
            forwarded = False
            if public_ip:
                forwarded = check_port_forwarding(public_ip, port)
            services.append({
                "pid": pid,
                "name": name,
                "port": port,
                "protocol": protocol,
                "uptime": uptime,
                "cpu": cpu,
                "mem": mem,
                "forwarded": forwarded,
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            # The process may have finished or we don't have permission.
            continue

    # Sort services by port for consistent ordering.
    services.sort(key=lambda s: s["port"])
    return services


@app.route("/stop/<int:pid>", methods=["POST"])
def stop_service(pid: int):
    """Terminate the process with the given PID."""
    try:
        # Use psutil to locate and terminate the target process
        proc = psutil.Process(pid)
        proc.terminate()
    except psutil.NoSuchProcess:
        pass
    return redirect(url_for("index"))


@app.route("/restart/<int:pid>", methods=["POST"])
def restart_service(pid: int):
    """Terminate a process and start it again using a user provided command."""
    cmd = request.form.get("cmd")
    try:
        # Stop the running process first
        proc = psutil.Process(pid)
        proc.terminate()
        proc.wait(timeout=5)
    except psutil.NoSuchProcess:
        pass
    if cmd:
        # Launch the new command in the background if provided
        subprocess.Popen(cmd, shell=True)
    return redirect(url_for("index"))


@app.route("/add", methods=["POST"])
def add_service():
    """Start a new service from a given path or command."""
    path = request.form.get("path")
    if path:
        # Launch the service using the provided path/command
        subprocess.Popen(path, shell=True)
    return redirect(url_for("index"))


@app.route("/")
def index():
    host = request.host.split(":")[0]
    services = list_services()
    return render_template_string(
        HTML_TEMPLATE,
        services=services,
        host=host,
        external_ip=EXTERNAL_IP,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run the service listing web server"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to run the server on (default: 8000)",
    )
    parser.add_argument(
        "--production",
        action="store_true",
        help="Run using the Waitress production server",
    )
    args = parser.parse_args()

    # When --production is specified, use Waitress for a robust deployment.
    # Otherwise fall back to Flask's built-in development server.
    if args.production:
        # Waitress serves the Flask app with better performance than the
        # built-in development server and is safe for production use.
        serve(app, host="0.0.0.0", port=args.port)
    else:
        # Flask development server is convenient for testing and debugging.
        app.run(host="0.0.0.0", port=args.port)
