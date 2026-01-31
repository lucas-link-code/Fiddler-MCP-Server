import System;
import System.Windows.Forms;
import System.IO;
import System.Net;
import System.Text;
import System.Collections;
import Fiddler;

// INTRODUCTION
//
// Well, hello there!
//
// Don't be scared! :-)
//
// This is the FiddlerScript Rules file, which creates some of the menu commands and
// other features of Progress Telerik Fiddler Classic. You can edit this file to modify or add new commands.
//
// The original version of this file is named SampleRules.js and it is in the
// \Program Files\Fiddler\ folder. When Fiddler Classic first runs, it creates a copy named
// CustomRules.js inside your \Documents\Fiddler2\Scripts folder. If you make a
// mistake in editing this file, simply delete the CustomRules.js file and restart
// Fiddler Classic. A fresh copy of the default rules will be created from the original
// sample rules file.

// The best way to edit this file is to install the FiddlerScript Editor, located in the Fiddler
// install directory %localappdata%\Programs\Fiddler\ScriptEditor\FSE2.exe

// GLOBALIZATION NOTE: Save this file using UTF-8 Encoding.

// JScript.NET Reference
// https://api.getfiddler.com/r/?msdnjsnet
//
// FiddlerScript Reference
// https://api.getfiddler.com/r/?fiddlerscriptcookbook

class Handlers
{
    // *****************
    //
    // This is the Handlers class. Pretty much everything you ever add to FiddlerScript
    // belongs right inside here, or inside one of the already-existing functions below.
    //
    // *****************

    // ======================= MCP CONFIG (edit as needed) =======================
    public static var MCP_URL: String = "http://127.0.0.1:8081";
    public static var MCP_POST_ENDPOINT: String = "/live-session";
    public static var MCP_TIMEOUT_MS: int = 2500; // not used by WebClient, kept for compatibility

    // Toggle in Rules menu to enable automatic real-time posts
    // NOTE: Posts are now asynchronous via ThreadPool to prevent Fiddler UI blocking
    public static RulesOption("Post to MCP in real-time")
    var m_McpLive: boolean = false;

    // Only text responses get bodies posted; others are metadata-only
    public static var BODY_MIME_ALLOW: String[] = [
        "text/html",
        "application/javascript", 
        "application/x-javascript",
        "text/javascript",
        "application/json",
        "text/plain",
        "text/css"
    ];

    // Max bytes of response body to include (Base64). 0 = never include body.
    public static var BODY_MAX_BYTES: int = 2000000; // 2 MB cap

    // ======================= MCP HELPERS =======================

    // Returns true if MIME type looks text-like and is in allow-list.
    static function McpIsAllowedTextMime(mime: String): boolean {
        if ((null == mime) || (mime.Length == 0)) return false;
        mime = mime.ToLower();
        var semi: int = mime.IndexOf(';');
        if (semi > 0) mime = mime.Substring(0, semi).Trim();
        for (var i: int = 0; i < BODY_MIME_ALLOW.length; i++) {
            if (mime == BODY_MIME_ALLOW[i]) return true;
        }
        return false;
    }

    // Enhanced JSON string escaper using StringBuilder for performance
    // Uses efficient StringBuilder to avoid O(n²) string concatenation
    static function McpJsonEscape(str: String): String {
        if (!str || str.length == 0) return "";
        
        // Declare all variables at function scope (JScript.NET requirement)
        var needsEscaping: boolean = false;
        var code: int = 0;
        var j: int = 0;
        var i: int = 0;
        var c: char;
        var sb: System.Text.StringBuilder;
        
        // Quick check: if no control chars or special chars, return as-is
        // This avoids expensive escaping for most short strings
        for (j = 0; j < str.length; j++) {
            code = System.Convert.ToInt32(str[j]);
            if (code < 0x20 || code == 0x22 || code == 0x5C || code == 0x7F) {
                needsEscaping = true;
                break;
            }
        }
        if (!needsEscaping) return str;
        
        // Use StringBuilder for efficient string building (O(n) instead of O(n²))
        sb = new System.Text.StringBuilder(str.length + 100);
        
        for (i = 0; i < str.length; i++) {
            c = str[i];
            code = System.Convert.ToInt32(c);
            
            // Handle common escape sequences using string literals for JScript.NET compatibility
            if (c == '\\') sb.Append("\\\\");
            else if (c == '"') sb.Append("\\\"");
            else if (c == '\b') sb.Append("\\b");
            else if (c == '\f') sb.Append("\\f");
            else if (c == '\n') sb.Append("\\n");
            else if (c == '\r') sb.Append("\\r");
            else if (c == '\t') sb.Append("\\t");
            // Handle control characters (0x00-0x1F) and DEL (0x7F)
            else if (code < 0x20 || code == 0x7F) {
                sb.Append("\\u");
                sb.Append(code.ToString("X4").PadLeft(4, '0'));
            }
            // Normal characters pass through
            else sb.Append(c);
        }
        return sb.ToString();
    }

