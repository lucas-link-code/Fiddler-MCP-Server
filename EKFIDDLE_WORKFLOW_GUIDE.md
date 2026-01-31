EKFiddle-Focused Analysis Workflow Guide

Date: October 26, 2025
Version: 1.0
Status: Production Ready

# OVERVIEW

This guide explains how to use the enhanced Gemini-powered Fiddler client with EKFiddle threat intelligence integration. EKFiddle comments are now treated as authoritative threat intelligence that guides and validates the security analysis framework.

# WHAT IS EKFIDDLE?

EKFiddle is a Fiddler extension that:
- Analyzes HTTP traffic against threat intelligence databases
- Identifies exploit kits, malware campaigns, and phishing attempts
- Writes findings to Fiddler's Comments column
- Provides structured threat assessments with severity levels

EKFiddle comments are AUTHORITATIVE - when EKFiddle flags something, it's based on known threat intelligence.

# HOW IT WORKS

## Data Flow

1. Fiddler captures traffic
2. EKFiddle extension analyzes sessions and adds comments
3. CustomRules.js extracts EKFiddle comments and sends to enhanced-bridge
4. enhanced-bridge stores sessions with ekfiddle_comment field
5. 5ire-bridge exposes sessions to Gemini client with ekfiddle_comment included
6. Gemini analyzes sessions, prioritizing EKFiddle intelligence

## Trust Hierarchy

The system now uses this trust hierarchy for threat assessment:

1. HIGHEST: EKFiddle Comments (authoritative threat intelligence)
2. HIGH: Behavioral Analysis (malicious pattern checklist)
3. MEDIUM: Heuristics (file extensions, keywords)
4. LOWEST: String Content (easily manipulated)

# USAGE WORKFLOWS

## Workflow 1: List EKFiddle-Flagged Sessions

**User Query:**
```
list sessions flagged with EKFiddle comments
```
OR
```
show me EKFiddle alerts
```

**What Gemini Does:**

1. Calls `fiddler_mcp__live_sessions` with `suspicious_only: true`
2. Filters for sessions with ekfiddle_comment field
3. Creates a CLEAN, FOCUSED LIST:

```
EKFIDDLE-FLAGGED SESSIONS:

Session 142 | cdn.malicious-ads.com | High: JavaScript obfuscation with eval()
Session 158 | tracking.adnetwork.io | Medium: Suspicious redirect chain detected
Session 201 | evil.example.org      | Critical: Known malware distribution site

FLAGGED DOMAINS TO INVESTIGATE:
1. evil.example.org (1 session, Critical severity)
2. cdn.malicious-ads.com (1 session, High severity)
3. tracking.adnetwork.io (1 session, Medium severity)

These EKFiddle-flagged sessions should be the PRIMARY focus of code investigation.
To analyze the code, use: fiddler_mcp__session_body with the session ID.
```

**Key Features:**
- Sessions sorted by severity (Critical > High > Medium > Low)
- Domain/subdomain extraction
- Clear, table-like format
- Summary of unique flagged domains
- Guidance for next steps

## Workflow 2: Investigate Flagged Session

**User Query (Follow-up):**
```
are there any malicious sessions?
```
OR
```
show me suspicious traffic
```

**What Gemini Does:**

1. Automatically identifies HIGHEST SEVERITY session from previous EKFiddle list
2. Calls `fiddler_mcp__session_body` for that session
3. Applies SECURITY ANALYSIS FRAMEWORK
4. CORRELATES analysis with EKFiddle comment

**Example Output:**

```
ANALYZING SESSION 201 (Critical: Known malware distribution site)

EKFIDDLE ASSESSMENT: Critical - Known malware distribution site
CONFIRMING WITH BEHAVIORAL ANALYSIS...

MALICIOUS PATTERN CHECKLIST:
[X] Iframe/Script Injection: FOUND
    - Creates hidden iframe element
    - Sets src to external malware domain
    
[X] Dynamic Code Execution: FOUND
    - Uses eval() to execute obfuscated payload
    - Function constructor detected
    
[X] Anti-Analysis: FOUND
    - document.referrer check (only runs from specific sites)
    - localStorage counter limits analysis attempts
    
[ ] Redirection: NOT FOUND

[ ] Overlay/UI Hijacking: NOT FOUND

BEHAVIORAL ANALYSIS:
Primary Action: Inject iframe to load external malware
Trigger Condition: Referrer must match legitimate news site
Anti-Analysis: View counter prevents repeated execution

EKFIDDLE CORRELATION:
✓ EKFiddle identified as "Known malware distribution site"
✓ Behavioral analysis CONFIRMS malware distribution
✓ Site matches known threat intelligence signatures

CONCLUSION:
This is CONFIRMED MALWARE. The EKFiddle assessment is validated by behavioral
analysis showing iframe injection, eval() usage, and anti-analysis techniques.
The code is designed to load external malware only when accessed from specific
referrer sites, a common malware delivery pattern.

RISK LEVEL: CRITICAL
RECOMMENDATION: Block domain immediately, investigate infection source
```

