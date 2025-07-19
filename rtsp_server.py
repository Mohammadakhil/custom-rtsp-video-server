import socket
import struct
import cv2
import time
import threading
import sys

# --- Configuration ---
# UDP port for RTP video streaming. This is where the actual video data goes.
# Ensure this port is open in your firewall for UDP traffic.
RTP_PORT = 5004

# TCP port for RTSP control. This is where clients send commands (PLAY, TEARDOWN).
# Ensure this port is open in your firewall for TCP traffic.
RTSP_PORT = 554

# Video source:
# 0 for the default webcam.
# You can try 1, 2, etc., if you have multiple webcams.
# Or provide a path to a video file (e.g., 'video.mp4').
VIDEO_SOURCE = 0

# Maximum size for UDP packets. This is important to avoid fragmentation.
# Standard Ethernet MTU is 1500 bytes; subtracting IP/UDP headers leaves ~1472.
# We use 1400 to be safe and leave room for RTP header.
MAX_PACKET_SIZE = 1400

# JPEG compression quality (0-100). Higher quality means larger frames/packets.
JPEG_QUALITY = 80

# --- Global Flags and Resources for Control ---
# Flag to control the RTP streaming thread. Set to False to stop streaming.
streaming_active = False
# Reference to the RTP streaming thread.
rtp_thread = None
# Sockets for RTSP server and client connections.
rtsp_server_socket = None
rtsp_client_socket = None
rtsp_client_address = None
rtsp_server_thread = None # Reference to the RTSP listening thread

# --- RTP Packet Structure (Simplified) ---
RTP_HEADER_SIZE = 12

def create_rtp_header(sequence_number, timestamp, ssrc):
    """
    Constructs a simplified RTP header as bytes.
    """
    version_padding_extension_csrc = 0x80
    payload_type = 26
    marker_payload_type = payload_type
    header = struct.pack(
        "!BBHII",
        version_padding_extension_csrc,
        marker_payload_type,
        sequence_number,
        timestamp,
        ssrc
    )
    return header

def rtp_stream_video():
    """
    Captures video frames, encodes them, packetizes them into RTP, and sends them over UDP.
    This function runs in a separate thread when streaming is active.
    """
    global streaming_active

    print(f"[RTP Stream] Attempting to open video source {VIDEO_SOURCE}...")
    cap = cv2.VideoCapture(VIDEO_SOURCE)
    if not cap.isOpened():
        print(f"[RTP Stream] Error: Could not open video source {VIDEO_SOURCE}.")
        print("[RTP Stream] Please check if a webcam is connected, if it's in use by another application, or if the video file path is correct.")
        streaming_active = False
        return # Exit the streaming thread gracefully

    rtp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print(f"[RTP Stream] RTP streaming thread started. Sending on UDP port {RTP_PORT}...")

    sequence_number = 0
    ssrc = 0x12345678
    start_time = time.time()

    while streaming_active:
        ret, frame = cap.read()
        if not ret:
            print("[RTP Stream] Error: Could not read frame or end of video stream reached. Stopping RTP stream.")
            streaming_active = False
            break

        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY]
        _, encoded_frame = cv2.imencode('.jpg', frame, encode_param)
        jpeg_data = encoded_frame.tobytes()

        timestamp = int((time.time() - start_time) * 90000)

        offset = 0
        while offset < len(jpeg_data):
            # Corrected payload_size calculation: MAX_PACKET_SIZE minus header size
            payload_size = min(len(jpeg_data) - offset, MAX_PACKET_SIZE - RTP_HEADER_SIZE)
            if payload_size <= 0:
                break

            header = create_rtp_header(sequence_number, timestamp, ssrc)
            rtp_packet = header + jpeg_data[offset : offset + payload_size]

            try:
                rtp_socket.sendto(rtp_packet, ('127.0.0.1', RTP_PORT))
            except Exception as e:
                print(f"[RTP Stream] Error sending RTP packet: {e}")
                streaming_active = False
                break

            offset += payload_size
            sequence_number += 1
            if sequence_number > 65535:
                sequence_number = 0
            time.sleep(0.001)

    print("[RTP Stream] RTP streaming thread stopped.")
    cap.release()
    rtp_socket.close()

