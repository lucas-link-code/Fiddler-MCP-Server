import System;
import System.Windows.Forms;
import System.IO;
import System.Net;
import System.Text;
import System.Collections;
import Fiddler;
import System.Text.RegularExpressions;


// INTRODUCTION
//
// Well, hello there!
//
// This is the FiddlerScript Rules file, which creates some of the menu commands and
// other features of Fiddler. You can edit this file to modify or add new commands.
//
// The original version of this file is named SampleRules.js and it is in the
// \Program Files\Fiddler\ folder. When Fiddler first runs, it creates a copy named
// CustomRules.js inside your \Documents\Fiddler2\Scripts folder. If you make a 
// mistake in editing this file, simply delete the CustomRules.js file and restart
// Fiddler. A fresh copy of the default rules will be created from the original
// sample rules file.

// The best way to edit this file is to install the FiddlerScript Editor, part of
// the free SyntaxEditing addons. Get it here: http://fiddler2.com/r/?SYNTAXVIEWINSTALL

// GLOBALIZATION NOTE: Save this file using UTF-8 Encoding.

// JScript.NET Reference
// http://fiddler2.com/r/?msdnjsnet
//
// FiddlerScript Reference
// http://fiddler2.com/r/?fiddlerscriptcookbook

class Handlers
{
	
	// *****************
	//
	// This is the Handlers class. Pretty much everything you ever add to FiddlerScript
	// belongs right inside here, or inside one of the already-existing functions below.
	//
	// *****************
	
	
    // Create a new option on the Rules menu. Set the default value for the option.
  				
	//public static RulesOption("&Decode ZSTD")
	//BindPref("fiddlerscript.rules.DecodeZSTD")
	//var m_ZSTDdoDecode: boolean = true; 
		
	public static RulesOption("ZSTD Bin Path")
	BindPref("fiddlerscript.rules.ZSTDBinPath")
	var m_ZSTDBinPath: String = "C:\\Users\\user\\Downloads\\zstd-v1.5.6-win64"; // Path to your zstd.exe bin	
	
	RulesString("&ZSTD Options", false) 
	BindPref("fiddlerscript.rules.ZSTDOption")
	RulesStringValue(0,"Decompress", "decompress")
	RulesStringValue(1,"Remove", "remove")
	RulesStringValue(2,"Do Nothing", "disable",true)
	public static var zstdOption: String = null;	
			
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
				
		
			
	static function OnBoot(){
		if(zstdOption=="decompress"){ //user can disable the decoding so we dont need to check
			checkZSTDBinPath();
		}
	}
    
    // Create a new item on the Tools menu (and the toolbar).
    public static ToolsAction("Set ZSTD Path")
	function changeZSTDPath(oSessions: Fiddler.Session[]){
		//var newPath = prompt("bob");
		//var result = MessageBox.Show("BBBB","User Prompt",MessageBoxButtons.YesNo,MessageBoxIcon.Question);
		//FiddlerObject.log("Changing ZSTD path from "+m_ZSTDBinPath+" to " +newPath)
		var form = new Form();
		form.Text = "Change ZSTD Path";
		form.Width = 300;
		form.Height = 150;

		var label = new Label();
		label.Text = "Enter the new ZSTD Path (the folder where zstd.exe lives):";
		label.AutoSize = false; 
		label.Top = 10;
		label.Left = 10;
		label.Width = 250;
		form.Controls.Add(label);

		var textBox = new TextBox();
		textBox.Text = m_ZSTDBinPath;
		textBox.Top = 40;
		textBox.Left = 10;
		textBox.Width = 260;
		form.Controls.Add(textBox);
		
		var buttonReset = new Button();
		buttonReset.Text = "Reset To Default";
		buttonReset.Top = 70;
		buttonReset.Left = 90;
		buttonReset.Width = 100;
		buttonReset.DialogResult = DialogResult.Ignore;
		form.Controls.Add(buttonReset);
		
		var buttonOK = new Button();
		buttonOK.Text = "Change";
		buttonOK.Top = 70;
		buttonOK.Left = 10;
		buttonOK.DialogResult = DialogResult.OK;
		form.Controls.Add(buttonOK);
		
		var buttonCancel = new Button();
		buttonCancel.Text = "Cancel";
		buttonCancel.Top = 70;
		buttonCancel.Left = 200;
		buttonCancel.DialogResult = DialogResult.Cancel;
		form.Controls.Add(buttonCancel);
		
		var result = form.ShowDialog();

		
		if (result == DialogResult.OK) { //Change clicked
			var userInput = textBox.Text;
				FiddlerObject.log("user entered new ZSTD path: "+userInput);
			// Modify the request based on the input
			if (String.IsNullOrEmpty(userInput)) {
				FiddlerObject.alert("You did not enter anything!");
				//MessageBox.Show("You did not enter anything!");	
			}
			if (!String.IsNullOrEmpty(userInput)){
				m_ZSTDBinPath = userInput;
			}
			}
		else if (result == DialogResult.Ignore){
			
			//textBox.Text = "C:\\Users\\user\\Downloads\\zstd-v1.5.6-win64"
			m_ZSTDBinPath = "C:\\Users\\user\\Downloads\\zstd-v1.5.6-win64"
		} else { 
			//use clicked Cancel or X or pressed ESC
			//FiddlerObject.log("CANCELED");
		}

    }
 

