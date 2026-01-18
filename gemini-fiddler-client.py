#!/usr/bin/env python3
"""
Gemini-Powered Fiddler MCP Client
Natural language interface for analyzing Fiddler traffic using Google Gemini 2.5

Features:
- Natural language queries about Fiddler traffic
- Automatic tool selection and execution
- Conversation history and context
- Easy configuration
- Production-ready error handling
"""
import json
import os
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional
from datetime import datetime
from pathlib import Path

# Suppress gRPC/absl logging noise
os.environ.setdefault("GRPC_VERBOSITY", "NONE")
os.environ.setdefault("GRPC_LOG_SEVERITY_LEVEL", "ERROR")
os.environ["GRPC_VERBOSITY"] = "ERROR"
os.environ["GRPC_TRACE"] = ""

try:
    import warnings
    warnings.filterwarnings("ignore", category=UserWarning)
    warnings.filterwarnings("ignore", message=r"Unrecognized FinishReason enum value", category=UserWarning)
    
    import google.generativeai as genai
except ImportError:
    print("ERROR: Google Generative AI library not installed.")
    print("Install with: pip install google-generativeai")
    sys.exit(1)

try:
    from rich.console import Console
    from rich.markdown import Markdown
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

# Available Gemini models for selection (centralized for consistency)
AVAILABLE_MODELS = {
    "1": "gemini-3-pro",
    "2": "gemini-2.5-flash",
    "3": "gemini-2.0-flash",
    "4": "gemini-2.5-pro",
    "5": "gemini-1.5-pro",
    "6": "gemini-2.5-flash-lite",
    "7": "gemini-2.0-flash-lite",
    "8": "gemini-1.5-flash",
    "9": "gemini-1.5-flash-8b",
    "10": "gemini-2.5-flash-preview",
    "11": "gemini-2.0-flash-exp",
}


