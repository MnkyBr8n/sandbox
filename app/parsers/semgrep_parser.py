"""
Semgrep parser for security vulnerability and code quality detection.

Supports 14 languages, same as tree_sitter.
Outputs only authorized fields: code.security.*, code.quality.*
"""

from pathlib import Path
from typing import Dict, Any, Optional, List
import subprocess
import json
import time

from app.logging.logger import get_logger

logger = get_logger("parsers.semgrep")

# Semgrep timeout per file/shard
SEMGREP_TIMEOUT_SECONDS = 30

# Code context lines before/after findings
CONTEXT_LINES = 3

# Semgrep rulesets
DEFAULT_RULESETS = [
    "p/security-audit",
    "p/owasp-top-10",
    "auto"
]


def parse_code_semgrep(
    path: Optional[Path] = None,
    content: Optional[str] = None,
    language: Optional[str] = None
) -> Dict[str, Any]:
    """
    Parse code file using semgrep static analysis.
    
    Args:
        path: File path (if parsing from file)
        content: File content (if parsing from string, e.g., god parser shard)
        language: Language/extension (py, ts, js, etc.)
    
    Returns:
        Dict with field_id keys matching master_notebook.yaml
        
    Raises:
        Exception if parsing fails (caller handles fallback)
    """
    start_time = time.time()
    
    # Get file path for semgrep execution
    if path is None and content is None:
        raise ValueError("Either path or content must be provided")

    # Initialize temp_path before try block to avoid NameError in finally
    temp_path: Optional[Path] = None
    is_temp = False

    if content is not None:
        # For god parser shards: write to temp file
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix=f'.{language}', delete=False) as f:
            f.write(content)
            temp_path = Path(f.name)
        file_path = temp_path
        is_temp = True
    else:
        file_path = path

    try:
        # Execute semgrep CLI
        findings = _run_semgrep(file_path, language)
        
        # Extract code context for findings
        file_lines = _read_file_lines(file_path)
        findings_with_context = _add_code_context(findings, file_lines)
        
        # Map to field_ids
        result = _map_findings_to_fields(findings_with_context)
        
        duration_ms = (time.time() - start_time) * 1000
        
        logger.info("Semgrep scan complete", extra={
            "file": str(file_path),
            "language": language,
            "scan_duration_ms": duration_ms,
            "findings_total": len(findings),
            "vulnerabilities": len(result.get("code.security.vulnerabilities", [])),
            "quality_issues": len(result.get("code.quality.code_smells", []))
        })
        
        return result
        
    finally:
        # Clean up temp file
        if is_temp and temp_path is not None and temp_path.exists():
            temp_path.unlink()


def _run_semgrep(file_path: Path, language: Optional[str]) -> List[Dict[str, Any]]:
    """Execute semgrep CLI and parse JSON output."""
    cmd = [
        "semgrep",
        "--json",
        "--config", ",".join(DEFAULT_RULESETS),
        str(file_path)
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=SEMGREP_TIMEOUT_SECONDS
        )
        
        # Semgrep returns non-zero on findings, which is not an error
        if result.returncode not in (0, 1):
            logger.warning("Semgrep execution failed", extra={
                "file": str(file_path),
                "returncode": result.returncode,
                "stderr": result.stderr
            })
            return []
        
        # Parse JSON output
        output = json.loads(result.stdout)
        findings = output.get("results", [])
        
        logger.debug("Semgrep execution complete", extra={
            "file": str(file_path),
            "findings_count": len(findings)
        })
        
        return findings
        
    except subprocess.TimeoutExpired:
        logger.error("Semgrep timeout", extra={
            "file": str(file_path),
            "timeout_seconds": SEMGREP_TIMEOUT_SECONDS
        })
        return []
    except json.JSONDecodeError as e:
        logger.error("Semgrep JSON parse error", extra={
            "file": str(file_path),
            "error": str(e)
        })
        return []
    except Exception as e:
        logger.error("Semgrep execution error", extra={
            "file": str(file_path),
            "error": str(e)
        })
        return []


def _read_file_lines(file_path: Path) -> List[str]:
    """Read file into line array for context extraction."""
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.readlines()
    except Exception as e:
        logger.warning(f"Failed to read file for context: {e}")
        return []