    public static RulesOption("Prevent WSS/H2/H2c/H3 Upgrades")
    BindPref("fiddlerscript.rules.removeUpgrades")
	var removeUpgrades: boolean = true;
	
	public static RulesOption("SocGholish Replacements")
	BindPref("fiddlerscript.rules.theSocReplacements")
	var theSocReplacements: boolean = true;
	//var theSocReplacements = new Boolean(true);


    public static RulesOption("Hide 304s")
    BindPref("fiddlerscript.rules.Hide304s")
    var m_Hide304s: boolean = false;

    // Cause Fiddler to override the Accept-Language header with one of the defined values
    public static RulesOption("Request &Japanese Content")
    var m_Japanese: boolean = false;

    // Automatic Authentication
    public static RulesOption("&Automatically Authenticate")
    BindPref("fiddlerscript.rules.AutoAuth")
    var m_AutoAuth: boolean = false;

    // Cause Fiddler to override the User-Agent header with one of the defined values
    RulesString("&User-Agents", true) 
    BindPref("fiddlerscript.ephemeral.UserAgentString")
    // ... [User-Agent definitions remain unchanged] ...
    public static var sUA: String = null;

    // Cause Fiddler to delay HTTP traffic to simulate typical 56k modem conditions
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

	static function StrToHex(input){
	
		var bytes: Byte[] = System.Text.Encoding.UTF8.GetBytes(input);
		return BitConverter.ToString(bytes).Replace("-","").ToLower();
		
	}
	static function isBinary(input){
		for (var i=0; i<input.Length-1; i++){
			//FiddlerObject.log("here"+input[i])
			var b=input[i]
			if(b<0x09 || (input > 0x0D && b < 0x20) || b > 0x7E){
				return true;
				}
			}
		return false;
	
			}
					
