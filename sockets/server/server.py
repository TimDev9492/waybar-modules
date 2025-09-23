#!/usr/bin/env python3
"""
Unix domain socket server for waybar modules with configurable permissions.
Creates a socket and handles JSON-based method calls.
"""

import os
import socket
import signal
import sys
import tempfile
import threading
import json
import pwd
import grp
from dotenv import load_dotenv
from pathlib import Path
from methods import METHODS

class UnixSocketServer:
    def __init__(self, socket_path=None, socket_user=None, socket_group=None, socket_mode=0o666):
        if socket_path is None:
            # Use a constant path in temp directory
            self.socket_path = os.path.join(tempfile.gettempdir(), 'waybar_modules.socket')
        else:
            self.socket_path = socket_path
        
        # Permission settings
        self.socket_user = socket_user    # Username or UID
        self.socket_group = socket_group  # Group name or GID  
        self.socket_mode = socket_mode    # File permissions (octal)
        
        self.server_socket = None
        self.running = False
        self.client_threads = []
        self.client_sockets = []  # Track all client sockets for cleanup
        self.client_lock = threading.Lock()  # Protect client lists
        
    def setup_signal_handlers(self):
        """Set up signal handlers for clean shutdown."""
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
        
    def _signal_handler(self, signum, frame):
        """Handle termination signals."""
        print(f"\nReceived signal {signum}. Shutting down gracefully...")
        self.shutdown()
        
    def set_socket_permissions(self):
        """Set socket file permissions and ownership for non-root access."""
        try:
            # Set file permissions
            os.chmod(self.socket_path, self.socket_mode)
            print(f"Set socket permissions to {oct(self.socket_mode)}")
            
            # Change ownership if running as root and user/group specified
            if os.getuid() == 0:  # Running as root
                uid = gid = -1  # -1 means don't change
                
                # Resolve user to UID
                if self.socket_user is not None:
                    if isinstance(self.socket_user, str):
                        try:
                            uid = pwd.getpwnam(self.socket_user).pw_uid
                            print(f"Resolved user '{self.socket_user}' to UID {uid}")
                        except KeyError:
                            print(f"Warning: User '{self.socket_user}' not found")
                    elif isinstance(self.socket_user, int):
                        uid = self.socket_user
                        print(f"Using UID {uid}")
                
                # Resolve group to GID  
                if self.socket_group is not None:
                    if isinstance(self.socket_group, str):
                        try:
                            gid = grp.getgrnam(self.socket_group).gr_gid
                            print(f"Resolved group '{self.socket_group}' to GID {gid}")
                        except KeyError:
                            print(f"Warning: Group '{self.socket_group}' not found")
                    elif isinstance(self.socket_group, int):
                        gid = self.socket_group
                        print(f"Using GID {gid}")
                
                # Change ownership if UID or GID specified
                if uid != -1 or gid != -1:
                    os.chown(self.socket_path, uid, gid)
                    print(f"Changed socket ownership to UID:{uid}, GID:{gid}")
                else:
                    print("No ownership change requested")
            else:
                if self.socket_user or self.socket_group:
                    print("Warning: Not running as root, cannot change socket ownership")
                    
        except Exception as e:
            print(f"Error setting socket permissions: {e}")
            # Don't fail completely, just warn
        
    def handle_client(self, client_socket, client_addr):
        """Handle individual client connections."""
        print(f"Client connected: {client_addr}")
        
        # Add client socket to tracking list
        with self.client_lock:
            self.client_sockets.append(client_socket)
        
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
                        request_id = json_data.get("request_id")
                        response = self.handle_request(json_data)
                        if request_id:
                            response["request_id"] = request_id
                        json_response = json.dumps(response)
                        client_socket.sendall(json_response.encode('utf-8'))
                    except json.JSONDecodeError as e:
                        print(f"Invalid JSON from client {client_addr}: {e}")
                        error_response = {
                            "success": False,
                            "error": "Invalid JSON format"
                        }
                        client_socket.sendall(json.dumps(error_response).encode('utf-8'))
                        break
                    except Exception as e:
                        print(f"Exception while handling client data from {client_addr}: {e}")
                        error_response = {
                            "success": False,
                            "error": f"Server error: {str(e)}"
                        }
                        try:
                            client_socket.sendall(json.dumps(error_response).encode('utf-8'))
                        except:
                            pass  # Client might have disconnected
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
            # Remove client socket from tracking list
            with self.client_lock:
                if client_socket in self.client_sockets:
                    self.client_sockets.remove(client_socket)
            
            # Close client socket
            try:
                client_socket.close()
            except:
                pass
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
                "error": f"Invalid arguments '{args}' for method '{method}': {str(e)}"
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Method '{method}' failed: {str(e)}"
            }

    def disconnect_all_clients(self):
        """Disconnect all connected clients gracefully."""
        print("Disconnecting all clients...")
        
        with self.client_lock:
            clients_to_close = self.client_sockets.copy()
        
        for client_socket in clients_to_close:
            try:
                # Send shutdown notification to client
                shutdown_msg = {
                    "success": False,
                    "error": "Server shutting down",
                    "shutdown": True
                }
                client_socket.sendall(json.dumps(shutdown_msg).encode('utf-8'))
                
                # Give client a moment to process the message
                client_socket.settimeout(0.5)
                try:
                    client_socket.recv(1024)  # Drain any remaining data
                except:
                    pass
                    
                # Close the socket
                client_socket.close()
            except Exception as e:
                print(f"Error disconnecting client: {e}")
                try:
                    client_socket.close()
                except:
                    pass
        
        # Clear the client lists
        with self.client_lock:
            self.client_sockets.clear()
        
        print(f"Disconnected {len(clients_to_close)} clients")

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
            
            # Set socket permissions and ownership
            self.set_socket_permissions()
            
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
        print("Initiating server shutdown...")
        self.running = False
        
        # Disconnect all clients first
        self.disconnect_all_clients()
        
    def cleanup(self):
        """Clean up resources."""
        print("Cleaning up...")
        
        # Stop accepting new connections
        self.running = False
        
        # Disconnect any remaining clients
        self.disconnect_all_clients()
        
        # Close server socket
        if self.server_socket:
            try:
                self.server_socket.close()
            except Exception as e:
                print(f"Error closing server socket: {e}")
        
        # Wait for client threads to finish (with timeout)
        active_threads = [t for t in self.client_threads if t.is_alive()]
        if active_threads:
            print(f"Waiting for {len(active_threads)} client threads to finish...")
            for thread in active_threads:
                thread.join(timeout=2.0)
                if thread.is_alive():
                    print(f"Warning: Thread {thread.name} did not terminate cleanly")
                
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
    import argparse
    
    # Load environment variables first
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))
    
    parser = argparse.ArgumentParser(
        description="Waybar modules Unix socket server with configurable permissions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
# Default permissions (world-readable/writable)
python3 server.py

# Make accessible to specific user and group
sudo python3 server.py -u myuser -g mygroup

# Set specific permissions (readable/writable by owner and group only)
sudo python3 server.py -m 0660

# Use environment variables and custom permissions
sudo python3 server.py -u waybar -g users -m 0664
        """
    )
    
    parser.add_argument(
        '-s', '--socket',
        default=os.getenv("SOCKET_FILE", "/tmp/waybar_modules.socket"),
        help='Socket path (default: from SOCKET_FILE env var or /tmp/waybar_modules.socket)'
    )
    
    parser.add_argument(
        '-u', '--user',
        default=os.getenv("SOCKET_USER"),
        help='Socket owner user (name or UID, default: from SOCKET_USER env var)'
    )
    
    parser.add_argument(
        '-g', '--group', 
        default=os.getenv("SOCKET_GROUP"),
        help='Socket owner group (name or GID, default: from SOCKET_GROUP env var)'
    )
    
    parser.add_argument(
        '-m', '--mode',
        default=os.getenv("SOCKET_MODE", "0666"),
        help='Socket file permissions in octal (default: from SOCKET_MODE env var or 0666)'
    )
    
    args = parser.parse_args()
    
    # Parse mode as octal
    try:
        mode = int(args.mode, 8)  # Parse as octal
    except (ValueError, TypeError):
        print(f"Error: Invalid mode '{args.mode}'. Use octal format like 0666")
        return 1
    
    # Convert user/group if they look like numbers
    user = args.user
    group = args.group
    
    if user and user.isdigit():
        user = int(user)
    if group and group.isdigit():
        group = int(group)
    
    # Create server with specified permissions
    server = UnixSocketServer(
        socket_path=args.socket,
        socket_user=user,
        socket_group=group, 
        socket_mode=mode
    )
    
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