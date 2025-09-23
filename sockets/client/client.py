#!/usr/bin/env python3
"""
Unix domain socket client with request/response matching using request IDs.
Connects to a server and handles method calls with argument passing.
"""

import os
import socket
import json
import threading
import time
import uuid
import tempfile
from typing import Any, Dict, List, Optional, Union
from concurrent.futures import Future
import logging

class UnixSocketClient:
    """
    Unix socket client that supports method calls with request/response matching.
    Uses request_id to match responses to requests in multi-threaded environments.
    """
    
    def __init__(self, socket_path: Optional[str] = None, timeout: float = 30.0, verbose=False):
        """
        Initialize the Unix socket client.
        
        Args:
            socket_path: Path to the Unix socket file
            timeout: Default timeout for requests in seconds
        """
        if socket_path is None:
            self.socket_path = os.path.join(tempfile.gettempdir(), 'waybard.socket')
        else:
            self.socket_path = socket_path
            
        self.timeout = timeout
        self.socket = None
        self.connected = False
        
        # Request/response handling
        self.pending_requests = {}  # request_id -> Future
        self.request_lock = threading.Lock()
        self.receive_thread = None
        self.running = False
        
        # Setup logging
        self.logger = logging.getLogger(f"{self.__class__.__name__}")
        if not verbose:
            self.logger.disabled = True
        
    def connect(self) -> bool:
        """
        Connect to the Unix socket server.
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            if self.connected:
                self.logger.warning("Already connected")
                return True
                
            if not os.path.exists(self.socket_path):
                self.logger.error(f"Socket file does not exist: {self.socket_path}")
                return False
                
            # Create and connect socket
            self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.socket.connect(self.socket_path)
            self.connected = True
            self.running = True
            
            # Start background thread to receive responses
            self.receive_thread = threading.Thread(
                target=self._receive_responses,
                daemon=True,
                name="SocketReceiver"
            )
            self.receive_thread.start()
            
            self.logger.info(f"Connected to Unix socket: {self.socket_path}")
            return True
            
        except socket.error as e:
            self.logger.error(f"Failed to connect to socket: {e}")
            self.connected = False
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error during connection: {e}")
            self.connected = False
            return False
    
    def disconnect(self):
        """Disconnect from the server and cleanup resources."""
        self.logger.info("Disconnecting from server...")
        self.running = False
        self.connected = False
        
        # Cancel all pending requests
        with self.request_lock:
            for request_id, future in self.pending_requests.items():
                if not future.done():
                    future.set_exception(ConnectionError("Client disconnected"))
            self.pending_requests.clear()
        
        # Close socket
        if self.socket:
            try:
                self.socket.close()
            except Exception as e:
                self.logger.error(f"Error closing socket: {e}")
            self.socket = None
        
        # Wait for receive thread to finish
        if self.receive_thread and self.receive_thread.is_alive():
            self.receive_thread.join(timeout=2.0)
            if self.receive_thread.is_alive():
                self.logger.warning("Receive thread did not terminate cleanly")
        
        self.logger.info("Disconnected from server")
    
    def _generate_request_id(self) -> str:
        """Generate a unique request ID."""
        return str(uuid.uuid4())
    
    def _receive_responses(self):
        """Background thread to receive and dispatch responses."""
        buffer = b""
        
        while self.running and self.connected:
            try:
                # Set a timeout so we can check if we should stop
                self.socket.settimeout(1.0)
                data = self.socket.recv(4096)
                
                if not data:
                    self.logger.info("Server closed connection")
                    break
                
                buffer += data
                
                # Try to parse complete JSON messages from buffer
                while buffer:
                    try:
                        # Find the end of a JSON object
                        decoder = json.JSONDecoder()
                        response, idx = decoder.raw_decode(buffer.decode('utf-8'))
                        
                        # Remove the parsed JSON from buffer
                        buffer = buffer[idx:].lstrip()
                        
                        # Handle the response
                        self._handle_response(response)
                        
                    except json.JSONDecodeError:
                        # Incomplete JSON, wait for more data
                        break
                    except UnicodeDecodeError as e:
                        self.logger.error(f"Unicode decode error: {e}")
                        buffer = b""  # Clear corrupted buffer
                        break
                
            except socket.timeout:
                # Timeout is expected, continue loop
                continue
            except socket.error as e:
                if self.running:
                    self.logger.error(f"Socket error in receive thread: {e}")
                break
            except Exception as e:
                self.logger.error(f"Unexpected error in receive thread: {e}")
                break
        
        # Connection lost, fail all pending requests
        with self.request_lock:
            for request_id, future in self.pending_requests.items():
                if not future.done():
                    future.set_exception(ConnectionError("Connection lost"))
            self.pending_requests.clear()
        
        self.connected = False
        self.logger.info("Receive thread terminated")
    
    def _handle_response(self, response: Dict[str, Any]):
        """
        Handle a response from the server.
        
        Args:
            response: JSON response from server
        """
        request_id = response.get('request_id')
        
        if not request_id:
            self.logger.warning(f"Received response without request_id: {response}")
            return
        
        with self.request_lock:
            future = self.pending_requests.pop(request_id, None)
        
        if future is None:
            self.logger.warning(f"Received response for unknown request_id: {request_id}")
            return
        
        if not future.done():
            future.set_result(response)
    
    def _send_request(self, method: str, args: List[Any] = None, 
                     timeout: Optional[float] = None) -> Dict[str, Any]:
        """
        Send a request to the server and wait for response.
        
        Args:
            method: Method name to call
            args: Arguments to pass to the method
            timeout: Request timeout (uses default if None)
            
        Returns:
            Response dictionary from server
            
        Raises:
            ConnectionError: If not connected to server
            TimeoutError: If request times out
            Exception: If server returns an error
        """
        if not self.connected:
            raise ConnectionError("Not connected to server")
        
        if args is None:
            args = []
        
        if timeout is None:
            timeout = self.timeout
        
        # Generate request ID and create future
        request_id = self._generate_request_id()
        future = Future()
        
        with self.request_lock:
            self.pending_requests[request_id] = future
        
        # Prepare request
        request = {
            "request_id": request_id,
            "method": method,
            "args": args
        }
        
        try:
            # Send request
            request_data = json.dumps(request).encode('utf-8')
            self.socket.sendall(request_data)
            self.logger.debug(f"Sent request {request_id}: {method}({args})")
            
            # Wait for response
            try:
                response = future.result(timeout=timeout)
                self.logger.debug(f"Received response for {request_id}: {response}")
                return response
                
            except Exception as e:
                # Remove from pending requests if still there
                with self.request_lock:
                    self.pending_requests.pop(request_id, None)
                raise
            
        except socket.error as e:
            # Remove from pending requests
            with self.request_lock:
                self.pending_requests.pop(request_id, None)
            raise ConnectionError(f"Socket error: {e}")
        except Exception as e:
            # Remove from pending requests  
            with self.request_lock:
                self.pending_requests.pop(request_id, None)
            raise
    
    def call_method(self, method: str, *args, timeout: Optional[float] = None) -> Any:
        """
        Call a method on the server with arguments.
        
        Args:
            method: Method name to call
            *args: Arguments to pass to the method
            timeout: Request timeout
            
        Returns:
            The result from the method call
            
        Raises:
            ConnectionError: If not connected
            TimeoutError: If request times out
            Exception: If method call fails
        """
        response = self._send_request(method, list(args), timeout)
        
        # Check if the response indicates success
        if not response.get('success', True):
            error_msg = response.get('error', 'Unknown error')
            raise Exception(f"Method '{method}' failed: {error_msg}")
        
        # Return the result or the entire response if no specific result field
        return response.get('result', response)
    
    def call_method_raw(self, method: str, args: List[Any] = None, 
                       timeout: Optional[float] = None) -> Dict[str, Any]:
        """
        Call a method and return the raw response dictionary.
        
        Args:
            method: Method name to call
            args: Arguments to pass to the method
            timeout: Request timeout
            
        Returns:
            Raw response dictionary from server
        """
        return self._send_request(method, args or [], timeout)
    
    def is_connected(self) -> bool:
        """Check if client is connected to server."""
        return self.connected
    
    def get_pending_requests_count(self) -> int:
        """Get the number of pending requests."""
        with self.request_lock:
            return len(self.pending_requests)
    
    def __enter__(self):
        """Context manager entry."""
        if not self.connect():
            raise ConnectionError("Failed to connect to server")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()


def demo_client():
    """Demonstrate the UnixSocketClient usage."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Unix Socket Client Demo")
    parser.add_argument('-s', '--socket', default=None, help='Socket path')
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose logging')
    args = parser.parse_args()
    
    # Setup logging
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)
    
    # Create client
    client = UnixSocketClient(socket_path=args.socket)
    
    try:
        # Connect to server
        if not client.connect():
            print("Failed to connect to server")
            return 1
        
        print("Connected to server! Trying some method calls...")
        
        # Example method calls (adjust based on your server's methods)
        try:
            # Call a method with no arguments
            print("\n1. Calling 'ping' method:")
            result = client.call_method("ping")
            print(f"Result: {result}")
            
        except Exception as e:
            print(f"Error calling 'ping': {e}")
        
        try:
            # Call a method with arguments
            print("\n2. Calling 'echo' method with arguments:")
            result = client.call_method("echo", "Hello", "World", 123)
            print(f"Result: {result}")
            
        except Exception as e:
            print(f"Error calling 'echo': {e}")
        
        try:
            # Call a method that might not exist
            print("\n3. Calling non-existent method:")
            result = client.call_method("nonexistent_method")
            print(f"Result: {result}")
            
        except Exception as e:
            print(f"Expected error: {e}")
        
        # Raw response example
        print("\n4. Getting raw response:")
        try:
            raw_response = client.call_method_raw("ping")
            print(f"Raw response: {raw_response}")
        except Exception as e:
            print(f"Error: {e}")
        
        # Multiple concurrent requests
        print("\n5. Testing concurrent requests:")
        import concurrent.futures
        
        def make_request(i):
            try:
                return client.call_method("echo", f"Request {i}")
            except Exception as e:
                return f"Error: {e}"
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(make_request, i) for i in range(5)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]
            
        for i, result in enumerate(results):
            print(f"  Concurrent request {i}: {result}")
        
        print(f"\nPending requests: {client.get_pending_requests_count()}")
        
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    except Exception as e:
        print(f"Unexpected error: {e}")
    finally:
        client.disconnect()
    
    return 0


def interactive_demo():
    """Interactive demo for testing the client."""
    client = UnixSocketClient()
    
    try:
        if not client.connect():
            print("Failed to connect to server")
            return
        
        print("Connected! Type method calls in the format: method_name arg1 arg2 ...")
        print("Type 'quit' to exit")
        
        while True:
            try:
                user_input = input("\n> ").strip()
                
                if user_input.lower() in ['quit', 'exit', 'q']:
                    break
                
                if not user_input:
                    continue
                
                # Parse input
                parts = user_input.split()
                method = parts[0]
                args = parts[1:] if len(parts) > 1 else []
                
                # Try to convert numeric arguments
                converted_args = []
                for arg in args:
                    try:
                        if '.' in arg:
                            converted_args.append(float(arg))
                        else:
                            converted_args.append(int(arg))
                    except ValueError:
                        converted_args.append(arg)
                
                # Make the call
                start_time = time.time()
                result = client.call_method_raw(method, converted_args)
                elapsed = time.time() - start_time
                
                print(f"Response ({elapsed:.3f}s): {json.dumps(result, indent=2)}")
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"Error: {e}")
    
    finally:
        client.disconnect()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "interactive":
        interactive_demo()
    else:
        sys.exit(demo_client())