		static function OnBeforeRequest(oSession: Session) {
		
			if (theSocReplacements == true){
				//oSession.bBufferResponse = true;
				// Replace specific process names with 'svchost.exe'
				var names=["ApplicationFrameHost","vmtoolsd","BurpSuiteCommunity","chrome","cmd","EXCEL","explorer","Fiddler","firefox","FSE2","HxD","ida","javaw","MicrosoftEdgeCP","MicrosoftPdfReader","notepad++","OUTLOOK","powershell","powershell_ise","Procmon64","ProcessHacker","procexp64","sublime_text"]
				var changes=[]
				changes.push(oSession.utilReplaceInRequest("ApplicationFrameHost.exe", "svchost.exe"));	
				changes.push(oSession.utilReplaceInRequest("vmtoolsd.exe", "svchost.exe"));		
				changes.push(oSession.utilReplaceInRequest("BurpSuiteCommunity.exe", "svchost.exe"));
				changes.push(oSession.utilReplaceInRequest("chrome.exe", "svchost.exe"));
				changes.push(oSession.utilReplaceInRequest("cmd.exe", "svchost.exe"));
				changes.push(oSession.utilReplaceInRequest("EXCEL.exe", "svchost.exe"));
				changes.push(oSession.utilReplaceInRequest("explorer.exe", "svchost.exe"));
				changes.push(oSession.utilReplaceInRequest("Fiddler.exe", "svchost.exe"));
				changes.push(oSession.utilReplaceInRequest("firefox.exe", "svchost.exe"));
				changes.push(oSession.utilReplaceInRequest("FSE2.exe", "svchost.exe"));
				changes.push(oSession.utilReplaceInRequest("HxD.exe", "svchost.exe"));
				changes.push(oSession.utilReplaceInRequest("ida.exe", "svchost.exe"));
				changes.push(oSession.utilReplaceInRequest("javaw.exe", "svchost.exe"));
				changes.push(oSession.utilReplaceInRequest("MicrosoftEdgeCP.exe", "svchost.exe"));
				changes.push(oSession.utilReplaceInRequest("MicrosoftPdfReader.exe", "svchost.exe"));
				changes.push(oSession.utilReplaceInRequest("notepad++.exe", "svchost.exe"));
				changes.push(oSession.utilReplaceInRequest("OUTLOOK.exe", "svchost.exe"));
				changes.push(oSession.utilReplaceInRequest("powershell.exe", "svchost.exe"));
				changes.push(oSession.utilReplaceInRequest("powershell_ise.exe", "svchost.exe"));
				changes.push(oSession.utilReplaceInRequest("Procmon64.exe", "svchost.exe"));
				changes.push(oSession.utilReplaceInRequest("ProcessHacker.exe", "svchost.exe"));
				changes.push(oSession.utilReplaceInRequest("procexp64.exe", "svchost.exe"));
				changes.push(oSession.utilReplaceInRequest("sublime_text.exe", "svchost.exe"));
			
				for(i=0; i<changes.length; i++){
					if(changes[i]==true){
						FiddlerObject.log("Soc Process Replacement: "+names[i]+" for session: " + oSession.id)
					}
				}
				// MAC address pattern with escaped backslashes
				var macAddressPattern = "([0-9A-Fa-f]{2})([:-])([0-9A-Fa-f]{2})\\2([0-9A-Fa-f]{2})\\2([0-9A-Fa-f]{2})\\2([0-9A-Fa-f]{2})\\2([0-9A-Fa-f]{2})";

				// Replace MAC addresses in the request body
				if (oSession.requestBodyBytes != null && oSession.requestBodyBytes.Length > 0 && isBinary(oSession.requestBodyBytes)==false) {
					var sBody = oSession.GetRequestBodyAsString();  //DOESNOT WORK ON BINARY DATA!!! AHHHHHH!!!!!!!
					var sBodyOriginal = sBody; 
			
					var reg = new Regex(macAddressPattern, RegexOptions.IgnoreCase);
					sBody = reg.Replace(sBody, ReplaceMacAddress);
					oSession.utilSetRequestBody(sBody);
					
					//FiddlerObject.log("body encoding is"+oSession.GetRequestBodyEncoding())
					//FiddlerObject.log(isBinary(oSession.requestBodyBytes))
					//FiddlerObject.log("r="+StrToHex(oSession.requestBodyBytes))
					//FiddlerObject.log("o="+StrToHex(sBodyOriginal))
					//FiddlerObject.log("n="+StrToHex(sBody))
					if(sBody.localeCompare(sBodyOriginal)!=0){ //LOCALECOMPARE ONLY WORKS ON STRINGS!! AHHHHH!!
						//FiddlerObject.log("MAC address was changed "+sBodyOriginal+" > "+sBody )
						FiddlerObject.log("Soc Replacement: MAC address in body for session:" + oSession.id)
					}
				}

				// Replace MAC addresses in the request headers
				if (oSession.oRequest.headers != null) {
					var headers = oSession.oRequest.headers;
					var reg = new Regex(macAddressPattern, RegexOptions.IgnoreCase);
					for (var i:int = 0; i < headers.Count(); i++) {
						var headerItem = headers[i];
						var headerValue = headerItem.Value;
						var newHeaderValue = reg.Replace(headerValue, ReplaceMacAddress);
						if (headerValue != newHeaderValue) {
							headerItem.Value = newHeaderValue;
							FiddlerObject.log("Soc Replacement: MAC address in header: "+headerValue+" > "+newHeaderValue + " for session " + oSession.id)
						}
					}
				}
			}
			// Other existing rules...

			if ((null != gs_ReplaceToken) && (oSession.url.indexOf(gs_ReplaceToken) > -1)) {
				oSession.url = oSession.url.Replace(gs_ReplaceToken, gs_ReplaceTokenWith); 
			}
			if ((null != gs_OverridenHost) && (oSession.host.toLowerCase() == gs_OverridenHost)) {
				oSession["x-overridehost"] = gs_OverrideHostWith; 
			}

			if ((null != bpRequestURI) && oSession.uriContains(bpRequestURI)) {
				oSession["x-breakrequest"] = "uri";
			}

			if ((null != bpMethod) && (oSession.HTTPMethodIs(bpMethod))) {
				oSession["x-breakrequest"] = "method";
			}

			if ((null != uiBoldURI) && oSession.uriContains(uiBoldURI)) {
				oSession["ui-bold"] = "QuickExec";
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
				// current Fiddler user's credentials. You can change (default)
				// to a domain\\username:password string if preferred.
				//
				// WARNING: This setting poses a security risk if remote 
				// connections are permitted!
				oSession["X-AutoAuth"] = "(default)";
			}

			if (m_AlwaysFresh && (oSession.oRequest.headers.Exists("If-Modified-Since") || oSession.oRequest.headers.Exists("If-None-Match"))) {
				oSession.utilCreateResponseAndBypassServer();
				oSession.responseCode = 304;
				oSession["ui-backcolor"] = "Lavender";
			}
		}

