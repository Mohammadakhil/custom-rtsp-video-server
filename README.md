## Command-Line RTP/RTSP Video Streaming Server

## DESC 
This project implements a basic RTP/RTSP video streaming server in Python, designed to run from the command line without a graphical user interface. 
It captures video frames using OpenCV, packetizes them into a simplified RTP format, and streams them over UDP. 
A basic TCP-based control server handles RTSP commands like OPTIONS, DESCRIBE, SETUP, PLAY, and TEARDOWN.
This server is primarily for educational purposes to demonstrate fundamental concepts of multimedia protocol implementation and network streaming.

## Features
Video Capture: Uses OpenCV to capture video from a webcam (or a specified video file).
RTP Streaming: Sends video frames as JPEG payloads over UDP using a simplified RTP header.
Basic RTSP Control: Responds to essential RTSP commands (OPTIONS, DESCRIBE, SETUP, PLAY, TEARDOWN) over TCP.
Multi-threaded: Separates RTSP control and RTP streaming into different threads for responsiveness.

## Command-Line Interface: All interactions and logs are handled directly in the terminal.

## Tech Stack
Python 3.x
socket: For network communication (TCP and UDP).
struct: For packing/unpacking binary data (RTP headers).
cv2 (OpenCV-Python): For video capture and JPEG encoding.
threading: For concurrent execution of server components.

## Setup and Installation
Clone the Repository (or download the files):

## git clone <your-repo-url>
cd REPO <your-repo-directory>

## Having Trouble? (Troubleshooting)
No Webcam? "Error: Could not open video source 0." -> Make sure your webcam isn't busy, or try VIDEO_SOURCE = 1 (or 2) in the code.
ffplay not found? "The term 'ffplay' is not recognized..." -> You need to install FFmpeg (it includes ffplay).
Video not showing, just blinking/errors?
Firewall again! Double-check that UDP Port 5004 is definitely open. This is the #1 reason.
Look at your server's terminal: Does it say [RTP Stream] RTP streaming thread started...? If so, the server is sending, and the problem is receiving.
