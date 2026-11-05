import os
import re

with open('router.py', 'r', encoding='utf-8') as f:
    content = f.read()

new_dict = '''import os
AGENT_PROMPTS = {
    GENERAL_ASSISTANT_AGENT: "You are a helpful, concise AI assistant. Answer general questions directly and conversationally."
}

def _load_agent_prompts():
    agent_files = {
        DSA_AGENT: "DSA_AGENT.md",
        SQL_AGENT: "SQL_AGENT.md",
        SYSTEM_DESIGN_AGENT: "SYSTEM_DESIGN_AGENT.md",
        PROJECT_BUILDER_AGENT: "FULLSTACK_AGENT.md",
        DEBUG_AGENT: "DEBUG_AGENT.md",
        CODE_REVIEW_AGENT: "CODE_REVIEW_AGENT.md",
        FULLSTACK_AGENT: "FULLSTACK_AGENT.md"
    }
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    for agent, filename in agent_files.items():
        filepath = os.path.join(base_dir, filename)
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                AGENT_PROMPTS[agent] = f.read()
        else:
            logger.warning(f"Agent prompt file missing: {filepath}")

_load_agent_prompts()
'''

content = re.sub(r'AGENT_PROMPTS = \{.*?GENERAL_ASSISTANT_AGENT:.*?\}', new_dict, content, flags=re.DOTALL)

with open('router.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Updated router.py to use Markdown files')