    // Enhanced JSON builder with fields needed for MCP threat detection
    // Schema matches Enhanced Bridge expectations:
    // id, fiddler_session_id, timestamp, method, url, host, statusCode, 
    // contentType, contentLength, requestHeaders, responseHeaders, responseBody
    static function McpBuildSimpleJson(oSession: Session): String {
        try {
            // Build JSON with exact schema expected by Enhanced Bridge
            var json: String = "{";
            json += '"id":"' + oSession.id + '",';
            json += '"fiddler_session_id":"' + oSession.id + '",';
            json += '"timestamp":"' + System.DateTime.UtcNow.ToString("o") + '",';
            
            // Method, URL, host - McpJsonEscape has quick-check optimization
            // Most are clean ASCII, so quick-check returns immediately (no escaping overhead)
            json += '"method":"' + McpJsonEscape(oSession.RequestMethod || "GET") + '",';
            json += '"url":"' + McpJsonEscape(oSession.fullUrl || "") + '",';
            json += '"host":"' + McpJsonEscape(oSession.host || "") + '",';
            json += '"statusCode":' + (oSession.responseCode || 0) + ',';
            
            // Add content type (critical for threat detection)
            var contentType: String = "";
            if (oSession.oResponse && oSession.oResponse["Content-Type"]) {
                contentType = oSession.oResponse["Content-Type"];
            }
            json += '"contentType":"' + McpJsonEscape(contentType) + '",';
            
            // Add content length
            var contentLength: int = 0;
            if (oSession.responseBodyBytes) {
                contentLength = oSession.responseBodyBytes.Length;
            }
            json += '"contentLength":' + contentLength + ',';
            
            // Add EKFiddle comments (threat intelligence from EKFiddle extension)
            // Try multiple property locations with fallback chain
            var ekfiddleComments: String = "";
            if (oSession["ui-comments"]) {
                ekfiddleComments = oSession["ui-comments"];
            } else if (oSession["$Comments"]) {
                ekfiddleComments = oSession["$Comments"];
            } else if (oSession["Comments"]) {
                ekfiddleComments = oSession["Comments"];
            }
            json += '"ekfiddleComments":"' + McpJsonEscape(ekfiddleComments) + '",';
            
            // Add session flags that might contain EKFiddle data (alternate location)
            var sessionFlags: String = "";
            if (oSession.oFlags && oSession.oFlags["ui-comments"]) {
                sessionFlags = oSession.oFlags["ui-comments"];
            } else if (oSession.oFlags && oSession.oFlags["$Comments"]) {
                sessionFlags = oSession.oFlags["$Comments"];
            }
            json += '"sessionFlags":"' + McpJsonEscape(sessionFlags) + '",';
            
            // Also check for EKFiddle-specific flags (enhanced coverage)
            var ekfiddleFlags: String = "";
            if (oSession["X-EKFiddle"]) {
                ekfiddleFlags = oSession["X-EKFiddle"];
            } else if (oSession["x-ekfiddle"]) {
                ekfiddleFlags = oSession["x-ekfiddle"];
            } else if (oSession["x-ekfiddle-analysis"]) {
                ekfiddleFlags = oSession["x-ekfiddle-analysis"];
            }
            json += '"ekfiddleFlags":"' + McpJsonEscape(ekfiddleFlags) + '",';
            
            // Add request headers
            json += '"requestHeaders":{';
            if (oSession.oRequest) {
                if (oSession.oRequest["User-Agent"]) {
                    json += '"User-Agent":"' + McpJsonEscape(oSession.oRequest["User-Agent"]) + '",';
                }
                if (oSession.oRequest["Referer"]) {
                    json += '"Referer":"' + McpJsonEscape(oSession.oRequest["Referer"]) + '",';
                }
            }
            json += '"_simplified":true},';
            
            // Add response headers
            json += '"responseHeaders":{';
            if (oSession.oResponse) {
                if (contentType) {
                    json += '"Content-Type":"' + McpJsonEscape(contentType) + '",';
                }
                if (oSession.oResponse["Server"]) {
                    json += '"Server":"' + McpJsonEscape(oSession.oResponse["Server"]) + '",';
                }
            }
            json += '"_simplified":true},';
            
            // Add request body (for POST analysis)
            json += '"requestBody":"';
            if (oSession.RequestMethod == "POST" && oSession.requestBodyBytes) {
                try {
                    var requestText: String = oSession.GetRequestBodyAsString();
                    if (requestText && requestText.length > 0 && requestText.length < 5000) {
                        json += McpJsonEscape(requestText);
                    }
                } catch (e) {
                    // If body extraction fails, log and continue without it
                    FiddlerApplication.Log.LogString("MCP: Failed to extract request body for session " + oSession.id + ": " + e.Message);
                }
            }
            json += '",';
            
            // Add response body for threat detection (gate by MIME type and size)
            // Strategy: Use base64 encoding for bodies >1KB to avoid JSON escaping edge cases
            // JavaScript files often contain complex code that can break JSON escaping
            var USE_BASE64_THRESHOLD: int = 1000; // 1KB - prioritize reliability over readability
            
            if (oSession.responseBodyBytes && contentLength > 0 && contentLength <= BODY_MAX_BYTES) {
                try {
                    // Check if MIME type is in allowed list for body inclusion
                    if (McpIsAllowedTextMime(contentType)) {
                        // CRITICAL FIX: Check byte length FIRST before attempting string decode
                        // This prevents encoding errors when response contains non-UTF8 bytes
                        if (contentLength > USE_BASE64_THRESHOLD) {
                            // For large bodies, use base64 directly without string decode
                            // This avoids encoding errors with binary or non-UTF8 content
                            json += '"responseBodyBase64":"' + System.Convert.ToBase64String(oSession.responseBodyBytes) + '",';
                            json += '"responseBodyEncoding":"base64",';
                            json += '"responseBody":""'; // Empty string for backward compatibility
                        } else {
                            // For small bodies only, attempt string decode
                            try {
                                var text: String = oSession.GetResponseBodyAsString();
                                if (text && text.length > 0) {
                                    json += '"responseBody":"' + McpJsonEscape(text) + '"';
                                } else {
                                    json += '"responseBody":""';
                                }
                            } catch (decodeError) {
                                // Encoding error - fall back to base64
                                FiddlerApplication.Log.LogString("MCP: String decode failed for session " + oSession.id + ", using base64 fallback");
                                json += '"responseBodyBase64":"' + System.Convert.ToBase64String(oSession.responseBodyBytes) + '",';
                                json += '"responseBodyEncoding":"base64",';
                                json += '"responseBody":""';
                            }
                        }
                    } else {
                        json += '"responseBody":""';
                    }
                } catch (e) {
                    // If body extraction fails, log and continue without it
                    FiddlerApplication.Log.LogString("MCP: Failed to extract response body for session " + oSession.id + ": " + e.Message);
                    json += '"responseBody":""';
                }
            } else {
                json += '"responseBody":""';
            }
            
            json += "}";
            return json;
        } catch (e) {
            FiddlerApplication.Log.LogString("MCP: JSON build failed for session " + oSession.id + ": " + e.Message);
            return '{"error":"json-build-failed","session_id":"' + oSession.id + '","details":"' + McpJsonEscape(e.Message) + '"}';
        }
    }

