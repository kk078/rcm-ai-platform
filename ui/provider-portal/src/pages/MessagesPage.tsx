import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { MessageSquare, Send } from 'lucide-react';
import api from '../lib/api';

interface Message {
  id: string;
  subject: string;
  from_name: string;
  body: string;
  is_read: boolean;
  created_at: string;
}

interface MessagesResponse {
  items: Message[];
  total: number;
  page: number;
  page_size: number;
}

export function MessagesPage() {
  const queryClient = useQueryClient();
  const [selectedMessage, setSelectedMessage] = useState<string | null>(null);

  const { data, isLoading } = useQuery<MessagesResponse>({
    queryKey: ['provider-messages'],
    queryFn: () =>
      api
        .get('/portal/messages/', { params: { page_size: 20 } })
        .then((r) => r.data),
  });

  const readMutation = useMutation({
    mutationFn: (messageId: string) => api.post(`/portal/messages/${messageId}/read`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['provider-messages'] }),
  });

  const selected = data?.items.find((m) => m.id === selectedMessage);

  const handleSelect = (id: string) => {
    setSelectedMessage(id);
    const msg = data?.items.find((m) => m.id === id);
    if (msg && !msg.is_read) {
      readMutation.mutate(id);
    }
  };

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Messages</h1>
        <p className="mt-1 text-sm text-gray-500">Secure inbox for billing communications</p>
      </div>

      <div className="flex gap-4" style={{ height: 'calc(100vh - 200px)' }}>
        {/* Message list */}
        <div className="w-80 flex-shrink-0 overflow-hidden rounded-xl border border-gray-200 bg-white">
          {isLoading ? (
            <div className="space-y-3 p-3">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="h-16 animate-pulse rounded-lg bg-gray-200" />
              ))}
            </div>
          ) : (
            <div className="divide-y divide-gray-100 overflow-y-auto" style={{ maxHeight: '100%' }}>
              {data?.items.map((msg) => (
                <button
                  key={msg.id}
                  onClick={() => handleSelect(msg.id)}
                  className={`w-full px-4 py-3 text-left hover:bg-gray-50 transition-colors ${
                    selectedMessage === msg.id ? 'bg-brand-50' : ''
                  } ${!msg.is_read ? 'bg-blue-50' : ''}`}
                >
                  <div className="flex items-center justify-between">
                    <span className={`text-sm ${!msg.is_read ? 'font-semibold text-gray-900' : 'text-gray-700'}`}>
                      {msg.from_name}
                    </span>
                    <span className="text-xs text-gray-400">{msg.created_at}</span>
                  </div>
                  <p className={`mt-0.5 text-sm ${!msg.is_read ? 'font-medium text-gray-900' : 'text-gray-600'}`}>
                    {msg.subject}
                  </p>
                </button>
              ))}
              {(!data?.items.length) && (
                <div className="py-12 text-center text-sm text-gray-500">
                  <MessageSquare className="mx-auto mb-2 h-8 w-8 text-gray-300" />
                  No messages
                </div>
              )}
            </div>
          )}
        </div>

        {/* Message detail */}
        <div className="flex-1 overflow-hidden rounded-xl border border-gray-200 bg-white">
          {selected ? (
            <div className="p-6">
              <h2 className="text-lg font-semibold text-gray-900">{selected.subject}</h2>
              <p className="mt-1 text-sm text-gray-500">From: {selected.from_name} · {selected.created_at}</p>
              <div className="mt-4 text-sm text-gray-700 whitespace-pre-wrap">{selected.body}</div>
            </div>
          ) : (
            <div className="flex h-full items-center justify-center">
              <div className="text-center">
                <Send className="mx-auto mb-2 h-8 w-8 text-gray-300" />
                <p className="text-sm text-gray-500">Select a message to view</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}