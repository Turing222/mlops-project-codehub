import type { ChatMessage, ChatSession } from '../../types/chat';
import type { ChatStreamStepEvent } from '../../schemas/chat';

export type ChatMode = 'normal' | 'rag' | 'web_rag' | 'repo_check';

export type SendMessageOptions = {
  clientRequestId?: string;
  addUserMessage?: boolean;
};

export type SessionStreamActions = {
  enterLiveMode: () => void;
  appendMessage: (message: ChatMessage) => void;
  updateMessages: (updater: (prev: ChatMessage[]) => ChatMessage[]) => void;
  commitSession: (session: ChatSession) => void;
};

export type TraceStreamActions = {
  reset: () => void;
  markNetworkStarted: (networkMs: number) => void;
  applyMetaSkips: (mode: ChatMode) => void;
  handleStep: (event: ChatStreamStepEvent) => void;
  completeIdle: () => void;
  markError: () => void;
  applyDetailFromAssistant: (
    lastAssistant: ChatMessage | undefined,
    session: ChatSession,
  ) => void;
};

export type UseChatStreamParams = {
  userId: string | null | undefined;
  refreshUser: () => Promise<unknown>;
  chatMode: ChatMode;
  activeSessionId: string | null;
  displayedMessages: ChatMessage[];
  sessionActions: SessionStreamActions;
  traceActions: TraceStreamActions;
  resolveDefaultKbId: () => Promise<string | null>;
  explicitRetryEnabled: boolean;
};

export type UseChatStreamReturn = {
  streamingText: string;
  isStreaming: boolean;
  sendQuery: (text: string, options?: SendMessageOptions) => Promise<void>;
  retryFailedMessage: (messageId: string) => void;
  abort: () => void;
  resetStream: () => void;
};