    // Internal worker function for threaded POST operation
    static function McpHttpPostWorker(jsonData: Object): void {
        var wc: System.Net.WebClient = null;
        try {
            wc = new System.Net.WebClient();
            wc.Headers.Add("Content-Type", "application/json");
            var response: String = wc.UploadString(MCP_URL + MCP_POST_ENDPOINT, "POST", String(jsonData));
            
            // Parse response to check for errors
            if (response && response.indexOf('"ok":false') >= 0) {
                FiddlerApplication.Log.LogString("MCP POST rejected: " + response);
            }
        } catch (ex) {
            // Log detailed error information
            var jsonStr: String = String(jsonData);
            var preview: String = (jsonStr.length > 200) ? jsonStr.Substring(0, 200) + "..." : jsonStr;
            FiddlerApplication.Log.LogString("MCP POST failed: " + ex.Message + " | Preview: " + preview);
        } finally {
            if (null != wc) wc.Dispose();
        }
    }

    static function McpHttpPost(json: String): void {
        // Queue POST operation on background thread to avoid blocking Fiddler UI
        System.Threading.ThreadPool.QueueUserWorkItem(McpHttpPostWorker, json);
    }

    // Public helper you can call from OnBeforeResponse, or from menu actions.
    static function McpTryPost(oSession: Session): void {
        try {
            // Skip tunnels or sessions with no HTTP response
            if ((oSession.oResponse == null) || (oSession.responseCode == 0)) return;
            
            // IMPORTANT: Skip hidden sessions to maintain ID alignment with Fiddler UI
            // This ensures session IDs in the bridge match what the analyst sees in Fiddler
            var uiHide: String = oSession["ui-hide"];
            if (uiHide != null && uiHide.Length > 0) {
                // Session is hidden from UI (CONNECT tunnel, filtered 304, etc.)
                return;
            }

            var json: String = McpBuildSimpleJson(oSession);
            McpHttpPost(json);
        } catch (e) {
            FiddlerApplication.Log.LogString("MCP error: " + e.Message);
        }
    }