**Key Features:**
- EKFiddle assessment stated upfront
- Behavioral analysis confirms or challenges assessment
- Explicit correlation between EKFiddle and behavioral findings
- Clear risk level and recommendations

## Workflow 3: Domain-Focused Investigation

**User Query:**
```
analyze all sessions from cdn.malicious-ads.com
```

**What Gemini Does:**

1. Calls `fiddler_mcp__sessions_search` with host_pattern
2. Identifies all sessions from that domain
3. Notes which have EKFiddle comments
4. Analyzes the most suspicious ones
5. Provides domain-level threat assessment

## Workflow 4: Severity-Based Triage

**User Query:**
```
show me critical and high severity threats
```

**What Gemini Does:**

1. Lists all EKFiddle-flagged sessions
2. Filters for Critical/High severity only
3. Provides prioritized investigation list
4. Recommends starting with Critical severity

# EKFIDDLE COMMENT INTERPRETATION

## Common Patterns

The system automatically interprets these EKFiddle patterns:

| EKFiddle Comment | What to Look For | Security Framework Action |
|------------------|------------------|---------------------------|
| "JavaScript obfuscation" | String arrays, hex encoding, packed code | Check obfuscation techniques |
| "eval()" or "Function constructor" | Dynamic code execution | Verify eval() usage |
| "redirect" | window.location manipulation | Check for redirects |
| "suspicious domain" | Domain reputation, TLD | Investigate domain |
| "known malware" | High priority threat | Full behavioral analysis |
| "exploit kit" | CVE references, advanced techniques | Deep dive analysis |
| "phishing" | Form manipulation, credential theft | Check for input hijacking |

## Severity Extraction

The system extracts severity from EKFiddle comments:

- **Critical:** Immediate threat, confirmed malware
- **High:** Strong indicators of malicious activity
- **Medium:** Suspicious patterns, needs investigation
- **Low:** Potentially unwanted behavior

# EXAMPLE QUERIES

## Listing and Filtering

```
list all ekfiddle alerts
show sessions with ekfiddle comments
list suspicious sessions flagged by ekfiddle
show me high severity threats
list critical sessions from last hour
```

## Investigation

```
analyze session 142
investigate the critical session
what does session 201 do?
explain the malware in session 158
analyze all high severity sessions
```

## Domain Analysis

```
what domains were flagged by ekfiddle?
analyze all sessions from evil.example.org
show me all traffic to suspicious domains
investigate cdn.malicious-ads.com
```

## Validation

```
does the behavioral analysis confirm ekfiddle?
is session 142 really malicious?
validate the ekfiddle assessment for session 201
```

# BENEFITS OF EKFIDDLE INTEGRATION

## 1. Authoritative Threat Intelligence

- EKFiddle uses known threat databases
- Reduces false positives
- Provides confirmed threat identification
- Industry-standard threat intelligence

## 2. Guided Analysis

- EKFiddle comment guides what to look for
- More efficient investigations
- Focused pattern matching
- Reduced analysis time

## 3. Validation

- Behavioral analysis confirms EKFiddle
- Two-layer verification (intelligence + behavior)
- Higher confidence in findings
- Explainable results

## 4. Prioritization

- Severity levels guide investigation order
- Critical threats addressed first
- Efficient resource allocation
- Clear action priorities

## 5. Domain Intelligence

- Quick identification of malicious domains
- Subdomain extraction
- Domain-level threat assessment
- Infrastructure mapping

# TECHNICAL IMPLEMENTATION

## Session Data Structure

Sessions now include `ekfiddle_comment` field:

```json
{
  "id": "142",
  "host": "cdn.malicious-ads.com",
  "url": "https://cdn.malicious-ads.com/script.js",
  "content_type": "application/javascript",
  "risk_level": "HIGH",
  "ekfiddle_comment": "High: JavaScript obfuscation with eval()"
}
```

## Gemini Prompt Enhancements

### Initial Prompt (Lines 635-706)

Added EKFiddle-specific instructions:
- How to list flagged sessions
- Clean formatting requirements
- Severity prioritization
- Domain extraction
- Follow-up investigation workflow

### Analysis Prompt (Lines 975-991)

Added EKFiddle correlation:
- Check ekfiddle_comment first
- Treat as authoritative intelligence
- Correlate with behavioral analysis
- Compare assessments

