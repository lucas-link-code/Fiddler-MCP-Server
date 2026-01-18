#!/usr/bin/env python3
"""
Enhanced Fiddler MCP Bridge with Improved Tool Accessibility
This version addresses naming conventions, schema clarity, and LLM usability issues
"""

import json
import sys
import asyncio
import requests
import time
import threading
import base64
from collections import Counter, deque
from datetime import datetime, timedelta
from typing import Dict, Any, List
from urllib.parse import urlparse
from flask import Flask, request, jsonify

MAX_BODY_PREVIEW_BYTES = 50_000
LARGE_BODY_WARNING_BYTES = 100_000

class EnhancedFiddlerMCPBridge:
    def __init__(self):
        self.capabilities = {
            "tools": {
                "listChanged": False
            }
        }
        
        # Real-time bridge configuration
        self.realtime_bridge_url = "http://localhost:8081"
        
        # Focused tool surface for manual traffic review
        self.tools = [
            {
                "name": "fiddler_mcp__live_sessions",
                "description": "List recent sessions with IDs, hosts, and status codes. Use this to decide what to inspect next; reasoning happens in the model.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "default": 30, "minimum": 1, "maximum": 200, "description": "Maximum number of sessions to return (1-200)."},
                        "since_minutes": {"type": "integer", "default": 60, "minimum": 1, "maximum": 360, "description": "How far back to look in minutes (1-360)."},
                        "host_filter": {"type": "string", "description": "Optional hostname substring or regex filter."},
                        "status_filter": {"type": "string", "description": "Filter by exact HTTP status code (e.g. '404')."},
                        "suspicious_only": {"type": "boolean", "default": False, "description": "Return only sessions flagged by the capture bridge."}
                    },
                    "additionalProperties": False
                }
            },
            {
                "name": "fiddler_mcp__sessions_search",
                "description": "Search buffered sessions by host, URL, status range, or method to build a review set.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "host_pattern": {"type": "string", "description": "Substring or regex to match hosts."},
                        "url_pattern": {"type": "string", "description": "Substring or regex to match URLs."},
                        "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD"], "description": "Filter by HTTP method."},
                        "status_min": {"type": "integer", "default": 0, "minimum": 0, "maximum": 999, "description": "Minimum HTTP status code."},
                        "status_max": {"type": "integer", "default": 999, "minimum": 0, "maximum": 999, "description": "Maximum HTTP status code."},
                        "content_type": {"type": "string", "description": "Optional MIME substring (e.g. 'javascript')."},
                        "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200, "description": "Maximum matches to return (1-200)."}
                    },
                    "additionalProperties": False
                }
            },
            {
                "name": "fiddler_mcp__session_headers",
                "description": "Fetch raw request and response headers for a session. The model should interpret any security impact itself.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string", "description": "Session ID from live sessions or search."}
                    },
                    "required": ["session_id"],
                    "additionalProperties": False
                }
            },
            {
                "name": "fiddler_mcp__session_body",
                "description": "Fetch raw request and response bodies for a session without automated scoring or classification.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string", "description": "Session ID from live sessions or search."},
                        "include_binary": {"type": "boolean", "default": False, "description": "When true, return base64 fields for non-text content."}
                    },
                    "required": ["session_id"],
                    "additionalProperties": False
                }
            },
            {
                "name": "fiddler_mcp__live_stats",
                "description": "Report buffer depth and capture cadence so the model understands collection context.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False
                }
            },
            {
                "name": "fiddler_mcp__sessions_timeline",
                "description": "Summarise buffered sessions over time to highlight spikes before deeper inspection.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "time_range_minutes": {"type": "integer", "default": 60, "minimum": 1, "maximum": 180, "description": "How far back to aggregate in minutes."},
                        "group_by": {"type": "string", "enum": ["minute", "host", "status_code", "content_type"], "default": "minute", "description": "Timeline grouping key."},
                        "include_details": {"type": "boolean", "default": True, "description": "Include representative session IDs per bucket."},
                        "filter_host": {"type": "string", "description": "Optional host substring filter."}
                    },
                    "additionalProperties": False
                }
            },
            {
                "name": "fiddler_mcp__sessions_clear",
                "description": "Clear live buffers after exporting data. Always confirm to avoid accidental loss.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "confirm": {"type": "boolean", "default": False, "description": "Set to true to confirm clearing buffers."},
                        "clear_suspicious": {"type": "boolean", "default": False, "description": "Also clear the suspicious session buffer."}
                    },
                    "additionalProperties": False
                }
            }
        ]


    async def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle MCP requests with enhanced error handling and logging"""
        
        try:
            if request.get("method") == "tools/list":
                return {
                    "jsonrpc": "2.0",
                    "id": request.get("id"),
                    "result": {
                        "tools": self.tools,
                        "_meta": {
                            "server_info": {
                                "name": "Enhanced Fiddler MCP Bridge",
                                "version": "2.0.0",
                                "description": "Improved accessibility and naming conventions"
                            }
                        }
                    }
                }
                
            elif request.get("method") == "tools/call":
                tool_name = request["params"]["name"]
                tool_args = request["params"].get("arguments", {})

                result = await self.execute_tool(tool_name, tool_args)

                return {
                    "jsonrpc": "2.0",
                    "id": request.get("id"),
                    "result": {
                        "content": [
                            {
                                "role": "function",
                                "parts": [
                                    {
                                        "functionResponse": {
                                            "name": tool_name,
                                            "response": result
                                        }
                                    }
                                ]
                            }
                        ],
                        "_meta": {
                            "tool_executed": tool_name,
                            "execution_time": datetime.now().isoformat()
                        }
                    }
                }
                
            elif request.get("method") == "initialize":
                return {
                    "jsonrpc": "2.0",
                    "id": request.get("id"), 
                    "result": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": self.capabilities,
                        "serverInfo": {
                            "name": "enhanced-fiddler-mcp",
                            "version": "2.0.0"
                        }
                    }
                }
                
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": request.get("id"),
                    "error": {
                        "code": -32601, 
                        "message": f"Method not found: {request.get('method')}",
                        "data": {
                            "available_methods": ["tools/list", "tools/call", "initialize"]
                        }
                    }
                }
                
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "error": {
                    "code": -32603,
                    "message": f"Internal error: {str(e)}",
                    "data": {
                        "error_type": type(e).__name__,
                        "timestamp": datetime.now().isoformat()
                    }
                }
            }

    async def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute tools with enhanced error handling and mapping"""
        
        # Map new tool names to streamlined implementations that return raw data
        tool_mapping = {
            "fiddler_mcp__live_sessions": "live.sessions",
            "fiddler_mcp__sessions_search": "sessions.search",
            "fiddler_mcp__session_headers": "session.headers",
            "fiddler_mcp__session_body": "session.body",
            "fiddler_mcp__live_stats": "live.stats",
            "fiddler_mcp__sessions_timeline": "sessions.timeline",
            "fiddler_mcp__sessions_clear": "sessions.clear"
        }
        
        original_tool_name = tool_mapping.get(tool_name, tool_name)
        
        try:
            if original_tool_name == "live.sessions":
                return await self.get_live_sessions(args)
            elif original_tool_name == "session.headers":
                return await self.get_session_headers(args)
            elif original_tool_name == "session.body":
                return await self.get_session_body(args)
            elif original_tool_name == "sessions.search":
                return await self.search_sessions(args)
            elif original_tool_name == "live.stats":
                return await self.get_live_stats()
            elif original_tool_name == "sessions.timeline":
                return await self.sessions_timeline(args)
            elif original_tool_name == "sessions.clear":
                return await self.sessions_clear(args)
            else:
                return {
                    "error": f"Unknown tool: {tool_name}",
                    "available_tools": list(tool_mapping.keys())
                }
                
        except Exception as e:
            return {
                "error": f"Tool execution failed: {str(e)}",
                "tool": tool_name,
                "error_type": type(e).__name__,
                "timestamp": datetime.now().isoformat()
            }

    async def get_live_sessions(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Enhanced live sessions with clear session ID extraction"""
        try:
            # Build query parameters with validation
            params = {}
            if args.get("limit"):
                params["limit"] = min(max(args["limit"], 1), 500)
            if args.get("since_minutes"):
                params["since_minutes"] = min(max(args["since_minutes"], 1), 360)
            if args.get("since_minutes"):
                params["since_minutes"] = min(max(args["since_minutes"], 1), 360)
            if args.get("host_filter"):
                params["host"] = args["host_filter"]
            if args.get("status_filter"):
                params["status"] = args["status_filter"]
            if args.get("suspicious_only"):
                params["suspicious_only"] = "true"
            
            # Query real-time bridge
            response = requests.get(f"{self.realtime_bridge_url}/api/sessions", params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            sessions = data.get("sessions", [])
            
            if not sessions:
                return {
                    "success": True,
                    "sessions": [],
                    "count": 0,
                    "message": "No sessions found matching criteria",
                    "bridge_status": "Connected",
                    "help": "Try adjusting filters or increasing time range"
                }
            
            # Enhanced session formatting with clear ID explanation
            formatted_sessions = []
            unique_hosts = set()
            
            for session in sessions:
                session_id = session.get("internal_id", session.get("id", "unknown"))
                host = session.get("host", "unknown")
                unique_hosts.add(host)
                
                formatted_session = {
                    "id": session_id,
                    "time": session.get("time") or datetime.fromtimestamp(session.get("received_at", time.time())).strftime("%H:%M:%S"),
                    "method": session.get("method", "GET"),
                    "url": session.get("url", ""),
                    "host": host,
                    "status": str(session.get("statusCode", "unknown")),
                    "statusCode": session.get("statusCode"),
                    "content_type": session.get("contentType", "").split(";")[0],
                    "size": session.get("contentLength", 0),
                    "is_https": session.get("is_https", session.get("scheme") == "https"),
                    "risk_flag": session.get("risk_flag"),
                    "risk_score": session.get("risk_score"),
                    "risk_level": session.get("risk_level"),
                    "risk_reasons": session.get("risk_reasons", []),
                    "received_at": session.get("received_at"),
                    "received_at_iso": session.get("received_at_iso"),
                }
                formatted_sessions.append(formatted_session)
            
            return {
                "success": True,
                "sessions": formatted_sessions,
                "count": len(formatted_sessions),
                "unique_hosts": sorted(list(unique_hosts)),
                "session_ids": [s["id"] for s in formatted_sessions],
                "message": f"Retrieved {len(formatted_sessions)} sessions with {len(unique_hosts)} unique hosts",
                "usage_note": "Use the 'id' field from sessions for detailed analysis with other tools",
                "bridge_status": "Connected",
                "query_timestamp": datetime.now().isoformat()
            }
            
        except requests.exceptions.ConnectionError:
            return {
                "success": False,
                "error": "Cannot connect to Fiddler real-time bridge",
                "bridge_status": "Disconnected",
                "help": "Ensure realtime-bridge.py is running on localhost:8081",
                "troubleshooting": [
                    "Check if realtime-bridge.py is running",
                    "Verify Fiddler is sending data to the bridge",
                    "Test with: curl http://localhost:8081/api/stats"
                ]
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to get live sessions: {str(e)}",
                "error_type": type(e).__name__
            }

    async def get_session_headers(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get detailed headers for a specific session"""
        try:
            session_id = args.get("session_id")
            if not session_id:
                return {
                    "error": "session_id parameter is required",
                    "help": "Get session IDs from fiddler_mcp__live_sessions or fiddler_mcp__sessions_search"
                }
            
            response = requests.get(f"{self.realtime_bridge_url}/api/sessions/headers/{session_id}", timeout=10)
            response.raise_for_status()

            data = response.json()
            if not data.get("success", False):
                return data

            return {
                "success": True,
                "session_id": session_id,
                "request_headers": data.get("request_headers", {}),
                "response_headers": data.get("response_headers", {}),
                "notes": [
                    "Use these headers to reason about authentication, caching, and security controls yourself."
                ]
            }
            
        except requests.exceptions.ConnectionError:
            return {
                "error": "Cannot connect to real-time bridge",
                "bridge_status": "Disconnected"
            }
        except Exception as e:
            return {
                "error": f"Failed to get session headers: {str(e)}",
                "session_id": session_id
            }

    async def get_session_body(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get request/response body for a specific session"""
        try:
            session_id = args.get("session_id")
            if not session_id:
                return {
                    "error": "session_id parameter is required",
                    "help": "Get session IDs from fiddler_mcp__live_sessions or fiddler_mcp__sessions_search"
                }
            
            include_binary = bool(args.get("include_binary"))

            response = requests.get(f"{self.realtime_bridge_url}/api/sessions/body/{session_id}", timeout=10)
            response.raise_for_status()

            data = response.json()

            if not data.get("success", False):
                return data

            result = {
                "success": True,
                "session_id": session_id,
                "content_type": data.get("content_type"),
                "content_length": data.get("content_length"),
                "request_body": data.get("request_body", ""),
                "response_body": data.get("response_body", ""),
                "truncated": data.get("truncated", False),
                "response_truncated": data.get("response_truncated", data.get("truncated", False)),
                "request_truncated": data.get("request_truncated", False),
                "full_size": data.get("full_size", {}),
                "notes": [
                    "Review bodies manually; no automated risk scoring is performed.",
                    "If content looks encoded or binary, request base64 via include_binary=true.",
                    "Fields 'response_truncated' and 'request_truncated' indicate when previews were shortened; consult 'full_size' for byte counts."
                ]
            }

            # Pass through EKFiddle data from Flask response
            result["ekfiddle_comments"] = data.get("ekfiddle_comments", "")
            result["ekfiddle_flags"] = data.get("ekfiddle_flags", "")
            result["session_flags"] = data.get("session_flags", "")

            if include_binary:
                # The real-time bridge currently returns text fields only; surface this clearly.
                if data.get("response_body_base64"):
                    result["response_body_base64"] = data.get("response_body_base64")
                else:
                    result.setdefault("warnings", []).append(
                        "Binary payload export not available from bridge; body is returned as-is."
                    )
                if data.get("request_body_base64"):
                    result["request_body_base64"] = data.get("request_body_base64")

            return result
            
        except requests.exceptions.ConnectionError:
            return {
                "error": "Cannot connect to real-time bridge",
                "bridge_status": "Disconnected"
            }
        except Exception as e:
            return {
                "error": f"Failed to get session body: {str(e)}",
                "session_id": session_id
            }

    async def search_sessions(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Enhanced session search with clear results"""
        try:
            params = {}
            if args.get("host_pattern"):
                params["host"] = args["host_pattern"]
            if args.get("url_pattern"):
                params["url"] = args["url_pattern"]
            if args.get("method"):
                params["method"] = args["method"]
            if args.get("status_min") is not None:
                params["status_min"] = args["status_min"]
            if args.get("status_max") is not None:
                params["status_max"] = args["status_max"]
            if args.get("limit"):
                params["limit"] = min(max(args["limit"], 1), 200)
            
            response = requests.get(f"{self.realtime_bridge_url}/api/sessions/search", params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            sessions = data.get("sessions", [])
            
            # Format results with clear session IDs
            formatted_sessions = []
            unique_hosts = set()
            
            for session in sessions:
                session_id = session.get("internal_id", session.get("id", "unknown"))
                host = session.get("host", "unknown")
                unique_hosts.add(host)

                formatted_sessions.append({
                    "id": session_id,
                    "host": host,
                    "url": session.get("url", ""),
                    "method": session.get("method", "GET"),
                    "status": str(session.get("statusCode", "unknown")),
                    "time": datetime.fromtimestamp(session.get("received_at", time.time())).strftime("%H:%M:%S"),
                    "content_type": session.get("contentType", "").split(";")[0],
                    "size": session.get("contentLength", 0),
                    "is_https": session.get("is_https", session.get("scheme") == "https"),
                    "risk_flag": session.get("risk_flag"),
                    "risk_score": session.get("risk_score"),
                    "risk_level": session.get("risk_level"),
                    "risk_reasons": session.get("risk_reasons", []),
                    "received_at": session.get("received_at"),
                    "received_at_iso": session.get("received_at_iso"),
                })
            
            return {
                "success": True,
                "sessions": formatted_sessions,
                "count": len(formatted_sessions),
                "unique_hosts": sorted(list(unique_hosts)),
                "session_ids": [s["id"] for s in formatted_sessions],
                "search_criteria": args,
                "message": f"Found {len(formatted_sessions)} sessions matching criteria"
            }
            
        except requests.exceptions.ConnectionError:
            return {
                "error": "Cannot connect to real-time bridge",
                "bridge_status": "Disconnected"
            }
        except Exception as e:
            return {
                "error": f"Search failed: {str(e)}",
                "search_criteria": args
            }

    async def analyze_live_session(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze specific session for threats"""
        try:
            session_id = args.get("session_id")
            if not session_id:
                return {
                    "error": "session_id parameter is required",
                    "help": "Get session IDs from fiddler_mcp__live_sessions"
                }
            
            response = requests.get(f"{self.realtime_bridge_url}/api/session/{session_id}", timeout=10)
            response.raise_for_status()
            
            return response.json()
            
        except requests.exceptions.ConnectionError:
            return {
                "error": "Cannot connect to real-time bridge",
                "bridge_status": "Disconnected"
            }
        except Exception as e:
            return {
                "error": f"Analysis failed: {str(e)}",
                "session_id": session_id
            }

    async def get_live_stats(self) -> Dict[str, Any]:
        """Get system statistics"""
        try:
            response = requests.get(f"{self.realtime_bridge_url}/api/stats", timeout=10)
            response.raise_for_status()
            
            stats = response.json()
            stats["bridge_status"] = "Connected"
            stats["timestamp"] = datetime.now().isoformat()
            
            return stats
            
        except requests.exceptions.ConnectionError:
            return {
                "error": "Real-time bridge is not running",
                "bridge_status": "Disconnected",
                "help": "Start with: python3 enhanced-bridge.py"
            }
        except Exception as e:
            return {
                "error": f"Failed to get stats: {str(e)}"
            }

    async def threat_hunt(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Hunt for threats in recent sessions"""
        try:
            params = {
                "hunt_type": args.get("hunt_type", "all"),
                "time_range": args.get("time_range_minutes", 30),
                "include_analysis": args.get("include_analysis", True)
            }
            
            response = requests.get(f"{self.realtime_bridge_url}/api/threat-hunt", params=params, timeout=30)
            response.raise_for_status()
            
            return response.json()
            
        except requests.exceptions.ConnectionError:
            return {
                "error": "Cannot connect to real-time bridge",
                "bridge_status": "Disconnected"
            }
        except Exception as e:
            return {
                "error": f"Threat hunt failed: {str(e)}",
                "hunt_criteria": args
            }

    # NEW: Specialized analysis functions for user's main use cases
    async def analyze_javascript(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze JavaScript content from a specific session"""
        try:
            session_id = args.get("session_id")
            if not session_id:
                return {
                    "error": "session_id parameter is required",
                    "help": "Get session IDs from fiddler_mcp__live_sessions"
                }
            
            # Get session body first
            body_response = await self.get_session_body({"session_id": session_id})
            if not body_response.get("success"):
                return body_response
            
            response_body = body_response.get("response_body", "")
            content_type = body_response.get("content_type", "")
            
            # Extract JavaScript content
            js_content = self.extract_js_from_content(response_body, content_type)
            
            if not js_content:
                return {
                    "success": False,
                    "error": "No JavaScript content found in session",
                    "session_id": session_id,
                    "content_type": content_type
                }
            
            # Analyze JavaScript
            analysis = self.analyze_js_content(js_content, args.get("include_security_analysis", True))
            
            return {
                "success": True,
                "session_id": session_id,
                "javascript_found": True,
                "content_type": content_type,
                "original_size": len(response_body),
                "javascript_size": len(js_content),
                "javascript_content": js_content[:1000] + "..." if len(js_content) > 1000 else js_content,
                "full_content_available": len(js_content) > 1000,
                "analysis": analysis,
                "usage_note": "This analyzes JavaScript from session response body"
            }
            
        except Exception as e:
            return {
                "error": f"JavaScript analysis failed: {str(e)}",
                "session_id": args.get("session_id")
            }

    async def analyze_domain(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Comprehensive domain analysis"""
        try:
            domain = args.get("domain")
            if not domain:
                return {
                    "error": "domain parameter is required",
                    "help": "Specify domain like 'example.com' or 'dot.example.com'"
                }
            
            time_range = args.get("time_range_minutes", 60)
            include_subdomains = args.get("include_subdomains", True)
            
            # Search for sessions from this domain
            search_pattern = domain if not include_subdomains else domain
            search_response = await self.search_sessions({
                "host_pattern": search_pattern,
                "limit": 200
            })
            
            if not search_response.get("success"):
                return search_response
            
            sessions = search_response.get("sessions", [])
            
            if not sessions:
                return {
                    "success": True,
                    "domain": domain,
                    "sessions_found": 0,
                    "message": f"No sessions found for domain {domain}",
                    "time_range_minutes": time_range
                }
            
            # Analyze all sessions for this domain
            domain_analysis = await self.comprehensive_domain_analysis(sessions, domain, args)
            
            return {
                "success": True,
                "domain": domain,
                "sessions_found": len(sessions),
                "time_range_minutes": time_range,
                "analysis": domain_analysis,
                "session_ids": [s["id"] for s in sessions],
                "usage_note": "Complete analysis of all traffic involving this domain"
            }
            
        except Exception as e:
            return {
                "error": f"Domain analysis failed: {str(e)}",
                "domain": args.get("domain")
            }

    async def extract_javascript(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Extract all JavaScript from domain sessions"""
        try:
            domain = args.get("domain")
            if not domain:
                return {
                    "error": "domain parameter is required",
                    "help": "Specify domain to extract JavaScript from"
                }
            
            # Search for sessions from this domain
            search_response = await self.search_sessions({
                "host_pattern": domain,
                "limit": 200
            })
            
            if not search_response.get("success"):
                return search_response
            
            sessions = search_response.get("sessions", [])
            
            if not sessions:
                return {
                    "success": True,
                    "domain": domain,
                    "javascript_found": False,
                    "message": f"No sessions found for domain {domain}"
                }
            
            # Extract JavaScript from all sessions
            js_extractions = []
            content_types = args.get("content_types", ["application/javascript", "text/javascript", "application/x-javascript"])
            
            for session in sessions:
                session_id = session["id"]
                
                # Get session body
                body_response = await self.get_session_body({"session_id": session_id})
                if body_response.get("success"):
                    response_body = body_response.get("response_body", "")
                    content_type = body_response.get("content_type", "")
                    
                    # Check if this is JavaScript content
                    if any(js_type in content_type.lower() for js_type in content_types) or \
                       (args.get("include_inline_js", True) and "text/html" in content_type.lower()):
                        
                        js_content = self.extract_js_from_content(response_body, content_type)
                        if js_content:
                            js_extractions.append({
                                "session_id": session_id,
                                "url": session.get("url", ""),
                                "content_type": content_type,
                                "javascript_size": len(js_content),
                                "javascript_content": js_content[:2000] + "..." if len(js_content) > 2000 else js_content,
                                "full_content_available": len(js_content) > 2000,
                                "analysis": self.analyze_js_content(js_content, True)
                            })
            
            return {
                "success": True,
                "domain": domain,
                "sessions_searched": len(sessions),
                "javascript_sessions_found": len(js_extractions),
                "extractions": js_extractions,
                "total_js_size": sum(e["javascript_size"] for e in js_extractions),
                "usage_note": "All JavaScript found in domain responses with security analysis"
            }
            
        except Exception as e:
            return {
                "error": f"JavaScript extraction failed: {str(e)}",
                "domain": args.get("domain")
            }

    async def analyze_traffic(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Bidirectional traffic analysis"""
        try:
            domain = args.get("domain")
            if not domain:
                return {
                    "error": "domain parameter is required",
                    "help": "Specify domain to analyze traffic patterns for"
                }
            
            direction = args.get("direction", "both")
            group_by = args.get("group_by", "url_pattern")
            
            # Search for sessions involving this domain
            search_response = await self.search_sessions({
                "host_pattern": domain,
                "limit": 200
            })
            
            if not search_response.get("success"):
                return search_response
            
            sessions = search_response.get("sessions", [])
            
            if not sessions:
                return {
                    "success": True,
                    "domain": domain,
                    "traffic_found": False,
                    "message": f"No traffic found for domain {domain}"
                }
            
            # Analyze traffic patterns
            traffic_analysis = self.analyze_traffic_patterns(sessions, domain, direction, group_by)
            
            return {
                "success": True,
                "domain": domain,
                "direction_analyzed": direction,
                "sessions_analyzed": len(sessions),
                "analysis": traffic_analysis,
                "usage_note": f"Traffic pattern analysis for {domain} showing {direction} traffic"
            }
            
        except Exception as e:
            return {
                "error": f"Traffic analysis failed: {str(e)}",
                "domain": args.get("domain")
            }

    def extract_js_from_content(self, content: str, content_type: str) -> str:
        """Extract JavaScript from response content"""
        if not content:
            return ""
        
        import re
        
        # If it's already JavaScript content type, return as-is
        if any(js_type in content_type.lower() for js_type in ["javascript", "ecmascript"]):
            return content
        
        # If it's HTML, extract JavaScript from script tags
        if "html" in content_type.lower():
            # Extract content from <script> tags
            script_pattern = r'<script[^>]*>(.*?)</script>'
            scripts = re.findall(script_pattern, content, re.DOTALL | re.IGNORECASE)
            return "\n\n// --- Script separation ---\n\n".join(scripts) if scripts else ""
        
        return ""

    def analyze_js_content(self, js_content: str, include_security: bool = True) -> Dict[str, Any]:
        """Analyze JavaScript content for patterns and security issues"""
        if not js_content:
            return {"error": "No JavaScript content to analyze"}
        
        analysis = {
            "size": len(js_content),
            "line_count": js_content.count('\n') + 1,
            "minified": self.is_minified(js_content),
            "obfuscated": self.is_obfuscated(js_content),
            "functions_found": self.count_functions(js_content),
            "external_calls": self.find_external_calls(js_content),
            "summary": self.generate_js_summary(js_content)
        }
        
        if include_security:
            analysis["security"] = self.analyze_js_security(js_content)
        
        return analysis

    def is_minified(self, js_content: str) -> bool:
        """Check if JavaScript appears minified"""
        lines = js_content.split('\n')
        avg_line_length = sum(len(line) for line in lines) / len(lines) if lines else 0
        return avg_line_length > 100 or len(lines) < 10

    def is_obfuscated(self, js_content: str) -> bool:
        """Check for common obfuscation patterns"""
        obfuscation_indicators = [
            "eval(", "atob(", "btoa(", "unescape(", "String.fromCharCode(",
            "\\x", "\\u", "_0x", "var _"
        ]
        return any(indicator in js_content for indicator in obfuscation_indicators)

    def count_functions(self, js_content: str) -> int:
        """Count function definitions"""
        import re
        function_pattern = r'function\s+\w+\s*\(|\w+\s*=\s*function|\w+\s*:\s*function'
        return len(re.findall(function_pattern, js_content, re.IGNORECASE))

    def find_external_calls(self, js_content: str) -> List[str]:
        """Find external API calls and URLs"""
        import re
        url_pattern = r'https?://[^\s\'"<>]+'
        urls = re.findall(url_pattern, js_content)
        return list(set(urls))[:10]  # Limit to 10 unique URLs

    def generate_js_summary(self, js_content: str) -> str:
        """Generate a summary of what the JavaScript does"""
        keywords = {
            "DOM manipulation": ["document.", "getElementById", "querySelector", "innerHTML", "appendChild"],
            "Network requests": ["XMLHttpRequest", "fetch(", "ajax", "$.get", "$.post"],
            "Event handling": ["addEventListener", "onclick", "onload", "$(document).ready"],
            "Data processing": ["JSON.parse", "JSON.stringify", "map(", "filter(", "reduce("],
            "Analytics/Tracking": ["analytics", "gtag", "_gaq", "track", "pixel"]
        }
        
        found_categories = []
        for category, terms in keywords.items():
            if any(term in js_content for term in terms):
                found_categories.append(category)
        
        return f"JavaScript appears to handle: {', '.join(found_categories)}" if found_categories else "Basic JavaScript functionality"

    def analyze_js_security(self, js_content: str) -> Dict[str, Any]:
        """Analyze JavaScript for security issues"""
        security_issues = []
        risk_score = 0.0
        
        # Check for dangerous functions
        dangerous_functions = ["eval", "innerHTML", "document.write", "setTimeout", "setInterval"]
        for func in dangerous_functions:
            if func in js_content:
                security_issues.append(f"Uses potentially dangerous function: {func}")
                risk_score += 0.2
        
        # Check for obfuscation (security red flag)
        if self.is_obfuscated(js_content):
            security_issues.append("Code appears obfuscated - potential malware indicator")
            risk_score += 0.4
        
        # Check for external domains
        external_urls = self.find_external_calls(js_content)
        if external_urls:
            security_issues.append(f"Makes external calls to: {', '.join(external_urls[:3])}")
            risk_score += 0.1 * len(external_urls)
        
        return {
            "risk_score": min(risk_score, 1.0),
            "risk_level": "HIGH" if risk_score > 0.7 else "MEDIUM" if risk_score > 0.3 else "LOW",
            "issues_found": security_issues,
            "external_domains": external_urls
        }

    async def comprehensive_domain_analysis(self, sessions: List[Dict], domain: str, args: Dict) -> Dict[str, Any]:
        """Perform comprehensive analysis of domain traffic"""
        analysis = {
            "request_patterns": {},
            "response_analysis": {},
            "status_codes": {},
            "content_types": {},
            "security_headers": {},
            "purposes_identified": []
        }
        
        for session in sessions:
            # Analyze status codes
            status = session.get("status", "unknown")
            analysis["status_codes"][status] = analysis["status_codes"].get(status, 0) + 1
            
            # Get headers if requested
            if args.get("include_content_analysis", True):
                try:
                    headers_response = await self.get_session_headers({"session_id": session["id"]})
                    if headers_response.get("success"):
                        # Analyze security headers
                        response_headers = headers_response.get("response_headers", {})
                        for header in ["Content-Security-Policy", "X-Frame-Options", "Strict-Transport-Security"]:
                            if header in response_headers:
                                analysis["security_headers"][header] = response_headers[header]
                except:
                    pass
        
        # Identify purposes
        purposes = self.identify_domain_purposes(sessions)
        analysis["purposes_identified"] = purposes
        
        return analysis

    def analyze_traffic_patterns(self, sessions: List[Dict], domain: str, direction: str, group_by: str) -> Dict[str, Any]:
        """Analyze traffic patterns and meanings"""
        patterns = {
            "total_requests": len(sessions),
            "request_methods": {},
            "url_patterns": {},
            "purposes": [],
            "timing_analysis": {},
            "explanations": []
        }
        
        # Group by specified criteria
        for session in sessions:
            method = session.get("method", "GET")
            patterns["request_methods"][method] = patterns["request_methods"].get(method, 0) + 1
            
            url = session.get("url", "")
            # Identify URL patterns
            if "/api/" in url:
                patterns["purposes"].append("API calls")
            elif ".js" in url:
                patterns["purposes"].append("JavaScript loading")
            elif ".css" in url:
                patterns["purposes"].append("Stylesheet loading")
            elif any(img_ext in url for img_ext in [".jpg", ".png", ".gif", ".svg"]):
                patterns["purposes"].append("Image loading")
        
        # Generate explanations
        patterns["explanations"] = self.generate_traffic_explanations(patterns, domain, direction)
        patterns["purposes"] = list(set(patterns["purposes"]))  # Remove duplicates
        
        return patterns

    def identify_domain_purposes(self, sessions: List[Dict]) -> List[str]:
        """Identify what the domain is used for based on traffic patterns"""
        purposes = []
        
        urls = [session.get("url", "") for session in sessions]
        all_urls = " ".join(urls)
        
        if any("/api/" in url for url in urls):
            purposes.append("API service")
        if any("analytics" in url or "track" in url for url in urls):
            purposes.append("Analytics/Tracking")
        if any(".js" in url for url in urls):
            purposes.append("JavaScript hosting")
        if any("cdn" in url for url in urls):
            purposes.append("Content delivery")
        if any("auth" in url or "login" in url for url in urls):
            purposes.append("Authentication")
        
        return purposes

    def generate_traffic_explanations(self, patterns: Dict, domain: str, direction: str) -> List[str]:
        """Generate human-readable explanations of traffic patterns"""
        explanations = []
        
        total = patterns["total_requests"]
        explanations.append(f"Total of {total} requests involving {domain}")
        
        # Method analysis
        methods = patterns["request_methods"]
        if methods.get("GET", 0) > methods.get("POST", 0):
            explanations.append("Primarily GET requests - likely content retrieval")
        elif methods.get("POST", 0) > 0:
            explanations.append("POST requests present - data submission or API calls")
        
        # Purpose analysis
        purposes = patterns["purposes"]
        if purposes:
            explanations.append(f"Identified purposes: {', '.join(purposes)}")
        
        return explanations

    # ADDITIONAL REQUESTED TOOLS IMPLEMENTATION
    async def extract_iocs(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Extract Indicators of Compromise from recent sessions"""
        try:
            time_range = args.get("time_range_minutes", 60)
            ioc_types = args.get("ioc_types", ["domains", "ips", "urls", "hashes"])
            suspicious_only = args.get("include_suspicious_only", False)
            
            # Get recent sessions
            search_args = {"limit": 200}
            if suspicious_only:
                search_args["suspicious_only"] = True
            
            sessions_response = await self.get_live_sessions(search_args)
            if not sessions_response.get("success"):
                return sessions_response
            
            sessions = sessions_response.get("sessions", [])
            
            # Extract IOCs
            iocs = {
                "domains": set(),
                "ips": set(), 
                "urls": set(),
                "hashes": set()
            }
            
            import re
            
            for session in sessions:
                if "domains" in ioc_types:
                    host = session.get("host", "")
                    if host:
                        iocs["domains"].add(host)
                
                if "urls" in ioc_types:
                    url = session.get("url", "")
                    if url:
                        iocs["urls"].add(url)
                
                # Extract IPs and hashes from session content if needed
                if "ips" in ioc_types or "hashes" in ioc_types:
                    try:
                        body_response = await self.get_session_body({"session_id": session["id"]})
                        if body_response.get("success"):
                            content = body_response.get("response_body", "")
                            
                            if "ips" in ioc_types:
                                # Extract IP addresses
                                ip_pattern = r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b'
                                ips = re.findall(ip_pattern, content)
                                iocs["ips"].update(ips)
                            
                            if "hashes" in ioc_types:
                                # Extract common hash formats
                                hash_patterns = [
                                    r'\b[a-fA-F0-9]{32}\b',  # MD5
                                    r'\b[a-fA-F0-9]{40}\b',  # SHA1
                                    r'\b[a-fA-F0-9]{64}\b'   # SHA256
                                ]
                                for pattern in hash_patterns:
                                    hashes = re.findall(pattern, content)
                                    iocs["hashes"].update(hashes)
                    except:
                        continue
            
            # Convert sets to lists and limit results
            result_iocs = {}
            for ioc_type, values in iocs.items():
                if ioc_type in ioc_types:
                    result_iocs[ioc_type] = list(values)[:50]  # Limit to 50 per type
            
            return {
                "success": True,
                "time_range_minutes": time_range,
                "sessions_analyzed": len(sessions),
                "ioc_types_extracted": ioc_types,
                "iocs": result_iocs,
                "total_iocs": sum(len(v) for v in result_iocs.values()),
                "usage_note": "IOCs extracted from session traffic and content"
            }
            
        except Exception as e:
            return {
                "error": f"IOC extraction failed: {str(e)}",
                "time_range": args.get("time_range_minutes", 60)
            }

    async def live_monitor(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Continuous monitoring with real-time alerts"""
        try:
            duration = args.get("duration_minutes", 10)
            alert_threshold = args.get("alert_threshold", 0.6)
            focus_hosts = args.get("focus_hosts", [])
            alert_types = args.get("alert_types", ["malware", "suspicious", "anomaly"])
            
            # Get current sessions for monitoring
            sessions_response = await self.get_live_sessions({"limit": 200})
            if not sessions_response.get("success"):
                return sessions_response
            
            sessions = sessions_response.get("sessions", [])
            
            # Filter by focus hosts if specified
            if focus_hosts:
                sessions = [s for s in sessions if any(host.lower() in s.get("host", "").lower() for host in focus_hosts)]
            
            # Analyze sessions for alerts
            alerts = []
            anomalies = []
            
            for session in sessions:
                session_id = session["id"]
                
                # Basic risk assessment
                risk_score = 0.0
                risk_factors = []
                
                # Check for suspicious patterns
                url = session.get("url", "")
                host = session.get("host", "")
                status = session.get("status", "200")
                
                if "malware" in alert_types:
                    if any(term in url.lower() for term in ["download", "update", "install", "security"]):
                        risk_score += 0.3
                        risk_factors.append("Potential fake update pattern")
                
                if "suspicious" in alert_types:
                    if int(status) >= 400:
                        risk_score += 0.2
                        risk_factors.append(f"Error status code: {status}")
                
                if "anomaly" in alert_types:
                    if session.get("size", 0) > 10000000:  # 10MB
                        risk_score += 0.2
                        risk_factors.append("Unusually large response")
                
                # Generate alert if above threshold
                if risk_score >= alert_threshold:
                    alerts.append({
                        "session_id": session_id,
                        "timestamp": session.get("time", ""),
                        "risk_score": risk_score,
                        "risk_factors": risk_factors,
                        "url": url,
                        "host": host,
                        "alert_level": "CRITICAL" if risk_score >= 0.8 else "HIGH" if risk_score >= 0.6 else "MEDIUM"
                    })
            
            return {
                "success": True,
                "monitoring_duration": duration,
                "alert_threshold": alert_threshold,
                "sessions_monitored": len(sessions),
                "alerts_generated": len(alerts),
                "alerts": alerts[:20],  # Limit to 20 alerts
                "focus_hosts": focus_hosts,
                "summary": f"Monitored {len(sessions)} sessions, generated {len(alerts)} alerts above threshold {alert_threshold}"
            }
            
        except Exception as e:
            return {
                "error": f"Live monitoring failed: {str(e)}",
                "duration": args.get("duration_minutes", 10)
            }

    async def sessions_timeline(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Generate timeline analysis of sessions"""
        try:
            time_range = args.get("time_range_minutes", 30)
            group_by = args.get("group_by", "minute")
            include_details = args.get("include_details", True)
            filter_host = args.get("filter_host")
            
            # Get sessions for timeline
            search_args = {"limit": 200}
            if filter_host:
                search_args["host_filter"] = filter_host
            
            sessions_response = await self.get_live_sessions(search_args)
            if not sessions_response.get("success"):
                return sessions_response
            
            sessions = sessions_response.get("sessions", [])
            
            # Group sessions by specified criteria
            timeline = {}
            
            for session in sessions:
                if group_by == "minute":
                    # Group by minute timestamp
                    key = session.get("time", "").split(":")[0:2]  # HH:MM
                    key = ":".join(key) if len(key) == 2 else "unknown"
                elif group_by == "host":
                    key = session.get("host", "unknown")
                elif group_by == "status_code":
                    key = session.get("status", "unknown")
                elif group_by == "content_type":
                    key = session.get("content_type", "unknown")
                else:
                    key = "default"
                
                if key not in timeline:
                    timeline[key] = {
                        "count": 0,
                        "sessions": [] if include_details else None
                    }
                
                timeline[key]["count"] += 1
                if include_details:
                    timeline[key]["sessions"].append({
                        "id": session["id"],
                        "time": session.get("time", ""),
                        "url": session.get("url", ""),
                        "host": session.get("host", ""),
                        "status": session.get("status", "")
                    })
            
            # Sort timeline by key
            sorted_timeline = dict(sorted(timeline.items()))
            
            return {
                "success": True,
                "time_range_minutes": time_range,
                "group_by": group_by,
                "filter_host": filter_host,
                "timeline_entries": len(sorted_timeline),
                "total_sessions": sum(entry["count"] for entry in sorted_timeline.values()),
                "timeline": sorted_timeline,
                "usage_note": f"Timeline grouped by {group_by} showing session patterns"
            }
            
        except Exception as e:
            return {
                "error": f"Timeline generation failed: {str(e)}",
                "group_by": args.get("group_by", "minute")
            }

    async def sessions_export(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Export session data in various formats"""
        try:
            format_type = args.get("format", "json")
            time_range = args.get("time_range_minutes", 60)
            include_bodies = args.get("include_bodies", False)
            filter_host = args.get("filter_host")
            limit = args.get("limit", 100)
            
            # Get sessions to export
            search_args = {"limit": min(limit, 1000)}
            if filter_host:
                search_args["host_filter"] = filter_host
            
            sessions_response = await self.get_live_sessions(search_args)
            if not sessions_response.get("success"):
                return sessions_response
            
            sessions = sessions_response.get("sessions", [])
            
            # Enhance sessions with bodies if requested
            if include_bodies:
                enhanced_sessions = []
                for session in sessions[:50]:  # Limit to 50 when including bodies
                    try:
                        body_response = await self.get_session_body({"session_id": session["id"]})
                        if body_response.get("success"):
                            session["request_body"] = body_response.get("request_body", "")
                            session["response_body"] = body_response.get("response_body", "")[:1000]  # Truncate
                    except:
                        pass
                    enhanced_sessions.append(session)
                sessions = enhanced_sessions
            
            # Format data based on requested format
            if format_type == "json":
                export_data = {
                    "export_info": {
                        "format": "json",
                        "exported_at": datetime.now().isoformat(),
                        "session_count": len(sessions),
                        "time_range_minutes": time_range,
                        "includes_bodies": include_bodies
                    },
                    "sessions": sessions
                }
            elif format_type == "csv":
                # Convert to CSV-like structure
                csv_data = []
                for session in sessions:
                    csv_data.append({
                        "id": session.get("id", ""),
                        "time": session.get("time", ""),
                        "method": session.get("method", ""),
                        "host": session.get("host", ""),
                        "url": session.get("url", ""),
                        "status": session.get("status", ""),
                        "content_type": session.get("content_type", ""),
                        "size": session.get("size", 0)
                    })
                export_data = {
                    "format": "csv",
                    "headers": ["id", "time", "method", "host", "url", "status", "content_type", "size"],
                    "data": csv_data
                }
            elif format_type == "har":
                # HAR format structure
                export_data = {
                    "log": {
                        "version": "1.2",
                        "creator": {
                            "name": "Fiddler MCP Bridge",
                            "version": "2.0"
                        },
                        "entries": []
                    }
                }
                for session in sessions:
                    entry = {
                        "startedDateTime": session.get("time", ""),
                        "request": {
                            "method": session.get("method", "GET"),
                            "url": session.get("url", ""),
                            "headers": [],
                            "bodySize": 0
                        },
                        "response": {
                            "status": int(session.get("status", "200")),
                            "statusText": "OK",
                            "headers": [],
                            "content": {
                                "size": session.get("size", 0),
                                "mimeType": session.get("content_type", "")
                            }
                        }
                    }
                    export_data["log"]["entries"].append(entry)
            
            return {
                "success": True,
                "format": format_type,
                "sessions_exported": len(sessions),
                "export_size": len(str(export_data)),
                "includes_bodies": include_bodies,
                "filter_host": filter_host,
                "export_data": export_data,
                "usage_note": f"Sessions exported in {format_type} format"
            }
            
        except Exception as e:
            return {
                "error": f"Export failed: {str(e)}",
                "format": args.get("format", "json")
            }

    async def ekfiddle_analysis(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get EKFiddle threat intelligence analysis"""
        try:
            time_range = args.get("time_range_minutes", 60)
            threat_level = args.get("threat_level", "all")
            limit = args.get("limit", 50)
            
            # Query real-time bridge for EKFiddle data
            params = {
                "time_range": time_range,
                "threat_level": threat_level,
                "limit": limit
            }
            
            response = requests.get(f"{self.realtime_bridge_url}/api/sessions/ekfiddle", params=params, timeout=10)
            response.raise_for_status()
            
            ekfiddle_data = response.json()
            
            return {
                "success": True,
                "time_range_minutes": time_range,
                "threat_level": threat_level,
                "sessions_analyzed": ekfiddle_data.get("total_sessions", 0),
                "threats_found": ekfiddle_data.get("threats_found", 0),
                "ekfiddle_results": ekfiddle_data.get("results", []),
                "usage_note": "EKFiddle threat intelligence analysis results"
            }
            
        except requests.exceptions.ConnectionError:
            return {
                "error": "Cannot connect to real-time bridge for EKFiddle data",
                "bridge_status": "Disconnected"
            }
        except Exception as e:
            return {
                "error": f"EKFiddle analysis failed: {str(e)}",
                "time_range": args.get("time_range_minutes", 60)
            }

    async def ekfiddle_session(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get detailed EKFiddle analysis for specific session"""
        try:
            session_id = args.get("session_id")
            if not session_id:
                return {
                    "error": "session_id parameter is required",
                    "help": "Get session IDs from fiddler_mcp__live_sessions"
                }
            
            # Query real-time bridge for session EKFiddle data
            response = requests.get(f"{self.realtime_bridge_url}/api/sessions/ekfiddle/{session_id}", timeout=10)
            response.raise_for_status()
            
            ekfiddle_data = response.json()
            
            return {
                "success": True,
                "session_id": session_id,
                "ekfiddle_analysis": ekfiddle_data.get("analysis", {}),
                "threat_score": ekfiddle_data.get("threat_score", 0),
                "threat_classification": ekfiddle_data.get("classification", "UNKNOWN"),
                "indicators": ekfiddle_data.get("indicators", []),
                "usage_note": f"Detailed EKFiddle analysis for session {session_id}"
            }
            
        except requests.exceptions.ConnectionError:
            return {
                "error": "Cannot connect to real-time bridge for EKFiddle data",
                "bridge_status": "Disconnected"
            }
        except Exception as e:
            return {
                "error": f"EKFiddle session analysis failed: {str(e)}",
                "session_id": args.get("session_id")
            }

    async def ekfiddle_threats(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get high-risk threats identified by EKFiddle"""
        try:
            time_range = args.get("time_range_minutes", 120)
            min_risk_score = args.get("min_risk_score", 0.7)
            threat_categories = args.get("threat_categories", ["malware", "exploit", "phishing"])
            
            # Query real-time bridge for high-risk threats
            params = {
                "time_range": time_range,
                "min_risk_score": min_risk_score,
                "categories": ",".join(threat_categories)
            }
            
            response = requests.get(f"{self.realtime_bridge_url}/api/sessions/ekfiddle/threats", params=params, timeout=10)
            response.raise_for_status()
            
            threats_data = response.json()
            
            return {
                "success": True,
                "time_range_minutes": time_range,
                "min_risk_score": min_risk_score,
                "threat_categories": threat_categories,
                "high_risk_threats": threats_data.get("threats", []),
                "total_threats": threats_data.get("total_count", 0),
                "critical_sessions": threats_data.get("critical_sessions", []),
                "usage_note": "High-risk threats identified by EKFiddle threat intelligence"
            }
            
        except requests.exceptions.ConnectionError:
            return {
                "error": "Cannot connect to real-time bridge for EKFiddle data",
                "bridge_status": "Disconnected"
            }
        except Exception as e:
            return {
                "error": f"EKFiddle threats analysis failed: {str(e)}",
                "time_range": args.get("time_range_minutes", 120)
            }

    async def sessions_clear(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Clear buffered sessions from memory"""
        try:
            confirm = args.get("confirm", False)
            clear_suspicious = args.get("clear_suspicious", False)
            
            if not confirm:
                return {
                    "error": "Confirmation required to clear sessions",
                    "help": "Set 'confirm': true to proceed with clearing sessions",
                    "warning": "This action will remove all buffered session data"
                }
            
            # Call real-time bridge to clear sessions
            clear_data = {
                "clear_suspicious": clear_suspicious
            }
            
            response = requests.post(f"{self.realtime_bridge_url}/api/clear", json=clear_data, timeout=10)
            response.raise_for_status()
            
            result = response.json()
            
            return {
                "success": True,
                "sessions_cleared": result.get("sessions_cleared", 0),
                "suspicious_cleared": result.get("suspicious_cleared", 0) if clear_suspicious else 0,
                "clear_suspicious": clear_suspicious,
                "message": "Sessions successfully cleared from memory",
                "usage_note": "All buffered session data has been removed"
            }
            
        except requests.exceptions.ConnectionError:
            return {
                "error": "Cannot connect to real-time bridge to clear sessions",
                "bridge_status": "Disconnected"
            }
        except Exception as e:
            return {
                "error": f"Session clearing failed: {str(e)}",
                "confirm": args.get("confirm", False)
            }

class EnhancedFiddlerRealtimeBridge:
    """Enhanced Real-Time Fiddler Bridge with Flask server and MCP capabilities"""
    
    def __init__(self):
        self.app = Flask(__name__)
        self.live_sessions = deque(maxlen=5000)  # Keep last 5000 sessions (increased from 2000)
        self.suspicious_sessions = deque(maxlen=1000)  # Keep suspicious ones longer (increased from 500)
        self.session_lock = threading.Lock()
        self.start_time = time.time()
        self.start_time = None
        self.mcp_bridge = EnhancedFiddlerMCPBridge()
        
        # Setup Flask routes
        self.setup_routes()
    
    def normalize_session(self, d: dict) -> dict:
        """Normalize session data from various field name variations to prevent 500 errors"""
        try:
            now_epoch = time.time()

            # Extract session ID - MUST preserve Fiddler's original ID to maintain alignment
            # Try multiple field names for compatibility, but NEVER generate a new ID
            # to avoid misalignment between Fiddler UI and buffer
            sid = None
            if "id" in d and d["id"] is not None:
                sid = str(d["id"])
            elif "session_id" in d and d["session_id"] is not None:
                sid = str(d["session_id"])
            elif "fiddler_session_id" in d and d["fiddler_session_id"] is not None:
                sid = str(d["fiddler_session_id"])
            
            if sid is None:
                # CRITICAL: No session ID provided - log warning and use timestamp as emergency fallback
                # This indicates Fiddler is not sending session IDs correctly
                print(f"[enhanced-bridge] WARNING: No session ID in payload! URL={d.get('url', 'unknown')[:100]}", file=sys.stderr)
                sid = f"missing-id-{int(now_epoch*1000)}"
            url = d.get("url") or ""
            parsed_url = urlparse(url) if url else None
            host = d.get("host") or (parsed_url.hostname if parsed_url else "")
            method = d.get("method") or d.get("RequestMethod") or ""

            code = d.get("statusCode", d.get("status", 0)) or 0
            try:
                code = int(code)
            except (ValueError, TypeError):
                code = 0

            ctype = d.get("contentType") or d.get("mime") or ""
            clen = d.get("contentLength", d.get("body_length", 0)) or 0
            try:
                clen = int(clen)
            except (ValueError, TypeError):
                clen = 0

            body_text = d.get("responseBody") or ""
            if not body_text:
                # Check for base64 encoded body (supports both naming conventions)
                # This handles bodies >1KB that were base64-encoded by CustomRules.js
                b64 = d.get("responseBodyBase64") or d.get("response_body_base64")
                if b64:
                    try:
                        # Decode base64 and convert to UTF-8 text
                        # Using 'replace' error handler to gracefully handle invalid UTF-8 bytes
                        body_bytes = base64.b64decode(b64)
                        body_text = body_bytes.decode("utf-8", errors="replace")
                    except Exception as e:
                        # Log detailed error for debugging
                        session_id = d.get("id", d.get("session_id", "unknown"))
                        print(
                            f"[enhanced-bridge] Base64 decode failed for session {session_id}: {type(e).__name__}: {e}",
                            file=sys.stderr
                        )
                        body_text = ""

            timestamp_raw = d.get("received_at") or d.get("timestamp") or d.get("StartedDateTime")
            received_at = self._coerce_timestamp(timestamp_raw, default_epoch=now_epoch)

            scheme = d.get("scheme") or d.get("protocol")
            if not scheme and parsed_url:
                scheme = parsed_url.scheme
            scheme = (scheme or "http").lower()

            return {
                "id": sid,
                "url": url,
                "host": host,
                "method": method,
                "scheme": scheme,
                "statusCode": code,
                "contentType": ctype,
                "contentLength": clen,
                "requestHeaders": d.get("requestHeaders") or d.get("request_headers") or {},
                "responseHeaders": d.get("responseHeaders") or d.get("response_headers") or {},
                "responseBody": body_text,
                "requestBody": d.get("requestBody") or d.get("request_body") or "",
                "received_at": received_at,
                "received_at_iso": datetime.utcfromtimestamp(received_at).isoformat() + "Z",
                "ekfiddleComments": d.get("ekfiddleComments") or "",
                "ekfiddleFlags": d.get("ekfiddleFlags") or "",
                "sessionFlags": d.get("sessionFlags") or "",
                "timestamp": datetime.utcfromtimestamp(received_at).isoformat() + "Z",
                "fiddler_session_id": d.get("fiddler_session_id") or sid,
            }
        except Exception as e:
            # Fallback: return minimal session with error info
            # CRITICAL: Even in error case, preserve original Fiddler session ID if available
            error_sid = None
            for key in ["id", "session_id", "fiddler_session_id"]:
                if key in d and d[key] is not None:
                    error_sid = str(d[key])
                    break
            
            if error_sid is None:
                # Only generate ID if absolutely no ID in payload
                print(f"[enhanced-bridge] ERROR: Normalization failed AND no session ID! Error: {str(e)}", file=sys.stderr)
                error_sid = f"error-{int(time.time()*1000)}"
            
            return {
                "id": error_sid,
                "url": str(d.get("url", "")),
                "host": str(d.get("host", "")),
                "method": str(d.get("method", "GET")),
                "statusCode": 0,
                "contentType": "",
                "contentLength": 0,
                "requestHeaders": {},
                "responseHeaders": {},
                "responseBody": "",
                "requestBody": "",
                "received_at": time.time(),
                "received_at_iso": datetime.utcnow().isoformat() + "Z",
                "ekfiddleComments": f"normalization_error: {str(e)}",
                "ekfiddleFlags": "",
                "sessionFlags": "",
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "fiddler_session_id": error_sid,
            }

    def _coerce_timestamp(self, value, default_epoch: float) -> float:
        """Convert assorted timestamp inputs into epoch seconds."""
        if value is None:
            return float(default_epoch)

        if isinstance(value, (int, float)):
            # Heuristic: timestamps can arrive in ms
            if value > 1e12:  # likely milliseconds
                return float(value) / 1000.0
            return float(value)

        if isinstance(value, str):
            value = value.strip()
            if not value:
                return float(default_epoch)

            try:
                # Attempt ISO parse
                dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return dt.timestamp()
            except ValueError:
                pass

            try:
                return float(value)
            except ValueError:
                pass

        return float(default_epoch)

    def _extract_intelligent_content(self, body_text: str, content_type: str, max_total: int = 24000) -> dict:
        """
        Extract security-relevant portions from large bodies for LLM analysis.
        Returns head, tail, and detected suspicious patterns separately.
        
        This provides better coverage than simple truncation by including:
        - First 8KB (variable declarations, imports, configs)
        - Last 4KB (execution logic, callbacks)
        - Middle patterns: suspicious code patterns with context (up to 4KB)
        
        Args:
            body_text: The full response body text
            content_type: MIME type of the content
            max_total: Maximum total bytes to extract (default 24KB)
        
        Returns:
            dict with keys: head, tail, suspicious_patterns, metadata
        """
        import re
        
        result = {
            "head": "",
            "tail": "",
            "suspicious_patterns": "",
            "metadata": {
                "original_size": len(body_text),
                "content_type": content_type,
                "extraction_method": "intelligent",
                "patterns_found": []
            }
        }
        
        if not body_text:
            return result
        
        body_size = len(body_text)
        
        # If body is small enough, no need for smart extraction
        if body_size <= max_total:
            result["head"] = body_text
            result["metadata"]["extraction_method"] = "full_content"
            return result
        
        # Allocate bytes: 8KB head, 4KB tail, rest for patterns
        head_size = min(8000, body_size)
        tail_size = min(4000, max(0, body_size - head_size))
        pattern_budget = max_total - head_size - tail_size  # ~12KB for patterns
        
        # Extract head (first 8KB)
        result["head"] = body_text[:head_size]
        
        # Extract tail (last 4KB) - avoid overlap with head
        if body_size > head_size + tail_size:
            result["tail"] = body_text[-tail_size:]
        elif body_size > head_size:
            # Small overlap region - just take what's after head
            result["tail"] = body_text[head_size:]
        
        # Search for suspicious patterns in the middle section
        # (between head and tail)
        middle_start = head_size
        middle_end = body_size - tail_size if body_size > head_size + tail_size else body_size
        middle_section = body_text[middle_start:middle_end]
        
        if middle_section and pattern_budget > 0:
            suspicious_snippets = []
            patterns_found = []
            
            # Define security-relevant patterns to search for
            security_patterns = [
                # Code execution
                (r'eval\s*\(', 'eval()'),
                (r'Function\s*\(', 'Function()'),
                (r'new\s+Function\s*\(', 'new Function()'),
                (r'setTimeout\s*\([^)]*["\']', 'setTimeout with string'),
                (r'setInterval\s*\([^)]*["\']', 'setInterval with string'),
                
                # DOM manipulation (potential injection)
                (r'document\.write\s*\(', 'document.write()'),
                (r'innerHTML\s*=', 'innerHTML assignment'),
                (r'outerHTML\s*=', 'outerHTML assignment'),
                (r'insertAdjacentHTML\s*\(', 'insertAdjacentHTML()'),
                
                # Redirects and navigation
                (r'window\.location\s*=', 'window.location redirect'),
                (r'document\.location\s*=', 'document.location redirect'),
                (r'location\.href\s*=', 'location.href redirect'),
                (r'location\.replace\s*\(', 'location.replace()'),
                
                # Element creation (potential script injection)
                (r'createElement\s*\(\s*["\']script', 'createElement script'),
                (r'createElement\s*\(\s*["\']iframe', 'createElement iframe'),
                (r'appendChild\s*\(', 'appendChild()'),
                
                # Obfuscation indicators
                (r'\\x[0-9a-fA-F]{2}', 'hex escape sequences'),
                (r'\\u[0-9a-fA-F]{4}', 'unicode escapes'),
                (r'fromCharCode\s*\(', 'fromCharCode()'),
                (r'charCodeAt\s*\(', 'charCodeAt()'),
                (r'atob\s*\(', 'atob() base64 decode'),
                (r'btoa\s*\(', 'btoa() base64 encode'),
                
                # Data exfiltration
                (r'XMLHttpRequest', 'XMLHttpRequest'),
                (r'fetch\s*\(', 'fetch()'),
                (r'sendBeacon\s*\(', 'sendBeacon()'),
                
                # Storage access
                (r'localStorage\s*[\.\[]', 'localStorage access'),
                (r'sessionStorage\s*[\.\[]', 'sessionStorage access'),
                (r'document\.cookie', 'cookie access'),
                
                # Anti-debugging
                (r'debugger\s*;', 'debugger statement'),
                (r'console\s*\.\s*clear\s*\(', 'console.clear()'),
            ]
            
            bytes_used = 0
            context_chars = 150  # Characters of context around each match
            
            for pattern_regex, pattern_name in security_patterns:
                if bytes_used >= pattern_budget:
                    break
                    
                try:
                    for match in re.finditer(pattern_regex, middle_section, re.IGNORECASE):
                        if bytes_used >= pattern_budget:
                            break
                        
                        # Get context around the match
                        start = max(0, match.start() - context_chars)
                        end = min(len(middle_section), match.end() + context_chars)
                        
                        # Find line boundaries for cleaner output
                        line_start = middle_section.rfind('\n', start - 50, match.start())
                        if line_start == -1:
                            line_start = start
                        else:
                            line_start += 1
                        
                        line_end = middle_section.find('\n', match.end(), end + 50)
                        if line_end == -1:
                            line_end = end
                        
                        snippet = middle_section[line_start:line_end].strip()
                        
                        if snippet and len(snippet) < 500:  # Reasonable snippet size
                            # Avoid duplicate snippets
                            if snippet not in [s.get('code', '') for s in suspicious_snippets]:
                                snippet_entry = {
                                    "pattern": pattern_name,
                                    "code": snippet,
                                    "position": middle_start + match.start()
                                }
                                suspicious_snippets.append(snippet_entry)
                                bytes_used += len(snippet) + 50  # Account for formatting
                                
                                if pattern_name not in patterns_found:
                                    patterns_found.append(pattern_name)
                                    
                except re.error:
                    # Skip invalid regex patterns
                    continue
            
            # Format suspicious patterns for output
            if suspicious_snippets:
                formatted_patterns = []
                for i, snippet in enumerate(suspicious_snippets[:20], 1):  # Limit to 20 patterns
                    formatted_patterns.append(
                        f"[{i}] {snippet['pattern']} (position ~{snippet['position']}):\n{snippet['code']}"
                    )
                result["suspicious_patterns"] = "\n\n".join(formatted_patterns)
                result["metadata"]["patterns_found"] = patterns_found
                result["metadata"]["patterns_count"] = len(suspicious_snippets)
        
        # Add size info to metadata
        result["metadata"]["head_size"] = len(result["head"])
        result["metadata"]["tail_size"] = len(result["tail"])
        result["metadata"]["patterns_size"] = len(result["suspicious_patterns"])
        result["metadata"]["total_extracted"] = (
            len(result["head"]) + len(result["tail"]) + len(result["suspicious_patterns"])
        )
        
        return result

    def _quick_risk_assessment(self, session: Dict[str, Any]) -> Dict[str, Any]:
        """
        Risk assessment based EXCLUSIVELY on EKFiddle threat intelligence.
        
        CHANGED: Only flags sessions as suspicious if EKFiddle has flagged them.
        Generic heuristics (file extensions, URL keywords) are NO LONGER used
        to prevent false positives on legitimate traffic.
        """
        status = session.get("statusCode") or 0
        try:
            status = int(status)
        except (ValueError, TypeError):
            status = 0

        # PRIORITY 1: Check EKFiddle Comments (EXCLUSIVE source of truth)
        # Check multiple possible fields where EKFiddle data might be stored
        ekfiddle = (session.get("ekfiddleComments") or 
                   session.get("sessionFlags") or 
                   session.get("ekfiddleFlags") or "").strip()
        
        if ekfiddle:
            # EKFiddle found something - this is authoritative threat intelligence
            # Parse severity level from EKFiddle comment (e.g., "High: JS Function with Eval")
            ekfiddle_lower = ekfiddle.lower()
            risk_score = 0.5  # Base score for any EKFiddle alert
            risk_level = "MEDIUM"  # Default
            
            # Parse explicit severity levels from EKFiddle
            if ekfiddle_lower.startswith("critical:") or "critical" in ekfiddle_lower[:20]:
                risk_score = 1.0
                risk_level = "CRITICAL"
            elif ekfiddle_lower.startswith("high:") or "high" in ekfiddle_lower[:20]:
                risk_score = 0.85
                risk_level = "HIGH"
            elif ekfiddle_lower.startswith("medium:") or "medium" in ekfiddle_lower[:20]:
                risk_score = 0.65
                risk_level = "MEDIUM"
            elif ekfiddle_lower.startswith("low:") or "low" in ekfiddle_lower[:20]:
                risk_score = 0.4
                risk_level = "MEDIUM"  # Still flag for review
            
            # Additional scoring based on threat keywords
            if any(pattern in ekfiddle_lower for pattern in ['exploit', 'malware', 'trojan', 'backdoor', 'ransomware']):
                risk_score = max(risk_score, 1.0)
                risk_level = "CRITICAL"
            elif any(pattern in ekfiddle_lower for pattern in ['phishing', 'credential', 'socgholish', 'fake update']):
                risk_score = max(risk_score, 0.85)
                risk_level = "HIGH"
            elif any(pattern in ekfiddle_lower for pattern in ['suspicious', 'obfuscated', 'encoded', 'eval']):
                risk_score = max(risk_score, 0.65)
                if risk_level == "MEDIUM" and "high" in ekfiddle_lower[:20]:
                    risk_level = "HIGH"
            
            return {
                "score": risk_score,
                "level": risk_level,
                "flag": "ekfiddle_alert",
                "reasons": [f"EKFiddle: {ekfiddle}"]
            }
        
        # PRIORITY 2: No EKFiddle data = NOT SUSPICIOUS
        # Sessions without EKFiddle alerts are considered clean
        # Even if they have .exe in URL, error status, etc.
        
        risk_score = 0.0
        risk_level = "LOW"
        flag = None
        reasons = []
        
        # Optional: Add informational flag for HTTP errors (NOT a security risk)
        if status >= 400:
            flag = "error_status"
            reasons.append(f"HTTP error status {status} (informational only)")
            # Note: risk_score stays 0.0 - errors are not security threats
        
        return {
            "score": risk_score,
            "level": risk_level,
            "flag": flag,
            "reasons": reasons
        }

    def _format_session_overview(self, session: Dict[str, Any]) -> Dict[str, Any]:
        assessment = self._quick_risk_assessment(session)
        received_at = session.get("received_at", time.time())
        try:
            display_time = datetime.fromtimestamp(received_at).strftime("%H:%M:%S")
        except (ValueError, OSError):
            display_time = datetime.utcnow().strftime("%H:%M:%S")

        content_type = (session.get("contentType") or "").split(";")[0]

        return {
            "id": session.get("id"),
            "time": display_time,
            "method": session.get("method", "GET"),
            "url": session.get("url", ""),
            "host": session.get("host", ""),
            "status": str(session.get("statusCode", "")),
            "statusCode": session.get("statusCode"),
            "content_type": content_type,
            "size": session.get("contentLength", 0),
            "is_https": (session.get("scheme") or "").lower() == "https",
            "risk_flag": assessment.get("flag"),
            "risk_score": assessment.get("score"),
            "risk_level": assessment.get("level"),
            "risk_reasons": assessment.get("reasons"),
            "received_at": received_at,
            "received_at_iso": session.get("received_at_iso")
        }

    def _collect_session_statistics(self, formatted_sessions: List[Dict[str, Any]]) -> Dict[str, Any]:
        status_codes: Counter = Counter()
        content_types: Counter = Counter()
        hosts: Counter = Counter()
        suspicious = 0

        for overview in formatted_sessions:
            status_codes[overview["status"]] += 1
            if overview.get("content_type"):
                content_types[overview["content_type"]] += 1
            if overview.get("host"):
                hosts[overview["host"]] += 1
            if overview.get("risk_flag"):
                suspicious += 1

        return {
            "status_codes": dict(status_codes.most_common(10)),
            "content_types": dict(content_types.most_common(10)),
            "top_hosts": dict(hosts.most_common(10)),
            "suspicious_count": suspicious
        }

    def _filter_sessions(self, sessions: List[Dict[str, Any]], *, host_filter: str = None,
                          status_filter: str = None, since_minutes: int = None) -> List[Dict[str, Any]]:
        host_filter_lower = host_filter.lower() if host_filter else None
        status_filter = str(status_filter) if status_filter is not None else None

        cutoff_epoch = None
        if since_minutes:
            cutoff_epoch = time.time() - (int(since_minutes) * 60)

        filtered: List[Dict[str, Any]] = []
        for session in sessions:
            if cutoff_epoch and session.get("received_at", 0) < cutoff_epoch:
                continue
            if host_filter_lower and host_filter_lower not in (session.get("host", "").lower()):
                continue
            if status_filter and str(session.get("statusCode")) != status_filter:
                continue
            filtered.append(session)

        return filtered

    def _build_session_detail(self, session: Dict[str, Any]) -> Dict[str, Any]:
        overview = self._format_session_overview(session)
        assessment = self._quick_risk_assessment(session)

        classification_map = {
            "potential_fake_update": "FAKE_UPDATE",
            "suspicious_download": "MALWARE_DOWNLOAD",
            "error_status": "ERROR_TRAFFIC",
            "suspicious_domain": "SUSPICIOUS_DOMAIN",
            "ekfiddle_alert": "EKFIDDLE",
        }
        classification = classification_map.get(assessment.get("flag"), "NORMAL")

        indicators = list(assessment.get("reasons", []))
        if session.get("ekfiddleComments"):
            ek_summary = self.parse_ekfiddle_comments(session.get("ekfiddleComments"))
            if ek_summary.get("indicators"):
                indicators.extend(ek_summary["indicators"])

        recommendations = []
        if assessment.get("flag") == "potential_fake_update":
            recommendations.append("Block domain and warn user about fake update lure")
        if assessment.get("flag") == "suspicious_download":
            recommendations.append("Detonate or scan downloaded file before execution")
        if assessment.get("flag") == "ekfiddle_alert":
            recommendations.append("Review EKFiddle findings for exploitation activity")

        return {
            "session": {
                "id": overview.get("id"),
                "url": session.get("url"),
                "host": session.get("host"),
                "method": session.get("method", "GET"),
                "statusCode": session.get("statusCode"),
                "contentType": session.get("contentType"),
                "contentLength": session.get("contentLength"),
                "scheme": session.get("scheme"),
                "received_at": session.get("received_at"),
                "received_at_iso": session.get("received_at_iso"),
                "requestHeaders": session.get("requestHeaders", {}),
                "responseHeaders": session.get("responseHeaders", {}),
                "ekfiddleComments": session.get("ekfiddleComments"),
                "sessionFlags": session.get("sessionFlags")
            },
            "analysis": {
                "risk_score": assessment.get("score"),
                "risk_level": assessment.get("level"),
                "classification": classification,
                "indicators": indicators,
                "reasons": assessment.get("reasons"),
                "recommendations": recommendations,
                "risk_flag": assessment.get("flag")
            }
        }
    
    def setup_routes(self):
        """Setup Flask HTTP endpoints"""
        
        @self.app.route('/live-session', methods=['POST'])
        def receive_session():
            """Receive live session from Fiddler - hardened against payload variations"""
            try:
                # Get raw data for debugging if JSON parse fails
                raw_data = request.get_data(as_text=True)
                
                data = request.get_json(silent=True)
                
                if data is None:
                    # JSON parsing failed - log details for debugging
                    print(f"[enhanced-bridge] JSON parse failed. Raw data length: {len(raw_data) if raw_data else 0}", file=sys.stderr)
                    
                    # Try to extract session ID from raw data for debugging
                    import re
                    session_id_match = re.search(r'"id"\s*:\s*"?(\d+)"?', raw_data[:500] if raw_data else "")
                    session_id = session_id_match.group(1) if session_id_match else "unknown"
                    
                    print(f"[enhanced-bridge] FAILED SESSION ID: {session_id}", file=sys.stderr)
                    
                    # For small payloads, show preview
                    if raw_data and len(raw_data) < 1000:
                        print(f"[enhanced-bridge] Raw data preview: {raw_data[:500]}", file=sys.stderr)
                    else:
                        # For large payloads, show start and problematic area
                        print(f"[enhanced-bridge] JSON header: {raw_data[:200] if raw_data else ''}", file=sys.stderr)
                        
                        # Try to find the problematic character
                        try:
                            # Attempt incremental parsing to find where it breaks
                            for i in range(100, min(len(raw_data), 5000), 100):
                                try:
                                    json.loads(raw_data[:i])
                                except json.JSONDecodeError as e:
                                    if i > 200:  # Found approximate break point
                                        problem_start = max(0, e.pos - 50)
                                        problem_end = min(len(raw_data), e.pos + 50)
                                        print(f"[enhanced-bridge] JSON error at position {e.pos}: {e.msg}", file=sys.stderr)
                                        print(f"[enhanced-bridge] Problem area: ...{raw_data[problem_start:problem_end]}...", file=sys.stderr)
                                        break
                        except Exception:
                            pass
                    
                    return jsonify({"ok": False, "error": "invalid_json", "hint": "Check Fiddler logs for encoding issues", "session_id": session_id}), 400
                
                if not data:
                    return jsonify({"ok": False, "error": "empty_payload"}), 400
                
                sess = self.normalize_session(data)
                
                with self.session_lock:
                    self.live_sessions.append(sess)
                    
                    # Check if session is suspicious
                    try:
                        if self.is_immediately_suspicious(sess):
                            self.suspicious_sessions.append(sess)
                    except Exception:
                        # Continue processing even if suspicious check fails
                        pass
                
                return jsonify({"ok": True, "id": sess["id"]}), 201
                
            except Exception as e:
                # Log the error with details for debugging
                print(f"[enhanced-bridge] Session ingest exception: {type(e).__name__}: {str(e)}", file=sys.stderr)
                return jsonify({"ok": False, "error": "ingest_failed", "details": str(e)}), 500
        
        @self.app.route('/api/sessions', methods=['GET'])
        def get_sessions():
            """Get recent sessions with optional filtering"""
            try:
                limit = max(1, min(int(request.args.get('limit', 50)), 500))
                suspicious_only = request.args.get('suspicious_only', 'false').lower() == 'true'
                host_filter = request.args.get('host_filter') or request.args.get('host')
                status_filter = request.args.get('status') or request.args.get('status_code')
                since_minutes_raw = request.args.get('since_minutes') or request.args.get('minutes')
                since_minutes = int(since_minutes_raw) if since_minutes_raw else None
                if since_minutes and since_minutes > 360:
                    since_minutes = 360

                with self.session_lock:
                    base_sessions = list(self.suspicious_sessions if suspicious_only else self.live_sessions)

                filtered_sessions = self._filter_sessions(
                    base_sessions,
                    host_filter=host_filter,
                    status_filter=status_filter,
                    since_minutes=since_minutes
                )

                filtered_sessions.sort(key=lambda s: s.get('received_at', 0))
                formatted_sessions = [self._format_session_overview(s) for s in filtered_sessions]

                returned_sessions = list(reversed(formatted_sessions[-limit:]))
                statistics = self._collect_session_statistics(formatted_sessions)

                oldest = formatted_sessions[0]["received_at"] if formatted_sessions else None
                newest = formatted_sessions[-1]["received_at"] if formatted_sessions else None
                oldest_iso = datetime.fromtimestamp(oldest).isoformat() + "Z" if oldest is not None else None
                newest_iso = datetime.fromtimestamp(newest).isoformat() + "Z" if newest is not None else None

                return jsonify({
                    "success": True,
                    "sessions": returned_sessions,
                    "returned_count": len(returned_sessions),
                    "matched_count": len(formatted_sessions),
                    "total_live": len(base_sessions),
                    "suspicious_only": suspicious_only,
                    "statistics": statistics,
                    "time_bounds": {
                        "oldest": oldest,
                        "newest": newest,
                        "oldest_iso": oldest_iso,
                        "newest_iso": newest_iso
                    },
                    "query": {
                        "limit": limit,
                        "host_filter": host_filter,
                        "status_filter": status_filter,
                        "since_minutes": since_minutes,
                        "suspicious_only": suspicious_only
                    }
                })
                
            except Exception as e:
                return jsonify({"error": f"Failed to get sessions: {str(e)}"}), 500

        @self.app.route('/health', methods=['GET'])
        def health_check():
            """Simple health-check endpoint for MCP clients."""
            uptime = time.time() - self.start_time
            with self.session_lock:
                live_count = len(self.live_sessions)
                suspicious_count = len(self.suspicious_sessions)
            return jsonify({
                "status": "healthy",
                "uptime_seconds": uptime,
                "live_buffer_size": live_count,
                "suspicious_buffer_size": suspicious_count
            }), 200

        @self.app.route('/api/session/<session_id>', methods=['GET'])
        def get_session_details(session_id):
            """Get detailed information for specific session"""
            try:
                with self.session_lock:
                    for session in reversed(self.live_sessions):
                        if str(session.get('id', '')) == str(session_id):
                            detail = self._build_session_detail(session)
                            detail.update({
                                "success": True,
                                "found": True
                            })
                            return jsonify(detail)

                return jsonify({
                    "success": False,
                    "error": f"Session {session_id} not found",
                    "found": False
                }), 404

            except Exception as e:
                return jsonify({"error": f"Failed to get session: {str(e)}"}), 500
        
        @self.app.route('/api/sessions/headers/<session_id>', methods=['GET'])
        def get_session_headers(session_id):
            """Get headers for specific session"""
            try:
                with self.session_lock:
                    for session in reversed(self.live_sessions):
                        if str(session.get('id', '')) == str(session_id):
                            return jsonify({
                                "success": True,
                                "session_id": session_id,
                                "request_headers": session.get('requestHeaders', {}),
                                "response_headers": session.get('responseHeaders', {}),
                                "found": True
                            })

                return jsonify({
                    "success": False,
                    "error": f"Session {session_id} not found",
                    "found": False
                }), 404
                
            except Exception as e:
                return jsonify({"error": f"Failed to get headers: {str(e)}"}), 500
        
        @self.app.route('/api/sessions/body/<session_id>', methods=['GET'])
        def get_session_body(session_id):
            """Get request/response body for specific session - returns both key formats"""
            sess = None
            with self.session_lock:
                for session in reversed(self.live_sessions):
                    if str(session.get('id', '')) == str(session_id):
                        sess = session
                        break

            if not sess:
                return jsonify({
                    "success": False,
                    "found": False,
                    "id": session_id,
                    "response_body": "",
                    "responseBody": ""
                }), 200

            response_body_full = sess.get("responseBody") or ""
            request_body_full = sess.get("requestBody", "")

            response_size = len(response_body_full)
            request_size = len(request_body_full)

            if response_size > LARGE_BODY_WARNING_BYTES:
                print(
                    f"[enhanced-bridge] Large response body for session {session_id}: {response_size:,} bytes",
                    file=sys.stderr,
                )

            raw = request.args.get('raw', 'false').lower() == 'true'
            # NEW: smart_extract parameter for intelligent content extraction (large files)
            # Default is false to preserve existing behavior exactly
            smart_extract = request.args.get('smart_extract', 'false').lower() == 'true'
            
            response_truncated = response_size > MAX_BODY_PREVIEW_BYTES
            request_truncated = request_size > MAX_BODY_PREVIEW_BYTES

            response_body_preview = response_body_full
            request_body_preview = request_body_full

            if response_truncated and not raw:
                response_body_preview = (
                    response_body_full[:MAX_BODY_PREVIEW_BYTES]
                    + f"\n\n... [TRUNCATED: Response was {response_size:,} bytes; showing first {MAX_BODY_PREVIEW_BYTES:,} bytes] ..."
                )

            if request_truncated and not raw:
                request_body_preview = (
                    request_body_full[:MAX_BODY_PREVIEW_BYTES]
                    + f"\n\n... [TRUNCATED: Request was {request_size:,} bytes; showing first {MAX_BODY_PREVIEW_BYTES:,} bytes] ..."
                )

            if raw:
                response_truncated = False
                request_truncated = False

            # Build base response (existing behavior preserved)
            response_data = {
                "success": True,
                "found": True,
                "id": session_id,
                "content_type": sess.get("contentType"),
                "content_length": sess.get("contentLength"),
                "response_body": response_body_preview,
                "responseBody": response_body_preview,
                "request_body": request_body_preview,
                "requestBody": request_body_preview,
                "truncated": response_truncated or request_truncated,
                "response_truncated": response_truncated,
                "request_truncated": request_truncated,
                "full_size": {
                    "response": response_size,
                    "request": request_size,
                },
            }
            
            # EKFiddle threat intelligence (additive - never affects existing fields)
            response_data["ekfiddle_comments"] = sess.get("ekfiddleComments") or ""
            response_data["ekfiddle_flags"] = sess.get("ekfiddleFlags") or ""
            response_data["session_flags"] = sess.get("sessionFlags") or ""
            
            # NEW: Add intelligent extraction for large files when requested
            # This is additive - existing fields remain unchanged
            if smart_extract and response_size > MAX_BODY_PREVIEW_BYTES:
                try:
                    content_type = sess.get("contentType") or ""
                    extraction = self._extract_intelligent_content(
                        response_body_full, 
                        content_type,
                        max_total=24000
                    )
                    # Add NEW fields - never replace existing ones
                    response_data["smart_extraction"] = extraction
                    response_data["smart_extraction_available"] = True
                except Exception as e:
                    # Graceful degradation - if extraction fails, just note it
                    response_data["smart_extraction_available"] = False
                    response_data["smart_extraction_error"] = str(e)
            else:
                response_data["smart_extraction_available"] = False
            
            return jsonify(response_data), 200
        
        @self.app.route('/api/sessions/search', methods=['GET'])
        def search_sessions():
            """Advanced search across sessions with multiple filter criteria - supports agent's params"""
            try:
                q = request.args
                host_pat   = q.get("host") or q.get("host_pattern") or ""
                url_pat    = q.get("url") or q.get("url_pattern") or ""
                method     = (q.get("method") or "").upper() or None
                ctype_want = q.get("content_type")  # accepts 'javascript' or full MIME
                status_min = int(q.get("status_min") or 0)
                status_max = int(q.get("status_max") or 999)
                min_size   = int(q.get("min_size") or 0)
                max_size   = int(q.get("max_size") or 1_000_000_000)
                limit      = max(1, min(int(q.get("limit") or 50), 500))
                since_raw  = q.get("since_minutes") or q.get("minutes")
                since_minutes = int(since_raw) if since_raw else None
                if since_minutes and since_minutes > 360:
                    since_minutes = 360
                cutoff_ts = time.time() - (since_minutes * 60) if since_minutes else None

                import re
                host_rx = re.compile(host_pat, re.I) if host_pat else None
                url_rx  = re.compile(url_pat,  re.I) if url_pat  else None

                def ctype_matches(ct, want):
                    if not want: return True
                    base = (ct or "").split(";",1)[0].strip().lower()
                    groups = {
                        "javascript": {"application/javascript","text/javascript","application/x-javascript"},
                        "html": {"text/html"}, "json": {"application/json","text/json"},
                        "css": {"text/css"},   "plain": {"text/plain"},
                    }
                    return (base in groups.get(want, set())) or (base == want.lower())

                out = []
                matched_total = 0
                with self.session_lock:
                    for s in reversed(list(self.live_sessions)):       # most recent first
                        url   = s.get("url") or ""
                        host  = s.get("host") or ""
                        if not host and url:
                            host = urlparse(url).hostname or ""
                        meth  = (s.get("method") or "").upper()
                        code  = int(s.get("statusCode") or s.get("status") or 0)
                        ctype = s.get("contentType") or s.get("mime") or ""
                        size  = int(s.get("contentLength") or s.get("body_length") or 0)
                        received_at = s.get("received_at") or 0

                        if cutoff_ts is not None and received_at < cutoff_ts:
                            continue
                        if host_rx and not host_rx.search(host): continue
                        if url_rx  and not url_rx.search(url):   continue
                        if method and meth != method:            continue
                        if not (status_min <= code <= status_max):   continue
                        if not (min_size  <= size <= max_size):      continue
                        if not ctype_matches(ctype, ctype_want):     continue

                        matched_total += 1
                        overview = self._format_session_overview(s)
                        overview.update({
                            "method": meth,
                            "content_type_full": ctype,
                            "contentLength": size
                        })
                        out.append(overview)
                        if len(out) >= limit:
                            break

                return jsonify({
                    "success": True,
                    "total_matched": matched_total,
                    "returned": len(out),
                    "sessions": out,
                    "query": {
                        "host_pattern": host_pat,
                        "url_pattern": url_pat,
                        "method": method,
                        "status_min": status_min,
                        "status_max": status_max,
                        "content_type": ctype_want,
                        "min_size": min_size,
                        "max_size": max_size,
                        "limit": limit,
                        "since_minutes": since_minutes
                    }
                }), 200

            except Exception as e:
                # Return 200 with empty list on any error to avoid 500s
                return jsonify({"success": False, "total_matched": 0, "sessions": [], "error": str(e)}), 200

        @self.app.route('/api/threat-hunt', methods=['GET'])
        def api_threat_hunt():
            """Run lightweight threat hunts across buffered sessions"""
            try:
                hunt_type = request.args.get('hunt_type', 'all')
                time_range = int(request.args.get('time_range', request.args.get('since_minutes', 30)))
                if time_range > 360:
                    time_range = 360
                include_analysis = request.args.get('include_analysis', 'true').lower() == 'true'

                with self.session_lock:
                    sessions = list(self.live_sessions)

                recent_sessions = self._filter_sessions(sessions, since_minutes=time_range)
                findings = []

                for session in recent_sessions:
                    url = (session.get('url') or '').lower()
                    host = (session.get('host') or '').lower()
                    overview = self._format_session_overview(session)

                    if hunt_type in ('fake_updates', 'all'):
                        if any(word in url for word in ["update", "download", "install"]) and \
                           any(prod in url for prod in ["chrome", "firefox", "edge", "browser", "flash"]):
                            findings.append({
                                "type": "fake_update",
                                "description": f"Potential fake update hosted on {host}",
                                "session_id": overview.get('id'),
                                "risk_score": 0.8,
                                "url": session.get('url'),
                                "host": session.get('host'),
                                "timestamp": overview.get('received_at'),
                                "details": overview if include_analysis else None
                            })

                    if hunt_type in ('malware_downloads', 'all'):
                        if any(url.endswith(ext) for ext in ['.exe', '.zip', '.scr', '.dll', '.bat']):
                            findings.append({
                                "type": "malware_download",
                                "description": f"Suspicious download {url.split('/')[-1]}",
                                "session_id": overview.get('id'),
                                "risk_score": 0.7,
                                "url": session.get('url'),
                                "host": session.get('host'),
                                "timestamp": overview.get('received_at'),
                                "details": overview if include_analysis else None
                            })

                    if hunt_type in ('c2_communication', 'all'):
                        if any(host.endswith(tld) for tld in ['.tk', '.ml', '.ga', '.cf', '.gq']):
                            findings.append({
                                "type": "c2_communication",
                                "description": f"Communication with high-risk TLD {host}",
                                "session_id": overview.get('id'),
                                "risk_score": 0.6,
                                "url": session.get('url'),
                                "host": session.get('host'),
                                "timestamp": overview.get('received_at'),
                                "details": overview if include_analysis else None
                            })

                return jsonify({
                    "success": True,
                    "hunt_type": hunt_type,
                    "time_range_minutes": time_range,
                    "sessions_analyzed": len(recent_sessions),
                    "findings": findings,
                    "findings_count": len(findings)
                })

            except Exception as e:
                return jsonify({"success": False, "error": f"Threat hunt failed: {str(e)}"}), 500

        @self.app.route('/api/sessions/timeline', methods=['GET'])
        def get_sessions_timeline():
            """Generate timeline analysis of session traffic"""
            try:
                time_range = int(request.args.get('time_range_minutes', 30))
                group_by = request.args.get('group_by', 'minute')
                include_details = request.args.get('include_details', 'true').lower() == 'true'
                filter_host = request.args.get('filter_host')
                
                timeline = {}
                
                with self.session_lock:
                    sessions = list(self.live_sessions)
                
                # Filter by host if specified
                if filter_host:
                    sessions = [s for s in sessions if filter_host.lower() in s.get('host', '').lower()]
                
                # Group sessions by specified criteria
                for session in sessions:
                    if group_by == 'minute':
                        # Group by minute timestamp
                        timestamp = session.get('received_at', time.time())
                        key = datetime.fromtimestamp(timestamp).strftime("%H:%M")
                    elif group_by == 'host':
                        key = session.get('host', 'unknown')
                    elif group_by == 'status_code':
                        key = str(session.get('statusCode', 'unknown'))
                    elif group_by == 'content_type':
                        key = session.get('contentType', 'unknown').split(';')[0]
                    else:
                        key = 'default'
                    
                    if key not in timeline:
                        timeline[key] = {
                            "count": 0,
                            "sessions": [] if include_details else None
                        }
                    
                    timeline[key]["count"] += 1
                    if include_details:
                        timeline[key]["sessions"].append({
                            "id": session.get("id", "unknown"),
                            "time": datetime.fromtimestamp(session.get('received_at', time.time())).strftime("%H:%M:%S"),
                            "url": session.get("url", ""),
                            "host": session.get("host", ""),
                            "status": str(session.get("statusCode", ""))
                        })
                
                # Sort timeline by key
                sorted_timeline = dict(sorted(timeline.items()))
                
                return jsonify({
                    "timeline": sorted_timeline,
                    "timeline_entries": len(sorted_timeline),
                    "total_sessions": sum(entry["count"] for entry in sorted_timeline.values()),
                    "group_by": group_by,
                    "time_range_minutes": time_range,
                    "filter_host": filter_host
                })
                
            except Exception as e:
                return jsonify({"error": f"Timeline generation failed: {str(e)}"}), 500
        
        @self.app.route('/api/sessions/export', methods=['GET'])
        def export_sessions():
            """Export session data in various formats"""
            try:
                format_type = request.args.get('format', 'json')
                time_range = int(request.args.get('time_range_minutes', 60))
                include_bodies = request.args.get('include_bodies', 'false').lower() == 'true'
                filter_host = request.args.get('filter_host')
                limit = min(int(request.args.get('limit', 100)), 1000)
                
                with self.session_lock:
                    sessions = list(self.live_sessions)
                
                # Filter by host if specified
                if filter_host:
                    sessions = [s for s in sessions if filter_host.lower() in s.get('host', '').lower()]
                
                # Get most recent sessions up to limit
                sessions = sessions[-limit:] if sessions else []
                
                # Format data based on requested format
                if format_type == 'json':
                    export_data = {
                        "export_info": {
                            "format": "json",
                            "exported_at": datetime.now().isoformat(),
                            "session_count": len(sessions),
                            "time_range_minutes": time_range,
                            "includes_bodies": include_bodies
                        },
                        "sessions": sessions
                    }
                elif format_type == 'csv':
                    # Convert to CSV-like structure
                    csv_data = []
                    for session in sessions:
                        csv_data.append({
                            "id": session.get("id", ""),
                            "time": datetime.fromtimestamp(session.get('received_at', time.time())).strftime("%Y-%m-%d %H:%M:%S"),
                            "method": session.get("method", ""),
                            "host": session.get("host", ""),
                            "url": session.get("url", ""),
                            "status": session.get("statusCode", ""),
                            "content_type": session.get("contentType", ""),
                            "size": session.get("contentLength", 0)
                        })
                    export_data = {
                        "format": "csv",
                        "headers": ["id", "time", "method", "host", "url", "status", "content_type", "size"],
                        "data": csv_data
                    }
                elif format_type == 'har':
                    # HAR format structure
                    export_data = {
                        "log": {
                            "version": "1.2",
                            "creator": {
                                "name": "Enhanced Fiddler Bridge",
                                "version": "2.0"
                            },
                            "entries": []
                        }
                    }
                    for session in sessions:
                        entry = {
                            "startedDateTime": datetime.fromtimestamp(session.get('received_at', time.time())).isoformat(),
                            "request": {
                                "method": session.get("method", "GET"),
                                "url": session.get("url", ""),
                                "headers": [],
                                "bodySize": 0
                            },
                            "response": {
                                "status": int(session.get("statusCode", 200)),
                                "statusText": "OK",
                                "headers": [],
                                "content": {
                                    "size": session.get("contentLength", 0),
                                    "mimeType": session.get("contentType", "")
                                }
                            }
                        }
                        export_data["log"]["entries"].append(entry)
                else:
                    export_data = {"error": f"Unsupported format: {format_type}"}
                
                return jsonify({
                    "success": True,
                    "format": format_type,
                    "sessions_exported": len(sessions),
                    "export_size": len(str(export_data)),
                    "includes_bodies": include_bodies,
                    "filter_host": filter_host,
                    "export_data": export_data
                })
                
            except Exception as e:
                return jsonify({"error": f"Export failed: {str(e)}"}), 500
        
        @self.app.route('/api/stats', methods=['GET'])
        def get_stats():
            """Get real-time statistics"""
            try:
                current_time = time.time()
                start_time = getattr(self, 'start_time', current_time)
                uptime = current_time - start_time

                with self.session_lock:
                    sessions_snapshot = list(self.live_sessions)
                    total_sessions = len(sessions_snapshot)
                    suspicious_count = len(self.suspicious_sessions)

                buffer_capacity = self.live_sessions.maxlen
                buffer_usage_ratio = total_sessions / buffer_capacity if buffer_capacity else 0

                last_activity = max((s.get('received_at', 0) for s in sessions_snapshot), default=0)
                minute_threshold = current_time - 60
                hour_threshold = current_time - 3600
                last_minute = sum(1 for s in sessions_snapshot if s.get('received_at', 0) >= minute_threshold)
                last_hour = sum(1 for s in sessions_snapshot if s.get('received_at', 0) >= hour_threshold)

                return jsonify({
                    "success": True,
                    "bridge_status": "Connected",
                    "uptime_seconds": uptime,
                    "total_sessions": total_sessions,
                    "buffered_sessions": total_sessions,
                    "suspicious_sessions": suspicious_count,
                    "last_minute": last_minute,
                    "last_hour": last_hour,
                    "buffer_capacity": buffer_capacity,
                    "buffer_usage": f"{buffer_usage_ratio*100:.1f}%",
                    "buffer_usage_ratio": buffer_usage_ratio,
                    "last_activity": last_activity,
                    "memory_usage": {
                        "live_buffer_full": buffer_usage_ratio >= 0.95,
                        "live_buffer_utilization": buffer_usage_ratio,
                        "suspicious_buffer_utilization": suspicious_count / self.suspicious_sessions.maxlen if self.suspicious_sessions.maxlen else 0
                    }
                })

            except Exception as e:
                return jsonify({"error": f"Failed to get stats: {str(e)}"}), 500
        
        @self.app.route('/api/sessions/ekfiddle', methods=['GET'])
        def get_ekfiddle_analysis():
            """Get sessions with EKFiddle analysis data"""
            try:
                limit = int(request.args.get('limit', 50))
                time_range = int(request.args.get('time_range', 60))
                threat_level = request.args.get('threat_level', 'all')
                
                sessions_with_ekfiddle = []
                
                with self.session_lock:
                    for session in self.live_sessions:
                        ekfiddle_data = session.get('ekfiddleComments', '')
                        if ekfiddle_data and ekfiddle_data.strip():
                            session_copy = session.copy()
                            session_copy['ekfiddle_analysis'] = self.parse_ekfiddle_comments(ekfiddle_data)
                            
                            # Filter by threat level if specified
                            if threat_level != 'all':
                                analysis = session_copy['ekfiddle_analysis']
                                session_severity = analysis.get('severity', 'unknown')
                                if threat_level == 'high' and session_severity != 'high':
                                    continue
                                elif threat_level == 'medium' and session_severity not in ['high', 'medium']:
                                    continue
                                elif threat_level == 'low' and session_severity not in ['high', 'medium', 'low']:
                                    continue
                            
                            sessions_with_ekfiddle.append(session_copy)
                
                # Return most recent ones first, limited by requested amount
                sessions_with_ekfiddle = sessions_with_ekfiddle[-limit:]
                
                return jsonify({
                    "results": sessions_with_ekfiddle,
                    "total_sessions": len(self.live_sessions),
                    "threats_found": len(sessions_with_ekfiddle),
                    "ekfiddle_summary": self.summarize_ekfiddle_findings(sessions_with_ekfiddle),
                    "time_range_minutes": time_range,
                    "threat_level_filter": threat_level
                })
                
            except Exception as e:
                return jsonify({"error": f"EKFiddle analysis failed: {str(e)}"}), 500
        
        @self.app.route('/api/sessions/ekfiddle/<session_id>', methods=['GET'])
        def get_session_ekfiddle(session_id):
            """Get detailed EKFiddle analysis for a specific session"""
            try:
                session = None
                with self.session_lock:
                    for s in self.live_sessions:
                        if str(s.get('id', '')) == str(session_id) or str(s.get('bridge_id', '')) == str(session_id):
                            session = s
                            break
                
                if not session:
                    return jsonify({"error": "Session not found", "found": False}), 404
                
                ekfiddle_data = session.get('ekfiddleComments', '')
                session_flags = session.get('sessionFlags', '')
                
                analysis = self.parse_ekfiddle_comments(ekfiddle_data)
                threat_assessment = self.assess_ekfiddle_threat(ekfiddle_data)
                
                return jsonify({
                    "session_id": session_id,
                    "found": True,
                    "analysis": analysis,
                    "threat_score": threat_assessment.get("risk_score", 0),
                    "classification": threat_assessment.get("threat_level", "UNKNOWN"),
                    "indicators": analysis.get("indicators", []),
                    "ekfiddle_comments": ekfiddle_data,
                    "session_flags": session_flags,
                    "threat_assessment": threat_assessment,
                    "raw_session": session
                })
                
            except Exception as e:
                return jsonify({"error": f"EKFiddle session analysis failed: {str(e)}"}), 500
        
        @self.app.route('/api/sessions/ekfiddle/threats', methods=['GET'])
        def get_ekfiddle_threats():
            """Get high-risk threats identified by EKFiddle"""
            try:
                time_range = int(request.args.get('time_range', 120))
                min_risk_score = float(request.args.get('min_risk_score', 0.7))
                categories = request.args.get('categories', 'malware,exploit,phishing').split(',')
                
                high_risk_threats = []
                critical_sessions = []
                
                with self.session_lock:
                    for session in self.live_sessions:
                        ekfiddle_data = session.get('ekfiddleComments', '')
                        if ekfiddle_data and ekfiddle_data.strip():
                            threat_assessment = self.assess_ekfiddle_threat(ekfiddle_data)
                            risk_score = threat_assessment.get("risk_score", 0)
                            
                            if risk_score >= min_risk_score:
                                analysis = self.parse_ekfiddle_comments(ekfiddle_data)
                                threat_types = analysis.get('threat_types', [])
                                
                                # Check if matches requested categories
                                if any(cat.strip() in threat_types for cat in categories):
                                    threat_info = {
                                        "session_id": session.get('id', session.get('bridge_id', 'unknown')),
                                        "host": session.get('host', ''),
                                        "url": session.get('url', ''),
                                        "risk_score": risk_score,
                                        "threat_level": threat_assessment.get("threat_level", "UNKNOWN"),
                                        "threat_types": threat_types,
                                        "indicators": analysis.get("indicators", []),
                                        "recommendations": threat_assessment.get("recommendations", [])
                                    }
                                    high_risk_threats.append(threat_info)
                                    
                                    if risk_score >= 0.8:  # Critical threshold
                                        critical_sessions.append(threat_info)
                
                return jsonify({
                    "threats": high_risk_threats,
                    "total_count": len(high_risk_threats),
                    "critical_sessions": critical_sessions,
                    "critical_count": len(critical_sessions),
                    "time_range_minutes": time_range,
                    "min_risk_score": min_risk_score,
                    "categories_searched": categories
                })
                
            except Exception as e:
                return jsonify({"error": f"EKFiddle threats analysis failed: {str(e)}"}), 500
        
        @self.app.route('/api/clear', methods=['POST'])
        def clear_sessions():
            """Clear session buffers"""
            try:
                data = request.get_json() or {}
                clear_suspicious = data.get('clear_suspicious', False)
                
                with self.session_lock:
                    sessions_cleared = len(self.live_sessions)
                    suspicious_cleared = 0

                    self.live_sessions.clear()
                    
                    if clear_suspicious:
                        suspicious_cleared = len(self.suspicious_sessions)
                        self.suspicious_sessions.clear()
                
                return jsonify({
                    "success": True,
                    "sessions_cleared": sessions_cleared,
                    "suspicious_cleared": suspicious_cleared,
                    "message": "Buffers cleared successfully"
                })
                
            except Exception as e:
                return jsonify({"error": f"Failed to clear sessions: {str(e)}"}), 500
    
    def is_immediately_suspicious(self, session):
        """Quick check if session is suspicious - PRIORITIZES EKFiddle threat intelligence"""
        try:
            # PRIORITY 1: Check for EKFiddle comments (authoritative threat intelligence)
            # Any session with EKFiddle data is automatically suspicious
            ekfiddle = (session.get("ekfiddleComments") or 
                       session.get("sessionFlags") or 
                       session.get("ekfiddleFlags") or "").strip()
            
            if ekfiddle:
                # Any EKFiddle comment = suspicious (Low, Medium, High, Critical)
                return True
            
            # PRIORITY 2: Check error status codes (informational, not security threat)
            status = session.get('statusCode', 200)
            try:
                status = int(status)
            except (ValueError, TypeError):
                status = 200
            
            if status >= 400:
                return True  # Keep for informational purposes
            
            # Note: Generic URL/host pattern matching removed to prevent false positives
            # Only EKFiddle threat intelligence determines suspicious sessions
            
            return False
            
        except Exception as e:
            print(f"[enhanced-bridge] WARNING: Exception in is_immediately_suspicious: {e}", file=sys.stderr)
            return False
    
    def parse_ekfiddle_comments(self, ekfiddle_data):
        """Parse EKFiddle comments into structured data"""
        analysis = {
            "indicators": [],
            "threat_types": [],
            "severity": "unknown",
            "patterns_detected": [],
            "raw_comments": ekfiddle_data
        }
        
        if not ekfiddle_data:
            return analysis
        
        try:
            # Common EKFiddle indicators
            ekfiddle_lower = ekfiddle_data.lower()
            
            # Threat type detection
            if any(pattern in ekfiddle_lower for pattern in ['exploit', 'malware', 'trojan']):
                analysis["threat_types"].append("malware")
                analysis["severity"] = "high"
            
            if any(pattern in ekfiddle_lower for pattern in ['phishing', 'fake', 'scam']):
                analysis["threat_types"].append("phishing")
                analysis["severity"] = "high"
            
            if any(pattern in ekfiddle_lower for pattern in ['suspicious', 'anomaly', 'unusual']):
                analysis["threat_types"].append("suspicious")
                if analysis["severity"] == "unknown":
                    analysis["severity"] = "medium"
            
            # Pattern detection
            if 'javascript' in ekfiddle_lower:
                analysis["patterns_detected"].append("JavaScript analysis")
            if 'payload' in ekfiddle_lower:
                analysis["patterns_detected"].append("Payload detected")
            if 'redirect' in ekfiddle_lower:
                analysis["patterns_detected"].append("Redirect chain")
            if 'obfuscated' in ekfiddle_lower:
                analysis["patterns_detected"].append("Obfuscated content")
            
            # Extract specific indicators
            lines = ekfiddle_data.split('\n')
            for line in lines:
                line = line.strip()
                if line and len(line) > 5:  # Skip very short lines
                    analysis["indicators"].append(line)
            
            if not analysis["threat_types"]:
                analysis["severity"] = "low"
                
        except Exception as e:
            analysis["error"] = str(e)
        
        return analysis
    
    def assess_ekfiddle_threat(self, ekfiddle_data):
        """Assess threat level based on EKFiddle comments"""
        assessment = {
            "risk_score": 0.0,
            "threat_level": "NONE",
            "recommendations": [],
            "confidence": "unknown"
        }
        
        if not ekfiddle_data:
            return assessment
        
        try:
            ekfiddle_lower = ekfiddle_data.lower()
            
            # Risk scoring based on EKFiddle indicators
            risk_score = 0.0
            
            # High-risk indicators
            if any(pattern in ekfiddle_lower for pattern in ['exploit', 'malware', 'trojan', 'backdoor']):
                risk_score += 0.8
                assessment["recommendations"].append("IMMEDIATE ISOLATION - Malware detected")
                assessment["confidence"] = "high"
            
            if any(pattern in ekfiddle_lower for pattern in ['phishing', 'credential', 'steal']):
                risk_score += 0.7
                assessment["recommendations"].append("BLOCK AND INVESTIGATE - Phishing attempt")
                assessment["confidence"] = "high"
            
            # Medium-risk indicators
            if any(pattern in ekfiddle_lower for pattern in ['suspicious', 'anomaly', 'unusual']):
                risk_score += 0.5
                assessment["recommendations"].append("Enhanced monitoring recommended")
                if assessment["confidence"] == "unknown":
                    assessment["confidence"] = "medium"
            
            if any(pattern in ekfiddle_lower for pattern in ['obfuscated', 'encoded', 'packed']):
                risk_score += 0.4
                assessment["recommendations"].append("Content analysis required")
            
            # Adjust based on multiple indicators
            indicator_count = len([word for word in ['exploit', 'malware', 'suspicious', 'phishing', 'obfuscated'] if word in ekfiddle_lower])
            if indicator_count > 2:
                risk_score += 0.2
            
            # Cap at 1.0
            assessment["risk_score"] = min(risk_score, 1.0)
            
            # Determine threat level
            if risk_score >= 0.8:
                assessment["threat_level"] = "CRITICAL"
            elif risk_score >= 0.6:
                assessment["threat_level"] = "HIGH"
            elif risk_score >= 0.4:
                assessment["threat_level"] = "MEDIUM"
            elif risk_score >= 0.2:
                assessment["threat_level"] = "LOW"
            else:
                assessment["threat_level"] = "MINIMAL"
            
            if not assessment["recommendations"]:
                assessment["recommendations"].append("No immediate action required")
                
        except Exception as e:
            assessment["error"] = str(e)
        
        return assessment
    
    def summarize_ekfiddle_findings(self, sessions_with_ekfiddle):
        """Summarize EKFiddle findings across multiple sessions"""
        summary = {
            "total_sessions": len(sessions_with_ekfiddle),
            "threat_distribution": {},
            "severity_distribution": {},
            "top_patterns": {},
            "recommendations": []
        }
        
        try:
            for session in sessions_with_ekfiddle:
                analysis = session.get('ekfiddle_analysis', {})
                
                # Count threat types
                for threat_type in analysis.get('threat_types', []):
                    summary["threat_distribution"][threat_type] = summary["threat_distribution"].get(threat_type, 0) + 1
                
                # Count severities
                severity = analysis.get('severity', 'unknown')
                summary["severity_distribution"][severity] = summary["severity_distribution"].get(severity, 0) + 1
                
                # Count patterns
                for pattern in analysis.get('patterns_detected', []):
                    summary["top_patterns"][pattern] = summary["top_patterns"].get(pattern, 0) + 1
            
            # Generate recommendations
            high_severity = summary["severity_distribution"].get("high", 0)
            if high_severity > 0:
                summary["recommendations"].append(f"URGENT: {high_severity} high-severity threats detected by EKFiddle")
            
            medium_severity = summary["severity_distribution"].get("medium", 0)
            if medium_severity > 0:
                summary["recommendations"].append(f"MONITOR: {medium_severity} medium-severity threats require attention")
            
            if summary["total_sessions"] == 0:
                summary["recommendations"].append("No EKFiddle analysis data available")
            
        except Exception as e:
            summary["error"] = str(e)
        
        return summary
    
    def run(self, host='localhost', port=8081):
        """Start the enhanced real-time bridge server"""
        self.start_time = time.time()
        print(" Enhanced Fiddler Bridge - Data Extraction Mode")
        print(" Using port 8081 for Windows compatibility")
        print()
        print(f" Enhanced Fiddler Real-Time Bridge starting on {host}:{port}")
        print(" Configure Fiddler CustomRules.js to send live sessions here")
        print(" MCP tools can now access live sessions in real-time")
        print(f" Buffer capacity: {self.live_sessions.maxlen} sessions (FIFO auto-overflow)")
        print(" Streamlined to raw-data tools for LLM reasoning")
        print()
        print("Endpoints:")
        print(f"   POST http://{host}:{port}/live-session (Fiddler sends sessions here)")
        print(f"   GET  http://{host}:{port}/api/sessions (MCP queries live sessions)")
        print(f"   GET  http://{host}:{port}/api/session/<id> (Detailed analysis)")
        print(f"   GET  http://{host}:{port}/api/sessions/headers/<id> (Session headers)")
        print(f"   GET  http://{host}:{port}/api/sessions/body/<id> (Session body)")
        print(f"   GET  http://{host}:{port}/api/stats (Real-time statistics)")
        print(f"   POST http://{host}:{port}/api/clear (Clear session buffers)")
        print()
        print("  IMPORTANT: Update Fiddler CustomRules.js MCP_URL to:")
        print(f"   MCP_URL = \"http://127.0.0.1:{port}\";")
        print()
        print("  MCP Tools Focused On:")
        print("    Listing and searching sessions")
        print("    Retrieving headers and bodies")
        print("    Checking capture stats and timelines")
        print("    Clearing buffers deliberately")
        print()
        
        try:
            self.app.run(host=host, port=port, threaded=True, debug=False)
        except OSError as e:
            if "access" in str(e).lower() or "permission" in str(e).lower():
                print(f" Port {port} blocked. Trying port {port+1}...")
                self.app.run(host=host, port=port+1, threaded=True, debug=False)
            else:
                raise

if __name__ == "__main__":
    print(" Enhanced Fiddler Bridge - Streamlined Toolset")
    print(" Windows-compatible on port 8081")
    print()
    bridge = EnhancedFiddlerRealtimeBridge()
    bridge.run()