    // ======================= TOOLS MENU ACTIONS =======================

    // Internal worker function for threaded connection test
    static function McpTestConnectionWorker(unused: Object): void {
        try {
            var wc: System.Net.WebClient = new System.Net.WebClient();
            wc.Headers.Add("Accept", "application/json");
            var s: String = wc.DownloadString(MCP_URL + "/api/stats");
            FiddlerApplication.UI.SetStatusText("MCP OK: " + s);
            wc.Dispose();
        } catch (e) {
            FiddlerApplication.UI.SetStatusText("MCP not reachable: " + e.Message);
        }
    }

    // Tools → Test MCP Connection (GET /api/stats)
    public static ToolsAction("Test MCP Connection")
    function McpTestConnection(): void {
        FiddlerApplication.UI.SetStatusText("Testing MCP connection...");
        
        // Test connection asynchronously to avoid blocking UI
        System.Threading.ThreadPool.QueueUserWorkItem(McpTestConnectionWorker, null);
    }

    // Tools → Send selected sessions to MCP (manual push)
    public static ToolsAction("Send selected to MCP")
    function McpSendSelected(): void {
        var sel: Session[] = FiddlerApplication.UI.GetSelectedSessions();
        if ((null == sel) || (sel.Length < 1)) {
            FiddlerApplication.UI.SetStatusText("No sessions selected.");
            return;
        }
        var sent: int = 0;
        for (var i: int = 0; i < sel.Length; i++) {
            var s: Session = sel[i];
            McpTryPost(s);
            s["ui-color"] = "yellow"; // visual mark
            sent++;
        }
        FiddlerApplication.UI.SetStatusText("MCP: sent " + sent + " session(s).");
    }

    // ==================================================================

    // The following snippet demonstrates a custom-bound column for the Web Sessions list.
    // See https://api.getfiddler.com/r/?fiddlercolumns for more info
    /*
      public static BindUIColumn("Method", 60)
      function FillMethodColumn(oS: Session): String {
         return oS.RequestMethod;
      }
    */

    // The following snippet demonstrates how to create a custom tab that shows simple text
    /*
       public BindUITab("Flags")
       static function FlagsReport(arrSess: Session[]):String {
        var oSB: System.Text.StringBuilder = new System.Text.StringBuilder();
        for (var i:int = 0; i<arrSess.Length; i++)
        {
            oSB.AppendLine("SESSION FLAGS");
            oSB.AppendFormat("{0}: {1}\n", arrSess[i].id, arrSess[i].fullUrl);
            for(var sFlag in arrSess[i].oFlags)
            {
                oSB.AppendFormat("\t{0}:\t\t{1}\n", sFlag.Key, sFlag.Value);
            }
        }
        return oSB.ToString();
    }
    */

    // You can create a custom menu like so:
    /*
    QuickLinkMenu("&Links") 
    QuickLinkItem("IE GeoLoc TestDrive", "http://ie.microsoft.com/testdrive/HTML5/Geolocation/Default.html")
    QuickLinkItem("FiddlerCore", "https://api.getfiddler.com/r/?fiddlercore")
    public static function DoLinksMenu(sText: String, sAction: String)
    {
        Utilities.LaunchHyperlink(sAction);
    }
    */

    public static RulesOption("Hide 304s")
    BindPref("fiddlerscript.rules.Hide304s")
    var m_Hide304s: boolean = false;

    // Cause Fiddler Classic to override the Accept-Language header with one of the defined values
    public static RulesOption("Request &Japanese Content")
    var m_Japanese: boolean = false;

    // Automatic Authentication
    public static RulesOption("&Automatically Authenticate")
    BindPref("fiddlerscript.rules.AutoAuth")
    var m_AutoAuth: boolean = false;

