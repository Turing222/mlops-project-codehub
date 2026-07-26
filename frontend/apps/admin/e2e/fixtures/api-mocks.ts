import {
  buildMockAuthResponse,
  buildMockChatMessage,
  buildMockChunkEvent,
  buildMockMetaEvent,
  buildMockSession,
  buildMockSessionDetail,
  buildMockSessionList,
  buildMockSuperuser,
  buildMockUser,
} from '../../src/test/mock-data';

export function mockUser(overrides: Record<string, unknown> = {}) {
  return buildMockUser(overrides);
}

export function mockSuperuser(overrides: Record<string, unknown> = {}) {
  return buildMockSuperuser(overrides);
}

export function mockAuthResponse(overrides: Record<string, unknown> = {}) {
  return buildMockAuthResponse(overrides);
}

export function mockSession(overrides: Record<string, unknown> = {}) {
  return buildMockSession(overrides);
}

export function mockChatMessage(overrides: Record<string, unknown> = {}) {
  return buildMockChatMessage(overrides);
}

export function mockSessionDetail(options: {
  session?: Record<string, unknown>;
  messages?: Record<string, unknown>[];
} = {}) {
  return buildMockSessionDetail(options);
}

export function mockSessionList(sessions: Record<string, unknown>[] = [mockSession()]) {
  return buildMockSessionList(sessions);
}

export function metaEvent(overrides: Record<string, unknown> = {}) {
  return buildMockMetaEvent(overrides);
}

export function chunkEvent(content: string) {
  return buildMockChunkEvent(content);
}
