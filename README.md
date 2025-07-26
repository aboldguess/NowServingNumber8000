# NowServingNumber8000

This repository contains a lightweight Python web application that lists running web services on a Raspberry Pi. By default the app runs on port 8000 and displays information such as port, uptime, CPU and memory usage for each detected service. Services listed are clickable so you can quickly open them in a new tab. For Python-based services the table will also show the name of the script being executed rather than just `python`.

## Setup

1. Create and activate a virtual environment (optional but recommended):
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Start the server (optionally specify a custom port using `--port`):
   ```bash
   python app.py --port 8001
   ```
4. Visit `http://<your-ip>:<port>` in your browser (replace `<port>` with the number chosen, default is 8000).

The application attempts to determine if ports are forwarded to be accessible externally by making a connection to the device's public IP. This may not always be reliable depending on your network setup.
