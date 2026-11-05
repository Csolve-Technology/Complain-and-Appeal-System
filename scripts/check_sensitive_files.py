"""Check tracked content without logging any matching secret values."""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
PATTERNS = {
    "private key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "GitHub token": re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,})\b"),
    "AWS access key": re.compile(rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
}

def main():
    names = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    findings = []
    for name in filter(None, names):
        path = Path(name)
        allowed_template = path.name in {".env.example", ".env.sample"}
        private = (path.name == ".env" or path.name.startswith(".env.")) and not allowed_template
        private = private or bool(re.search(r"\.(?:sqlite3?|db)(?:-(?:journal|wal|shm))?$", name, re.I))
        private = private or path.suffix.lower() in {".pem", ".key", ".p12", ".pfx"}
        private = private or any(part in {".docker-data", "backups", "secrets"} for part in path.parts)
        if private:
            findings.append((name, "private runtime file is tracked"))
            continue
        # Check index contents: this is exactly what the next commit contains.
        data = subprocess.check_output(["git", "show", ":" + name], cwd=ROOT)
        for label, pattern in PATTERNS.items():
            if pattern.search(data): findings.append((name, label))
        if allowed_template:
            for line in data.decode("utf-8", errors="replace").splitlines():
                match = re.match(r"\s*([A-Z_]*(?:SECRET|PASSWORD|PRIVATE_KEY|API_KEY|ACCESS_TOKEN))\s*=\s*(.*)", line)
                if not match: continue
                value = match[2].strip().strip("\"'")
                placeholder = not value or any(word in value.lower() for word in ["your-", "your_", "change", "replace", "example", "generate", "<"])
                if not placeholder: findings.append((name, "non-placeholder credential in environment template"))
    for name, label in findings: print(f"{name}: {label}")
    if findings:
        print("Sensitive-file check failed. Remove private files from tracking and replace credentials with placeholders.")
        return 1
    print("Tracked-file checks passed; no prohibited runtime files or recognized secret patterns found.")
    return 0

if __name__ == "__main__": sys.exit(main())
