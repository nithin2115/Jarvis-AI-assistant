import sys

with open('router.py', 'r', encoding='utf-8') as f:
    content = f.read()

start_idx = content.find('def run_agent(')

new_func = """def run_agent(agent: str, user_query: str, **kwargs) -> str:
    \"\"\"
    Executes the selected agent with the user's query.
    Never passes router prompts to the model. Never asks the model to classify itself.
    \"\"\"
    import brain_manager
    import requirement_tracker
    import verifier_agent
    import time

    sys_prompt = AGENT_PROMPTS.get(agent, AGENT_PROMPTS[GENERAL_ASSISTANT_AGENT])

    on_chunk = kwargs.pop('on_chunk', None)
    context = kwargs.pop('context', "")
    
    # Optional helper to show status in UI
    def _emit_status(msg, is_active=True):
        try:
            from app import socketio
            socketio.emit("search_status", {"searching": is_active, "query": msg, "category": "Agent Pipeline"}, namespace="/")
        except Exception:
            pass

    # 1. Extract requirements before generation
    requirements = requirement_tracker.extract_requirements(user_query)
    
    max_attempts = 3
    final_response = ""
    current_sys_prompt = sys_prompt
    
    for attempt in range(max_attempts):
        logger.info(f"[ROUTER] Specialist Agent Draft Attempt {attempt + 1}/{max_attempts}")
        _emit_status(f"Drafting response (Attempt {attempt + 1})...")
        
        # Buffer the response, DO NOT stream to user yet
        draft_response, provider = brain_manager.ask(
            user_query,
            context,
            current_sys_prompt,
            **kwargs
        )
        
        # 2. Check requirements
        _emit_status("Verifying requirements...")
        missing = []
        if requirements:
            # Create a fresh copy of requirements for this draft
            current_reqs = {k: False for k in requirements.keys()}
            requirement_tracker.check_requirements_satisfied(draft_response, current_reqs)
            missing = requirement_tracker.get_missing_requirements(current_reqs)
            
        if missing:
            logger.warning(f"[REQUIREMENTS] Missing: {missing}. Rejecting draft.")
            current_sys_prompt += f"\\n\\nIMPORTANT FEEDBACK: You completely missed the following requirements: {', '.join(missing)}. You MUST include them in your response."
            if attempt < max_attempts - 1:
                continue
                
        # 3. Verifier Agent checks quality/completeness
        _emit_status("Running Verifier Agent...")
        verification = verifier_agent.verify(agent, user_query, draft_response)
        
        if verification["verified"] and not missing:
            final_response = draft_response
            break
        else:
            feedback = verification["feedback"]
            if missing:
                feedback = f"Missing requirements: {missing}. " + feedback
            current_sys_prompt += f"\\n\\nIMPORTANT VERIFIER FEEDBACK: {feedback}. Fix these issues."
            if attempt == max_attempts - 1:
                # Last attempt, we just use whatever we got
                final_response = draft_response
                break
                
    _emit_status("Done", False)

    # 4. Stream verified response to the user
    if on_chunk:
        chunk_size = 30
        for i in range(0, len(final_response), chunk_size):
            on_chunk(final_response[i:i+chunk_size])
            time.sleep(0.01)

    return final_response
"""

content = content[:start_idx] + new_func + '\n'

with open('router.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Updated router.py with verifier agent pipeline')
