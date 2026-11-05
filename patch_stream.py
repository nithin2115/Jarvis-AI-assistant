import re

with open('templates/index.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Locate the target block
start_str = "socket.on('response_start', d=>{"
end_str = "if(_chatMsgs.scrollHeight - _chatMsgs.scrollTop - _chatMsgs.clientHeight < 200){"

start_idx = content.find(start_str)
if start_idx == -1:
    print("Could not find start_str")
    exit(1)

# Find the end of _finalizeStreamingBubble
match = re.search(r'if\(_chatMsgs\.scrollHeight - _chatMsgs\.scrollTop - _chatMsgs\.clientHeight < 200\)\{', content[start_idx:])
if not match:
    print("Could not find end_str")
    exit(1)
end_idx = start_idx + match.start()

new_block = """window._continuationEntry = null;

socket.on('response_start', d=>{
  if(!d || !d.id) return;
  clearTimeout(_cmdWatchdog);
  const mode = d.mode || window._chatMode;
  console.log(`[STREAM_START] - ID: ${d.id}`);

  if (window._continuationEntry) {
    console.log(`[STREAM_START] Resuming truncated bubble - ID: ${d.id}`);
    const entry = window._continuationEntry;
    window._streamBubbles[d.id] = entry; // Map new ID to old entry
    window._activeStreamId = d.id;
    window._currentActiveEntry = entry;
    entry.status = RESPONSE_STATUS.STREAMING;
    entry.completed = false;
    if(entry.doneTimer) { clearTimeout(entry.doneTimer); entry.doneTimer = null; }
    if(entry.inactivityTimer) { clearTimeout(entry.inactivityTimer); entry.inactivityTimer = null; }
    window._continuationEntry = null;
    return;
  }

  // Open an empty Jarvis bubble in streaming state.
  const bubble = window._addChat('', 'jarvis', mode, true, {streaming: true, deepthink: !!d.deepthink, id: d.id});
  const entry = window._streamBubbles[d.id] = { id: d.id, el: bubble, mode, buffer: '', deepthink: !!d.deepthink, lastRender: 0, raf: 0, firstChunkSeen: false, status: RESPONSE_STATUS.STREAMING, openCodeBlock:false, fenceParity:0, completed:false, doneTimer: null, inactivityTimer: null, long:false };
  window._activeStreamId = d.id;
  window._currentActiveEntry = entry;
  _showStopBtn(true);
  _updateDebugPanel(entry);
});

socket.on('response_chunk', d=>{
  if(!d || !d.id || !d.delta) return;
  console.log(`[STREAM_CHUNK] length: ${d.delta.length}`);
  let entry = window._streamBubbles[d.id];
  if(!entry){
    const mode = d.mode || window._chatMode;
    const bubble = window._addChat('', 'jarvis', mode, true, {streaming: true, deepthink: !!d.deepthink, id: d.id});
    entry = window._streamBubbles[d.id] = { id: d.id, el: bubble, mode: mode, buffer: '', deepthink: !!d.deepthink, lastRender: 0, raf: 0, firstChunkSeen: false, status: RESPONSE_STATUS.STREAMING, openCodeBlock:false, fenceParity:0, completed:false, doneTimer: null, inactivityTimer:null, long:false };
    window._activeStreamId = d.id;
    _showStopBtn(true);
    console.log(`[STREAM_START] (lazy) - ID: ${d.id}, Mode: ${mode}`);
  }
  window._currentActiveEntry = entry;
  entry.buffer += d.delta;
  
  window._responseBuffers[d.id] = window._responseBuffers[d.id] || { buffer:'', mode: entry.mode, deepthink: entry.deepthink };
  window._responseBuffers[d.id].buffer = entry.buffer;
  
  const fencesInDelta = (d.delta.match(/```/g) || []).length;
  entry.fenceParity = (entry.fenceParity + fencesInDelta) % 2;
  entry.openCodeBlock = entry.fenceParity === 1;
  
  // Removed buffer slice to prevent any chunk loss/overwrite
  entry.status = RESPONSE_STATUS.STREAMING;
  entry.long = entry.buffer.length >= _LONG_RESPONSE_THRESHOLD;
  _updateDebugPanel(entry);
  
  if(entry.doneTimer){ clearTimeout(entry.doneTimer); }
  entry.doneTimer = setTimeout(()=>{
    if(entry.completed) return;
    entry.completed = true;
    _finalizeStreamingBubble(entry, entry.buffer || '');
    delete window._streamBubbles[d.id];
    delete window._responseBuffers[d.id];
  }, _STREAM_DONE_GRACE_MS);
  
  if(entry.inactivityTimer){ clearTimeout(entry.inactivityTimer); }
  // WATCHDOG: 5000ms
  entry.inactivityTimer = setTimeout(()=>{
    if(entry.completed) return;
    console.warn(`[WATCHDOG] Inactivity >5s. Forcing final render - ID: ${d.id}`);
    entry.completed = true;
    _finalizeStreamingBubble(entry, entry.buffer || '');
    delete window._streamBubbles[d.id];
    delete window._responseBuffers[d.id];
  }, 5000);
  
  if(!entry.raf){
    entry.raf = requestAnimationFrame(()=>{
      entry.raf = 0;
      _renderStreamingBuffer(entry);
    });
  }
});

socket.on('response_done', d=>{
  if(!d || !d.id) return;
  console.log(`[STREAM_END] ID: ${d.id}`);
  clearTimeout(_cmdWatchdog);
  _isResponding = false;
  if(d.text) _lastAiResponse = (d.text || '').substring(0, 500);
  if(window._activeStreamId === d.id){
    window._activeStreamId = null;
    _showStopBtn(false);
  }
  const entry = window._streamBubbles[d.id];
  if(!entry){
    if(d.text){
      const mode = d.mode || window._chatMode;
      const stabilized = _stabilizeResponseText(d.text || '');
      console.log(`[RENDER_START] Fallback standard add`);
      const prepared = _prepareResponse(mode, stabilized || '');
      if(prepared.status === RESPONSE_STATUS.READY){
        window._addChat('', 'jarvis', mode, false, {deepthink: !!d.deepthink, preparedNode: prepared.node, serialized: prepared.serialized});
      }
      console.log(`[RENDER_END] Fallback standard add`);
    }
    return;
  }
  if(entry.completed){
    delete window._streamBubbles[d.id];
    delete window._responseBuffers[d.id];
    return;
  }
  window._currentActiveEntry = entry;
  if(entry.raf){ cancelAnimationFrame(entry.raf); entry.raf = 0; }
  if(entry.doneTimer){ clearTimeout(entry.doneTimer); entry.doneTimer = null; }
  if(entry.inactivityTimer){ clearTimeout(entry.inactivityTimer); entry.inactivityTimer = null; }
  entry.completed = true;
  _updateDebugPanel(entry);
  _finalizeStreamingBubble(entry, d.text || entry.buffer || '');
  delete window._streamBubbles[d.id];
  delete window._responseBuffers[d.id];
});

function _renderStreamingBuffer(entry){
  if(!entry || !entry.el) return;
  const body = entry.el.querySelector('.msg-body');
  if(!body) return;
  if(!entry._cursorEl){
    body.innerHTML = '';
    entry._cursorEl   = document.createElement('span');
    entry._cursorEl.className = 'thinking-dots';
    entry._cursorEl.innerHTML = '<span></span><span></span><span></span>';
    body.appendChild(entry._cursorEl);
  }
}

function _checkResponseIntegrity(text) {
  let isComplete = true;
  const fences = (text.match(/```/g) || []).length;
  console.log(`[INTEGRITY] Code fences count: ${fences}`);
  if (fences % 2 !== 0) {
     isComplete = false;
     console.log(`[INTEGRITY] Unbalanced code fences detected.`);
  }

  const sections = (text.match(/^## /gm) || []).length;
  console.log(`[INTEGRITY] Markdown sections count: ${sections}`);

  const diffs = _braceDiff(text);
  for(const d of diffs) {
    if(d.diff > 0) {
      console.log(`[INTEGRITY] Unbalanced blocks for ${d.pair.o}: diff=${d.diff}`);
      isComplete = false;
    }
  }
  return isComplete;
}

function _finalizeStreamingBubble(entry, finalText){
  const el = entry.el;
  if(!el) return;
  el.classList.remove('streaming');
  if(entry.doneTimer){ clearTimeout(entry.doneTimer); entry.doneTimer = null; }
  if(entry.inactivityTimer){ clearTimeout(entry.inactivityTimer); entry.inactivityTimer = null; }

  const mode = entry.mode || window._chatMode;
  
  // Integrity check and automatic retry
  const isComplete = _checkResponseIntegrity(finalText);
  if (!isComplete && !entry._isRetrying) {
    console.warn(`[RETRY] Response ends unexpectedly. Regenerating missing portion...`);
    entry._isRetrying = true;
    window._continuationEntry = entry;
    const cleanText = finalText.replace('_— stopped by user —_', '').trim();
    entry.buffer = cleanText;
    
    socket.emit('command', {
      text: "Continue exactly from where you left off. Do not repeat previous parts. Only output the rest of the code/text.",
      mode: mode,
      deepthink: entry.deepthink,
      stream: true
    });
    return;
  }

  const body = el.querySelector('.msg-body');
  if(body){
    body.innerHTML = '';
    
    console.log(`[VALIDATION_START]`);
    entry.status = RESPONSE_STATUS.VALIDATING;
    _updateDebugPanel(entry);

    let prepared;
    try {
      const stabilized = _stabilizeResponseText(finalText || '');
      console.log(`[VALIDATION_END]`);
      console.log(`[RENDER_START]`);
      prepared = _prepareResponse(mode, stabilized || '');
    } catch (err) {
      console.log(`[VALIDATION_END]`);
      console.error(`[STATE] ERROR - Validator crashed:`, err);
      console.log(`[RENDER_START] Fallback`);
      prepared = {
        status: RESPONSE_STATUS.READY,
        node: _renderMarkdown(finalText || ''),
        serialized: finalText || ''
      };
    }
    console.log(`[RENDER_END]`);

    if(prepared.status === RESPONSE_STATUS.READY){
      body.appendChild(prepared.node);
      entry.status = RESPONSE_STATUS.READY;
      entry.serialized = prepared.serialized;
      _updateDebugPanel(entry);

      setTimeout(() => {
        if (window._currentActiveEntry === entry) {
          _updateDebugPanel(null);
        }
      }, 5000);
    } else {
      body.textContent = '[validating…]';
      const forceReady = () => {
        if (entry.status === RESPONSE_STATUS.READY) return;
        body.innerHTML = '';
        console.log(`[RENDER_START] Timeout Fallback`);
        try {
          if (mode === 'codeme') {
            const repaired = _ensureClosedFences(_sanitizeResponse(finalText || ''));
            const rendered = _renderCodemeStructured(repaired);
            body.appendChild(rendered.frag);
            entry.serialized = rendered.serialized;
          } else {
            body.appendChild(_renderMarkdown(finalText || ''));
            entry.serialized = finalText || '';
          }
        } catch (fallbackErr) {
          body.textContent = finalText || '';
          entry.serialized = finalText || '';
        }
        console.log(`[RENDER_END] Timeout Fallback`);

        entry.status = RESPONSE_STATUS.READY;
        _updateDebugPanel(entry);

        const toStore = entry.serialized || finalText || '';
        _saveChatEntry(mode, 'jarvis', toStore, 'text');

        setTimeout(() => {
          if (window._currentActiveEntry === entry) {
            _updateDebugPanel(null);
          }
        }, 5000);
      };

      const timeoutId = setTimeout(forceReady, 2000);
      entry.validationTimeoutId = timeoutId;
    }
  }

  if(entry.status === RESPONSE_STATUS.READY){
    const toStore = entry.serialized || ((mode === 'codeme') ? _sanitizeResponse(finalText) : finalText);
    _saveChatEntry(mode, 'jarvis', toStore, 'text');
  }

  """

new_content = content[:start_idx] + new_block + content[end_idx:]

with open('templates/index.html', 'w', encoding='utf-8') as f:
    f.write(new_content)

print("Successfully replaced streaming block.")