		// Function to replace MAC addresses
		static function ReplaceMacAddress(match: Match): String {
			var sep = match.Groups[2].Value;
			return generateRandomMAC(sep);
		}

	// Function to generate a random MAC address with a specific separator
	static function generateRandomMAC(separator: String): String {
		var mac = '';
		var rand = new System.Random();
		for (var i: int = 0; i < 6; i++) {
			var hexPair = rand.Next(0, 256).ToString("X2");
			mac += hexPair + (i < 5 ? separator : '');
		}
		return mac;
	}

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

	static function OnPeekAtResponseHeaders(oSession: Session) {
        
			/*check if the server sent us a zstd compressed session even though we told it not to*/
		if(zstdOption=="remove" && oSession.oResponse.headers.ExistsAndContains("Content-Encoding","zstd")){
			FiddlerObject.log("Warning: Server sent zstd encoded session even though asked it not to for session:"+oSession.id)			
			}
		
			if(removeUpgrades==true)
			{
				//remove http3, http2, http2c, and quic response header
				if (oSession.ResponseHeaders.ExistsAndContains("alt-svc", "h3") || oSession.ResponseHeaders.ExistsAndContains("alt-svc", "h2") || oSession.ResponseHeaders.ExistsAndContains("alt-svc", "h2c") || oSession.ResponseHeaders.ExistsAndContains("alt-svc", "quic")){
					oSession.oResponse.headers.Remove("alt-svc");
					FiddlerObject.log("Removing alt-svc header response from session: "+oSession.id);	
				}
            
				//remove wss upgrade response header
				if (oSession.ResponseHeaders.ExistsAndContains("Upgrade", "websocket")) {
					//oSession.oResponse.headers.Remove("Upgrade");
					FiddlerObject.log("Removing wss upgrade response header for session: "+oSession.id);	
					//oSession.oRequest.FailSession(501, "Blocked", "Fiddler blocked websocket Upgrade response");
					oSession.oResponse.headers.Remove("Upgrade");
				}
            
				//remove h2 upgrade response header
				if (oSession.ResponseHeaders.ExistsAndContains("Upgrade", "h2")) {
					//oSession.oResponse.headers.Remove("Upgrade");
					FiddlerObject.log("Removing h2 upgrade response header for session: "+oSession.id);	
					//oSession.oRequest.FailSession(501, "Blocked", "Fiddler blocked h2 Upgrade response");
					oSession.oResponse.headers.Remove("Upgrade");
				}
            
				//remove h2c upgrade response header
				if (oSession.ResponseHeaders.ExistsAndContains("Upgrade", "h2c")) {
					//oSession.oResponse.headers.Remove("Upgrade");
					FiddlerObject.log("Removing h2c upgrade response header for session: "+oSession.id);	
					//oSession.oRequest.FailSession(501, "Blocked", "Fiddler blocked h2c Upgrade response");
					oSession.oResponse.headers.Remove("Upgrade");
				}
			}    
        
			if (m_DisableCaching) {
				oSession.oResponse.headers.Remove("Expires");
				oSession.oResponse["Cache-Control"] = "no-cache";
			}

			if ((bpStatus > 0) && (oSession.responseCode == bpStatus)) {
				oSession["x-breakresponse"] = "status";
				oSession.bBufferResponse = true;
			}
        
			if ((null != bpResponseURI) && oSession.uriContains(bpResponseURI)) {
				oSession["x-breakresponse"] = "uri";
				oSession.bBufferResponse = true;
			}
		}
    
