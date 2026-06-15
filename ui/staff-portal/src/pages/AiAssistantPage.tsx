import { useState, useRef, useEffect } from 'react';
import api from '../lib/api';
import { useAuth } from '../hooks/useAuth';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  tokens?: number;
}

const SUGGESTED = [
  'What are common reasons for CPT 99213 denials?',
  'How do I appeal a medical necessity denial?',
  'When should I use modifier 25?',
  'What is timely filing for Medicare?',
  'Explain coordination of benefits rules',
  'What ICD-10 codes are used for hypertension with CKD?',
];

const COMMAND_SUGGESTED = [
  'Raise the coding agent confidence threshold to 0.9',
  'Pause the billing agent',
  'For coding, always prefer the most specific ICD-10 code',
  'Turn on auto-advance for eligibility',
  'Reprocess all escalated denial items',
];

function formatCommandResult(data: any): string {
  const p = data?.parsed || {}; const r = data?.result || {};
  const agent = p.agent === '*' ? 'all agents' : p.agent;
  if (p.action === 'reprocess') return `**Reprocess queued** — ${r.requeued ?? 0} ${agent} item(s) reset to pending. ${r.note ?? ''}`;
  if (p.action === 'set_threshold') return `**Directive applied** — confidence threshold for **${agent}** set to **${p.value}**. Items below this now route to a human.`;
  if (p.action === 'set_enabled') return `**Directive applied** — **${agent}** ${p.value ? 'enabled (resumed)' : 'paused — its items now escalate to humans'}.`;
  if (p.action === 'set_auto_advance') return `**Directive applied** — auto-advance for **${agent}** turned **${p.value ? 'on' : 'off'}**.`;
  if (p.action === 'set_instructions') return `**Standing instruction set for ${agent}** — the agent follows this on every item:\n\n> ${p.value}`;
  return '**Applied.**';
}