def _add_code_context(
    findings: List[Dict[str, Any]],
    file_lines: List[str]
) -> List[Dict[str, Any]]:
    """Add code context (lines before/after) to each finding."""
    findings_with_context = []
    
    for finding in findings:
        # Get line number (1-indexed)
        start_line = finding.get("start", {}).get("line", 0)
        
        if start_line == 0 or not file_lines:
            # No line number or no file content
            finding["code_context"] = None
            findings_with_context.append(finding)
            continue
        
        # Extract context (convert to 0-indexed)
        line_idx = start_line - 1
        before_start = max(0, line_idx - CONTEXT_LINES)
        after_end = min(len(file_lines), line_idx + CONTEXT_LINES + 1)
        
        before_lines = [line.rstrip() for line in file_lines[before_start:line_idx]]
        match_line = file_lines[line_idx].rstrip() if line_idx < len(file_lines) else ""
        after_lines = [line.rstrip() for line in file_lines[line_idx + 1:after_end]]
        
        finding["code_context"] = {
            "before": before_lines,
            "match": match_line,
            "after": after_lines
        }
        
        findings_with_context.append(finding)
    
    return findings_with_context


def _map_findings_to_fields(findings: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Map semgrep findings to field_ids.
    
    Severity mapping:
    - ERROR/WARNING → vulnerabilities, with categorization
    - INFO → code_smells, todos, deprecated_usage
    """
    result = {
        "code.security.vulnerabilities": [],
        "code.security.hardcoded_secrets": [],
        "code.security.sql_injection_risks": [],
        "code.security.xss_risks": [],
        "code.quality.antipatterns": [],
        "code.quality.code_smells": [],
        "code.quality.todos": [],
        "code.quality.deprecated_usage": []
    }
    
    for finding in findings:
        severity = finding.get("extra", {}).get("severity", "INFO")
        rule_id = finding.get("check_id", "")
        message = finding.get("extra", {}).get("message", "")
        line = finding.get("start", {}).get("line", 0)
        code_context = finding.get("code_context")
        
        finding_data = {
            "rule_id": rule_id,
            "severity": severity,
            "line": line,
            "message": message,
            "code_context": code_context
        }
        
        # Categorize by severity and rule pattern
        if severity in ("ERROR", "WARNING"):
            # Security vulnerabilities
            if "secret" in rule_id.lower() or "password" in rule_id.lower() or "token" in rule_id.lower():
                result["code.security.hardcoded_secrets"].append(finding_data)
            elif "sql" in rule_id.lower() or "injection" in rule_id.lower():
                result["code.security.sql_injection_risks"].append(finding_data)
            elif "xss" in rule_id.lower() or "cross-site" in rule_id.lower():
                result["code.security.xss_risks"].append(finding_data)
            else:
                result["code.security.vulnerabilities"].append(finding_data)
        else:
            # Code quality issues (INFO)
            if "todo" in message.lower() or "fixme" in message.lower():
                # Extract TODO text
                result["code.quality.todos"].append(f"{message} (line {line})")
            elif "deprecated" in message.lower():
                result["code.quality.deprecated_usage"].append(finding_data)
            elif "anti" in message.lower() or "pattern" in message.lower():
                result["code.quality.antipatterns"].append(finding_data)
            else:
                result["code.quality.code_smells"].append(finding_data)
    
    return result


def validate_semgrep_installation() -> Dict[str, Any]:
    """
    Validate semgrep CLI installation on startup.
    
    Returns:
        Dict with validation status and version info
    """
    try:
        result = subprocess.run(
            ["semgrep", "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode != 0:
            logger.error("Semgrep CLI not installed or not in PATH")
            return {
                "installed": False,
                "version": None,
                "compatible": False
            }
        
        version_output = result.stdout.strip()
        
        # Parse version (format: "1.95.0")
        try:
            version_parts = version_output.split()[0].split('.')
            major = int(version_parts[0])
            minor = int(version_parts[1])
            
            # Check compatibility (>=1.50.0)
            compatible = major >= 1 and minor >= 50
            
            if not compatible:
                logger.warning(f"Semgrep version {version_output} may not be compatible (require >=1.50.0)")
            else:
                logger.info(f"Semgrep validated: {version_output}")
            
            return {
                "installed": True,
                "version": version_output,
                "compatible": compatible
            }
        except Exception as e:
            logger.warning(f"Could not parse semgrep version: {e}")
            return {
                "installed": True,
                "version": version_output,
                "compatible": None  # Unknown
            }
        
    except FileNotFoundError:
        logger.error("Semgrep CLI not found in PATH")
        return {
            "installed": False,
            "version": None,
            "compatible": False
        }
    except Exception as e:
        logger.error(f"Semgrep validation error: {e}")
        return {
            "installed": False,
            "version": None,
            "compatible": False,
            "error": str(e)
        }
