# PocketAgent

A local-first AI agent that runs entirely on your Android phone via Termux.
No cloud, no data upload, no account. Just your phone, your scripts, and your
own AI brain.

## What it does

- Chat with your phone like a personal assistant
- Executes local scripts (backups, data processing, automation)
- Long-term memory across conversations
- Async task runner (long tasks don't block the UI)
- Human-in-the-loop approval (dangerous operations require confirmation)
- Scheduled tasks (run something every day at 9:00)
- Sandboxed code execution (LLM can write Python on the fly, safely)
- Internet tools: web search, fetch URL, download files, call APIs

## Requirements

- Android phone (Android 8+)
- Termux (install from F-Droid)
- A free Zhipu API Key (https://open.bigmodel.cn)

## Install

    pkg install python git -y
    git clone <this-repo>
    cd pocketagent
    pip install -r requirements.txt
    export ZHIPU_API_KEY="your-key-here"
    python pocketagent.py

Then open http://YOUR-PHONE-IP:5000 in any browser on your LAN.

## Use cases

- One-person company running their own automation
- Writers who want AI to process their manuscript locally
- Privacy-focused users who don't want cloud AI
- Anyone with a spare Android phone collecting dust

## Custom scripts

Drop your own scripts in `examples/` and tell the agent about them in the
system prompt. The agent will discover and run them on demand.

## License

MIT
