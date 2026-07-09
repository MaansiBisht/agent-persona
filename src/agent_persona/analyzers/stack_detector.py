from __future__ import annotations

LANGUAGE_SIGNALS: dict[str, set[str]] = {
    "python": {".py", "pip", "uv ", "poetry", "pytest", "python3", "python "},
    "typescript": {".ts", ".tsx", "tsc ", "ts-node"},
    "javascript": {".js", ".mjs", "node ", "nodemon"},
    "go": {".go", "go build", "go test", "go run"},
    "rust": {".rs", "cargo build", "cargo test"},
    "java": {".java", "mvn ", "gradle "},
    "ruby": {".rb", "bundle exec", "rails "},
    "bash": {".sh", "#!/bin/bash", "#!/bin/zsh"},
}

FRAMEWORK_SIGNALS: dict[str, set[str]] = {
    "react": {"useState", "useEffect", ".jsx", ".tsx", "import React", "react-dom"},
    "fastapi": {"fastapi", "from fastapi", "uvicorn"},
    "django": {"django", "manage.py", "django.db"},
    "express": {"express()", "app.get(", "app.post("},
    "nextjs": {"next/router", "getServerSideProps", "next.config"},
    "vue": {".vue", "createApp(", "defineComponent"},
}

TOOL_SIGNALS: dict[str, set[str]] = {
    "docker": {"dockerfile", "docker-compose", "docker build", "docker run"},
    "git": {"git commit", "git push", "git pull", "git merge"},
    "npm": {"npm install", "npm run", "npm ci"},
    "yarn": {"yarn add", "yarn install", "yarn run"},
    "pnpm": {"pnpm add", "pnpm install"},
    "mysql": {".sql", "mysql ", "create table", "select * from"},
    "mongo": {"mongodb", "mongoose", "db.collection"},
    "postgres": {"psql ", "pg_dump", "postgresql"},
    "redis": {"redis-cli", "redis.Redis("},
    "aws": {"aws s3", "aws ec2", "boto3", "aws lambda"},
}


def detect_stack(
    tool_signals: list[str],
    commands: list[str],
    extensions: dict[str, int],
) -> dict[str, dict[str, int]]:
    all_text = tool_signals + commands
    ext_text = [f".{ext}" for ext, count in extensions.items() for _ in range(count)]
    combined = all_text + ext_text

    languages = _score_category(LANGUAGE_SIGNALS, combined)
    frameworks = _score_category(FRAMEWORK_SIGNALS, combined)
    tools = _score_category(TOOL_SIGNALS, combined)

    return {"languages": languages, "frameworks": frameworks, "tools": tools}


def _score_category(
    signal_map: dict[str, set[str]],
    corpus: list[str],
) -> dict[str, int]:
    scores: dict[str, int] = {}
    corpus_lower = [item.lower() for item in corpus]

    for name, signals in signal_map.items():
        total = 0
        for signal in signals:
            sig_lower = signal.lower()
            matches = sum(1 for item in corpus_lower if sig_lower in item)
            total += min(matches, 5)
        if total > 0:
            scores[name] = total

    return scores