		static function OnPeekAtRequestHeaders(oSession: Session) {
		
			if(oSession.oRequest.headers.ExistsAndContains("Accept-Encoding","zstd") && zstdOption=="remove")
			{ 
				//FiddlerObject.log("len of acept-encoding is:"+oSession.oRequest["Accept-Encoding"].Split(",").Length)
				if(oSession.oRequest["Accept-Encoding"].Split(",").Length==1){
					FiddlerObject.log("Removing Accept-Encoding header of ZSTD from session:"+oSession.id);
					oSession.oRequest.headers.Remove("Accept-Encoding");
				}
				else{				
					//FiddlerObject.log("Removing ZSTD Accept-Encoding header param (keeping others) from session:"+oSession.id)		
					var currEncodings = oSession.oRequest["Accept-Encoding"]
					var newEncodings = currEncodings.Replace("zstd,","").Replace(",zstd","").Replace("zstd","");
					oSession.oRequest["Accept-Encoding"] = newEncodings
					FiddlerObject.log("Changed Accept-Encoding from "+currEncodings+" to "+newEncodings+" for session:"+oSession.id)
					//oSession.oRequest.headers.Remove("Accept-Encoding")
					//oSession.oRequest.headers.Add("Accept-Encoding","gzip, deflate, br")	
				} 
			}
		
			//var sProc = ("" + oSession["x-ProcessInfo"]).ToLower();
			//if (!sProc.StartsWith("mylowercaseappname")) oSession["ui-hide"] = "NotMyApp";
		
		
			if(removeUpgrades==true)
			{
				//remove wss upgrade request
				if(oSession.oRequest.headers.ExistsAndContains("Upgrade","websocket")){
					oSession.oRequest.headers.Remove("Upgrade")
					FiddlerObject.log("Removed wss upgrade header from request session: "+oSession.id)		   
				}	
            
				//remove h2 upgrade request
				if(oSession.oRequest.headers.ExistsAndContains("Upgrade","h2")){
					oSession.oRequest.headers.Remove("Upgrade")
					FiddlerObject.log("Removed h2 upgrade header from request session: "+oSession.id)		   
				}	
            
				//remove h2c upgrade request
				if(oSession.oRequest.headers.ExistsAndContains("Upgrade","h2c")){
					oSession.oRequest.headers.Remove("Upgrade")
					FiddlerObject.log("Removed h2c upgrade header from request session: "+oSession.id)		   
				}	
			}
        
		}


	
		static function checkZSTDBinPath() {
			try {
				var zstdBin = System.IO.Path.Combine(m_ZSTDBinPath, "zstd.exe");
				if (System.IO.File.Exists(zstdBin)) {
					return true; // Path exists, return true
				} else {
					throw new Error("ZSTD binary not found at specified path: " + zstdBin);
				}
			} catch (err) {
				// Log the error
				FiddlerApplication.Log.LogString(err.message);
				if (FiddlerApplication.Prefs.GetBoolPref("fiddlerscript.rules.ShowAlerts", true)) {
					MessageBox.Show(err.message, "Error with ZSTD Path");
				}
				return false; // Path does not exist, return false
			}
		}	