class GeminiFiddlerClient:
    """Gemini-powered MCP client for Fiddler traffic analysis"""

    def __init__(
        self,
        api_key: str,
        model_name: str = "gemini-2.5-flash",
        auto_save_full_bodies: bool = False,
    ):
        """Initialize client with Gemini API key"""
        self.api_key = api_key
        self.model_name = model_name
        self.mcp_process = None
        self.mcp_stderr_file = None
        self.request_id = 0
        self.conversation_history = []
        self.available_tools = []
        self.session_start = datetime.now()
        self.auto_save_full_bodies = auto_save_full_bodies
        self.verbose_logging = os.environ.get("GEMINI_FIDDLER_VERBOSE_LOG", "0") == "1"
        
        # Performance settings
        self.tool_timeout = int(os.environ.get("GEMINI_TOOL_TIMEOUT", "30"))  # seconds
        self.gemini_timeout = int(os.environ.get("GEMINI_API_TIMEOUT", "60"))  # seconds
        self.show_progress = os.environ.get("GEMINI_HIDE_PROGRESS", "").strip() != "1"
        self.max_followups = int(os.environ.get("GEMINI_MAX_TOOL_CALLS", "10"))  # Maximum tool calls per query
        
        if RICH_AVAILABLE:
            self.console = Console()
            self.use_rich = True
        else:
            self.console = None
            self.use_rich = False
        
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel(model_name)
        
        print(f"Initialized Gemini {model_name}")
        if not RICH_AVAILABLE:
            print("[!] Tip: Install 'rich' library for better formatting: pip install rich")

    def log_with_timestamp(self, message: str, to_console: bool = True, prefix: str = "") -> None:
        """Log a message with timestamp to both console and log file"""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        formatted_message = f"[{timestamp}] {prefix}{message}"
        
        # Always log to file if available
        if self.mcp_stderr_file and not self.mcp_stderr_file.closed:
            try:
                self.mcp_stderr_file.write(formatted_message + "\n")
                self.mcp_stderr_file.flush()
            except Exception:
                pass  # Silently fail if file is closed
        
        # Optionally log to console
        if to_console:
            print(formatted_message)

    def _format_size(self, size_bytes: int) -> str:
        """Format byte size to human readable string (KB, MB)"""
        if size_bytes < 1024:
            return f"{size_bytes} bytes"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f}KB"
        else:
            return f"{size_bytes / (1024 * 1024):.1f}MB"

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count (rough approximation: ~4 chars per token for English)"""
        return len(text) // 4

    def _extract_finish_reason(self, response) -> str:
        """Extract finish_reason from Gemini response"""
        try:
            candidates = getattr(response, "candidates", []) or []
            if candidates:
                finish_reason = getattr(candidates[0], "finish_reason", None)
                if finish_reason is not None:
                    return str(finish_reason).replace("FinishReason.", "")
        except Exception:
            pass
        return "UNKNOWN"

    def _count_candidates(self, response) -> int:
        """Count number of candidates in Gemini response"""
        try:
            candidates = getattr(response, "candidates", []) or []
            return len(candidates)
        except Exception:
            return 0

    def start_mcp_server(self, server_command: List[str]):
        """Start the MCP server (5ire-bridge.py) as subprocess"""
        print(f"\n[*] Starting MCP server: {' '.join(server_command)}")
        try:
            log_dir = Path(__file__).parent
            err_path = log_dir / "mcp_server.err.log"
            
            if self.verbose_logging:
                print(f"[*] Opening log file: {err_path}")
            
            try:
                err_file = open(err_path, "w", buffering=1, encoding="utf-8", errors="replace")
                self.mcp_stderr_file = err_file
                if self.verbose_logging:
                    print(f"[+] Log file opened (fd={err_file.fileno()})")
            except Exception as e:
                print(f"[!] Failed to open log file: {e}")
                self.mcp_stderr_file = None
                raise

            log_mode = "VERBOSE" if self.verbose_logging else "OPTIMIZED"
            try:
                self.mcp_stderr_file.write(f"=== MCP Server Log Started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===\n")
                self.mcp_stderr_file.write(f"Command: {' '.join(server_command)}\n")
                self.mcp_stderr_file.write(f"Log Mode: {log_mode} (set GEMINI_FIDDLER_VERBOSE_LOG=1 for full JSON)\n")
                self.mcp_stderr_file.write("=" * 70 + "\n\n")
                self.mcp_stderr_file.flush()
            except Exception as e:
                print(f"[!] Error writing log file header: {e}")
                raise

            self.mcp_process = subprocess.Popen(
                server_command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',  # Explicit UTF-8 encoding for cross-platform consistency
                errors='replace',  # Replace invalid bytes instead of crashing
                bufsize=0
            )
            
            import threading
            def log_server_stderr():
                try:
                    while True:
                        line = self.mcp_process.stderr.readline()
                        if not line:
                            break
                        if self.mcp_stderr_file and not self.mcp_stderr_file.closed:
                            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                            self.mcp_stderr_file.write(f"[{timestamp}] Server: {line}")
                            self.mcp_stderr_file.flush()
                except Exception as e:
                    if self.mcp_stderr_file and not self.mcp_stderr_file.closed:
                        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                        self.mcp_stderr_file.write(f"[{timestamp}] Stderr thread error: {e}\n")
                        self.mcp_stderr_file.flush()
            
            stderr_thread = threading.Thread(target=log_server_stderr, daemon=True)
            stderr_thread.start()
            
            self.mcp_stderr_file.write(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] Client: Starting stderr capture thread\n")
            self.mcp_stderr_file.flush()
            
            time.sleep(0.5)
            print("[+] MCP server started")
            print(f"[*] Logging to: {err_path}")
            
            if self.verbose_logging:
                try:
                    self.mcp_stderr_file.write(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] Client: Log file test successful\n")
                    self.mcp_stderr_file.flush()
                    print(f"[+] Log file test successful")
                except Exception as e:
                    print(f"[!] Log file test failed: {e}")
            
            try:
                print("[*] Initializing connection...")
                self.initialize_mcp()
            except Exception as e:
                print(f"[X] Initialize failed: {e}")
                print("[!] This usually means the MCP server isn't ready yet")
                raise
        except Exception as e:
            print(f"[X] Failed to start MCP server: {e}")
            if hasattr(self, 'mcp_process') and self.mcp_process:
                try:
                    print("[*] Terminating MCP server subprocess...")
                    self.mcp_process.terminate()
                    self.mcp_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    print("[!] Force killing MCP server subprocess...")
                    self.mcp_process.kill()
                except Exception as cleanup_error:
                    print(f"[!] Error during cleanup: {cleanup_error}")
            if self.mcp_stderr_file:
                try:
                    self.mcp_stderr_file.close()
                finally:
                    self.mcp_stderr_file = None
            sys.exit(1)

    def send_mcp_request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Send JSON-RPC request to MCP server with timeout"""
        self.request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": method,
        }
        if params:
            request["params"] = params

        request_start = time.time()
        
        try:
            if self.mcp_process.poll() is not None:
                return {"error": "MCP server process has terminated"}
            
            request_json = json.dumps(request)
            request_size = len(request_json)
            
            # Log MCP request with details
            if self.mcp_stderr_file and not self.mcp_stderr_file.closed:
                timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                if method == "tools/call":
                    tool_name = params.get("name", "unknown") if params else "unknown"
                    self.mcp_stderr_file.write(f"[{timestamp}] MCP Request: method={method}, tool={tool_name}, size={self._format_size(request_size)}\n")
                else:
                    self.mcp_stderr_file.write(f"[{timestamp}] MCP Request: method={method}, size={self._format_size(request_size)}\n")
                self.mcp_stderr_file.flush()
            self.mcp_process.stdin.write(request_json + "\n")
            self.mcp_process.stdin.flush()

            import select
            import sys
            
            if sys.platform == "win32":
                import threading
                response_line = []
                error = []
                
                def read_with_timeout():
                    try:
                        line = self.mcp_process.stdout.readline()
                        response_line.append(line)
                    except Exception as e:
                        error.append(str(e))
                
                thread = threading.Thread(target=read_with_timeout, daemon=True)
                thread.start()
                thread.join(timeout=30.0)
                
                if not response_line:
                    if error:
                        raise RuntimeError(f"Read error: {error[0]}")
                    raise RuntimeError("MCP server response timeout (30s) - server may not be responding")
                
                response_line = response_line[0]
            else:
                ready = select.select([self.mcp_process.stdout], [], [], 30.0)
                if not ready[0]:
                    raise RuntimeError("MCP server response timeout (30s)")
                response_line = self.mcp_process.stdout.readline()
            
            if not response_line:
                raise RuntimeError("MCP server closed connection")

            response = json.loads(response_line)
            response_size = len(response_line)
            elapsed_ms = int((time.time() - request_start) * 1000)
            
            # Log MCP response with timing and size
            if self.mcp_stderr_file and not self.mcp_stderr_file.closed:
                timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                
                if self.verbose_logging:
                    self.mcp_stderr_file.write(f"[{timestamp}] MCP Response: {elapsed_ms}ms, size={self._format_size(response_size)}\n")
                    self.mcp_stderr_file.write(f"[{timestamp}] Response: {json.dumps(response)}\n")
                else:
                    if "error" in response:
                        self.mcp_stderr_file.write(f"[{timestamp}] MCP Response: {elapsed_ms}ms, ERROR: {json.dumps(response.get('error', {}))}\n")
                    elif method == "tools/call":
                        tool_name = params.get("name", "unknown") if params else "unknown"
                        if "result" in response:
                            result = response.get("result", {})
                            content = result.get("content", [])
                            item_count = len(content) if isinstance(content, list) else 0
                            self.mcp_stderr_file.write(f"[{timestamp}] MCP Response: {elapsed_ms}ms, tool='{tool_name}', items={item_count}, size={self._format_size(response_size)}\n")
                        else:
                            self.mcp_stderr_file.write(f"[{timestamp}] MCP Response: {elapsed_ms}ms, tool='{tool_name}', no result\n")
                    else:
                        self.mcp_stderr_file.write(f"[{timestamp}] MCP Response: {elapsed_ms}ms, method='{method}', size={self._format_size(response_size)}\n")
                
                self.mcp_stderr_file.flush()
            return response
        except json.JSONDecodeError as e:
            elapsed_ms = int((time.time() - request_start) * 1000)
            self.log_with_timestamp(f"MCP Response: {elapsed_ms}ms, JSON decode error: {e}", to_console=False)
            return {"error": f"Invalid JSON response: {e}"}
        except Exception as e:
            elapsed_ms = int((time.time() - request_start) * 1000)
            self.log_with_timestamp(f"MCP Response: {elapsed_ms}ms, error: {e}", to_console=False)
            return {"error": f"MCP request failed: {e}"}

    def send_mcp_notification(self, method: str, params: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """Send JSON-RPC notification (no response expected)."""
        try:
            if self.mcp_process.poll() is not None:
                return "MCP server process has terminated"

            notification = {
                "jsonrpc": "2.0",
                "method": method,
                "params": params or {},
            }

            self.mcp_process.stdin.write(json.dumps(notification) + "\n")
            self.mcp_process.stdin.flush()
        except Exception as exc:
            return f"Failed to send notification: {exc}"
        return None

    def initialize_mcp(self):
        """Initialize MCP connection"""
        response = self.send_mcp_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "gemini-fiddler-client", "version": "1.0.0"},
            },
        )
        
        if "result" in response:
            server_info = response["result"].get("serverInfo", {})
            print(f"[+] Connected to {server_info.get('name', 'MCP server')}")

            # MCP spec requires clients to notify once initialization completes.
            error = self.send_mcp_notification("notifications/initialized")
            if error and self.verbose_logging:
                print(f"[!] Warning: {error}")
        else:
            print(f"[X] Initialization failed: {response.get('error', 'Unknown error')}")

    def list_tools(self) -> List[Dict[str, Any]]:
        """List all available MCP tools"""
        response = self.send_mcp_request("tools/list")
        
        if "error" in response:
            print(f"\n[X] Error listing tools: {response['error']}")
            print("\n[!] Diagnostics:")
            print(f"    - Process alive: {self.mcp_process.poll() is None}")
            print(f"    - Process PID: {self.mcp_process.pid if self.mcp_process else 'N/A'}")
            print("\n[!] This usually means:")
            print("    1. The 5ire-bridge.py failed to start properly")
            print("    2. The enhanced-bridge.py is not running (needed on port 8081)")
            print("    3. There's a port conflict or network issue")
            print("\n[!] Try:")
            print("    1. Start enhanced-bridge.py first: python enhanced-bridge.py")
            print("    2. Check if port 8081 is available: netstat -an | findstr 8081")
            print("    3. Kill stuck processes: taskkill /F /IM python.exe")
            return []
        
        tools = response.get("result", {}).get("tools", [])
        self.available_tools = tools
        return tools

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call a specific MCP tool with progress indicator"""
        # Correct common tool name hallucinations from LLM
        TOOL_ALIASES = {
            "fiddler_mcp__session_details": "fiddler_mcp__session_body",
            "fiddler_mcp__sessions_details": "fiddler_mcp__session_body",
            "fiddler_mcp__get_session": "fiddler_mcp__session_body",
            "fiddler_mcp__list_sessions": "fiddler_mcp__live_sessions",
            "fiddler_mcp__sessions_list": "fiddler_mcp__live_sessions",
        }
        if tool_name in TOOL_ALIASES:
            corrected = TOOL_ALIASES[tool_name]
            self.log_with_timestamp(f"Auto-corrected tool: {tool_name} -> {corrected}", to_console=True, prefix="[!] ")
            tool_name = corrected
        
        # Enhanced bridge call logging
        args_str = ", ".join(f"{k}={v}" for k, v in arguments.items())
        self.log_with_timestamp(f"Bridge Call: {tool_name}({args_str})", to_console=False)
        
        if self.verbose_logging:
            self.log_with_timestamp(f"  Arguments: {json.dumps(arguments, indent=2)}", to_console=False, prefix="Client: ")
        
        # Progress indicator
        spinner = ['|', '/', '-', '\\']
        spinner_idx = 0
        start_time = time.time()
        
        # Show initial progress - specify it's the Fiddler HTTP bridge
        sys.stdout.write(f"\r  {spinner[spinner_idx]} Waiting for Fiddler HTTP bridge... (0s)")
        sys.stdout.flush()
        
        response = self.send_mcp_request("tools/call", {"name": tool_name, "arguments": arguments})
        
        # Stop progress and show completion with descriptive info
        elapsed_ms = int((time.time() - start_time) * 1000)
        elapsed_s = elapsed_ms / 1000
        
        result = self._parse_tool_response(response)
        
        # Enhanced result logging with session metadata
        try:
            if isinstance(result, dict):
                if result.get("error"):
                    self.log_with_timestamp(f"Bridge Result: {elapsed_ms}ms, error={result.get('error')}", to_console=False)
                    sys.stdout.write(f"\r  [Fiddler Bridge] Error ({elapsed_s:.1f}s)                    \n")
                elif 'sessions' in result:
                    sessions = result.get('sessions', [])
                    count = len(sessions)
                    suspicious = sum(1 for s in sessions if s.get('risk_flag') or s.get('ekfiddle_comment'))
                    ekfiddle = sum(1 for s in sessions if s.get('ekfiddle_comment'))
                    self.log_with_timestamp(f"Bridge Result: {elapsed_ms}ms, success=true, sessions={count}, suspicious={suspicious}, ekfiddle={ekfiddle}", to_console=False)
                    sys.stdout.write(f"\r  [Fiddler Bridge] Received {count} sessions ({elapsed_s:.1f}s)                    \n")
                elif 'response_body' in result or 'responseBody' in result:
                    body = result.get('response_body', '') or result.get('responseBody', '') or ''
                    body_len = len(body)
                    content_type = result.get('content_type', 'unknown')
                    # Try to get host from result or infer from session data
                    host = result.get('host', '')
                    self.log_with_timestamp(f"Bridge Result: {elapsed_ms}ms, success=true, content_type={content_type}, response_body={self._format_size(body_len)}", to_console=False)
                    if host:
                        self.log_with_timestamp(f"Bridge Result: host={host}", to_console=False)
                    sys.stdout.write(f"\r  [Fiddler Bridge] Received session body: {self._format_size(body_len)} ({elapsed_s:.1f}s)                    \n")
                else:
                    result_size = len(json.dumps(result))
                    self.log_with_timestamp(f"Bridge Result: {elapsed_ms}ms, success=true, result_size={self._format_size(result_size)}", to_console=False)
                    sys.stdout.write(f"\r  [Fiddler Bridge] Response received ({elapsed_s:.1f}s)                    \n")
            else:
                self.log_with_timestamp(f"Bridge Result: {elapsed_ms}ms, unexpected_type={type(result)}", to_console=False)
                sys.stdout.write(f"\r  [Fiddler Bridge] Response received ({elapsed_s:.1f}s)                    \n")
        except Exception as e:
            # Fallback if we can't parse the response
            self.log_with_timestamp(f"Bridge Result: {elapsed_ms}ms, parse_error={e}", to_console=False)
            sys.stdout.write(f"\r  [Fiddler Bridge] Response received ({elapsed_s:.1f}s)                    \n")
        
        sys.stdout.flush()

        if tool_name == "fiddler_mcp__sessions_search" and result.get("success"):
            follow_up = self._auto_fetch_session_body(result)
            if follow_up:
                result.setdefault("_follow_up", {})["session_body_preview"] = follow_up
                
                # Get metadata for better status reporting
                metadata = follow_up.get("_auto_fetch_metadata", {})
                note = follow_up.get("auto_note", "Session body retrieved")
                follow_id = follow_up.get("session_id") or follow_up.get("id")
                
                if follow_id:
                    status_msg = f"[+] Auto body fetch for session {follow_id}"
                    if metadata.get("has_duplicate_ids"):
                        status_msg += f" at {metadata.get('fetched_timestamp', 'unknown time')}"
                    print(status_msg)
                else:
                    print(f"[+] Auto body fetch complete")

        return result

    def _parse_tool_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        if "result" not in response:
            return {"error": response.get("error", "Tool call failed")}

        result = response["result"]

        if isinstance(result, dict):
            content = result.get("content")
            if isinstance(content, list) and content:
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text" and "text" in item:
                            text_data = item["text"]
                            if isinstance(text_data, str) and (text_data.strip().startswith('{') or text_data.strip().startswith('[')):
                                try:
                                    return json.loads(text_data)
                                except json.JSONDecodeError:
                                    return {"text": text_data}
                            return {"text": text_data}
                        return item

            if any(key in result for key in ("success", "error", "sessions", "bridge_status")):
                return result

            response_envelope = result.get("response")
            if isinstance(response_envelope, dict):
                data = response_envelope.get("data")
                if data is not None:
                    return data if isinstance(data, dict) else {"data": data}
                return response_envelope

        return result if isinstance(result, dict) else {"result": result}

    def _auto_fetch_session_body(self, search_result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Automatically retrieve the body for the first session returned by a search."""
        sessions = search_result.get("sessions") or []
        if not sessions:
            return None

        first = sessions[0]
        session_id = str(first.get("id", "")).strip()
        if not session_id:
            return None

        # Extract timestamp info for disambiguation
        received_at = first.get("received_at")
        received_at_iso = first.get("received_at_iso") or first.get("time")
        
        # Check if there are duplicate session IDs with different timestamps
        duplicate_ids = [s for s in sessions if str(s.get("id", "")) == session_id]
        has_duplicates = len(duplicate_ids) > 1
        
        # Build informative log message
        log_msg = f"[*] Auto-fetching body for session {session_id}"
        if received_at_iso:
            log_msg += f" (timestamp: {received_at_iso})"
        if has_duplicates:
            log_msg += f" [WARNING: {len(duplicate_ids)} sessions share this ID]"
        print(log_msg)
        
        response = self.send_mcp_request(
            "tools/call",
            {"name": "fiddler_mcp__session_body", "arguments": {"session_id": session_id}},
        )
        body_data = self._parse_tool_response(response)

        if not isinstance(body_data, dict) or body_data.get("success") is False:
            if isinstance(body_data, dict):
                body_data.setdefault("note", "Automatic session body lookup failed or returned no content.")
            return body_data

        # Add disambiguation metadata to help AI understand which session was fetched
        body_data["_auto_fetch_metadata"] = {
            "fetched_session_id": session_id,
            "fetched_timestamp": received_at_iso,
            "fetched_received_at": received_at,
            "has_duplicate_ids": has_duplicates,
            "note": f"This is session {session_id} from the search results (first match)" 
                    + (f" - WARNING: {len(duplicate_ids)} sessions share this ID with different timestamps" if has_duplicates else "")
        }

        truncated_flag = body_data.get("response_truncated") or body_data.get("truncated")
        size_bytes = body_data.get("content_length")

        # If preview is truncated, request the raw body and persist it to disk.
        # NEW: For large JavaScript files, also request smart extraction for better LLM analysis
        if truncated_flag:
            content_type = body_data.get("content_type", "") or ""
            is_javascript = "javascript" in content_type.lower()
            
            # Determine if we should use smart extraction (large JS files benefit most)
            # Default threshold: 50KB - matches enhanced-bridge MAX_BODY_PREVIEW_BYTES
            use_smart_extract = is_javascript and size_bytes and size_bytes > 50000
            
            if use_smart_extract:
                print(f"[*] Large JavaScript detected ({size_bytes:,} bytes); using smart extraction for session {session_id}...")
            else:
                print(f"[*] Preview for session {session_id} was truncated; requesting full body...")
            
            raw_response = self.send_mcp_request(
                "tools/call",
                {
                    "name": "fiddler_mcp__session_body",
                    "arguments": {
                        "session_id": session_id, 
                        "include_binary": True,
                        "smart_extract": use_smart_extract,  # NEW: Request intelligent extraction
                    },
                },
            )
            raw_data = self._parse_tool_response(raw_response)
            if isinstance(raw_data, dict) and raw_data.get("success"):
                body_data = raw_data
                truncated_flag = body_data.get("response_truncated") or body_data.get("truncated")
                size_bytes = body_data.get("content_length", size_bytes)
            else:
                body_data.setdefault(
                    "auto_note",
                    "Body preview was truncated and full fetch failed; inspect manually via fiddler_mcp__session_body",
                )
                return body_data

        # Check if smart extraction is available (from the bridge response)
        smart_extraction = body_data.get("smart_extraction")
        smart_extraction_available = body_data.get("smart_extraction_available", False)
        
        response_text = body_data.get("response_body") or ""
        
        # NEW: If smart extraction is available, use it for better LLM analysis
        if smart_extraction_available and smart_extraction:
            # Format the smart extraction for LLM consumption
            formatted_extraction = self._format_smart_extraction(smart_extraction)
            
            if formatted_extraction:
                # Use larger snippet limit for curated smart extraction content
                snippet_limit = 24000  # ~24KB of curated, security-relevant content
                
                if len(formatted_extraction) > snippet_limit:
                    body_data["response_body_analyzed"] = (
                        formatted_extraction[:snippet_limit]
                        + "\n\n...[smart extraction shortened for conversation output]"
                    )
                else:
                    body_data["response_body_analyzed"] = formatted_extraction
                
                # Add the analyzed content as the primary response for LLM
                body_data["response_body"] = body_data["response_body_analyzed"]
                body_data["response_body_preview"] = body_data["response_body_analyzed"]
                body_data["analysis_method"] = "smart_extraction"
                
                # Log what was extracted
                metadata = smart_extraction.get("metadata", {})
                patterns_found = metadata.get("patterns_found", [])
                if patterns_found:
                    print(f"[+] Smart extraction found {len(patterns_found)} suspicious patterns: {', '.join(patterns_found[:5])}")
                
                # Still save the full body to disk if enabled
                saved_path = self._save_body_to_file(session_id, response_text)
                if saved_path:
                    body_data["saved_response_path"] = saved_path
                    body_data.setdefault(
                        "auto_note_details",
                        f"Smart extraction from {size_bytes:,} byte file; full response saved to {saved_path}"
                    )
                    body_data["auto_note"] = f"Smart extraction applied; full body saved to {saved_path}"
                else:
                    body_data["auto_note"] = "Smart extraction applied for enhanced analysis"
        
        # FALLBACK: Existing behavior for non-JavaScript or when smart extraction not available
        elif response_text:
            snippet_limit = 8000  # Original limit preserved
            if len(response_text) > snippet_limit:
                body_data["response_body_preview"] = (
                    response_text[:snippet_limit]
                    + "\n\n...[preview shortened for conversation output]"
                )
                body_data["response_body"] = body_data["response_body_preview"]
            else:
                body_data["response_body_preview"] = response_text

            saved_path = self._save_body_to_file(session_id, response_text)
            if saved_path:
                body_data["saved_response_path"] = saved_path
                body_data.setdefault(
                    "auto_note_details",
                    f"Body length reported as {size_bytes} bytes; full response saved to {saved_path}"
                    if size_bytes is not None
                    else f"Full response saved to {saved_path}",
                )
                if not truncated_flag:
                    body_data["auto_note"] = f"Full body retrieved and saved to {saved_path}"
                else:
                    body_data["auto_note"] = f"Body preview truncated; full response saved to {saved_path}"

        request_text = body_data.get("request_body") or ""
        if request_text:
            snippet_limit = 4000
            if len(request_text) > snippet_limit:
                body_data["request_body_preview"] = (
                    request_text[:snippet_limit]
                    + "\n\n...[preview shortened for conversation output]"
                )
                body_data["request_body"] = body_data["request_body_preview"]
            else:
                body_data["request_body_preview"] = request_text

            saved_req_path = self._save_body_to_file(session_id, request_text, kind="request")
            if saved_req_path:
                body_data["saved_request_path"] = saved_req_path

        # Build auto_note with disambiguation info
        base_note = "Full body retrieved" if not truncated_flag else "Body preview truncated; saved full payload to disk"
        if has_duplicates:
            base_note += f" [Session {session_id} at {received_at_iso} - {len(duplicate_ids)} total with this ID]"
        
        body_data.setdefault("auto_note", base_note)
        
        if size_bytes is not None:
            body_data.setdefault("auto_note_details", f"Body length reported as {size_bytes} bytes")

        return body_data

    def _save_body_to_file(self, session_id: str, body_text: str, kind: str = "response") -> Optional[str]:
        if not self.auto_save_full_bodies:
            return None

        try:
            dump_dir = Path(__file__).parent / "session_dumps"
            dump_dir.mkdir(exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            safe_id = str(session_id).replace(os.sep, "_")
            file_path = dump_dir / f"session_{safe_id}_{kind}_{timestamp}.txt"
            file_path.write_text(body_text, encoding="utf-8", errors="replace")
            return str(file_path)
        except Exception as exc:
            print(f"[!] Failed to persist {kind} body for session {session_id}: {exc}")
            return None

    def _format_smart_extraction(self, extraction: dict) -> str:
        """
        Format intelligent extraction data for LLM consumption.
        
        This method takes the smart_extraction dict from the bridge and formats it
        into a structured string that helps the LLM understand the content layout.
        
        Args:
            extraction: Dict with keys: head, tail, suspicious_patterns, metadata
        
        Returns:
            Formatted string combining head, patterns, and tail sections
        """
        if not extraction or not isinstance(extraction, dict):
            return ""
        
        parts = []
        metadata = extraction.get("metadata", {})
        original_size = metadata.get("original_size", 0)
        patterns_found = metadata.get("patterns_found", [])
        
        # Add header with context
        if original_size > 0:
            parts.append(f"[INTELLIGENT EXTRACTION from {original_size:,} byte file]")
            if patterns_found:
                parts.append(f"[Suspicious patterns detected: {', '.join(patterns_found[:10])}]")
            parts.append("")
        
        # Add head section (first 8KB - variable declarations, imports, configs)
        head = extraction.get("head", "")
        if head:
            parts.append("=" * 60)
            parts.append("=== FILE START (first 8KB) ===")
            parts.append("=" * 60)
            parts.append(head)
        
        # Add suspicious patterns section (security-relevant code from middle)
        suspicious = extraction.get("suspicious_patterns", "")
        if suspicious:
            parts.append("")
            parts.append("=" * 60)
            parts.append("=== DETECTED SUSPICIOUS PATTERNS (from middle section) ===")
            parts.append("=" * 60)
            parts.append(suspicious)
        
        # Add tail section (last 4KB - execution logic, callbacks)
        tail = extraction.get("tail", "")
        if tail:
            parts.append("")
            parts.append("=" * 60)
            parts.append("=== FILE END (last 4KB) ===")
            parts.append("=" * 60)
            parts.append(tail)
        
        # Add extraction summary
        if metadata:
            parts.append("")
            parts.append("-" * 40)
            total_extracted = metadata.get("total_extracted", 0)
            patterns_count = metadata.get("patterns_count", 0)
            parts.append(f"[Extraction summary: {total_extracted:,} bytes extracted from {original_size:,} bytes original]")
            if patterns_count > 0:
                parts.append(f"[{patterns_count} suspicious code patterns identified]")
        
        return "\n".join(parts)

    def create_tool_descriptions(self) -> str:
        """Create formatted tool descriptions for Gemini with security focus"""
        if not self.available_tools:
            return "No tools available."
        
        descriptions = ["Available Fiddler MCP Tools:\n"]
        for i, tool in enumerate(self.available_tools, 1):
            name = tool.get("name", "")
            desc = tool.get("description", "No description")
            schema = tool.get("inputSchema", {})
            props = schema.get("properties", {})
            
            descriptions.append(f"{i}. {name}")
            descriptions.append(f"   Description: {desc}")
            
            # Add security guidance for session_body tool
            if "session_body" in name:
                descriptions.append("   SECURITY NOTE: Use this tool to analyze script behavior, not just content.")
                descriptions.append("   Focus on: DOM manipulation, redirects, iframe injection, anti-analysis patterns.")
            
            if props:
                descriptions.append("   Parameters:")
                for param_name, param_info in props.items():
                    param_type = param_info.get("type", "any")
                    param_desc = param_info.get("description", "")
                    required = "required" if param_name in schema.get("required", []) else "optional"
                    descriptions.append(f"     - {param_name} ({param_type}, {required}): {param_desc}")
            descriptions.append("")
        
        # Add note about multiple tool calls
        descriptions.append("\n" + "="*80)
        descriptions.append("IMPORTANT: YOU CAN CALL ANY TOOL MULTIPLE TIMES!")
        descriptions.append("="*80)
        descriptions.append("")
        descriptions.append("You are NOT limited to one tool call per user request.")
        descriptions.append(f"You can call tools up to {self.max_followups} times to gather all necessary information.")
        descriptions.append("")
        descriptions.append("Common multi-call scenarios:")
        descriptions.append("  - List sessions, then analyze multiple session bodies")
        descriptions.append("  - Search for pattern, then examine each matching session")
        descriptions.append("  - Get suspicious sessions, then investigate top 5 in detail")
        descriptions.append("  - Discover attack chain, then trace each stage")
        descriptions.append("")
        descriptions.append("After EACH tool result, you can either:")
        descriptions.append("  a) Make ANOTHER tool call (no permission needed)")
        descriptions.append("  b) Provide your final analysis")
        descriptions.append("")
        descriptions.append("Make calls as needed to provide thorough, complete analysis!")
        descriptions.append("="*80 + "\n")
        
        return "\n".join(descriptions)

    def build_gemini_prompt(self, user_query: str) -> str:
        """Build comprehensive prompt for Gemini"""
        tool_descriptions = self.create_tool_descriptions()
        
        prompt = f"""You are an expert security analyst helping analyze web traffic captured by Fiddler.

{tool_descriptions}

SECURITY ANALYSIS MANDATE - CRITICAL FOR OBFUSCATED CODE:
When encountering obfuscated JavaScript (code with string arrays, hex encoding, complex control flow, or anti-debugging patterns), your primary objective is to perform a SECURITY ANALYSIS. Assume malicious intent until the code's behavior is proven to be benign. Do not accept embedded strings at face value without cross-validating them against the script's executable logic.

ANALYTICAL HIERARCHY - BEHAVIOR OVER CONTENT:
When analyzing a script, you MUST prioritize evidence in the following order:
1. EXECUTABLE ACTIONS: Identify and prioritize analysis of actions that modify the browser environment or user experience. This includes:
   - DOM manipulation (e.g., creating iframe, div, script elements)
   - Style changes (e.g., creating overlays with position:fixed, z-index:99999)
   - Redirection (window.location, document.location)
2. CONTROL FLOW & LOGIC: Analyze conditional checks (if/else), loops, and timers (setTimeout). Pay close attention to conditions that trigger actions, such as checks against:
   - document.referrer
   - localStorage
   - Counters or view limits
3. DATA AND API INTERACTION: Examine how the script interacts with:
   - localStorage
   - document.cookie
   - Network requests
4. STATIC CONTENT (STRINGS): Only after analyzing the behavior should you use embedded strings for context. Be highly skeptical of familiar-looking strings within obfuscated code, as they may be included as decoys to mislead analysis.

MANDATORY MALICIOUS PATTERN CHECKLIST:
For any obfuscated script, you MUST verify the presence or absence of the following patterns:
[ ] Iframe/Script Injection: Does the code dynamically create and append <iframe> or <script> elements to the DOM?
[ ] Redirection: Does the code manipulate window.location or document.location?
[ ] Anti-Analysis Techniques:
    [ ] Does it check document.referrer to alter its behavior?
    [ ] Does it use localStorage or cookies to implement view counters or persistent flags?
    [ ] Does it contain anti-debugging patterns (e.g., debugger; statements inside a loop)?
[ ] Overlay/UI Hijacking: Does the script apply CSS to create full-screen overlays (e.g., position:fixed, z-index:99999, width:100%)?
[ ] Dynamic Code Execution: Is eval() or new Function() used to execute strings as code?

HOLISTIC SYNTHESIS REQUIREMENT:
Your final conclusion MUST synthesize all evidence. If conflicting evidence is found (e.g., telemetry-like strings alongside ad-injection logic), you MUST address the discrepancy. Do not base your conclusion on a single piece of evidence if other behavioral indicators contradict it. State the script's most probable primary purpose based on the weight of the behavioral evidence.

HOW TO ANALYZE OBFUSCATED CODE:
When asked to "explain" or "analyze" a session, follow this structured approach:
1. Request the session body using fiddler_mcp__session_body
2. Identify if the code is obfuscated (string arrays, hex encoding, etc.)
3. If obfuscated, ASSUME MALICIOUS until proven otherwise
4. Analyze BEHAVIOR first:
   - What does the code DO (not what strings it contains)?
   - What DOM elements does it create?
   - What APIs does it call?
   - What conditions trigger its actions?
5. Check against the malicious pattern checklist
6. Only then consider static strings for context
7. Provide a holistic synthesis that reconciles all findings

IMPROVED REQUEST PHRASING EXAMPLES:
Instead of: "explain 265"
Use: "Analyze the behavior of the script in session 265. What actions does it perform on the webpage?"

Instead of: "what is this script doing"
Use: "Analyze session X for any malicious behavior, such as ad injection, redirects, or anti-analysis techniques."

Instead of: "show me the code"
Use: "Attempt to deobfuscate the script in session X and explain its primary function or purpose."

UNDERSTANDING SUSPICIOUS SESSIONS - CRITICAL DISTINCTION:
There are TWO types of suspicious sessions you may encounter:

1. FIDDLER-FLAGGED SUSPICIOUS SESSIONS:
   - Marked by Fiddler's internal risk assessment
   - May have various risk_reasons (large response, suspicious patterns, etc.)
   - Accessed via suspicious_only: true parameter
   - These are based on heuristics, not specific threat intelligence

2. EKFIDDLE-FLAGGED SESSIONS:
   - Have ekfiddle_comment field with SPECIFIC threat intelligence
   - This is AUTHORITATIVE intelligence from the EKFiddle extension
   - These are a SUBSET of suspicious sessions
   - Much higher confidence of actual threats

CRITICAL: Not all suspicious sessions have EKFiddle comments! Be VERY CLEAR about which type you're reporting to avoid confusion.

WHEN ASKED ABOUT SUSPICIOUS OR EKFIDDLE SESSIONS:

1. CALL THE TOOL FIRST:
   IMPORTANT: Use since_minutes=360 (6 hours) to capture ALL suspicious/EKFiddle sessions:
   {{"tool": "fiddler_mcp__live_sessions", "arguments": {{"suspicious_only": true, "limit": 100, "since_minutes": 360}}}}

2. ANALYZE AND REPORT CLEARLY:
   First, state the TOTALS:
   - "Found X suspicious sessions (Fiddler risk assessment)"
   - "Of these, Y have EKFiddle threat intelligence"
   
   If Y = 0, state clearly: "None of the suspicious sessions have EKFiddle threat intelligence comments."
   
3. CREATE APPROPRIATE LISTS:
   Format output as a table or structured list showing ONLY:
   - Session ID
   - Domain/Host (extract subdomain if present)
   - EKFiddle Comment/Alert Message
   
   Example format when EKFiddle sessions exist:
   ```
   SUMMARY: Found 62 suspicious sessions (Fiddler risk assessment).
   Of these, 3 have EKFiddle threat intelligence:
   
   EKFIDDLE-FLAGGED SESSIONS:
   Session 142 | cdn.malicious-ads.com | High: JavaScript obfuscation with eval()
   Session 158 | tracking.adnetwork.io | Medium: Suspicious redirect chain detected
   Session 201 | evil.example.org      | Critical: Known malware distribution site
   ```
   
   Example format when NO EKFiddle sessions exist:
   ```
   SUMMARY: Found 62 suspicious sessions (Fiddler risk assessment).
   None of these have EKFiddle threat intelligence comments.
   
   The suspicious sessions are based on Fiddler's heuristics (large responses, unusual patterns, etc.)
   but lack specific threat intelligence from EKFiddle.
   ```

3. PRIORITIZE BY SEVERITY:
   - List Critical/High severity first
   - Then Medium
   - Then Low (if present)
   - Extract severity from EKFiddle comment (Critical, High, Medium, Low)

4. EXTRACT KEY DOMAINS:
   After the list, summarize unique domains/subdomains that were flagged:
   ```
   FLAGGED DOMAINS TO INVESTIGATE:
   1. cdn.malicious-ads.com (1 session, High severity)
   2. evil.example.org (1 session, Critical severity)
   3. tracking.adnetwork.io (1 session, Medium severity)
   ```

5. SET INVESTIGATION FOCUS:
   End with: "These EKFiddle-flagged sessions should be the PRIMARY focus of code investigation.
   To analyze the code, use: fiddler_mcp__session_body with the session ID."

WHEN ASKED ABOUT MALICIOUS/SUSPICIOUS SESSIONS IN FOLLOW-UP:
If user asks "are there any malicious sessions?" or "show me suspicious traffic" AFTER you've listed EKFiddle flags:

1. AUTOMATICALLY FETCH CODE from the HIGHEST SEVERITY EKFiddle-flagged session:
   {{"tool": "fiddler_mcp__session_body", "arguments": {{"session_id": "<highest_severity_id>"}}}}

2. APPLY SECURITY ANALYSIS FRAMEWORK to that code
3. CORRELATE your analysis with the EKFiddle comment
4. If EKFiddle says "JavaScript obfuscation", LOOK FOR obfuscation patterns
5. If EKFiddle says "redirect chain", LOOK FOR window.location manipulation
6. If EKFiddle says "eval()", LOOK FOR dynamic code execution

EKFIDDLE COMMENT INTERPRETATION:
Common EKFiddle patterns and what to look for:
- "JavaScript obfuscation" → Check for string arrays, hex encoding, packed code
- "eval()" or "Function constructor" → Dynamic code execution pattern
- "redirect" → window.location, document.location manipulation
- "suspicious domain" → Check domain reputation, TLD
- "known malware" → Treat as HIGH PRIORITY threat
- "exploit kit" → Advanced threat, check for CVE references

TRUST HIERARCHY for THREAT ASSESSMENT:
1. HIGHEST: EKFiddle Comments (authoritative threat intelligence)
2. HIGH: Behavioral analysis (your malicious pattern checklist)
3. MEDIUM: Heuristics (file extensions, keywords)
4. LOWEST: String content (easily manipulated)

If EKFiddle has flagged something, it IS suspicious - focus analysis on CONFIRMING the threat type.

CRITICAL INSTRUCTIONS FOR TOOL CALLING:
1. When the user asks about Fiddler traffic, you MUST use the MCP tools listed above
2. To use a tool, respond with EXACTLY this JSON format (no markdown, no extra text, no code execution):
{{"tool": "tool_name", "arguments": {{"param": "value"}}}}

3. EXAMPLES OF CORRECT TOOL CALLS:
   - List sessions: {{"tool": "fiddler_mcp__live_sessions", "arguments": {{"limit": 50}}}}
   - Get body: {{"tool": "fiddler_mcp__session_body", "arguments": {{"session_id": "142"}}}}
   - Compare sessions: {{"tool": "fiddler_mcp__compare_sessions", "arguments": {{"session_ids": ["134", "148", "192", "194"]}}}}
   - Search: {{"tool": "fiddler_mcp__sessions_search", "arguments": {{"host_pattern": "facebook.net"}}}}

4. MAKE ONE TOOL CALL AT A TIME (not an array of calls)
5. After each tool result, decide if another call is needed
6. DO NOT use Python code execution or print() statements
7. DO NOT respond with {{"tool_code": ...}} - this is incorrect
8. DO NOT respond with [{{"tool_code": ...}}, ...] - this is an array and incorrect
9. After receiving tool results, you can either make another tool call OR provide analysis
10. For session IDs, always use them exactly as provided (they may be numbers or strings)

MULTI-SESSION COMPARISON - NEW CAPABILITY:
When user explicitly asks to COMPARE multiple sessions, use the fiddler_mcp__compare_sessions tool:

USE CASES FOR fiddler_mcp__compare_sessions:
- "Compare sessions 134, 148, 192, 194"
- "What are the differences between sessions X, Y, Z?"
- "Analyze sessions A, B, C and tell me how they fit together"
- "Compare the code from sessions 10, 20, 30"
- "Check sessions X, Y, Z and show me the similarities"

WHEN TO USE COMPARE vs SINGLE SESSION:
- User says "compare", "differences", "how do they fit together" → Use fiddler_mcp__compare_sessions
- User lists 2-10 specific session IDs to analyze together → Use fiddler_mcp__compare_sessions
- User asks about ONE session only → Use fiddler_mcp__session_body
- User asks "analyze top 5 EKFiddle" → Fetch ONE at a time with fiddler_mcp__session_body

EXAMPLE COMPARISON WORKFLOW:
User: "compare sessions 134, 148, 192, 194 check code from all fresh again and tell me the difference and summary of all - how does this all fit together"

Step 1: Call comparison tool:
{{"tool": "fiddler_mcp__compare_sessions", "arguments": {{"session_ids": ["134", "148", "192", "194"]}}}}

Step 2: Analyze ALL sessions together:
- Compare code structure and patterns
- Identify common functions, variables, strings
- Note KEY differences in behavior
- Explain the RELATIONSHIP (e.g., multi-stage attack, related scripts, same malware family)
- Provide HOLISTIC SUMMARY of how they all fit together

Step 3: Apply SECURITY ANALYSIS FRAMEWORK:
- Check malicious pattern checklist across ALL sessions
- Identify if they're part of a coordinated attack
- Note any progression or staging (loader → payload → C&C)
- Correlate with EKFiddle comments if present

COMPARISON ANALYSIS STRUCTURE:
1. OVERVIEW: "Comparing code from sessions X, Y, Z..."
2. COMMONALITIES: "All sessions share: [list patterns, functions, domains, etc.]"
3. DIFFERENCES: "Key differences: Session X does A, Session Y does B..."
4. RELATIONSHIPS: "How they fit together: Session X loads Session Y which executes Session Z..."
5. SYNTHESIS: "Overall assessment: This appears to be [type of attack/behavior]"

MULTIPLE TOOL CALLS - YOU CAN CALL TOOLS REPEATEDLY:

IMPORTANT: You are ALLOWED and ENCOURAGED to call tools multiple times to provide complete analysis!

YOU CAN MAKE UP TO {self.max_followups} TOOL CALLS in a single user request if needed to:
- Analyze multiple sessions sequentially (e.g., top 5 EKFiddle sessions)
- Fetch additional context after initial analysis
- Investigate related sessions discovered during analysis
- Gather comprehensive information for thorough security assessment
- Follow investigation leads as they emerge

HOW MULTIPLE TOOL CALLS WORK:

1. Make Initial Tool Call:
   {{"tool": "fiddler_mcp__live_sessions", "arguments": {{"suspicious_only": true, "limit": 100}}}}

2. After Receiving Results, You Can:
   a) Provide final analysis (if you have enough information)
   b) Make ANOTHER tool call to get more data (you don't need permission!)

3. Example Multi-Call Flow:
   First call:  List suspicious sessions
   Second call: Get body of highest risk session
   Third call:  Get body of another related session
   Fourth call: Search for similar patterns
   [Continue until you have complete picture, up to {self.max_followups} calls total]

4. When to Make Additional Calls:
   - You found suspicious sessions and need to examine their code
   - Initial session reveals references to other sessions
   - User asks for "comprehensive" or "detailed" analysis
   - You need to verify findings across multiple sessions
   - Investigation uncovers new leads
   - You need more context to provide confident assessment

5. When to Stop Making Calls:
   - You have sufficient information to answer the user's question
   - You've examined the most critical sessions
   - You've reached {self.max_followups} tool calls (system limit)
   - User explicitly asks for summary/conclusion

EXAMPLE WORKFLOWS WITH MULTIPLE CALLS:

Example 1: Analyzing EKFiddle Sessions
Query: "Analyze EKFiddle sessions in detail"

Call 1: {{"tool": "fiddler_mcp__live_sessions", "arguments": {{"suspicious_only": true}}}}
Result: Found 5 EKFiddle-flagged sessions

Call 2: {{"tool": "fiddler_mcp__session_body", "arguments": {{"session_id": "312"}}}}
Analysis: Session 312 has eval() - HIGH RISK

Call 3: {{"tool": "fiddler_mcp__session_body", "arguments": {{"session_id": "287"}}}}
Analysis: Session 287 has redirect chain - MEDIUM RISK

Call 4: {{"tool": "fiddler_mcp__session_body", "arguments": {{"session_id": "156"}}}}
Analysis: Session 156 is benign false positive

Final Response: Comprehensive threat assessment of all 3 sessions

Example 2: Investigating Attack Chain
Query: "Investigate suspicious sessions"

Call 1: {{"tool": "fiddler_mcp__live_sessions", "arguments": {{"suspicious_only": true}}}}
Result: Found suspicious iframe injection in session 100

Call 2: {{"tool": "fiddler_mcp__session_body", "arguments": {{"session_id": "100"}}}}
Analysis: Session 100 loads external script from session 105

Call 3: {{"tool": "fiddler_mcp__session_body", "arguments": {{"session_id": "105"}}}}
Analysis: Session 105 is the malicious payload

Final Response: Explains the 2-stage attack chain

IMPORTANT: Don't announce "I will make X calls" - just make them as needed!
Between each call, provide brief progress: "Analyzing session X..." then continue.

IMPORTANT WORKFLOW RULES:
- When user explicitly requests COMPARISON of multiple sessions → Use fiddler_mcp__compare_sessions (efficient, one call)
- When analyzing EKFiddle or suspicious sessions sequentially → Fetch ONE at a time with fiddler_mcp__session_body, make multiple calls
- DO NOT list "I will call session X, Y, Z..." - just make the calls as you analyze
- After each call, provide brief analysis THEN decide if another call is needed
- DO NOT repeat previous summaries - each response should ADD NEW information only
- Focus on HIGH risk sessions first, then MEDIUM only if user specifically asks
- You have a limit of {self.max_followups} tool calls per user query - use them wisely

PERFORMANCE OPTIMIZATION INSTRUCTIONS:
1. Be CONCISE in your initial responses - acknowledge the request in 1 sentence
2. For tool calls, don't provide lengthy explanations beforehand
3. After getting results, provide analysis WITHOUT repeating all raw data
4. If listing items, show only ESSENTIAL information (ID, domain, key finding)
5. Keep responses focused and actionable
6. Offer to provide more detail if needed, don't dump everything at once

RESPONSE SPEED PRIORITY:
- Make tool calls immediately without preamble
- Analyze results efficiently  
- Keep initial responses under 10 lines unless specifically asked for detail
- Focus on answering the specific question asked

CONVERSATION CONTEXT:
{self._format_recent_history(5)}

USER QUERY: {user_query}

YOUR RESPONSE (if tool needed, use JSON format above; otherwise natural language):"""
        return prompt

    def _format_recent_history(self, limit: int = 5) -> str:
        """Format recent conversation history"""
        if not self.conversation_history:
            return "No previous conversation."
        
        recent = self.conversation_history[-limit:]
        formatted = []
        for entry in recent:
            role = entry.get("role", "unknown")
            content = entry.get("content", "")
            if len(content) > 200:
                content = content[:200] + "..."
            formatted.append(f"[{role}] {content}")
        
        return "\n".join(formatted)

    def parse_gemini_response(self, response_text: str) -> Optional[Dict[str, Any]]:
        """Parse Gemini response for tool calls - handles multiple formats"""
        import re
        
        response_text = response_text.strip()
        
        if not response_text:
            return None
        
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            response_text = "\n".join(lines[1:-1]).strip()
        
        try:
            data = json.loads(response_text)
            return self._process_tool_call_data(data)
        except json.JSONDecodeError:
            pass
        
        json_patterns = [
            r'\{(?:[^{}]|\{[^{}]*\})*"tool(?:_code)?"(?:[^{}]|\{[^{}]*\})*\}',
            r'\[(?:[^\[\]]|\[[^\[\]]*\])*"tool(?:_code)?"(?:[^\[\]]|\[[^\[\]]*\])*\]',
        ]
        
        for pattern in json_patterns:
            matches = re.findall(pattern, response_text, re.DOTALL)
            for match in matches:
                try:
                    data = json.loads(match)
                    result = self._process_tool_call_data(data)
                    if result:
                        print("  Extracted tool call from mixed text/JSON response")
                        return result
                except json.JSONDecodeError:
                    continue
        
        plain_text_pattern = r'(fiddler_mcp__\w+)\((.*?)\)'
        match = re.search(plain_text_pattern, response_text)
        if match:
            tool_name = match.group(1)
            args_str = match.group(2)
            
            arguments = {}
            arg_matches = re.findall(r'(\w+)=(["\']?)([^,\'"]+)\2', args_str)
            for key, quote, value in arg_matches:
                if not quote and value.isdigit():
                    arguments[key] = int(value)
                else:
                    arguments[key] = value
            
            print(f"  Gemini used plain text format instead of JSON")
            print(f"    Extracted: {tool_name} with arguments {arguments}")
            return {"tool": tool_name, "arguments": arguments}
        
        return None
    
    def _extract_text_before_tool_call(self, response_text: str) -> str:
        """Extract text before tool call"""
        import re
        
        response_text = response_text.strip()
        
        json_patterns = [
            r'\{(?:[^{}]|\{[^{}]*\})*"tool(?:_code)?"(?:[^{}]|\{[^{}]*\})*\}',
            r'\[(?:[^\[\]]|\[[^\[\]]*\])*"tool(?:_code)?"(?:[^\[\]]|\[[^\[\]]*\])*\]',
        ]
        
        earliest_pos = len(response_text)
        
        for pattern in json_patterns:
            match = re.search(pattern, response_text, re.DOTALL)
            if match:
                earliest_pos = min(earliest_pos, match.start())
        
        plain_text_pattern = r'(fiddler_mcp__\w+)\('
        plain_match = re.search(plain_text_pattern, response_text)
        if plain_match:
            earliest_pos = min(earliest_pos, plain_match.start())
        
        if earliest_pos < len(response_text):
            explanatory_text = response_text[:earliest_pos].strip()
            explanatory_text = re.sub(r'(Tool Call|Next):\s*$', '', explanatory_text, flags=re.IGNORECASE).strip()
            return explanatory_text
        
        return response_text
    
    def _process_tool_call_data(self, data: Any) -> Optional[Dict[str, Any]]:
        """Process parsed JSON to extract tool call"""
        import re
        
        if isinstance(data, list):
            print(f"  Gemini returned multiple tool calls ({len(data)} calls)")
            print("   Processing first call only (will chain the rest)")
            if data:
                data = data[0]
            else:
                return None
        
        if not isinstance(data, dict):
            return None
        
        if "tool" in data and "arguments" in data:
            return data
        
        if "tool_code" in data:
            print("  Gemini used incorrect tool_code format instead of MCP tool calling")
            print("   Attempting to extract tool call from code...")
            
            code = data.get("tool_code", "")
            tool_name = None
            args_str = None
            
            match = re.search(r'(fiddler_mcp__\w+)\((.*?)\)', code)
            if match:
                tool_name = match.group(1)
                args_str = match.group(2)
            else:
                match = re.search(r'fiddler_mcp\.(\w+)\((.*?)\)', code)
                if match:
                    tool_suffix = match.group(1)
                    tool_name = f"fiddler_mcp__{tool_suffix}"
                    args_str = match.group(2)
            
            if tool_name and args_str is not None:
                arguments = {}
                arg_matches = re.findall(r'(\w+)=[\'"]([^\'"]+)[\'"]', args_str)
                for key, value in arg_matches:
                    arguments[key] = value
                
                print(f"    Extracted: {tool_name} with arguments {arguments}")
                return {"tool": tool_name, "arguments": arguments}
        
        return None
    
    def _looks_like_markdown(self, text: str) -> bool:
        """Detect if text contains markdown"""
        if not text or len(text) < 3:
            return False
        
        markdown_indicators = ['**', '__', '`', '# ', '## ', '### ', '* ', '- ', '+ ', '[', '|']
        return any(indicator in text for indicator in markdown_indicators)

    def chat(self, user_query: str) -> str:
        """Process user query with Gemini and execute tools as needed
        
        User can press Ctrl+C at any time to interrupt the model's response chain.
        """
        # Log the new query (log file only)
        self.log_with_timestamp(f"User query: {user_query[:100]}{'...' if len(user_query) > 100 else ''}", to_console=False, prefix="Client: ")
        
        # Add user query to history
        self.conversation_history.append({"role": "user", "content": user_query})
        
        # Build prompt
        self.log_with_timestamp("Building comprehensive prompt for Gemini...", to_console=False, prefix="Client: ")
        prompt = self.build_gemini_prompt(user_query)
        
        def extract_text_safe(resp) -> str:
            """Safely extract text from Gemini response, even if no Parts were returned."""
            try:
                return resp.text  # fast path
            except Exception:
                pass
            try:
                # Fallback: manual extraction
                candidates = getattr(resp, "candidates", []) or []
                if not candidates:
                    return ""
                first = candidates[0]
                # Log finish_reason if present
                finish_reason = getattr(first, "finish_reason", None)
                if finish_reason is not None and self.mcp_stderr_file and not self.mcp_stderr_file.closed:
                    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    self.mcp_stderr_file.write(f"[{ts}] Gemini finish_reason: {finish_reason}\n")
                    self.mcp_stderr_file.flush()
                content = getattr(first, "content", None)
                parts = getattr(content, "parts", []) if content else []
                # Concatenate any text parts
                texts = []
                for p in parts:
                    t = getattr(p, "text", None)
                    if isinstance(t, str) and t:
                        texts.append(t)
                return "\n".join(texts)
            except Exception:
                return ""

        # Track timing for query summary
        query_start_time = time.time()
        total_gemini_time = 0.0
        total_bridge_time = 0.0
        tool_call_count = 0
        
        try:
            # Get Gemini response with progress indicator (user can interrupt with Ctrl+C)
            prompt_length = len(prompt)
            estimated_tokens = self._estimate_tokens(prompt)
            
            # Enhanced Gemini request logging
            self.log_with_timestamp(f"Gemini Request: model={self.model_name}, type=initial_query", to_console=False)
            self.log_with_timestamp(f"Gemini Request: prompt_length={prompt_length} chars (~{estimated_tokens} tokens)", to_console=False)
            self.log_with_timestamp(f"Gemini Request: user_query=\"{user_query[:80]}{'...' if len(user_query) > 80 else ''}\"", to_console=False)
            
            # Show console feedback while waiting for Gemini
            sys.stdout.write("\r  Waiting for Gemini LLM response...")
            sys.stdout.flush()
            
            start_time = time.time()
            response = self.model.generate_content(prompt)
            elapsed_ms = int((time.time() - start_time) * 1000)
            elapsed_s = elapsed_ms / 1000
            total_gemini_time += elapsed_s
            
            # Clear the waiting message and show completion
            sys.stdout.write(f"\r  [Gemini LLM] Response received ({elapsed_s:.1f}s)                    \n")
            sys.stdout.flush()
            
            gemini_text = extract_text_safe(response)
            finish_reason = self._extract_finish_reason(response)
            candidates_count = self._count_candidates(response)
            
            # Enhanced Gemini response logging
            self.log_with_timestamp(f"Gemini Response: {elapsed_ms}ms, response_length={len(gemini_text)} chars", to_console=False)
            self.log_with_timestamp(f"Gemini Response: finish_reason={finish_reason}, candidates={candidates_count}", to_console=False)
            
            # If model produced no text (e.g., finish_reason blocked), retry once with stricter prompt
            if not gemini_text:
                self.log_with_timestamp(f"Gemini Warning: finish_reason={finish_reason}, response blocked/empty", to_console=False)
                self.log_with_timestamp("Gemini Warning: retrying with stricter prompt (temperature=0)", to_console=False)
                retry_prompt = prompt + "\n\nIMPORTANT: Respond ONLY with the JSON tool call format if a tool is needed, or a concise sentence otherwise."
                # Low temperature to reduce safety blocks/hallucinations
                start_retry = time.time()
                response = self.model.generate_content(retry_prompt, generation_config={"temperature": 0})
                retry_elapsed_ms = int((time.time() - start_retry) * 1000)
                total_gemini_time += retry_elapsed_ms / 1000
                retry_finish_reason = self._extract_finish_reason(response)
                self.log_with_timestamp(f"Gemini Retry: {retry_elapsed_ms}ms, finish_reason={retry_finish_reason}", to_console=False)
                gemini_text = extract_text_safe(response)
            
            # Check if Gemini wants to call a tool
            tool_call = self.parse_gemini_response(gemini_text)
            
            # Log tool detection result
            if tool_call:
                tool_name = tool_call["tool"]
                arguments = tool_call["arguments"]
                args_str = ", ".join(f"{k}={v}" for k, v in arguments.items())
                self.log_with_timestamp(f"Gemini Response: tool_call detected: {tool_name}({args_str})", to_console=False)
                self.log_with_timestamp(f"Tool Chain: starting (max_followups={self.max_followups})", to_console=False)
                
                # Execute the tool with timing
                bridge_start = time.time()
                tool_result = self.call_tool(tool_name, arguments)
                bridge_elapsed = time.time() - bridge_start
                total_bridge_time += bridge_elapsed
                tool_call_count += 1
                self.log_with_timestamp(f"Tool Chain: call #{tool_call_count} -> {tool_name} ({bridge_elapsed*1000:.0f}ms)", to_console=False)
                
                # Add tool result to history
                self.conversation_history.append({
                    "role": "tool",
                    "tool": tool_name,
                    "content": json.dumps(tool_result, indent=2)
                })
                
                # Ask Gemini to analyze the tool result with security framework
                self.log_with_timestamp("Preparing analysis prompt for tool results...", to_console=False, prefix="Client: ")
                
                analysis_prompt = f"""The tool '{tool_name}' returned this result:

{json.dumps(tool_result, indent=2)}

CRITICAL: Apply the SECURITY ANALYSIS FRAMEWORK to analyze this result.

User's original question: "{user_query}"

ANALYSIS REQUIREMENTS:
1. DISTINGUISH BETWEEN SUSPICIOUS TYPES:
   - "Suspicious sessions" = Fiddler's internal risk assessment (could be various reasons)
   - "EKFiddle-flagged sessions" = Sessions with ekfiddle_comment field (specific threat intelligence)
   - Be CLEAR about which type you're reporting

2. CHECK FOR EKFIDDLE COMMENTS:
   - Look for ekfiddle_comment field in EACH session
   - If present: This is AUTHORITATIVE threat intelligence from EKFiddle
   - If absent: Session may still be suspicious for OTHER reasons

3. REPORT CLEARLY:
   - State total suspicious sessions found
   - State how many have EKFiddle comments specifically
   - Example: "Found 62 suspicious sessions total. Of these, 3 have EKFiddle threat intelligence."

4. If response_body contains JavaScript, check if it's obfuscated

5. For security analysis, prioritize:
   - EKFiddle-flagged sessions FIRST (if any)
   - Then other high-risk suspicious sessions
   - Focus on BEHAVIOR over string content

If you need to call another tool, respond with JSON format: {{"tool": "tool_name", "arguments": {{...}}}}

Otherwise, provide your security-focused analysis."""
                
                # Log tool result size for context
                tool_result_str = json.dumps(tool_result, indent=2)
                tool_result_size = len(tool_result_str)
                analysis_prompt_len = len(analysis_prompt)
                self.log_with_timestamp(f"Gemini Request: type=tool_analysis, tool_result_size={self._format_size(tool_result_size)}", to_console=False)
                self.log_with_timestamp(f"Gemini Request: analysis_prompt_length={analysis_prompt_len} chars (~{self._estimate_tokens(analysis_prompt)} tokens)", to_console=False)
                
                # Show console feedback
                sys.stdout.write("\r  Waiting for Gemini LLM analysis...")
                sys.stdout.flush()
                
                analysis_start = time.time()
                analysis_response = self.model.generate_content(analysis_prompt)
                analysis_elapsed_ms = int((time.time() - analysis_start) * 1000)
                analysis_elapsed_s = analysis_elapsed_ms / 1000
                total_gemini_time += analysis_elapsed_s
                
                # Show completion
                sys.stdout.write(f"\r  [Gemini LLM] Analysis complete ({analysis_elapsed_s:.1f}s)                    \n")
                sys.stdout.flush()
                
                final_text = extract_text_safe(analysis_response)
                analysis_finish_reason = self._extract_finish_reason(analysis_response)
                
                # Enhanced analysis response logging
                self.log_with_timestamp(f"Gemini Response: {analysis_elapsed_ms}ms, response_length={len(final_text)} chars", to_console=False)
                self.log_with_timestamp(f"Gemini Response: finish_reason={analysis_finish_reason}", to_console=False)
                
                # If blocked, provide helpful error message
                if not final_text:
                    self.log_with_timestamp(f"Gemini Warning: finish_reason={analysis_finish_reason}, analysis blocked", to_console=False)
                    final_text = "Analysis blocked by safety filters. This may indicate the content contains potentially harmful code. Try: 'Analyze session X for malicious patterns' with a fresh request."
                
                current_text = final_text
                max_followups = self.max_followups
                followup_count = 0
                
                # Inform user they can interrupt if needed
                if self.show_progress:
                    print(f"  (Model can make up to {max_followups} tool calls. Press Ctrl+C at any time to interrupt)")
                
                while followup_count < max_followups:
                    next_tool_call = self.parse_gemini_response(current_text)
                    
                    if not next_tool_call:
                        # Log completion with query summary
                        total_time = time.time() - query_start_time
                        self.log_with_timestamp(f"Gemini Response: no further tool calls, providing analysis", to_console=False)
                        self.log_with_timestamp(f"Tool Chain: completed after {tool_call_count} tool calls", to_console=False)
                        self.log_with_timestamp(f"Query Summary: gemini_api={total_gemini_time:.1f}s, bridge={total_bridge_time:.1f}s, total={total_time:.1f}s", to_console=False)
                        self.log_with_timestamp(f"Query Summary: tool_calls={tool_call_count}, follow_ups={followup_count}", to_console=False)
                        self.conversation_history.append({"role": "assistant", "content": current_text})
                        return current_text
                    
                    explanatory_text = self._extract_text_before_tool_call(current_text)
                    
                    if explanatory_text.strip():
                        self.conversation_history.append({"role": "assistant", "content": explanatory_text})
                        if self.use_rich and self.console:
                            self.console.print("\n[bold cyan]< Gemini:[/bold cyan]")
                            if self._looks_like_markdown(explanatory_text):
                                from rich.markdown import Markdown
                                md = Markdown(explanatory_text)
                                self.console.print(md)
                            else:
                                self.console.print(explanatory_text)
                        else:
                            print(f"\n< Gemini: {explanatory_text}")
                    
                    next_tool_name = next_tool_call["tool"]
                    next_arguments = next_tool_call["arguments"]
                    next_args_str = ", ".join(f"{k}={v}" for k, v in next_arguments.items())
                    self.log_with_timestamp(f"Gemini Response: tool_call detected: {next_tool_name}({next_args_str})", to_console=False)
                    
                    # Execute follow-up tool with timing
                    bridge_start = time.time()
                    next_tool_result = self.call_tool(next_tool_name, next_arguments)
                    bridge_elapsed = time.time() - bridge_start
                    total_bridge_time += bridge_elapsed
                    tool_call_count += 1
                    self.log_with_timestamp(f"Tool Chain: call #{tool_call_count} -> {next_tool_name} ({bridge_elapsed*1000:.0f}ms)", to_console=False)
                    
                    self.conversation_history.append({
                        "role": "tool",
                        "tool": next_tool_name,
                        "content": json.dumps(next_tool_result, indent=2)
                    })
                    
                    followup_prompt = f"""The tool '{next_tool_name}' returned this result:

{json.dumps(next_tool_result, indent=2)}

CRITICAL: Apply SECURITY ANALYSIS FRAMEWORK. Analyze ONLY this new data. DO NOT repeat previous summary.

ANALYSIS REQUIREMENTS:
1. MAINTAIN CLARITY ON SUSPICIOUS TYPES:
   - Remember: "suspicious" doesn't always mean "EKFiddle-flagged"
   - Be clear about whether this session has ekfiddle_comment or not

2. CHECK FOR EKFIDDLE COMMENT:
   - If ekfiddle_comment present, this confirms threat intelligence
   - Note the EKFiddle assessment and use it to guide your analysis

3. If obfuscated JavaScript detected OR EKFiddle-flagged, run MALICIOUS PATTERN CHECKLIST:
   [ ] Iframe/Script Injection
   [ ] Redirection (window.location)
   [ ] Anti-Analysis (referrer checks, localStorage counters)
   [ ] Overlay/UI Hijacking (position:fixed, z-index)
   [ ] Dynamic Code Execution (eval, Function constructor)

3. Focus on BEHAVIOR over string content

4. CORRELATE with EKFiddle:
   - If EKFiddle says "eval()", verify eval() usage in code
   - If EKFiddle says "obfuscation", identify obfuscation techniques
   - If your analysis confirms EKFiddle: Strong threat confirmation

5. Provide HOLISTIC SYNTHESIS

Questions:
- What does this specific session's code DO (not what strings it contains)?
- Does your behavioral analysis CONFIRM the EKFiddle assessment?
- What are the key security findings?
- Do you need to check ONE more session? If yes, use JSON format: {{"tool": "tool_name", "arguments": {{...}}}}. If no, provide final recommendations."""
                    
                    # Log follow-up prompt details
                    followup_result_str = json.dumps(next_tool_result, indent=2)
                    followup_result_size = len(followup_result_str)
                    self.log_with_timestamp(f"Gemini Request: type=followup_analysis, tool_result_size={self._format_size(followup_result_size)}", to_console=False)
                    self.log_with_timestamp(f"Gemini Request: followup_prompt_length={len(followup_prompt)} chars (~{self._estimate_tokens(followup_prompt)} tokens)", to_console=False)
                    
                    # Show console feedback
                    sys.stdout.write(f"\r  Waiting for Gemini LLM follow-up #{followup_count}...")
                    sys.stdout.flush()
                    
                    followup_start = time.time()
                    followup_response = self.model.generate_content(followup_prompt)
                    followup_elapsed_ms = int((time.time() - followup_start) * 1000)
                    followup_elapsed_s = followup_elapsed_ms / 1000
                    total_gemini_time += followup_elapsed_s
                    
                    # Show completion
                    sys.stdout.write(f"\r  [Gemini LLM] Follow-up #{followup_count} complete ({followup_elapsed_s:.1f}s)                    \n")
                    sys.stdout.flush()
                    
                    current_text = extract_text_safe(followup_response)
                    followup_finish_reason = self._extract_finish_reason(followup_response)
                    
                    # Enhanced follow-up response logging
                    self.log_with_timestamp(f"Gemini Response: {followup_elapsed_ms}ms, response_length={len(current_text)} chars", to_console=False)
                    self.log_with_timestamp(f"Gemini Response: finish_reason={followup_finish_reason}", to_console=False)
                    
                    # Handle blocked responses
                    if not current_text:
                        self.log_with_timestamp(f"Gemini Warning: finish_reason={followup_finish_reason}, follow-up blocked", to_console=False)
                        current_text = "Follow-up analysis blocked by safety filters. The content may contain malicious code patterns."
                        # Log query summary even on blocked response
                        total_time = time.time() - query_start_time
                        self.log_with_timestamp(f"Query Summary: gemini_api={total_gemini_time:.1f}s, bridge={total_bridge_time:.1f}s, total={total_time:.1f}s", to_console=False)
                        self.conversation_history.append({"role": "assistant", "content": current_text})
                        return current_text
                    followup_count += 1
                
                # Reached max follow-ups - log query summary
                total_time = time.time() - query_start_time
                self.log_with_timestamp(f"Gemini Warning: reached max follow-up limit ({max_followups})", to_console=False)
                self.log_with_timestamp(f"Tool Chain: completed after {tool_call_count} tool calls (limit reached)", to_console=False)
                self.log_with_timestamp(f"Query Summary: gemini_api={total_gemini_time:.1f}s, bridge={total_bridge_time:.1f}s, total={total_time:.1f}s", to_console=False)
                self.log_with_timestamp(f"Query Summary: tool_calls={tool_call_count}, follow_ups={followup_count}", to_console=False)
                self.conversation_history.append({"role": "assistant", "content": current_text})
                return current_text
            else:
                # Direct response from Gemini (no tool needed)
                total_time = time.time() - query_start_time
                self.log_with_timestamp(f"Gemini Response: no tool call, direct response", to_console=False)
                self.log_with_timestamp(f"Query Summary: gemini_api={total_gemini_time:.1f}s, bridge=0.0s, total={total_time:.1f}s", to_console=False)
                self.log_with_timestamp(f"Query Summary: tool_calls=0, follow_ups=0", to_console=False)
                self.conversation_history.append({"role": "assistant", "content": gemini_text})
                return gemini_text
                
        except KeyboardInterrupt:
            # User pressed Ctrl+C to interrupt the model
            interrupt_msg = "\n\n[INTERRUPTED] User stopped the model's response chain. You can ask a new question or modify your prompt."
            print(interrupt_msg)
            self.log_with_timestamp("User interrupted with Ctrl+C", to_console=False, prefix="Client: ")
            self.conversation_history.append({"role": "system", "content": "[User interrupted the response]"})
            return interrupt_msg
                
        except Exception as e:
            error_msg = f"Error processing query: {e}"
            self.conversation_history.append({"role": "error", "content": error_msg})
            return error_msg

    def interactive_mode(self):
        """Run interactive chat session"""
        print("\n" + "=" * 70)
        print("Gemini-Powered Fiddler Traffic Analyzer")
        print("=" * 70)
        print("\nAsk questions about your Fiddler traffic in natural language!")
        print("Examples:")
        print("  - Show me recent sessions from the last 5 minutes")
        print("  - What hosts are in the captured traffic?")
        print("  - Show me the body of session 240")
        print("  - Are there any suspicious sessions?")
        print("  - Search for JavaScript files from example.com")
        print("\nCommands:")
        print("  /help    - Show example queries")
        print("  /stats   - Show bridge statistics")
        print("  /tools   - List available tools")
        print("  /model   - Show/change Gemini model")
        print("  /history - Show conversation history")
        print("  /clear   - Clear conversation history")
        print("  /quit    - Exit")
        print("\n" + "=" * 70)
        
        while True:
            try:
                user_input = input("\n> You: ").strip()
                
                if not user_input:
                    continue
                
                # Handle commands
                if user_input.startswith("/"):
                    if user_input == "/quit":
                        print("\nGoodbye!")
                        break
                    elif user_input == "/help":
                        self.show_help()
                    elif user_input == "/stats":
                        self.show_stats()
                    elif user_input == "/tools":
                        self.show_tools()
                    elif user_input == "/history":
                        self.show_history()
                    elif user_input == "/clear":
                        self.conversation_history.clear()
                        print("[+] Conversation history cleared")
                    elif user_input == "/model":
                        self.show_models()
                    elif user_input.startswith("/model "):
                        model_arg = user_input[7:].strip()
                        self.change_model(model_arg)
                    else:
                        print(f"Unknown command: {user_input}")
                    continue
                
                # Process natural language query
                response = self.chat(user_input)
                
                # Render response with rich formatting if available
                if self.use_rich and self.console:
                    self.console.print("\n[bold cyan]< Gemini:[/bold cyan]")
                    # Detect if response is markdown and render accordingly
                    if self._looks_like_markdown(response):
                        md = Markdown(response)
                        self.console.print(md)
                    else:
                        self.console.print(response)
                else:
                    print("\n< Gemini: ", end="", flush=True)
                    print(response)
                
            except KeyboardInterrupt:
                print("\n\nInterrupted. Type /quit to exit.")
            except Exception as e:
                print(f"\n[X] Error: {e}")

    def show_help(self):
        """Show example queries"""
        print("\n" + "=" * 70)
        print("Example Queries for Fiddler Traffic Analysis")
        print("=" * 70)
        print("\n[*] OVERVIEW QUERIES:")
        print("  - Show me statistics about the captured traffic")
        print("  - How many sessions are in the buffer?")
        print("  - What's the status of the Fiddler bridge?")
        print("\n[*] SESSION QUERIES:")
        print("  - Show me the last 20 sessions")
        print("  - Get sessions from the last 10 minutes")
        print("  - Show me only suspicious sessions")
        print("  - Find all sessions from example.com")
        print("\n[*] DETAILED ANALYSIS:")
        print("  - Show me the headers for session 189")
        print("  - Get the response body for session 240")
        print("  - Analyze session 191 for threats")
        print("\n[*] ADVANCED SEARCHES:")
        print("  - Search for POST requests with status 404")
        print("  - Find all JavaScript files from cdn.example.com")
        print("  - Show me sessions larger than 1MB")
        print("  - Get all failed requests (status >= 400)")
        print("\n[*] TIMELINE & PATTERNS:")
        print("  - Show me a timeline of traffic by host")
        print("  - Group sessions by status code")
        print("  - What's the traffic pattern for the last hour?")
        print("=" * 70)

    def show_stats(self):
        """Show current bridge statistics"""
        print("\n[*] Fetching bridge statistics...")
        result = self.call_tool("fiddler_mcp__live_stats", {})
        if "error" not in result:
            print(f"\n[+] Bridge Status: {result.get('bridge_status', 'Unknown')}")
            print(f"  Total Sessions: {result.get('total_sessions', 0)}")
            print(f"  Buffered: {result.get('buffered_sessions', 0)}")
            print(f"  Suspicious: {result.get('suspicious_sessions', 0)}")
            print(f"  Uptime: {result.get('uptime_hours', 0):.1f} hours")
            print(f"  Last Minute: {result.get('last_minute', 0)} sessions")
            print(f"  Last Hour: {result.get('last_hour', 0)} sessions")
        else:
            print(f"\n[X] Error: {result.get('error')}")

    def show_tools(self):
        """Show available MCP tools"""
        print("\n" + "=" * 70)
        print("Available Fiddler MCP Tools")
        print("=" * 70)
        for i, tool in enumerate(self.available_tools, 1):
            name = tool.get("name", "")
            desc = tool.get("description", "")
            print(f"\n{i}. {name}")
            print(f"   {desc}")
        print("=" * 70)

    def show_history(self):
        """Show conversation history"""
        print("\n" + "=" * 70)
        print("Conversation History")
        print("=" * 70)
        if not self.conversation_history:
            print("No conversation history yet.")
        else:
            for i, entry in enumerate(self.conversation_history, 1):
                role = entry.get("role", "unknown").upper()
                content = entry.get("content", "")
                tool = entry.get("tool", "")
                
                # Truncate long content
                if len(content) > 300:
                    content = content[:300] + "... [truncated]"
                
                if tool:
                    print(f"\n[{i}] {role} ({tool}):")
                else:
                    print(f"\n[{i}] {role}:")
                print(f"  {content}")
        print("=" * 70)

    def show_models(self):
        """Show available Gemini models and current selection"""
        print("\n" + "=" * 70)
        print("Available Gemini Models")
        print("=" * 70)
        print(f"\nCurrent model: {self.model_name}")
        print("\nAvailable models:")
        for num, name in AVAILABLE_MODELS.items():
            marker = " <-- CURRENT" if name == self.model_name else ""
            print(f"  {num}. {name}{marker}")
        print("\nTo switch: /model <number> or /model <name>")
        print("Example: /model 2  or  /model gemini-2.5-flash")
        print("=" * 70)

    def change_model(self, model_identifier: str):
        """Switch to a different Gemini model at runtime"""
        model_identifier = model_identifier.strip()
        
        # Resolve number to model name
        if model_identifier in AVAILABLE_MODELS:
            new_model = AVAILABLE_MODELS[model_identifier]
        elif model_identifier in AVAILABLE_MODELS.values():
            new_model = model_identifier
        else:
            print(f"[X] Unknown model: {model_identifier}")
            print("    Use /model to see available options")
            return
        
        if new_model == self.model_name:
            print(f"[*] Already using {new_model}")
            return
        
        old_model = self.model_name
        try:
            self.model = genai.GenerativeModel(new_model)
            self.model_name = new_model
            print(f"[+] Switched from {old_model} to {new_model}")
        except Exception as e:
            print(f"[X] Failed to switch model: {e}")

    def close(self):
        """Clean up resources"""
        if self.mcp_process:
            self.mcp_process.stdin.close()
            self.mcp_process.terminate()
            self.mcp_process.wait(timeout=5)
        if self.mcp_stderr_file:
            try:
                self.mcp_stderr_file.close()
            finally:
                self.mcp_stderr_file = None
        
        # Print session summary
        duration = (datetime.now() - self.session_start).total_seconds()
        print(f"\nSession duration: {duration:.1f} seconds")
        print(f"Queries processed: {len([h for h in self.conversation_history if h.get('role') == 'user'])}")


def load_config() -> Dict[str, str]:
    """Load configuration from file or environment"""
    config_file = Path(__file__).parent / "gemini-fiddler-config.json"
    
    # Try to load from config file
    if config_file.exists():
        try:
            with open(config_file) as f:
                config = json.load(f)
                if config.get("api_key"):
                    config.setdefault("auto_save_full_bodies", False)
                    return config
        except Exception:
            pass
    
    # Try environment variable
    api_key = os.getenv("GEMINI_API_KEY")
    if api_key:
        return {
            "api_key": api_key,
            "model": os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            "auto_save_full_bodies": os.getenv("GEMINI_AUTO_SAVE_FULL_BODIES", "false").lower() in {"1", "true", "yes", "on"},
        }
    
    return {}


def create_config_file():
    """Interactive config file creation"""
    print("\n" + "=" * 70)
    print("Gemini Fiddler Client - Configuration Setup")
    print("=" * 70)
    print("\nNo configuration found. Let's set it up!")
    print("\n1. Get your Gemini API key:")
    print("   https://makersuite.google.com/app/apikey")
    print("\n2. Enter your API key below:")
    
    api_key = input("\nGemini API Key: ").strip()
    
    if not api_key:
        print("[X] No API key provided. Exiting.")
        sys.exit(1)
    
    print("\n3. Select Gemini model:")
    print("\n   LATEST (Gemini 3):")
    print("   1. gemini-3-pro (LATEST)")
    print("\n   RECOMMENDED (Gemini 2.5):")
    print("   2. gemini-2.5-flash (Fast, recommended)")
    print("   3. gemini-2.0-flash")
    print("\n   POWERFUL:")
    print("   4. gemini-2.5-pro (Most capable)")
    print("   5. gemini-1.5-pro")
    print("\n   FAST & EFFICIENT:")
    print("   6. gemini-2.5-flash-lite")
    print("   7. gemini-2.0-flash-lite")
    print("   8. gemini-1.5-flash")
    print("   9. gemini-1.5-flash-8b")
    print("\n   EXPERIMENTAL:")
    print("   10. gemini-2.5-flash-preview")
    print("   11. gemini-2.0-flash-exp")
    print("\n   Enter number (1-11) or full model name")
    
    model_choice = input("\nModel [2 for gemini-2.5-flash]: ").strip() or "2"
    
    # Get model name from choice (uses centralized AVAILABLE_MODELS constant)
    if model_choice in AVAILABLE_MODELS:
        model = AVAILABLE_MODELS[model_choice]
    elif model_choice in AVAILABLE_MODELS.values():
        # User entered a model name directly
        model = model_choice
    else:
        # Unknown model name, use as-is (user may know a newer model)
        model = model_choice
    
    print(f"\n[+] Selected model: {model}")
    
    # Detect OS and use appropriate Python command
    import platform
    python_cmd = "python" if platform.system() == "Windows" else "python3"
    
    auto_save_prompt = input("\nSave full response bodies to disk automatically? [y/N]: ").strip().lower()
    auto_save_full_bodies = auto_save_prompt in {"y", "yes"}

    config = {
        "api_key": api_key,
        "model": model,
        "auto_save_full_bodies": auto_save_full_bodies,
        "mcp_server_command": [python_cmd, "5ire-bridge.py"],
        "bridge_url": "http://127.0.0.1:8081"
    }
    
    config_file = Path(__file__).parent / "gemini-fiddler-config.json"
    try:
        with open(config_file, "w") as f:
            json.dump(config, f, indent=2)
        print(f"\n[+] Configuration saved to {config_file}")
        return config
    except Exception as e:
        print(f"\n[X] Failed to save config: {e}")
        print("You can set the GEMINI_API_KEY environment variable instead.")
        return config


def main():
    """Main entry point"""
    import platform
    import signal
    
    client = None
    
    # Handle Ctrl+C gracefully
    def signal_handler(sig, frame):
        print("\n\n[!] Interrupted by user (Ctrl+C)")
        if client:
            print("[*] Cleaning up...")
            try:
                client.close()
            except:
                pass
        print("[+] Goodbye!")
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        print("\nGemini-Powered Fiddler Traffic Analyzer")
        print("=" * 70)
        
        # Load or create configuration
        config = load_config()
        if not config.get("api_key"):
            config = create_config_file()
        
        api_key = config.get("api_key")
        model = config.get("model", "gemini-2.5-flash")
        
        # Initialize client
        auto_save_bodies = config.get("auto_save_full_bodies", False)

        client = GeminiFiddlerClient(
            api_key=api_key,
            model_name=model,
            auto_save_full_bodies=auto_save_bodies,
        )
        
        # Start MCP server with OS-appropriate Python command
        python_cmd = "python" if platform.system() == "Windows" else "python3"
        server_command = config.get("mcp_server_command", [python_cmd, "5ire-bridge.py"])
        client.start_mcp_server(server_command)
        
        # MCP connection is initialized in start_mcp_server
        
        # List available tools with timeout
        print("[*] Discovering tools...")
        tools = client.list_tools()
        
        if not tools:
            print("[X] Failed to discover tools. Cannot continue.")
            print("[!] Make sure enhanced-bridge.py is running first!")
            sys.exit(1)
        
        print(f"[+] Ready with {len(tools)} tools:")
        for tool in tools:
            tool_name = tool.get("name", "unknown").replace("fiddler_mcp__", "")
            print(f"    - {tool_name}")
        
        try:
            # Run interactive mode
            client.interactive_mode()
        finally:
            # Cleanup
            if client:
                client.close()
    
    except KeyboardInterrupt:
        print("\n\n[!] Interrupted by user")
        if client:
            try:
                client.close()
            except:
                pass
        sys.exit(0)
    except Exception as e:
        print(f"\n[X] Fatal error: {e}")
        if client:
            try:
                client.close()
            except:
                pass
        sys.exit(1)


if __name__ == "__main__":
    main()