    // Cause Fiddler Classic to override the User-Agent header with one of the defined values
    // The page http://browserscope2.org/browse?category=selectors&ua=Mobile%20Safari is a good place to find updated versions of these
    RulesString("&User-Agents", true) 
    BindPref("fiddlerscript.ephemeral.UserAgentString")
    RulesStringValue(0,"Netscape &3", "Mozilla/3.0 (Win95; I)")
    RulesStringValue(1,"WinPhone8.1", "Mozilla/5.0 (Mobile; Windows Phone 8.1; Android 4.0; ARM; Trident/7.0; Touch; rv:11.0; IEMobile/11.0; NOKIA; Lumia 520) like iPhone OS 7_0_3 Mac OS X AppleWebKit/537 (KHTML, like Gecko) Mobile Safari/537")
    RulesStringValue(2,"&Safari5 (Win7)", "Mozilla/5.0 (Windows; U; Windows NT 6.1; en-US) AppleWebKit/533.21.1 (KHTML, like Gecko) Version/5.0.5 Safari/533.21.1")
    RulesStringValue(3,"Safari9 (Mac)", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11) AppleWebKit/601.1.56 (KHTML, like Gecko) Version/9.0 Safari/601.1.56")
    RulesStringValue(4,"iPad", "Mozilla/5.0 (iPad; CPU OS 8_3 like Mac OS X) AppleWebKit/600.1.4 (KHTML, like Gecko) Version/8.0 Mobile/12F5027d Safari/600.1.4")
    RulesStringValue(5,"iPhone6", "Mozilla/5.0 (iPhone; CPU iPhone OS 8_3 like Mac OS X) AppleWebKit/600.1.4 (KHTML, like Gecko) Version/8.0 Mobile/12F70 Safari/600.1.4")
    RulesStringValue(6,"IE &6 (XPSP2)", "Mozilla/4.0 (compatible; MSIE 6.0; Windows NT 5.1; SV1)")
    RulesStringValue(7,"IE &7 (Vista)", "Mozilla/4.0 (compatible; MSIE 7.0; Windows NT 6.0; SLCC1)")
    RulesStringValue(8,"IE 8 (Win2k3 x64)", "Mozilla/4.0 (compatible; MSIE 8.0; Windows NT 5.2; WOW64; Trident/4.0)")
    RulesStringValue(9,"IE &8 (Win7)", "Mozilla/4.0 (compatible; MSIE 8.0; Windows NT 6.1; Trident/4.0)")
    RulesStringValue(10,"IE 9 (Win7)", "Mozilla/5.0 (compatible; MSIE 9.0; Windows NT 6.1; Trident/5.0)")
    RulesStringValue(11,"IE 10 (Win8)", "Mozilla/5.0 (compatible; MSIE 10.0; Windows NT 6.2; WOW64; Trident/6.0)")
    RulesStringValue(12,"IE 11 (Surface2)", "Mozilla/5.0 (Windows NT 6.3; ARM; Trident/7.0; Touch; rv:11.0) like Gecko")
    RulesStringValue(13,"IE 11 (Win8.1)", "Mozilla/5.0 (Windows NT 6.3; WOW64; Trident/7.0; rv:11.0) like Gecko")
    RulesStringValue(14,"Edge (Win10)", "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/46.0.2486.0 Safari/537.36 Edge/13.11082")
    RulesStringValue(15,"&Opera", "Opera/9.80 (Windows NT 6.2; WOW64) Presto/2.12.388 Version/12.17")
    RulesStringValue(16,"&Firefox 3.6", "Mozilla/5.0 (Windows; U; Windows NT 6.1; en-US; rv:1.9.2.7) Gecko/20100625 Firefox/3.6.7")
    RulesStringValue(17,"&Firefox 43", "Mozilla/5.0 (Windows NT 6.3; WOW64; rv:43.0) Gecko/20100101 Firefox/43.0")
    RulesStringValue(18,"&Firefox Phone", "Mozilla/5.0 (Mobile; rv:18.0) Gecko/18.0 Firefox/18.0")
    RulesStringValue(19,"&Firefox (Mac)", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.8; rv:24.0) Gecko/20100101 Firefox/24.0")
    RulesStringValue(20,"Chrome (Win)", "Mozilla/5.0 (Windows NT 6.3; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/48.0.2564.48 Safari/537.36")
    RulesStringValue(21,"Chrome (Android)", "Mozilla/5.0 (Linux; Android 5.1.1; Nexus 5 Build/LMY48B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/43.0.2357.78 Mobile Safari/537.36")
    RulesStringValue(22,"ChromeBook", "Mozilla/5.0 (X11; CrOS x86_64 6680.52.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/41.0.2272.74 Safari/537.36")
    RulesStringValue(23,"GoogleBot Crawler", "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)")
    RulesStringValue(24,"Kindle Fire (Silk)", "Mozilla/5.0 (Macintosh; U; Intel Mac OS X 10_6_3; en-us; Silk/1.0.22.79_10013310) AppleWebKit/533.16 (KHTML, like Gecko) Version/5.0 Safari/533.16 Silk-Accelerated=true")
    RulesStringValue(25,"&Custom...", "%CUSTOM%")
    public static var sUA: String = null;

    // Cause Fiddler Classic to delay HTTP traffic to simulate typical 56k modem conditions
    public static RulesOption("Simulate &Modem Speeds", "Per&formance")
    var m_SimulateModem: boolean = false;

    // Removes HTTP-caching related headers and specifies "no-cache" on requests and responses
    public static RulesOption("&Disable Caching", "Per&formance")
    var m_DisableCaching: boolean = false;

    public static RulesOption("Cache Always &Fresh", "Per&formance")
    var m_AlwaysFresh: boolean = false;
        