// Lightweight markdown renderer — handles headings, bold, bullet lists, line breaks
function MarkdownContent({ text }: { text: string }) {
  const lines = text.split('\n');
  const elements: React.ReactNode[] = [];
  let listItems: string[] = [];

  const flushList = (key: string) => {
    if (listItems.length) {
      elements.push(
        <ul key={key} className="list-disc pl-5 space-y-1 my-2">
          {listItems.map((li, i) => (
            <li key={i}>{renderInline(li)}</li>
          ))}
        </ul>
      );
      listItems = [];
    }
  };

  const renderInline = (s: string): React.ReactNode => {
    // Bold: **text**
    const parts = s.split(/(\*\*[^*]+\*\*)/g);
    return parts.map((p, i) =>
      p.startsWith('**') && p.endsWith('**')
        ? <strong key={i}>{p.slice(2, -2)}</strong>
        : p
    );
  };

  lines.forEach((line, i) => {
    const trimmed = line.trim();
    // Heading ## or ###
    if (/^#{1,3}\s/.test(trimmed)) {
      flushList(`list-${i}`);
      const headingText = trimmed.replace(/^#+\s/, '');
      elements.push(<p key={i} className="font-semibold text-gray-900 mt-3 mb-1">{renderInline(headingText)}</p>);
    } else if (/^[-*•]\s/.test(trimmed)) {
      // Bullet list item
      listItems.push(trimmed.replace(/^[-*•]\s/, ''));
    } else if (/^\d+\.\s/.test(trimmed)) {
      // Numbered list
      listItems.push(trimmed.replace(/^\d+\.\s/, ''));
    } else if (trimmed === '') {
      flushList(`list-${i}`);
    } else {
      flushList(`list-${i}`);
      elements.push(<p key={i} className="my-1">{renderInline(trimmed)}</p>);
    }
  });
  flushList('list-end');

  return <div className="space-y-0.5">{elements}</div>;
}

function classifyDestructive(text: string): string | null {
  const t = text.toLowerCase();
  if (/(pause|disable|\bstop\b|turn off|shut off|deactivate)/.test(t)) return 'pause an agent — its work items will route to humans';
  if ((/threshold|confidence/.test(t) || /(raise|lower|set)/.test(t)) && /(0?\.\d+|\d{1,3}\s*%)/.test(t)) return 'change an agent confidence threshold';
  return null;
}

export function AiAssistantPage() {
  const [messages, setMessages] = useState<Message[]>([
    {
      id: '0',
      role: 'assistant',
      content: "Hi! I'm Aethera AI, your Revenue Cycle Management assistant. I can help with ICD-10/CPT coding questions, denial management, payer policies, billing workflows, and more. What can I help you with today?",
      timestamp: new Date(),
    },
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const { user } = useAuth();
  const isSuper = user?.internal_role === 'company_admin';
  const [mode, setMode] = useState<'chat' | 'command'>('chat');
  const [pendingCmd, setPendingCmd] = useState<{ text: string; label: string } | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const doSend = async (text: string, confirmCmd = false) => {
    if (!text.trim() || loading) return;
    setError('');

    const userMsg: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: text.trim(),
      timestamp: new Date(),
    };
    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setLoading(true);

    const history = [...messages, userMsg].map(m => ({ role: m.role, content: m.content }));

    try {
      let content: string;
      let tokens: number | undefined;
      if (mode === 'command') {
        const { data } = await api.post('/ai/agent-command', { instruction: text.trim(), confirm: confirmCmd });
        content = formatCommandResult(data);
      } else {
        const { data } = await api.post('/ai/chat', { messages: history, stream: false });
        content = data.message;
        tokens = data.tokens_used;
      }
      const assistantMsg: Message = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content,
        timestamp: new Date(),
        tokens,
      };
      setMessages(prev => [...prev, assistantMsg]);
    } catch (err: any) {
      const detail409 = err?.response?.status === 409 ? err?.response?.data?.detail : null;
      if (mode === 'command' && detail409 && detail409.requires_confirmation) {
        setMessages(prev => prev.filter(m => m.id !== userMsg.id));
        setPendingCmd({ text: text.trim(), label: detail409.message || 'apply this change to the agents' });
        return;
      }
      const detail = err?.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'AI assistant is temporarily unavailable. Please try again.');
      setMessages(prev => prev.filter(m => m.id !== userMsg.id));
      setInput(text);
    } finally {
      setLoading(false);
    }
  };

  const submit = (text: string) => {
    if (!text.trim() || loading) return;
    if (mode === 'command') {
      const danger = classifyDestructive(text);
      if (danger) { setPendingCmd({ text: text.trim(), label: danger }); return; }
    }
    setPendingCmd(null);
    doSend(text);
  };

  const confirmPending = () => {
    if (!pendingCmd) return;
    const t = pendingCmd.text;
    setPendingCmd(null);
    doSend(t, true);
  };

  const cancelPending = () => {
    if (pendingCmd) setInput(pendingCmd.text);
    setPendingCmd(null);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      submit(input);
    }
  };

  const formatTime = (d: Date) =>
    d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  return (
    <div className="flex flex-col h-[calc(100vh-4rem)] max-w-4xl mx-auto">
      {/* Header */}
      <div className="px-6 py-4 border-b border-gray-200 bg-white flex items-center gap-3">
        <div className="w-10 h-10 rounded-full bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center text-white font-bold text-sm flex-shrink-0">
          AI
        </div>
        <div>
          <h1 className="text-lg font-semibold text-gray-900">Aethera AI Assistant</h1>
          <p className="text-xs text-gray-500">Powered by Claude — RCM expert for coding, billing &amp; denials</p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <div className="flex rounded-lg border border-gray-200 p-0.5">
            <button onClick={() => setMode('chat')}
              className={`rounded-md px-3 py-1 text-xs font-medium ${mode === 'chat' ? 'bg-blue-600 text-white' : 'text-gray-600 hover:bg-gray-50'}`}>Ask</button>
            {isSuper && (
            <button onClick={() => setMode('command')}
              className={`rounded-md px-3 py-1 text-xs font-medium ${mode === 'command' ? 'bg-indigo-600 text-white' : 'text-gray-600 hover:bg-gray-50'}`}>Direct agents</button>
            )}
          </div>
          <span className="w-2 h-2 bg-green-400 rounded-full"></span>
          <span className="text-xs text-gray-500">Online</span>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4 bg-gray-50">
        {messages.map(msg => (
          <div key={msg.id} className={`flex gap-3 ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}>
            <div className={`w-8 h-8 rounded-full flex-shrink-0 flex items-center justify-center text-xs font-semibold ${
              msg.role === 'assistant'
                ? 'bg-gradient-to-br from-blue-500 to-indigo-600 text-white'
                : 'bg-gray-200 text-gray-600'
            }`}>
              {msg.role === 'assistant' ? 'AI' : 'You'}
            </div>
            <div className={`max-w-[75%] ${msg.role === 'user' ? 'items-end' : 'items-start'} flex flex-col gap-1`}>
              <div className={`px-4 py-3 rounded-2xl text-sm leading-relaxed ${
                msg.role === 'assistant'
                  ? 'bg-white text-gray-800 shadow-sm border border-gray-100 rounded-tl-sm'
                  : 'bg-blue-600 text-white rounded-tr-sm whitespace-pre-wrap'
              }`}>
                {msg.role === 'assistant' ? <MarkdownContent text={msg.content} /> : msg.content}
              </div>
              <span className="text-xs text-gray-400 px-1">
                {formatTime(msg.timestamp)}
                {msg.tokens ? ` · ${msg.tokens.toLocaleString()} tokens` : ''}
              </span>
            </div>
          </div>
        ))}

        {/* Loading indicator */}
        {loading && (
          <div className="flex gap-3">
            <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-500 to-indigo-600 flex-shrink-0 flex items-center justify-center text-white text-xs font-semibold">AI</div>
            <div className="bg-white border border-gray-100 shadow-sm px-4 py-3 rounded-2xl rounded-tl-sm">
              <div className="flex gap-1 items-center h-5">
                <div className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }}></div>
                <div className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }}></div>
                <div className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }}></div>
              </div>
            </div>
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg text-sm text-center">
            {error}
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Suggestions (shown only at start) */}
      {messages.length === 1 && !loading && (
        <div className="px-6 py-3 bg-white border-t border-gray-100">
          <p className="text-xs text-gray-400 mb-2 font-medium">{mode === 'command' ? 'DIRECT THE AGENTS' : 'SUGGESTED QUESTIONS'}</p>
          <div className="flex flex-wrap gap-2">
            {(mode === 'command' ? COMMAND_SUGGESTED : SUGGESTED).map(s => (
              <button
                key={s}
                onClick={() => submit(s)}
                className="text-xs px-3 py-1.5 rounded-full bg-blue-50 text-blue-700 hover:bg-blue-100 transition border border-blue-100"
              >
                {s}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Destructive command confirmation */}
      {pendingCmd && (
        <div className="px-6 py-3 bg-amber-50 border-t border-amber-200">
          <p className="text-sm text-amber-800 mb-2">
            <span className="font-semibold">Confirm:</span> this command will <span className="font-semibold">{pendingCmd.label}</span>. It affects live processing until you change it back.
          </p>
          <div className="flex gap-2">
            <button onClick={confirmPending}
              className="px-3 py-1.5 rounded-lg bg-amber-600 text-white text-sm font-medium hover:bg-amber-700">
              Confirm &amp; apply
            </button>
            <button onClick={cancelPending}
              className="px-3 py-1.5 rounded-lg border border-gray-300 text-sm font-medium text-gray-700 hover:bg-gray-50">
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Input */}
      <div className="px-6 py-4 bg-white border-t border-gray-200">
        <div className="flex gap-3 items-end">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={mode === 'command' ? 'Direct the AI agents: e.g. raise coding threshold to 0.9, pause billing, reprocess escalated denials…' : 'Ask about coding, billing, denials, payer policies… (Enter to send, Shift+Enter for new line)'}
            rows={2}
            className="flex-1 resize-none px-4 py-2.5 border border-gray-300 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none text-sm leading-relaxed"
          />
          <button
            onClick={() => submit(input)}
            disabled={!input.trim() || loading}
            className="px-4 py-2.5 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white rounded-xl transition font-medium text-sm flex-shrink-0 flex items-center gap-2"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
            </svg>
            Send
          </button>
        </div>
        <p className="text-xs text-gray-400 mt-2">
          For informational purposes only. Verify codes with official guidelines before submitting claims.
        </p>
      </div>
    </div>
  );
}
