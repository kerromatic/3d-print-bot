"""
Bambu Lab X1C MQTT integration.
Connects to the printer via MQTT over TLS to get real-time print status.
"""

import json
import ssl
import threading
import logging
import time

import paho.mqtt.client as mqtt

from config.settings import settings

logger = logging.getLogger(__name__)


class PrinterStatus:
    """Holds the current printer state from MQTT messages."""

    def __init__(self):
        self.gcode_state = "UNKNOWN"   # IDLE, RUNNING, PREPARE, PAUSE, FAILED, FINISH
        self.gcode_file = ""
        self.mc_percent = 0            # 0-100
        self.mc_remaining_time = 0     # minutes
        self.mc_print_stage = ""
        self.nozzle_temper = 0.0
        self.bed_temper = 0.0
        self.layer_num = 0
        self.total_layer_num = 0
        self.subtask_name = ""
        self._connected = False
        self._last_update = 0

    @property
    def is_printing(self) -> bool:
        return self.gcode_state in ("RUNNING", "PREPARE", "PAUSE")

    @property
    def is_idle(self) -> bool:
        return self.gcode_state in ("IDLE", "UNKNOWN", "FINISH", "FAILED")

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def print_name(self) -> str:
        name = self.subtask_name or self.gcode_file
        for suffix in (".3mf", ".gcode", ".gcode.3mf"):
            if name.lower().endswith(suffix):
                name = name[:-len(suffix)]
        return name or "Unknown"

    @property
    def remaining_str(self) -> str:
        mins = self.mc_remaining_time
        if mins <= 0:
            return ""
        hours = mins // 60
        m = mins % 60
        if hours > 0:
            return f"{hours}h {m}m"
        return f"{m}m"

    def summary(self) -> str:
        if not self._connected:
            return "Printer offline"
        if self.is_idle:
            return f"Printer idle ({self.gcode_state})"
        parts = [f"Printing: {self.print_name}"]
        parts.append(f"{self.mc_percent}% complete")
        if self.remaining_str:
            parts.append(f"{self.remaining_str} remaining")
        if self.layer_num and self.total_layer_num:
            parts.append(f"Layer {self.layer_num}/{self.total_layer_num}")
        return " | ".join(parts)

    def caption_for_snapshot(self) -> str:
        if not self._connected or self.is_idle:
            return "Live snapshot - Printer idle"
        lines = [f"<b>{self.print_name}</b>"]
        lines.append(f"{self.mc_percent}% complete")
        if self.remaining_str:
            lines.append(f"ETA: {self.remaining_str}")
        if self.layer_num and self.total_layer_num:
            lines.append(f"Layer {self.layer_num}/{self.total_layer_num}")
        return " | ".join(lines)


# Global printer status instance
printer_status = PrinterStatus()


def _on_connect(client, userdata, flags, reason_code, properties=None):
    serial = settings.PRINTER_SERIAL
    logger.info(f"MQTT connected to printer (rc={reason_code})")
    client.subscribe(f"device/{serial}/report")
    printer_status._connected = True


def _on_disconnect(client, userdata, flags, reason_code, properties=None):
    logger.warning(f"MQTT disconnected (rc={reason_code})")
    printer_status._connected = False


def _on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return

    if "print" not in payload:
        return

    data = payload["print"]
    ps = printer_status

    if "gcode_state" in data:
        ps.gcode_state = data["gcode_state"]
    if "gcode_file" in data:
        ps.gcode_file = data["gcode_file"]
    if "mc_percent" in data:
        ps.mc_percent = data["mc_percent"]
    if "mc_remaining_time" in data:
        ps.mc_remaining_time = data["mc_remaining_time"]
    if "mc_print_stage" in data:
        ps.mc_print_stage = str(data["mc_print_stage"])
    if "nozzle_temper" in data:
        ps.nozzle_temper = data["nozzle_temper"]
    if "bed_temper" in data:
        ps.bed_temper = data["bed_temper"]
    if "layer_num" in data:
        ps.layer_num = data["layer_num"]
    if "total_layer_num" in data:
        ps.total_layer_num = data["total_layer_num"]
    if "subtask_name" in data:
        ps.subtask_name = data["subtask_name"]

    ps._last_update = time.time()


def start_mqtt_listener():
    """Start the MQTT listener in a background thread."""
    if not settings.PRINTER_IP or not settings.PRINTER_SERIAL:
        logger.warning("MQTT not started: PRINTER_IP or PRINTER_SERIAL not set")
        return

    def _run():
        while True:
            try:
                client = mqtt.Client(
                    mqtt.CallbackAPIVersion.VERSION2,
                    client_id=None,
                    clean_session=True,
                    protocol=mqtt.MQTTv311,
                    transport="tcp",
                )
                client.username_pw_set("bblp", settings.PRINTER_ACCESS_CODE)
                client.tls_set(tls_version=ssl.PROTOCOL_TLS, cert_reqs=ssl.CERT_NONE)
                client.tls_insecure_set(True)

                client.on_connect = _on_connect
                client.on_disconnect = _on_disconnect
                client.on_message = _on_message

                logger.info(f"Connecting MQTT to {settings.PRINTER_IP}:8883...")
                client.connect(settings.PRINTER_IP, 8883, keepalive=60)
                client.loop_forever()
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"MQTT error: {e}, reconnecting in 10s...")
                printer_status._connected = False
                time.sleep(10)

    thread = threading.Thread(target=_run, daemon=True, name="mqtt-listener")
    thread.start()
    logger.info("MQTT listener thread started")