    // Force a manual reload of the script file.  Resets all
    // RulesOption variables to their defaults.
    public static ToolsAction("Reset Script")
    function DoManualReload() { 
        FiddlerObject.ReloadScript();
    }

    public static ContextAction("Decode Selected Sessions")
    function DoRemoveEncoding(oSessions: Session[]) {
        for (var x:int = 0; x < oSessions.Length; x++){
            oSessions[x].utilDecodeRequest();
            oSessions[x].utilDecodeResponse();
        }
        UI.actUpdateInspector(true,true);
    }

    static function OnBeforeRequest(oSession: Session) {
        // Sample Rule: Color ASPX requests in RED
        // if (oSession.uriContains(".aspx")) {	oSession["ui-color"] = "red";	}

        // Sample Rule: Flag POSTs to telerik.com in italics
        // if (oSession.HostnameIs("www.telerik.com") && oSession.HTTPMethodIs("POST")) {	oSession["ui-italic"] = "yup";	}

        // Sample Rule: Break requests for URLs containing "/sandbox/"
        // if (oSession.uriContains("/sandbox/")) {
        //     oSession.oFlags["x-breakrequest"] = "yup";	// Existence of the x-breakrequest flag creates a breakpoint; the "yup" value is unimportant.
        // }

        if ((null != gs_ReplaceToken) && (oSession.url.indexOf(gs_ReplaceToken)>-1)) {   // Case sensitive
            oSession.url = oSession.url.Replace(gs_ReplaceToken, gs_ReplaceTokenWith); 
        }
        if ((null != gs_OverridenHost) && (oSession.host.toLowerCase() == gs_OverridenHost)) {
            oSession["x-overridehost"] = gs_OverrideHostWith; 
        }

        if ((null!=bpRequestURI) && oSession.uriContains(bpRequestURI)) {
            oSession["x-breakrequest"]="uri";
        }

        if ((null!=bpMethod) && (oSession.HTTPMethodIs(bpMethod))) {
            oSession["x-breakrequest"]="method";
        }

        if ((null!=uiBoldURI) && oSession.uriContains(uiBoldURI)) {
            oSession["ui-bold"]="QuickExec";
        }

        if (m_SimulateModem) {
            // Delay sends by 300ms per KB uploaded.
            oSession["request-trickle-delay"] = "300"; 
            // Delay receives by 150ms per KB downloaded.
            oSession["response-trickle-delay"] = "150"; 
        }

        if (m_DisableCaching) {
            oSession.oRequest.headers.Remove("If-None-Match");
            oSession.oRequest.headers.Remove("If-Modified-Since");
            oSession.oRequest["Pragma"] = "no-cache";
        }

        // User-Agent Overrides
        if (null != sUA) {
            oSession.oRequest["User-Agent"] = sUA; 
        }

        if (m_Japanese) {
            oSession.oRequest["Accept-Language"] = "ja";
        }

        if (m_AutoAuth) {
            // Automatically respond to any authentication challenges using the 
            // current Fiddler Classic user's credentials. You can change (default)
            // to a domain\\username:password string if preferred.
            //
            // WARNING: This setting poses a security risk if remote 
            // connections are permitted!
            oSession["X-AutoAuth"] = "(default)";
        }

        if (m_AlwaysFresh && (oSession.oRequest.headers.Exists("If-Modified-Since") || oSession.oRequest.headers.Exists("If-None-Match")))
        {
            oSession.utilCreateResponseAndBypassServer();
            oSession.responseCode = 304;
            oSession["ui-backcolor"] = "Lavender";
        }
    }

    // This function is called immediately after a set of request headers has
    // been read from the client. This is typically too early to do much useful
    // work, since the body hasn't yet been read, but sometimes it may be useful.
    //
    // For instance, see 
    // http://blogs.msdn.com/b/fiddler/archive/2011/11/05/http-expect-continue-delays-transmitting-post-bodies-by-up-to-350-milliseconds.aspx
    // for one useful thing you can do with this handler.
    //
    // Note: oSession.requestBodyBytes is not available within this function!
/*
    static function OnPeekAtRequestHeaders(oSession: Session) {
        var sProc = ("" + oSession["x-ProcessInfo"]).ToLower();
        if (!sProc.StartsWith("mylowercaseappname")) oSession["ui-hide"] = "NotMyApp";
    }
*/