		static function decodeZSTD(oSession: Session) {
			var tempDir = System.IO.Path.GetTempPath();
			var encodedFileName = System.IO.Path.GetRandomFileName();
			var decodedFileName = System.IO.Path.GetRandomFileName();

			var encodedFilePath = System.IO.Path.Combine(tempDir, encodedFileName);
			var decodedFilePath = System.IO.Path.Combine(tempDir, decodedFileName);
			try {
				oSession.utilDecodeResponse();
				oSession.SaveResponseBody(encodedFilePath);

				var psi = new System.Diagnostics.ProcessStartInfo();
				psi.FileName = System.IO.Path.Combine(m_ZSTDBinPath, "zstd.exe");
				psi.Arguments = "-d -f " + encodedFilePath + " -o " + decodedFilePath;
				psi.CreateNoWindow = true;
				psi.UseShellExecute = false;
				psi.RedirectStandardOutput = true;
				psi.RedirectStandardError = true;

				var process = System.Diagnostics.Process.Start(psi);
				var output = process.StandardOutput.ReadToEnd() + process.StandardError.ReadToEnd();

				if (!process.WaitForExit(10000)) {
					process.Kill();
					FiddlerApplication.Log.LogString("Zstd process timed out and was forcibly terminated.");
				} else if (process.ExitCode === 0) {
					var content = System.IO.File.ReadAllText(decodedFilePath);
					oSession.utilSetResponseBody(content);
					oSession.oResponse.headers.Remove("Content-Encoding");
					oSession.oResponse.headers["Content-Length"] = content.length.toString();
					FiddlerApplication.Log.LogString("Decoded ZSTD response for session: " + oSession.id);
				} else {
					FiddlerApplication.Log.LogString("Failed to decode ZSTD for session: " + oSession.id + ". Exit code: " + process.ExitCode + ". Output: " + output);
				}
			} catch (ex) {
				FiddlerApplication.Log.LogString("Error in ZSTD decoding: " + ex.Message);
				} finally {
			try {
				if (System.IO.File.Exists(encodedFilePath)) System.IO.File.Delete(encodedFilePath);
				if (System.IO.File.Exists(decodedFilePath)) System.IO.File.Delete(decodedFilePath);
			} catch (cleanupEx) {
				FiddlerApplication.Log.LogString("Failed to clean up temporary files: " + cleanupEx.Message);
			}
		}
			}
	static function OnBeforeResponse(oSession: Session) {
		if (m_Hide304s && oSession.responseCode == 304) {
			oSession["ui-hide"] = "true";
		}
		
		// === MCP: Real-time post if enabled ===
		if (m_McpLive) Handlers.McpTryPost(oSession);
		
		if (oSession.ResponseHeaders.ExistsAndContains("Content-Encoding", "zstd") && zstdOption=="decompress") {
			//FiddlerObject.log("GOING TO DECOMPRESS SESSION:"+oSession.id)
			if (!checkZSTDBinPath()) { 
				return; // Skip decoding attempt if path check fails               
			} 
			decodeZSTD(oSession);
		}
        
        
			if (oSession.oResponse != null && 
				oSession.oResponse.headers.Exists("Content-Type") &&
			oSession.oResponse["Content-Type"].ToLower().Contains("javascript")) {
				oSession["ui-backcolor"] = null;
			}

			// Decode the response body if compressed
			oSession.utilDecodeResponse();

			// Get the response body as a string
			var sResponseBody = oSession.GetResponseBodyAsString();



		}

  
		// The Main() function runs every time your FiddlerScript compiles
		static function Main() {
			var today: Date = new Date();
			FiddlerObject.StatusText = " CustomRules.js was loaded at: " + today;
			FiddlerObject.log("HOWDY "+today);	
			// Uncomment to add a "Server" column containing the response "Server" header, if present
			// UI.lvSessions.AddBoundColumn("Server", 50, "@response.server");

			// Uncomment to add a global hotkey (Win+G) that invokes the ExecAction method below...
			// UI.RegisterCustomHotkey(HotkeyModifiers.Windows, Keys.G, "screenshot"); 
		}

		// These static variables are used for simple breakpointing & other QuickExec rules 
		BindPref("fiddlerscript.ephemeral.bpRequestURI")
		public static var bpRequestURI: String = null;

		BindPref("fiddlerscript.ephemeral.bpResponseURI")
		public static var bpResponseURI: String = null;

		BindPref("fiddlerscript.ephemeral.bpMethod")
		public static var bpMethod: String = null;

		static var bpStatus: int = -1;
		static var uiBoldURI: String = null;
		static var gs_ReplaceToken: String = null;
		static var gs_ReplaceTokenWith: String = null;
		static var gs_OverridenHost: String = null;
		static var gs_OverrideHostWith: String = null;