### Follow-up Prompt (Lines 1048-1072)

Added EKFiddle validation:
- Note EKFiddle assessment
- Run patterns mentioned by EKFiddle
- Confirm or challenge assessment
- Provide holistic synthesis

## Data Flow Changes

### 5ire-bridge.py (Lines 195-221)

```python
# Extract EKFiddle comments from multiple possible fields
ekfiddle_comment = (session.get("ekfiddleComments") or 
                   session.get("sessionFlags") or 
                   session.get("ekfiddleFlags") or "").strip()

# Include in normalized session data
"ekfiddle_comment": ekfiddle_comment if ekfiddle_comment else None
```

# BEST PRACTICES

## For Security Analysts

1. **Always Start with EKFiddle List**
   - Query: "list sessions flagged with ekfiddle comments"
   - Review the clean list first
   - Identify high-priority targets

2. **Investigate by Severity**
   - Start with Critical
   - Then High
   - Medium if time permits
   - Low for completeness

3. **Validate with Behavioral Analysis**
   - Don't trust EKFiddle alone (though it's highly reliable)
   - Confirm with security framework
   - Look for patterns EKFiddle mentioned

4. **Document Findings**
   - Save session IDs
   - Note domain clusters
   - Track threat families

## For Investigators

1. **Use Specific Queries**
   - "analyze session X" (not "explain X")
   - "investigate critical threats"
   - "validate ekfiddle assessment"

2. **Follow the Workflow**
   - List → Prioritize → Investigate → Validate → Report

3. **Check Correlations**
   - Does behavioral match EKFiddle?
   - Are there domain patterns?
   - Multiple sessions from same source?

4. **Trust the Hierarchy**
   - EKFiddle = authoritative
   - Behavioral = validation
   - Heuristics = supporting
   - Strings = context only

# TROUBLESHOOTING

## "No EKFiddle comments found"

**Possible Causes:**
1. EKFiddle extension not installed in Fiddler
2. EKFiddle not analyzing traffic (check Fiddler settings)
3. No malicious traffic captured
4. Comments column property not being captured

**Solution:**
- Verify EKFiddle extension is active
- Check Fiddler Comments column manually
- Review CustomRules.js comment extraction

## "EKFiddle says malicious but behavioral analysis doesn't confirm"

**Possible Causes:**
1. Partial code in session (incomplete capture)
2. Sophisticated obfuscation hiding patterns
3. EKFiddle detecting domain/URL pattern, not code
4. Code requires specific execution context

**Solution:**
- Note the discrepancy
- Trust EKFiddle (it's threat intelligence-based)
- Look for domain-level indicators
- Check if code is context-dependent

## "Behavioral analysis finds threats EKFiddle didn't flag"

**Possible Causes:**
1. New/unknown threat pattern
2. EKFiddle rules not updated for this threat
3. Legitimate false positive in behavioral analysis

**Solution:**
- Perform deeper investigation
- Check if it's a known benign pattern
- Consider submitting to EKFiddle project if confirmed malicious

# SUMMARY

The EKFiddle integration provides:

✓ Authoritative threat intelligence
✓ Clean, focused session lists
✓ Severity-based prioritization
✓ Domain-level analysis
✓ Automated investigation workflow
✓ Two-layer validation (intelligence + behavior)
✓ Efficient triage and response

**Quick Start:**
1. Ask: "list sessions flagged with ekfiddle comments"
2. Review the clean list of flagged domains
3. Ask: "are there any malicious sessions?"
4. System auto-investigates highest severity session
5. Review behavioral analysis and EKFiddle correlation

**Key Takeaway:**
EKFiddle comments are now the PRIMARY driver for investigations. The security
analysis framework VALIDATES and CONFIRMS the EKFiddle assessment with behavioral
evidence, providing comprehensive, two-layer threat verification.

# FILES MODIFIED

Code Changes:
- 5ire-bridge.py (Lines 195-221, 313-339): Added ekfiddle_comment to sessions
- gemini-fiddler-client.py (Lines 635-706): EKFiddle workflow instructions
- gemini-fiddler-client.py (Lines 975-991): EKFiddle-aware analysis prompt
- gemini-fiddler-client.py (Lines 1048-1072): EKFiddle-aware follow-up prompt

Documentation:
- EKFIDDLE_WORKFLOW_GUIDE.md (this file): Complete workflow documentation

# VERSION HISTORY

- v1.0 (Oct 26, 2025): Initial EKFiddle integration with workflow guidance

For questions or issues, refer to:
- SECURITY_ANALYSIS_FRAMEWORK.md - Overall security framework
- SECURITY_ANALYSIS_QUICK_REFERENCE.txt - General usage guide
- This document - EKFiddle-specific workflows

