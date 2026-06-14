import type { Page } from '@playwright/test';
import { metaEvent, chunkEvent, mockSession } from './api-mocks';

function sseDataLine(data: string): string {
  return `data: ${data}\n\n`;
}

export function buildSSEBody(events: Record<string, unknown>[]): string {
  const parts = events.map((e) => sseDataLine(JSON.stringify(e)));
  parts.push(sseDataLine('[DONE]'));
  return parts.join('');
}

export function buildChatSSEBody(options: {
  sessionId?: string;
  sessionTitle?: string;
  chunks?: string[];
} = {}) {
  const {
    sessionId = 'session-1',
    sessionTitle = 'New Chat',
    chunks = ['Hello', ' from', ' AI', ' assistant', '.'],
  } = options;
  const events = [
    metaEvent({ session_id: sessionId, session_title: sessionTitle }),
    ...chunks.map((c) => chunkEvent(c)),
  ];
  return buildSSEBody(events);
}

export async function mockChatSSERoute(
  page: Page,
  options: {
    sseBody?: string;
    sessionId?: string;
    sessionTitle?: string;
    chunks?: string[];
  } = {},
) {
  const sseBody = options.sseBody ?? buildChatSSEBody(options);
  await page.route('**/api/v1/chat/query_stream', async (route) => {
    await route.fulfill({
      status: 200,
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        Connection: 'keep-alive',
      },
      body: sseBody,
    });
  });
}

export async function mockSessionsRoute(
  page: Page,
  sessions: Record<string, unknown>[] = [mockSession()],
) {
  await page.route('**/api/v1/chat/sessions**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: sessions,
        total: sessions.length,
        skip: 0,
        limit: 50,
      }),
    });
  });
}
