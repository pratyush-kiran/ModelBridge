"""A stand-in for the Codex and Claude Code CLIs that speaks the parts Model Bridge uses."""

import json
import sys

provider, arguments = sys.argv[1], sys.argv[2:]


def reply(value):
    print(json.dumps(value), flush=True)


if arguments[:1] == ["app-server"]:
    results = {
        "initialize": {},
        "account/read": {"account": {"type": "chatgpt", "planType": "plus"}},
        "model/list": {"data": [{"model": "gpt-test", "displayName": "GPT Test"}]},
    }
    for line in sys.stdin:
        message = json.loads(line)
        if "id" in message:
            reply({"id": message["id"], "result": results[message["method"]]})
elif arguments[:2] == ["auth", "status"]:
    reply({"loggedIn": True, "authMethod": "claude.ai", "subscriptionType": "pro"})
elif "stream-json" in arguments:
    for line in sys.stdin:
        message = json.loads(line)
        reply({"type": "control_response", "response": {
            "request_id": message["request_id"], "subtype": "success",
            "response": {"models": [{"value": "opus", "displayName": "Opus"}]}}})
else:
    answer = f"{provider} heard: {sys.stdin.read()}"
    if provider == "codex":
        with open(arguments[arguments.index("--output-last-message") + 1], "w", encoding="utf-8") as output:
            output.write(answer)
    else:
        print(answer)
