import re

with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

start_idx = content.find('def ask_ai(text: str, mode: str = chat_modes.MODE_ASSISTANT,')
if start_idx == -1:
    print('Could not find start of ask_ai')
    exit(1)

# Find the end of ask_ai by looking for the next top-level def
end_idx = content.find('\ndef ', start_idx + 1)
if end_idx == -1:
    end_idx = len(content)

old_func = content[start_idx:end_idx]

new_func = """def ask_ai(text: str, mode: str = chat_modes.MODE_ASSISTANT,
           session_key: str = None, uid: str = None,
           deepthink: bool = False, attachments: list = None,
           on_chunk=None) -> str:
    \"\"\"Deterministically route and execute using router.py.\"\"\"
    import router
    import time
    
    t_start = time.time()
    session_key = session_key or _safe_session_key()
    attachments = attachments or []
    uid = uid or _safe_uid()

    def _emit_full(reply: str):
        if on_chunk and reply:
            try: on_chunk(reply)
            except Exception: pass

    has_attachments = bool(attachments)

    # 1. Deterministic Routing (Phase 7)
    agent = router.route_agent(text)
    
    # Inject attachment context (file extracts) if available
    images = []
    att_ctx = ""
    if has_attachments:
        att_ctx = file_processor.build_attachment_context(attachments)
        images = file_processor.collect_images(attachments)
        
    # Build user context
    context = memory.build_context(text, user_id=uid)
    if att_ctx:
        context = att_ctx + "\\n\\n" + context

    # 2. Agent Execution
    logger.info(f"[ROUTER] Passing query to {agent}")
    
    response = router.run_agent(
        agent=agent,
        user_query=text,
        context=context,
        deepthink=deepthink,
        images=images,
        on_chunk=on_chunk
    )
    
    # Save memory
    if response:
        memory.save_conversation(text, response, user_id=uid)
        
    logger.info(f"[ROUTER] Completed in {time.time()-t_start:.3f}s")
    return response"""

new_content = content[:start_idx] + new_func + content[end_idx:]

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(new_content)
print('Replaced ask_ai successfully!')