    //
    // If a given session has response streaming enabled, then the OnBeforeResponse function 
    // is actually called AFTER the response was returned to the client.
    //
    // In contrast, this OnPeekAtResponseHeaders function is called before the response headers are 
    // sent to the client (and before the body is read from the server).  Hence this is an opportune time 
    // to disable streaming (oSession.bBufferResponse = true) if there is something in the response headers 
    // which suggests that tampering with the response body is necessary.
    // 
    // Note: oSession.responseBodyBytes is not available within this function!
    //
    static function OnPeekAtResponseHeaders(oSession: Session) {
        //FiddlerApplication.Log.LogFormat("Session {0}: Response header peek shows status is {1}", oSession.id, oSession.responseCode);
        if (m_DisableCaching) {
            oSession.oResponse.headers.Remove("Expires");
            oSession.oResponse["Cache-Control"] = "no-cache";
        }

        if ((bpStatus>0) && (oSession.responseCode == bpStatus)) {
            oSession["x-breakresponse"]="status";
            oSession.bBufferResponse = true;
        }
        
        if ((null!=bpResponseURI) && oSession.uriContains(bpResponseURI)) {
            oSession["x-breakresponse"]="uri";
            oSession.bBufferResponse = true;
        }

    }

    static function OnBeforeResponse(oSession: Session) {
        if (m_Hide304s && oSession.responseCode == 304) {
            oSession["ui-hide"] = "true";
        }
        // === MCP: Real-time post if enabled ===
        if (m_McpLive) Handlers.McpTryPost(oSession);
    }

/*
    // This function executes just before Fiddler Classic returns an error that it has
    // itself generated (e.g. "DNS Lookup failure") to the client application.
    // These responses will not run through the OnBeforeResponse function above.
    static function OnReturningError(oSession: Session) {
    }
*/
/*
    // This function executes after Fiddler Classic finishes processing a Session, regardless
    // of whether it succeeded or failed. Note that this typically runs AFTER the last
    // update of the Web Sessions UI listitem, so you must manually refresh the Session's
    // UI if you intend to change it.
    static function OnDone(oSession: Session) {
    }
*/

    /*
    static function OnBoot() {
        MessageBox.Show("Fiddler Classic has finished booting");
        System.Diagnostics.Process.Start("iexplore.exe");

        UI.ActivateRequestInspector("HEADERS");
        UI.ActivateResponseInspector("HEADERS");
    }
    */

    /*
    static function OnBeforeShutdown(): Boolean {
        // Return false to cancel shutdown.
        return ((0 == FiddlerApplication.UI.lvSessions.TotalItemCount()) ||
                (DialogResult.Yes == MessageBox.Show("Allow Fiddler Classic to exit?", "Go Bye-bye?",
                 MessageBoxButtons.YesNo, MessageBoxIcon.Question, MessageBoxDefaultButton.Button2)));
    }
    */

    /*
    static function OnShutdown() {
            MessageBox.Show("Fiddler Classic has shutdown");
    }
    */

    /*
    static function OnAttach() {
        MessageBox.Show("Fiddler Classic is now the system proxy");
    }
    */

    /*
    static function OnDetach() {
        MessageBox.Show("Fiddler Classic is no longer the system proxy");
    }
    */

    // The Main() function runs everytime your FiddlerScript compiles
    static function Main() {
        var today: Date = new Date();
        FiddlerObject.StatusText = " CustomRules.js was loaded at: " + today;

        // Uncomment to add a "Server" column containing the response "Server" header, if present
        // UI.lvSessions.AddBoundColumn("Server", 50, "@response.server");

        // Uncomment to add a global hotkey (Win+G) that invokes the ExecAction method below...
        // UI.RegisterCustomHotkey(HotkeyModifiers.Windows, Keys.G, "screenshot"); 
    }

    // These static variables are used for simple breakpointing & other QuickExec rules 
    BindPref("fiddlerscript.ephemeral.bpRequestURI")
    public static var bpRequestURI:String = null;

    BindPref("fiddlerscript.ephemeral.bpResponseURI")
    public static var bpResponseURI:String = null;

    BindPref("fiddlerscript.ephemeral.bpMethod")
    public static var bpMethod: String = null;

    static var bpStatus:int = -1;
    static var uiBoldURI: String = null;
    static var gs_ReplaceToken: String = null;
    static var gs_ReplaceTokenWith: String = null;
    static var gs_OverridenHost: String = null;
    static var gs_OverrideHostWith: String = null;