		// The OnExecAction function is called by either the QuickExec box in the Fiddler window,
		// or by the ExecAction.exe command line utility.
		static function OnExecAction(sParams: String[]): Boolean {

			FiddlerObject.StatusText = "ExecAction: " + sParams[0];

			var sAction = sParams[0].toLowerCase();
			switch (sAction) {
				case "bold":
					if (sParams.Length < 2) { uiBoldURI = null; FiddlerObject.StatusText = "Bolding cleared"; return false; }
					uiBoldURI = sParams[1]; FiddlerObject.StatusText = "Bolding requests for " + uiBoldURI;
					return true;
				case "bp":
					FiddlerObject.alert("bpu = breakpoint request for uri\nbpm = breakpoint request method\nbps=breakpoint response status\nbpafter = breakpoint response for URI");
					return true;
				case "bps":
					if (sParams.Length < 2) { bpStatus = -1; FiddlerObject.StatusText = "Response Status breakpoint cleared"; return false; }
					bpStatus = parseInt(sParams[1]); FiddlerObject.StatusText = "Response status breakpoint for " + sParams[1];
					return true;
				case "bpv":
				case "bpm":
					if (sParams.Length < 2) { bpMethod = null; FiddlerObject.StatusText = "Request Method breakpoint cleared"; return false; }
					bpMethod = sParams[1].toUpperCase(); FiddlerObject.StatusText = "Request Method breakpoint for " + bpMethod;
					return true;
				case "bpu":
					if (sParams.Length < 2) { bpRequestURI = null; FiddlerObject.StatusText = "RequestURI breakpoint cleared"; return false; }
					bpRequestURI = sParams[1];
					FiddlerObject.StatusText = "RequestURI breakpoint for " + sParams[1];
					return true;
				case "bpa":
				case "bpafter":
					if (sParams.Length < 2) { bpResponseURI = null; FiddlerObject.StatusText = "ResponseURI breakpoint cleared"; return false; }
					bpResponseURI = sParams[1];
					FiddlerObject.StatusText = "ResponseURI breakpoint for " + sParams[1];
					return true;
				case "overridehost":
					if (sParams.Length < 3) { gs_OverridenHost = null; FiddlerObject.StatusText = "Host Override cleared"; return false; }
					gs_OverridenHost = sParams[1].toLowerCase();
					gs_OverrideHostWith = sParams[2];
					FiddlerObject.StatusText = "Connecting to [" + gs_OverrideHostWith + "] for requests to [" + gs_OverridenHost + "]";
					return true;
				case "urlreplace":
					if (sParams.Length < 3) { gs_ReplaceToken = null; FiddlerObject.StatusText = "URL Replacement cleared"; return false; }
					gs_ReplaceToken = sParams[1];
					gs_ReplaceTokenWith = sParams[2].Replace(" ", "%20");  // Simple helper
					FiddlerObject.StatusText = "Replacing [" + gs_ReplaceToken + "] in URIs with [" + gs_ReplaceTokenWith + "]";
					return true;
				case "allbut":
				case "keeponly":
					if (sParams.Length < 2) { FiddlerObject.StatusText = "Please specify Content-Type to retain during wipe."; return false; }
					UI.actSelectSessionsWithResponseHeaderValue("Content-Type", sParams[1]);
					UI.actRemoveUnselectedSessions();
					UI.lvSessions.SelectedItems.Clear();
					FiddlerObject.StatusText = "Removed all but Content-Type: " + sParams[1];
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
					Utilities.LaunchHyperlink("http://www.google.com/search?hl=en&btnI=I%27m+Feeling+Lucky&q=" + Utilities.UrlEncode(sParams[1]));
					return true;
				case "help":
					Utilities.LaunchHyperlink("http://fiddler2.com/r/?quickexec");
					return true;
				case "hide":
					UI.actMinimizeToTray();
					return true;
				case "log":
					FiddlerApplication.Log.LogString((sParams.Length < 2) ? "User couldn't think of anything to say..." : sParams[1]);
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
					if (sParams.Length < 2) { FiddlerObject.StatusText = "Please specify # of sessions to trim the session list to."; return false; }
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
					} else {
						FiddlerObject.StatusText = "Requested ExecAction: '" + sAction + "' not found. Type HELP to learn more.";
						return false;
					}
			}
		}
	}


