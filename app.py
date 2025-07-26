import datetime
import socket
import time
from typing import List, Dict
import os
import importlib.util

import psutil
import requests
from flask import Flask, render_template_string, request
import argparse  # used to parse command line options like --port

app = Flask(__name__)

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
            <th>Path</th>
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
            <td>{{ svc.path }}</td>
        </tr>
        {% endfor %}
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


def resolve_module_to_path(module_name: str) -> str:
    """Return the absolute file path for a Python module if possible."""
    try:
        spec = importlib.util.find_spec(module_name)
        if spec and spec.origin:
            return os.path.abspath(spec.origin)
    except Exception:
        pass
    return ""


def get_process_path(proc: psutil.Process) -> str:
    """Return a representative path for the running application.

    The function tries to determine a meaningful path for a process. For
    Python and Node applications the script path is returned when
    possible. For other processes the path to the executable is used as a
    fallback. If detection fails an empty string is returned.
    """
    try:
        cmdline = proc.cmdline()
        if not cmdline:
            return proc.exe()

        name = proc.name().lower()

        # Handle Python interpreters specially so we show the running
        # script rather than the interpreter executable.
        if name.startswith("python") and len(cmdline) > 1:
            arg = cmdline[1]
            if arg == "-m" and len(cmdline) > 2:
                # Attempt to resolve module names to their file path.
                module_path = resolve_module_to_path(cmdline[2])
                return module_path or cmdline[2]
            if os.path.isfile(arg):
                return os.path.abspath(arg)

        # Node.js typically has the script as the first argument after
        # the node executable.
        if name == "node" and len(cmdline) > 1 and os.path.isfile(cmdline[1]):
            return os.path.abspath(cmdline[1])

        # For other processes scan the command line for a readable file.
        for arg in cmdline[1:]:
            if os.path.isfile(arg):
                return os.path.abspath(arg)

        return proc.exe()
    except (psutil.Error, FileNotFoundError, IndexError):
        # As a last resort try the process' current working directory.
        try:
            return proc.cwd()
        except Exception:
            return ""


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
            # Determine the full path to the running executable or script.
            path = get_process_path(proc)
            forwarded = False
            if public_ip:
                forwarded = check_port_forwarding(public_ip, port)
            services.append({
                "name": name,
                "port": port,
                "protocol": protocol,
                "uptime": uptime,
                "cpu": cpu,
                "mem": mem,
                "forwarded": forwarded,
                "path": path,
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            # The process may have finished or we don't have permission.
            continue

    # Sort services by port for consistent ordering.
    services.sort(key=lambda s: s["port"])
    return services


@app.route("/")
def index():
    host = request.host.split(":")[0]
    services = list_services()
    return render_template_string(HTML_TEMPLATE, services=services, host=host)


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
    args = parser.parse_args()

    # Run the web server accessible on all network interfaces using the
    # specified port. Defaults to 8000 when no --port argument is provided.
    app.run(host="0.0.0.0", port=args.port)