def handle_rtsp_client(client_socket, client_address):
    """
    Handles a single RTSP client connection.
    This is a very basic, simplified RTSP server implementation, not a full RFC-compliant one.
    It primarily responds to SETUP, PLAY, and TEARDOWN commands.
    """
    global streaming_active, rtp_thread, rtsp_client_socket, rtsp_client_address

    print(f"[RTSP Control] Accepted connection from {client_address}")
    rtsp_client_socket = client_socket
    rtsp_client_address = client_address

    try:
        while True:
            data = client_socket.recv(1024).decode('utf-8')
            if not data:
                print(f"[RTSP Control] Client {client_address} disconnected.")
                break

            print(f"[RTSP Control] Received from {client_address}:\n---BEGIN RTSP COMMAND---\n{data.strip()}\n---END RTSP COMMAND---")

            response = ""
            cseq = "1"
            lines = data.split('\r\n')
            for line in lines:
                if line.startswith("CSeq:"):
                    cseq = line.split(":")[1].strip()
                    break

            if "SETUP" in data:
                response = (
                    f"RTSP/1.0 200 OK\r\n"
                    f"CSeq: {cseq}\r\n"
                    f"Transport: RTP/AVP;unicast;client_port={RTP_PORT}-{RTP_PORT+1}\r\n"
                    f"Session: 12345678\r\n\r\n"
                )
                print(f"[RTSP Control] Sending SETUP response to {client_address}")
                client_socket.sendall(response.encode('utf-8'))

            elif "PLAY" in data:
                if not streaming_active:
                    print("[RTSP Control] PLAY command received. Starting RTP stream thread...")
                    global rtp_thread # Ensure global reference is used
                    streaming_active = True
                    rtp_thread = threading.Thread(target=rtp_stream_video)
                    rtp_thread.daemon = True
                    rtp_thread.start()
                else:
                    print("[RTSP Control] PLAY command received, but RTP stream is already active.")

                response = (
                    f"RTSP/1.0 200 OK\r\n"
                    f"CSeq: {cseq}\r\n"
                    f"Session: 12345678\r\n\r\n"
                )
                print(f"[RTSP Control] Sending PLAY response to {client_address}")
                client_socket.sendall(response.encode('utf-8'))

            elif "TEARDOWN" in data:
                print("[RTSP Control] TEARDOWN command received. Stopping RTP stream...")
                streaming_active = False
                if rtp_thread and rtp_thread.is_alive():
                    print("[RTSP Control] Waiting for RTP streaming thread to finish...")
                    rtp_thread.join(timeout=5)
                    if rtp_thread.is_alive():
                        print("[RTSP Control] Warning: RTP thread did not terminate gracefully within timeout.")
                response = (
                    f"RTSP/1.0 200 OK\r\n"
                    f"CSeq: {cseq}\r\n\r\n"
                )
                print(f"[RTSP Control] Sending TEARDOWN response to {client_address}")
                client_socket.sendall(response.encode('utf-8'))
                break

            elif "DESCRIBE" in data:
                payload_type_jpeg = 26
                sdp_payload = (
                    "v=0\r\n"
                    f"o=- 0 0 IN IP4 127.0.0.1\r\n"
                    "s=RTSP Stream\r\n"
                    "t=0 0\r\n"
                    f"a=control:rtsp://127.0.0.1:{RTSP_PORT}/stream\r\n"
                    f"m=video 0 RTP/AVP {payload_type_jpeg}\r\n"
                    f"a=rtpmap:{payload_type_jpeg} JPEG/90000\r\n"
                    f"a=control:streamid=0\r\n"
                )

                response_headers = (
                    f"RTSP/1.0 200 OK\r\n"
                    f"CSeq: {cseq}\r\n"
                    f"Content-Type: application/sdp\r\n"
                    f"Content-Length: {len(sdp_payload)}\r\n"
                    f"\r\n"
                )
                full_response = response_headers + sdp_payload
                print(f"[RTSP Control] Sending DESCRIBE response with SDP to {client_address}:\n{full_response.strip()}")
                client_socket.sendall(full_response.encode('utf-8'))

            elif "OPTIONS" in data:
                response = (
                    f"RTSP/1.0 200 OK\r\n"
                    f"CSeq: {cseq}\r\n"
                    f"Public: DESCRIBE, SETUP, TEARDOWN, PLAY, PAUSE, OPTIONS\r\n\r\n"
                )
                print(f"[RTSP Control] Sending OPTIONS response to {client_address}")
                client_socket.sendall(response.encode('utf-8'))

            else:
                print(f"[RTSP Control] Unknown command received: {data.strip()}")
                response = (
                    f"RTSP/1.0 400 Bad Request\r\n"
                    f"CSeq: {cseq}\r\n\r\n"
                )
                client_socket.sendall(response.encode('utf-8'))

    except ConnectionResetError:
        print(f"[RTSP Control] Client {client_address} forcibly closed the connection.")
    except Exception as e:
        print(f"[RTSP Control] Error handling client {client_address}: {e}")
    finally:
        print(f"[RTSP Control] Closing client socket for {client_address}")
        client_socket.close()
        rtsp_client_socket = None
        rtsp_client_address = None