    // The OnExecAction function is called by either the QuickExec box in the Fiddler Classic window,
    // or by the ExecAction.exe command line utility.
    static function OnExecAction(sParams: String[]): Boolean {

        FiddlerObject.StatusText = "ExecAction: " + sParams[0];

        var sAction = sParams[0].toLowerCase();
        switch (sAction) {
        case "bold":
            if (sParams.Length<2) {uiBoldURI=null; FiddlerObject.StatusText="Bolding cleared"; return false;}
            uiBoldURI = sParams[1]; FiddlerObject.StatusText="Bolding requests for " + uiBoldURI;
            return true;
        case "bp":
            FiddlerObject.alert("bpu = breakpoint request for uri\nbpm = breakpoint request method\nbps=breakpoint response status\nbpafter = breakpoint response for URI");
            return true;
        case "bps":
            if (sParams.Length<2) {bpStatus=-1; FiddlerObject.StatusText="Response Status breakpoint cleared"; return false;}
            bpStatus = parseInt(sParams[1]); FiddlerObject.StatusText="Response status breakpoint for " + sParams[1];
            return true;
        case "bpv":
        case "bpm":
            if (sParams.Length<2) {bpMethod=null; FiddlerObject.StatusText="Request Method breakpoint cleared"; return false;}
            bpMethod = sParams[1].toUpperCase(); FiddlerObject.StatusText="Request Method breakpoint for " + bpMethod;
            return true;
        case "bpu":
            if (sParams.Length<2) {bpRequestURI=null; FiddlerObject.StatusText="RequestURI breakpoint cleared"; return false;}
            bpRequestURI = sParams[1]; 
            FiddlerObject.StatusText="RequestURI breakpoint for "+sParams[1];
            return true;
        case "bpa":
        case "bpafter":
            if (sParams.Length<2) {bpResponseURI=null; FiddlerObject.StatusText="ResponseURI breakpoint cleared"; return false;}
            bpResponseURI = sParams[1]; 
            FiddlerObject.StatusText="ResponseURI breakpoint for "+sParams[1];
            return true;
        case "overridehost":
            if (sParams.Length<3) {gs_OverridenHost=null; FiddlerObject.StatusText="Host Override cleared"; return false;}
            gs_OverridenHost = sParams[1].toLowerCase();
            gs_OverrideHostWith = sParams[2];
            FiddlerObject.StatusText="Connecting to [" + gs_OverrideHostWith + "] for requests to [" + gs_OverridenHost + "]";
            return true;
        case "urlreplace":
            if (sParams.Length<3) {gs_ReplaceToken=null; FiddlerObject.StatusText="URL Replacement cleared"; return false;}
            gs_ReplaceToken = sParams[1];
            gs_ReplaceTokenWith = sParams[2].Replace(" ", "%20");  // Simple helper
            FiddlerObject.StatusText="Replacing [" + gs_ReplaceToken + "] in URIs with [" + gs_ReplaceTokenWith + "]";
            return true;
        case "allbut":
        case "keeponly":
            if (sParams.Length<2) { FiddlerObject.StatusText="Please specify Content-Type to retain during wipe."; return false;}
            UI.actSelectSessionsWithResponseHeaderValue("Content-Type", sParams[1]);
            UI.actRemoveUnselectedSessions();
            UI.lvSessions.SelectedItems.Clear();
            FiddlerObject.StatusText="Removed all but Content-Type: " + sParams[1];
            return true;
        case "stop":
            UI.actDetachProxy();
            return true;
        case "start":
            UI.actAttachProxy();
            return true;
        case "cls":
        case "clear":
            UI.actRemoveAllSessions();
            return true;
        case "g":
        case "go":
            UI.actResumeAllSessions();
            return true;
        case "goto":
            if (sParams.Length != 2) return false;
            Utilities.LaunchHyperlink("https://www.google.com/search?hl=en&btnI=I%27m+Feeling+Lucky&q=" + Utilities.UrlEncode(sParams[1]));
            return true;
        case "help":
            Utilities.LaunchHyperlink("https://api.getfiddler.com/r/?quickexec");
            return true;
        case "hide":
            UI.actMinimizeToTray();
            return true;
        case "log":
            FiddlerApplication.Log.LogString((sParams.Length<2) ? "User couldn't think of anything to say..." : sParams[1]);
            return true;
        case "nuke":
            UI.actClearWinINETCache();
            UI.actClearWinINETCookies(); 
            return true;
        case "screenshot":
            UI.actCaptureScreenshot(false);
            return true;
        case "show":
            UI.actRestoreWindow();
            return true;
        case "tail":
            if (sParams.Length<2) { FiddlerObject.StatusText="Please specify # of sessions to trim the session list to."; return false;}
            UI.TrimSessionList(int.Parse(sParams[1]));
            return true;
        case "quit":
            UI.actExit();
            return true;
        case "dump":
            UI.actSelectAll();
            UI.actSaveSessionsToZip(CONFIG.GetPath("Captures") + "dump.saz");
            UI.actRemoveAllSessions();
            FiddlerObject.StatusText = "Dumped all sessions to " + CONFIG.GetPath("Captures") + "dump.saz";
            return true;

        default:
            if (sAction.StartsWith("http") || sAction.StartsWith("www.")) {
                System.Diagnostics.Process.Start(sParams[0]);
                return true;
            }
            else
            {
                FiddlerObject.StatusText = "Requested ExecAction: '" + sAction + "' not found. Type HELP to learn more.";
                return false;
            }
        }
    }
}
