#!/usr/bin/env python3
"""
Unix domain socket echo server with clean shutdown handling.
Creates a socket at /tmp/echo_socket and echoes all received data.
"""

import os
import socket
import signal
import sys
import tempfile
import threading
import json
from dotenv import load_dotenv
from pathlib import Path
from methods import METHODS

class UnixSocketServer:
    def __init__(self, socket_path=None):
        if socket_path is None:
            # Use a constant path in temp directory
            self.socket_path = os.path.join(tempfile.gettempdir(), 'waybar_modules')
        else:
            self.socket_path = socket_path
        
        self.server_socket = None
        self.running = False
        self.client_threads = []
        
    def setup_signal_handlers(self):
        """Set up signal handlers for clean shutdown."""
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
        
    def _signal_handler(self, signum, frame):
        """Handle termination signals."""
        print(f"\nReceived signal {signum}. Shutting down gracefully...")
        self.shutdown()
        
    def handle_client(self, client_socket, client_addr):
        """Handle individual client connections."""
        print(f"Client connected: {client_addr}")
        
        try:
            while self.running:
                try:
                    # Set a timeout so we can check if server is still running
                    client_socket.settimeout(1.0)
                    data = client_socket.recv(4096)
                    
                    if not data:
                        print(f"Client {client_addr} disconnected")
                        break
                    
                    # Decode data as json, on error disconnect the client
                    try:
                        json_data = json.loads(data.decode('utf-8'))

                        # Handle the request
                        response = self.handle_request(json_data)
                        json_data = json.dumps(response)
                        client_socket.sendall(json_data.encode('utf-8'))
                    except Exception as e:
                        print(f"Exception while handling client data from {client_addr}: {e}")
                        break
                    
                except socket.timeout:
                    # Timeout is expected, continue loop to check if server is running
                    continue
                except socket.error as e:
                    print(f"Socket error with client {client_addr}: {e}")
                    break
                    
        except Exception as e:
            print(f"Error handling client {client_addr}: {e}")
        finally:
            client_socket.close()
            print(f"Client {client_addr} connection closed")
    
    def handle_request(self, json_data):
        """Handles the request from a client"""
        method = json_data.get("method")
        if not method:
            return {
                "success": False,
                "error": "No 'method' provided."
            }
        method_handler = METHODS.get(method)
        if not method_handler:
            return {
                "success": False,
                "error": f"No such method: '{method}'"
            }
        args = json_data.get("args", [])
        try:
            return method_handler(*args)
        except TypeError as e:
            return {
                "success": False,
                "error": "Invalid arguments '{args}' for method '{method}'."
            }

    def start(self):
        """Start the Unix socket server."""
        try:
            # Remove existing socket file if it exists
            if os.path.exists(self.socket_path):
                os.unlink(self.socket_path)
                
            # Create Unix domain socket
            self.server_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.server_socket.bind(self.socket_path)
            self.server_socket.listen(5)
            
            # Set socket permissions (readable/writable by owner and group)
            os.chmod(self.socket_path, 0o660)
            
            self.running = True
            print(f"Unix socket server listening on: {self.socket_path}")
            print("Press Ctrl+C to stop the server")
            
            # Accept connections
            while self.running:
                try:
                    # Set timeout so we can periodically check if we should stop
                    self.server_socket.settimeout(1.0)
                    client_socket, client_addr = self.server_socket.accept()
                    
                    # Handle each client in a separate thread
                    client_thread = threading.Thread(
                        target=self.handle_client,
                        args=(client_socket, client_addr),
                        daemon=True
                    )
                    client_thread.start()
                    self.client_threads.append(client_thread)
                    
                except socket.timeout:
                    # Timeout is expected, continue loop
                    continue
                except socket.error as e:
                    if self.running:  # Only log error if we're still supposed to be running
                        print(f"Socket error: {e}")
                    break
                    
        except Exception as e:
            print(f"Error starting server: {e}")
            return 1
        finally:
            self.cleanup()
            
        return 0
    
    def shutdown(self):
        """Signal the server to shutdown."""
        self.running = False
        
    def cleanup(self):
        """Clean up resources."""
        print("Cleaning up...")
        
        # Stop accepting new connections
        self.running = False
        
        # Close server socket
        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception as e:
                print(f"Error closing server socket: {e}")
        
        # Wait for client threads to finish (with timeout)
        for thread in self.client_threads:
            if thread.is_alive():
                thread.join(timeout=2.0)
                
        # Remove socket file
        try:
            if os.path.exists(self.socket_path):
                os.unlink(self.socket_path)
                print(f"Removed socket file: {self.socket_path}")
        except Exception as e:
            print(f"Error removing socket file: {e}")
            
        print("Cleanup complete")

def main():
    """Main entry point."""
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))
    server = UnixSocketServer(socket_path=os.getenv("SOCKET_FILE"))
    
    # Set up signal handlers for clean shutdown
    server.setup_signal_handlers()
    
    try:
        return server.start()
    except KeyboardInterrupt:
        print("\nKeyboard interrupt received")
        server.shutdown()
        return 0
    except Exception as e:
        print(f"Unexpected error: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())