def start_rtsp_server_thread():
    """
    Initializes and starts the RTSP control server (TCP listener).
    This function runs in a separate thread.
    """
    global rtsp_server_socket, rtsp_server_thread # Declare global for modification
    try:
        rtsp_server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        rtsp_server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        rtsp_server_socket.bind(('0.0.0.0', RTSP_PORT))
        rtsp_server_socket.listen(1)
        print(f"[RTSP Control] RTSP control server listening on TCP port {RTSP_PORT}...")

        while True:
            print("[RTSP Control] Waiting for client connection...")
            conn, addr = rtsp_server_socket.accept()
            client_handler = threading.Thread(target=handle_rtsp_client, args=(conn, addr))
            client_handler.daemon = True
            client_handler.start()

    except OSError as e:
        if e.errno == 98:
            print(f"[RTSP Control] Error: Port {RTSP_PORT} is already in use. Please close other applications or choose a different port.")
        else:
            print(f"[RTSP Control] Error starting RTSP server: {e}")
        # No sys.exit(1) here as it would kill the main thread directly from a child thread
        # Instead, rely on main thread's cleanup or let it continue if possible.
    except Exception as e:
        print(f"[RTSP Control] An unexpected error occurred in RTSP server: {e}")
    finally:
        if rtsp_server_socket:
            print("[RTSP Control] RTSP server socket closing.")
            rtsp_server_socket.close()
            rtsp_server_socket = None # Clear reference

def stop_server_cleanup():
    """
    Performs graceful shutdown of all server components.
    """
    global streaming_active, rtp_thread, rtsp_server_socket, rtsp_client_socket, rtsp_server_thread

    print("\n--- Server shutdown initiated ---")
    streaming_active = False # Signal RTP thread to stop

    # Close RTSP server socket to break accept() loop
    if rtsp_server_socket:
        try:
            print("[Main] Shutting down RTSP server listening socket...")
            rtsp_server_socket.shutdown(socket.SHUT_RDWR)
            rtsp_server_socket.close()
        except OSError as e:
            print(f"[Main] Error closing RTSP server listening socket: {e}")
        rtsp_server_socket = None

    # Wait for RTSP server thread to finish
    if rtsp_server_thread and rtsp_server_thread.is_alive():
        print("[Main] Waiting for RTSP server thread to finish...")
        rtsp_server_thread.join(timeout=5)
        if rtsp_server_thread.is_alive():
            print("[Main] Warning: RTSP server thread did not terminate gracefully.")

    # Wait for RTP thread to finish
    if rtp_thread and rtp_thread.is_alive():
        print("[Main] Waiting for RTP streaming thread to finish...")
        rtp_thread.join(timeout=5)
        if rtp_thread.is_alive():
            print("[Main] Warning: RTP streaming thread did not terminate gracefully.")

    # Close any active RTSP client socket
    if rtsp_client_socket:
        try:
            print("[Main] Shutting down RTSP client socket...")
            rtsp_client_socket.shutdown(socket.SHUT_RDWR)
            rtsp_client_socket.close()
        except OSError as e:
            print(f"[Main] Error closing RTSP client socket: {e}")
        rtsp_client_socket = None

    print("--- Server stopped successfully ---")


if __name__ == "__main__":
    print("--- Starting RTP/RTSP Video Streaming Server ---")
    print("Hello! Attempting to start server components...")

    # Start the RTSP control server in a separate thread.
    rtsp_server_thread = threading.Thread(target=start_rtsp_server_thread)
    rtsp_server_thread.daemon = True
    rtsp_server_thread.start()

    print("\nServer is initialized.")
    print(f"RTSP Control Port (TCP): {RTSP_PORT}")
    print(f"RTP Streaming Port (UDP): {RTP_PORT}")
    print("\nServer is ready. You can now connect with an RTSP client.")
    print(f"Example client command (using ffplay): ffplay rtsp://127.0.0.1:{RTSP_PORT}/stream")
    print("Or use a custom client that sends 'PLAY' and 'TEARDOWN' commands to TCP port 554.")
    print("\nPress Ctrl+C to stop the server.")

    try:
        # The main thread will simply sleep to keep the program alive while
        # the background threads (RTSP server and RTP streamer) do their work.
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop_server_cleanup() # Call cleanup function on Ctrl+C
    except Exception as e:
        print(f"[Main] An unexpected error occurred in main thread: {e}")
        stop_server_cleanup() # Attempt cleanup on other exceptions too

