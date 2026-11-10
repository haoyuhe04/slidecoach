(function (root) {
  'use strict';

  class VoiceSession {
    constructor({ input, Recognition, onState = () => {}, onMessage = () => {} }) {
      this.input = input;
      this.Recognition = Recognition;
      this.onState = onState;
      this.onMessage = onMessage;
      this.recognition = null;
      this.state = 'idle';
      this.limitReported = false;
    }

    updateState(state) {
      this.state = state;
      this.input.readOnly = state === 'idle' ? this.wasReadOnly : true;
      this.onState(state);
    }

    start() {
      if (this.state !== 'idle') return;
      this.wasReadOnly = this.input.readOnly;
      const start = this.input.selectionStart ?? this.input.value.length;
      const end = this.input.selectionEnd ?? start;
      this.prefix = this.input.value.slice(0, start);
      this.suffix = this.input.value.slice(end);
      this.limitReported = false;
      let recognition;
      try {
        recognition = new this.Recognition();
      } catch (error) {
        this.updateState('idle');
        this.onMessage('当前浏览器无法开启语音识别，请尝试 Chrome 或 Edge。');
        return;
      }
      this.recognition = recognition;
      recognition.lang = 'zh-CN';
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.maxAlternatives = 1;
      recognition.onstart = () => {
        if (this.recognition === recognition) this.updateState('listening');
      };
      recognition.onresult = event => {
        if (this.recognition !== recognition || !this.input.isConnected) return;
        let transcript = Array.from(event.results, result => result[0].transcript).join('');
        const limit = this.input.maxLength;
        if (limit >= 0) {
          const available = Math.max(0, limit - this.prefix.length - this.suffix.length);
          if (transcript.length > available) {
            let truncated = '';
            for (const character of transcript) {
              if (truncated.length + character.length > available) break;
              truncated += character;
            }
            transcript = truncated;
            if (!this.limitReported) {
              this.onMessage('已达到这个输入框的字数上限，请先整理文字。');
              this.limitReported = true;
            }
          }
        }
        this.input.value = this.prefix + transcript + this.suffix;
        const cursor = this.prefix.length + transcript.length;
        this.input.setSelectionRange(cursor, cursor);
        this.input.dispatchEvent(new Event('input', { bubbles: true }));
      };
      recognition.onerror = event => {
        if (this.recognition !== recognition) return;
        const messages = {
          'not-allowed': '没有获得麦克风权限。请允许此页面使用麦克风后重试。',
          'service-not-allowed': '当前浏览器无法使用语音识别服务，请尝试 Chrome 或 Edge。',
          'audio-capture': '没有找到可用麦克风，请检查设备连接。',
          'network': '语音识别服务连接失败。已识别的文字会保留，可以稍后重试或继续打字。',
          'no-speech': '没有听到声音。点击语音输入后，靠近麦克风再说一次。',
          'language-not-supported': '当前浏览器暂不支持中文语音识别。'
        };
        if (event.error !== 'aborted') this.onMessage(messages[event.error] || '语音识别暂时不可用，请稍后重试。');
        this.finish(recognition);
        try { recognition.abort(); } catch (error) { /* The error may have ended capture already. */ }
      };
      recognition.onend = () => this.finish(recognition);
      this.updateState('starting');
      try {
        recognition.start();
      } catch (error) {
        this.finish(recognition);
        this.onMessage('暂时无法开始语音识别，请检查麦克风权限后重试。');
      }
    }

    finish(recognition) {
      if (this.recognition !== recognition) return;
      this.recognition = null;
      this.updateState('idle');
    }

    stop() {
      if (!this.recognition) return;
      try { this.recognition.stop(); }
      catch (error) { this.finish(this.recognition); }
    }

    abort() {
      if (!this.recognition) return;
      const recognition = this.recognition;
      this.finish(recognition);
      try { recognition.abort(); } catch (error) { /* The browser may have ended it already. */ }
    }
  }

  if (typeof module !== 'undefined' && module.exports) module.exports = { VoiceSession };
  if (!root.document) return;

  let activeSession = null;
  const microphone = '<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="2" width="6" height="13" rx="3"/><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3M8 22h8"/></svg>';

  function stop() {
    if (activeSession) activeSession.abort();
  }

  function mount(container, notify) {
    const Recognition = root.SpeechRecognition || root.webkitSpeechRecognition;
    const showMessage = notify || (() => {});
    container.querySelectorAll('textarea, input:not([type]), input[type="text"], input[type="search"], input[type="email"], input[type="url"]').forEach(input => {
      if (input.dataset.voiceReady || input.disabled || input.readOnly) return;
      input.dataset.voiceReady = 'true';
      const wrapper = document.createElement('div');
      wrapper.className = 'voice-field ' + (input.tagName === 'TEXTAREA' ? 'voice-area' : 'voice-line');
      input.parentNode.insertBefore(wrapper, input);
      wrapper.appendChild(input);
      const controls = document.createElement('div');
      controls.className = 'voice-controls';
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'voice-button';
      button.innerHTML = microphone + '<span>语音输入</span>';
      const label = input.labels?.[0]?.textContent.trim() || input.getAttribute('aria-label') || input.placeholder || '文字';
      button.setAttribute('aria-label', '语音输入：' + label);
      button.setAttribute('aria-pressed', 'false');
      button.title = Recognition ? '使用浏览器语音识别，文字可编辑后再提交' : '当前浏览器不支持语音识别，可使用 Chrome 或 Edge';
      const status = document.createElement('span');
      status.className = 'voice-status';
      status.setAttribute('role', 'status');
      if (input.id) {
        status.id = input.id + '-voice-status';
        button.setAttribute('aria-controls', input.id);
        input.setAttribute('aria-describedby', [input.getAttribute('aria-describedby'), status.id].filter(Boolean).join(' '));
      }
      controls.append(button, status);
      wrapper.appendChild(controls);
      let fieldSession = null;
      button.addEventListener('click', () => {
        if (fieldSession && activeSession === fieldSession) {
          fieldSession.stop();
          return;
        }
        if (!Recognition) {
          status.textContent = '此浏览器暂不支持语音识别';
          showMessage('当前浏览器不支持语音识别。请在 Chrome 或 Edge 中打开应用，也可以继续打字。');
          return;
        }
        if (!root.isSecureContext) {
          showMessage('语音输入需要通过 HTTPS 或本机 localhost 地址访问。');
          return;
        }
        if (activeSession) {
          showMessage('请先结束正在使用的语音输入。');
          return;
        }
        let hadError = false;
        fieldSession = new VoiceSession({
          input, Recognition,
          onState(state) {
            const listening = state !== 'idle';
            wrapper.classList.toggle('is-listening', listening);
            button.setAttribute('aria-pressed', String(listening));
            button.querySelector('span').textContent = listening ? '结束语音' : '语音输入';
            button.setAttribute('aria-label', (listening ? '结束语音：' : '语音输入：') + label);
            if (listening) status.textContent = state === 'starting' ? '正在开启麦克风…' : '正在听，结束后可编辑';
            else {
              if (!hadError) status.textContent = '文字已保留，请确认后提交';
              if (activeSession === fieldSession) activeSession = null;
            }
          },
          onMessage(message) {
            hadError = true;
            status.textContent = message;
            showMessage(message);
          }
        });
        activeSession = fieldSession;
        fieldSession.start();
      });
    });
  }

  document.addEventListener('submit', event => {
    if (activeSession && event.target.contains(activeSession.input)) {
      event.preventDefault();
      event.stopImmediatePropagation();
      activeSession.stop();
      if (root.SlideCoachNotify) root.SlideCoachNotify('语音已结束，请确认文字后再提交。');
    }
  }, true);
  document.addEventListener('click', event => {
    if (activeSession && event.target.closest('[data-mutate]')) {
      event.preventDefault();
      event.stopImmediatePropagation();
      activeSession.stop();
      if (root.SlideCoachNotify) root.SlideCoachNotify('语音已结束，请确认文字后再操作。');
    }
  }, true);
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) stop();
  });
  root.addEventListener('pagehide', stop);
  root.SlideCoachVoice = { mount, stop };
})(typeof window !== 'undefined' ? window : globalThis);
