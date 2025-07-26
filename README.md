# NowServingNumber8000

This repository contains a lightweight Python web application that lists running web services on a Raspberry Pi. The app runs on port 8000 and displays information such as port, uptime, CPU and memory usage for each detected service. Services listed are clickable so you can quickly open them in a new tab.

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
3. Start the server:
   ```bash
   python app.py
   ```
4. Visit `http://<your-ip>:8000` in your browser.

The application attempts to determine if ports are forwarded to be accessible externally by making a connection to the device's public IP. This may not always be reliable depending on your network setup.
